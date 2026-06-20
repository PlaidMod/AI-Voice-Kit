"""
The brain. Sends the conversation to Gemini 2.5 Flash (google-genai SDK) and
runs the tool loop.

Tools the model can use (all are "function tools" we run here on the Pi):
  * web_search        - we run a SEPARATE, Google-Search-grounded Gemini call
  * save_opportunity  - append a row to the Google Sheet
  * list_recent_chats - read back saved conversations
  * continue_chat     - switch to an older conversation
  * start_new_chat    - begin a fresh conversation

Why web_search is a function tool instead of built-in grounding: gemini-2.5-flash
CANNOT use the built-in google_search tool and custom function tools in the SAME
request (only the Gemini 3 series can). So we keep all of Scout's custom tools on
the main call, and when the model asks to search we satisfy it with a second,
grounding-only call. Every individual API call therefore uses either grounding OR
functions -- never both -- which is what 2.5 allows. As a bonus, search only runs
when the model actually needs it, which is gentle on the free daily quota.
"""

from datetime import date

from google import genai  # noqa: F401  (kept for clarity; client is passed in)
from google.genai import types

import config
import chats
import google_sync
import usage


# ---- Tool definitions handed to the model ---------------------------------

FUNCTION_DECLARATIONS = [
    {
        "name": "web_search",
        "description": (
            "Search the live web (Google) for current information such as "
            "deadlines, openings, dates, prices, or specific organizations. You "
            "have NO other internet access, so you MUST call this before stating "
            "anything time-sensitive or anything you are not sure of. Pass a "
            "focused search query."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "save_opportunity",
        "description": (
            "Save one opportunity (program, internship, competition, research, "
            "fellowship, scholarship) to the user's Google Sheet. Call once per "
            "opportunity when the user wants it kept, or when you find a strong "
            "match worth saving. Then tell the user you saved it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the opportunity/program"},
                "deadline": {"type": "string", "description": "Application deadline if known"},
                "eligibility": {"type": "string", "description": "Who can apply (e.g. high school sophomores)"},
                "link": {"type": "string", "description": "URL if known"},
                "why_relevant": {"type": "string", "description": "One line on why it fits this student"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "list_recent_chats",
        "description": "List the user's recent saved conversations so they can pick one to continue.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "How many to list (default 8)"},
            },
        },
    },
    {
        "name": "continue_chat",
        "description": (
            "Switch to an older conversation so the next questions continue it. "
            "Pass the exact id from list_recent_chats."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "chat_id": {"type": "string", "description": "The id of the chat to continue"},
            },
            "required": ["chat_id"],
        },
    },
    {
        "name": "start_new_chat",
        "description": "Start a brand new, empty conversation (forget the current topic).",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "set_volume",
        "description": (
            "Change Scout's speaker volume when the user asks (e.g. 'turn it up', "
            "'louder', 'quieter', 'set volume to 70 percent'). Use 'level' for an "
            "absolute target percent (0-200, where 100 is normal), OR 'change' for "
            "a relative step in percentage points (positive = louder, negative = "
            "quieter). Then confirm the new level in one short bullet."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "level": {"type": "integer", "description": "Absolute target volume percent, 0-200"},
                "change": {"type": "integer", "description": "Relative change in points, e.g. 20 or -20"},
            },
        },
    },
]

FUNCTION_TOOLS = types.Tool(function_declarations=FUNCTION_DECLARATIONS)

# Safety net so a confused tool loop can never spin forever on the Pi.
MAX_TOOL_ROUNDS = 8


class ToolContext:
    """Carries side effects out of the tool loop and back to main.py."""

    def __init__(self):
        self.switch_to = None    # chat id to continue after this turn, if any
        self.start_new = False   # start a fresh chat after this turn, if True


def _generate(client, **kwargs):
    """Make one Gemini request and count it against today's free quota."""
    response = client.models.generate_content(**kwargs)
    usage.record()
    return response


def _thinking_config():
    """Turn off 'thinking' for fast voice replies, in a model-safe way.

    Gemini 2.5 disables thinking with thinking_budget=0. Gemini 3 models use a
    different API (thinking_level) and reject thinking_budget, so for anything
    that isn't 2.5 we omit it and take the model's default. Lets SCOUT_MODEL be
    switched (e.g. to a Gemini 3 flash-lite) without a 400 on this parameter.
    """
    if config.MODEL.startswith("gemini-2.5"):
        return types.ThinkingConfig(thinking_budget=0)
    return None


def transcribe(client, audio, sample_rate):
    """Transcribe a mono float32 [-1, 1] clip with Gemini; return plain text."""
    import io
    import wave
    import numpy as np

    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)

    audio_part = types.Part.from_bytes(data=buf.getvalue(), mime_type="audio/wav")
    instruction = (
        "Transcribe the user's spoken question from this audio, in English. "
        "Return ONLY the exact words spoken -- no quotes, labels, or commentary. "
        "If there is no clear speech, return nothing."
    )
    cfg = types.GenerateContentConfig(
        thinking_config=_thinking_config(),
        temperature=0.0,
    )
    response = _generate(
        client,
        model=config.MODEL,
        contents=[instruction, audio_part],
        config=cfg,
    )
    return (response.text or "").strip()


def _grounded_search(client, query):
    """Answer `query` with a separate Google-Search-grounded Gemini call."""
    cfg = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
    )
    response = _generate(client, model=config.MODEL, contents=query, config=cfg)
    text = (response.text or "").strip()

    # Pull source titles so the main model can name them out loud.
    sources = []
    try:
        chunks = response.candidates[0].grounding_metadata.grounding_chunks or []
        for chunk in chunks:
            title = getattr(getattr(chunk, "web", None), "title", None)
            if title and title not in sources:
                sources.append(title)
    except (AttributeError, IndexError, TypeError):
        pass
    if sources:
        text += "\n\nSources: " + "; ".join(sources[:5])

    return text or "The search came back empty."


def _run_tool(client, name, args, ctx):
    """Execute one function call and return a text result for the model."""
    if name == "web_search":
        return _grounded_search(client, args.get("query", ""))

    if name == "save_opportunity":
        return google_sync.append_opportunity(
            name=args.get("name", ""),
            deadline=args.get("deadline", ""),
            eligibility=args.get("eligibility", ""),
            link=args.get("link", ""),
            why=args.get("why_relevant", ""),
        )

    if name == "list_recent_chats":
        recent = chats.list_recent(limit=args.get("limit", 8))
        if not recent:
            return "There are no saved conversations yet."
        lines = [f"{c['title']} (id: {c['id']}, {c['when']})" for c in recent]
        return "Recent conversations:\n" + "\n".join(lines)

    if name == "continue_chat":
        chat_id = args.get("chat_id", "")
        conv = chats.load(chat_id)
        if conv is None:
            return f"No conversation with id {chat_id}. Use list_recent_chats first."
        ctx.switch_to = chat_id
        return f"Loaded '{conv.title}'. It will continue from your next question."

    if name == "start_new_chat":
        ctx.start_new = True
        return "Started a new, empty conversation."

    if name == "set_volume":
        import volume
        current_pct = volume.get() * 100
        if args.get("level") is not None:
            target_pct = float(args["level"])
        else:
            target_pct = current_pct + float(args.get("change", 0))
        new_pct = volume.set(target_pct / 100.0) * 100
        return f"Volume is now {int(round(new_pct))} percent."

    return f"Unknown tool: {name}"


def _text_from(parts):
    """Concatenate the spoken text out of a list of response parts."""
    return "".join(p.text for p in (parts or []) if getattr(p, "text", None)).strip()


def respond(client, system_prompt, base_messages, question, ctx):
    """
    Ask Gemini and return the final spoken answer text.

    `base_messages` is the current chat's simple history (a list of
    {"role", "content"} dicts, where role is "user" or "assistant"). We map it
    to Gemini's Content list (assistant -> "model"), then grow it with the
    model's tool calls and our results; only the final answer text gets saved
    back into history (in main.py).
    """
    dated_prompt = f"Today's date is {date.today():%A, %B %d, %Y}.\n\n{system_prompt}"

    contents = []
    for msg in base_messages:
        role = "model" if msg["role"] == "assistant" else "user"
        contents.append(types.Content(role=role, parts=[types.Part(text=msg["content"])]))
    contents.append(types.Content(role="user", parts=[types.Part(text=question)]))

    cfg = types.GenerateContentConfig(
        system_instruction=dated_prompt,
        tools=[FUNCTION_TOOLS],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        thinking_config=_thinking_config(),
        max_output_tokens=config.MAX_TOKENS,
    )

    for _ in range(MAX_TOOL_ROUNDS):
        response = _generate(client, model=config.MODEL, contents=contents, config=cfg)
        candidate = response.candidates[0]
        parts = candidate.content.parts or []

        calls = [p.function_call for p in parts if getattr(p, "function_call", None)]
        if not calls:
            return _text_from(parts) or "I'm not sure how to answer that. Could you rephrase?"

        # Keep the model's tool-call turn, then answer each call it made.
        contents.append(candidate.content)
        result_parts = []
        for fc in calls:
            args = dict(fc.args) if fc.args else {}
            output = _run_tool(client, fc.name, args, ctx)
            result_parts.append(
                types.Part.from_function_response(name=fc.name, response={"result": output})
            )
        contents.append(types.Content(role="user", parts=result_parts))

    return "I got a bit stuck working through that. Mind asking it a different way?"
