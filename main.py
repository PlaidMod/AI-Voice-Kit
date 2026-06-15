#!/usr/bin/env python3
"""
Scout - a hands-free opportunity-scout voice assistant for the AIY Voice Kit V1.

What happens:
  * Idle: the button LED slowly PULSES, meaning "I'm listening for you."
  * You say "Hello Claude" (or press the button) -> Scout greets you, LED solid.
  * You ask your question -> it records until you stop talking.
  * It checks the voice is YOURS, transcribes locally with Whisper, then asks
    GPT-5.5 (with web search + Google Sheet saving + chat memory).
  * It speaks back a 3-5 bullet answer, then goes back to the pulsing idle state.

The pieces live in separate files: config, listener (mic + wake word),
voice_id (speaker check), assistant (GPT-5.5 + tools), chats (memory),
google_sync (Sheets). This file just orchestrates them.
"""

import os
import random
import sys
import threading

import openai
from openai import OpenAI

from aiy.board import Board, Led

import config
import chats
import voice_id
from assistant import ToolContext, respond
from listener import Listener

# --- Text-to-speech: AIY first, pyttsx3 as a fallback ----------------------
# IMPORTANT: aiy.voice.tts imports cleanly even when its underlying `pico2wave`
# binary is missing (common on a fresh 64-bit Raspberry Pi OS). The failure
# only shows up when say() actually runs. So we guard the *call*, not just the
# import, and fall back to pyttsx3 (espeak) so a TTS problem never crashes the
# main loop -- worst case is a silent answer that still prints to the log.
try:
    from aiy.voice import tts as _aiy_tts
    _aiy_say = _aiy_tts.say
except Exception:  # aiy module unavailable (e.g. running off-device)
    _aiy_say = None

_pyttsx3_engine = None


def _speak_pyttsx3(text):
    """Fallback voice via pyttsx3/espeak; engine is built lazily on first use."""
    global _pyttsx3_engine
    if _pyttsx3_engine is None:
        import pyttsx3
        _pyttsx3_engine = pyttsx3.init()
        _pyttsx3_engine.setProperty("rate", 165)
    _pyttsx3_engine.say(text)
    _pyttsx3_engine.runAndWait()


def speak(text):
    """Say text aloud. Prefer AIY TTS, fall back to pyttsx3, never crash."""
    if _aiy_say is not None:
        try:
            _aiy_say(text, lang="en-US", volume=70, pitch=130)
            return
        except Exception as e:
            print(f"  [AIY TTS failed, falling back to pyttsx3: {e}]")
    try:
        _speak_pyttsx3(text)
    except Exception as e:
        print(f"  [TTS unavailable: {e}]  (would have said: {text})")


GREETINGS = [
    "Hey! What can I help you find?",
    "Hi there. What's up?",
    "Hello! What are we scouting today?",
    "Hey, I'm listening.",
]

REFUSAL = ("Unfortunately I cannot answer this question. "
           "The question can only be answered if the user permits.")


def clean_for_speech(text):
    """Strip stray markdown so the speaker reads cleanly."""
    import re
    text = re.sub(r"[*#`_>]", "", text)
    text = re.sub(r"^\s*[-•]\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def start_button_thread(board, button_event):
    """
    Watch the physical button in the background and set an event when pressed.

    This lets the main mic loop notice a button press between audio frames
    without blocking on it.
    """
    def loop():
        while True:
            board.button.wait_for_press()
            button_event.set()
            board.button.wait_for_release()

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t


def main():
    # --- Required keys up front, before anything slow loads. ---
    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY is not set. See the setup steps.", file=sys.stderr)
        sys.exit(1)
    if not config.PICOVOICE_ACCESS_KEY:
        print("ERROR: PICOVOICE_ACCESS_KEY is not set (needed for the wake word).", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(config.WAKE_KEYWORD_PATH):
        print(f"ERROR: wake word file not found at {config.WAKE_KEYWORD_PATH}", file=sys.stderr)
        sys.exit(1)

    with open(config.SYSTEM_PROMPT_PATH, encoding="utf-8") as f:
        system_prompt = f.read()

    client = OpenAI()

    print(f"Loading Whisper '{config.WHISPER_MODEL}' (this can take a minute)...")
    import whisper
    whisper_model = whisper.load_model(config.WHISPER_MODEL)
    print("Whisper ready.")

    if not voice_id.has_voiceprint():
        print("NOTE: no voiceprint found -- speaker lock is OFF. Run enroll.py to lock it to your voice.")

    # Resume the most recent conversation so "continue" feels natural.
    current = chats.latest_or_new()

    listener = Listener()
    button_event = threading.Event()

    with Board() as board:
        start_button_thread(board, button_event)
        speak("Scout is online.")
        print("Idle. Say 'Hello Claude' or press the button. Ctrl+C to quit.")

        try:
            while True:
                # ---- IDLE: pulse the LED to show we're available. ----
                board.led.state = Led.PULSE_SLOW
                button_event.clear()              # ignore any stale button press
                listener.start()                  # mic on, only while we listen
                trigger = listener.wait_for_trigger(button_event)
                listener.stop()                   # mic off so the greeting isn't recorded

                # ---- GREET, then LISTEN for the question ----
                board.led.state = Led.ON
                speak(random.choice(GREETINGS))
                print(f"\n[{trigger}] Listening...")
                listener.start()                  # fresh buffer -> no greeting echo
                audio = listener.capture_utterance()
                listener.stop()                   # mic off during thinking + speaking

                if audio is None:
                    speak("I didn't hear a question. Say Hello Claude to try again.")
                    continue

                # ---- THINKING: pulse quickly. ----
                board.led.state = Led.PULSE_QUICK

                # ---- VOICE CHECK: only the owner gets answers. ----
                if not voice_id.is_owner(audio):
                    print("Voice did not match the owner -- refusing.")
                    board.led.state = Led.BLINK
                    speak(REFUSAL)
                    continue

                # ---- TRANSCRIBE locally (no internet needed for this step). ----
                try:
                    result = whisper_model.transcribe(audio, fp16=False, language="en")
                    question = result["text"].strip()
                except Exception as e:
                    print(f"Transcription failed: {e}")
                    speak("Sorry, I couldn't make out the audio. Try again.")
                    continue

                if not question:
                    speak("I didn't catch that. Say Hello Claude and try again.")
                    continue
                print(f"You said: {question}")

                # ---- ASK CLAUDE (web search + tools). ----
                ctx = ToolContext()
                try:
                    answer = respond(client, system_prompt, current.messages, question, ctx)
                except openai.OpenAIError as e:
                    print(f"OpenAI API error: {e}")
                    speak("I had trouble reaching the assistant. Please try again.")
                    continue

                # Save this Q&A into the active conversation.
                current.add_turn(question, answer)
                chats.save(current)

                # ---- SPEAK the answer. ----
                print(f"Scout: {answer}")
                board.led.state = Led.ON
                speak(clean_for_speech(answer))

                # ---- Apply any chat switch the model asked for. ----
                if ctx.start_new:
                    current = chats.new_conversation()
                    print("Switched to a new conversation.")
                elif ctx.switch_to:
                    loaded = chats.load(ctx.switch_to)
                    if loaded:
                        current = loaded
                        print(f"Now continuing: {current.title}")

        finally:
            listener.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nGoodbye.")
