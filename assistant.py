"""
The brain. Sends the conversation to GPT-5.5 (OpenAI Responses API) and runs
the tool loop.

Tools the model can use:
  * web_search        - built in, runs on OpenAI's servers (find live info)
  * save_opportunity  - we run it: append a row to the Google Sheet
  * list_recent_chats - we run it: read back saved conversations
  * continue_chat     - we run it: switch to an older conversation
  * start_new_chat    - we run it: begin a fresh conversation

web_search is a "hosted tool": OpenAI runs it server-side inside a single
create() call and folds the sourced results straight into the answer. The other
four are "function tools" -- the model asks for them, we run them here on the
Pi, hand the text result back, and let it keep going.
"""

import json
from datetime import date

import config
import chats
import google_sync


# ---- Tool definitions handed to the model ---------------------------------

# Hosted web search. OpenAI executes this server-side and returns sourced
# answers; there is no per-call cap to set here (unlike the old Anthropic tool).
WEB_SEARCH_TOOL = {"type": "web_search"}

CUSTOM_TOOLS = [
    {
        "type": "function",
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
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "list_recent_chats",
        "description": "List the user's recent saved conversations so they can pick one to continue.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "How many to list (default 8)"},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
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
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "start_new_chat",
        "description": "Start a brand new, empty conversation (forget the current topic).",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
]

ALL_TOOLS = [WEB_SEARCH_TOOL] + CUSTOM_TOOLS

# Safety net so a confused tool loop can never spin forever on the Pi.
MAX_TOOL_ROUNDS = 8


class ToolContext:
    """Carries side effects out of the tool loop and back to main.py."""

    def __init__(self):
        self.switch_to = None    # chat id to continue after this turn, if any
        self.start_new = False   # start a fresh chat after this turn, if True


def _run_custom_tool(name, tool_input, ctx):
    """Execute one function tool and return a text result for the model."""
    if name == "save_opportunity":
        return google_sync.append_opportunity(
            name=tool_input.get("name", ""),
            deadline=tool_input.get("deadline", ""),
            eligibility=tool_input.get("eligibility", ""),
            link=tool_input.get("link", ""),
            why=tool_input.get("why_relevant", ""),
        )

    if name == "list_recent_chats":
        recent = chats.list_recent(limit=tool_input.get("limit", 8))
        if not recent:
            return "There are no saved conversations yet."
        lines = [f"{c['title']} (id: {c['id']}, {c['when']})" for c in recent]
        return "Recent conversations:\n" + "\n".join(lines)

    if name == "continue_chat":
        chat_id = tool_input.get("chat_id", "")
        conv = chats.load(chat_id)
        if conv is None:
            return f"No conversation with id {chat_id}. Use list_recent_chats first."
        ctx.switch_to = chat_id
        return f"Loaded '{conv.title}'. It will continue from your next question."

    if name == "start_new_chat":
        ctx.start_new = True
        return "Started a new, empty conversation."

    return f"Unknown tool: {name}"


def respond(client, system_prompt, base_messages, question, ctx):
    """
    Ask GPT-5.5 and return the final spoken answer text.

    `base_messages` is the current chat's simple history (a list of
    {"role", "content"} dicts). We build a working input list for this turn
    that grows with the model's own output items and our tool results; only the
    final answer text gets saved back into history (in main.py).

    web_search is resolved server-side within each create() call, so the loop
    below only has to handle our four function tools.
    """
    # Give the model today's date so it can reason about deadlines correctly.
    dated_prompt = f"Today's date is {date.today():%A, %B %d, %Y}.\n\n{system_prompt}"

    input_list = list(base_messages) + [{"role": "user", "content": question}]

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.responses.create(
            model=config.MODEL,
            instructions=dated_prompt,
            tools=ALL_TOOLS,
            input=input_list,
            max_output_tokens=config.MAX_TOKENS,
        )

        # Carry the model's full output forward so any tool calls (and the
        # reasoning tied to them) stay linked on the next round.
        input_list += response.output

        tool_calls = [item for item in response.output
                      if getattr(item, "type", None) == "function_call"]
        if not tool_calls:
            text = (response.output_text or "").strip()
            return text or "I'm not sure how to answer that. Could you rephrase?"

        for call in tool_calls:
            try:
                args = json.loads(call.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            output = _run_custom_tool(call.name, args, ctx)
            input_list.append({
                "type": "function_call_output",
                "call_id": call.call_id,
                "output": output,
            })

    return "I got a bit stuck working through that. Mind asking it a different way?"
