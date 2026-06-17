#!/usr/bin/env python3
"""
Scout - a hands-free opportunity-scout voice assistant for the AIY Voice Kit V1.

What happens:
  * Idle: the button LED slowly PULSES, meaning "I'm listening for you."
  * You say "Hello Claude" (or press the button) -> Scout greets you, LED solid.
  * You ask your question -> it records until you stop talking.
  * It checks the voice is YOURS, transcribes the audio with Gemini, then asks
    Gemini 2.5 Flash (with web search + Google Sheet saving + chat memory).
  * It speaks back a 3-5 bullet answer, then goes back to the pulsing idle state.

The pieces live in separate files: config, listener (mic + wake word),
voice_id (speaker check), assistant (Gemini transcription + answer + tools),
chats (memory), google_sync (Sheets), volume (voice-set speaker level). This
file just orchestrates them.
"""

import io
import os
import random
import subprocess
import sys
import threading
import wave

from google import genai
from google.genai import errors

from aiy.board import Board, Led

import config
import chats
import usage
import voice_id
import volume
from assistant import ToolContext, respond, transcribe
from listener import Listener

# --- Text-to-speech: Piper (neural) → AIY pico2wave → pyttsx3/espeak ------
#
# Piper gives the best voice by far. It auto-enables once you:
#   pip install piper-tts
#   mkdir -p ~/scout/piper-voices && cd ~/scout/piper-voices
#   wget <en_US-lessac-medium.onnx>  (see setup notes)
#
# AIY pico2wave imports cleanly even when the binary is missing; failure shows
# at call time, so we guard the call and fall through to pyttsx3.

_piper_voice = None
if os.path.exists(config.PIPER_MODEL_PATH):
    try:
        from piper.voice import PiperVoice as _PiperVoice
        _piper_voice = _PiperVoice.load(config.PIPER_MODEL_PATH)
        print(f"Piper TTS loaded: {os.path.basename(config.PIPER_MODEL_PATH)}")
    except Exception as _e:
        print(f"[Piper TTS unavailable: {_e}]")

try:
    from aiy.voice import tts as _aiy_tts
    _aiy_say = _aiy_tts.say
except Exception:
    _aiy_say = None

_pyttsx3_engine = None


def _speak_piper(text):
    """Synthesize with Piper to a temp WAV, then play it on the Voice HAT.

    Piper's API changed between versions. Modern piper-tts (1.x) exposes
    synthesize_wav(text, wav_file), which writes real audio frames AND sets the
    WAV header itself. The legacy API used synthesize(text, wav_file) after the
    caller set the header. We support both, and verify the file actually has
    audio before playing so a silent synth surfaces instead of "playing" silence.
    """
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_path = f.name
    try:
        with wave.open(tmp_path, "wb") as wf:
            if hasattr(_piper_voice, "synthesize_wav"):
                _piper_voice.synthesize_wav(text, wf)        # piper-tts 1.x
            else:                                            # legacy API
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(_piper_voice.config.sample_rate)
                _piper_voice.synthesize(text, wf)
        if os.path.getsize(tmp_path) <= 44:                  # header only = no audio
            raise RuntimeError("Piper produced no audio frames")
        _apply_gain(tmp_path, volume.get())                  # voice-set volume
        subprocess.run(["aplay", "-q", "-D", config.PLAYBACK_DEVICE, tmp_path],
                       stderr=subprocess.DEVNULL)
    finally:
        os.unlink(tmp_path)


def _apply_gain(path, gain):
    """Scale a WAV's samples in place by `gain` (skip the no-op of 1.0)."""
    if abs(gain - 1.0) < 1e-3:
        return
    import numpy as np
    with wave.open(path, "rb") as wf:
        params = wf.getparams()
        frames = wf.readframes(wf.getnframes())
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) * gain
    samples = np.clip(samples, -32768, 32767).astype("<i2")
    with wave.open(path, "wb") as wf:
        wf.setparams(params)
        wf.writeframes(samples.tobytes())


def _speak_pyttsx3(text):
    """Last-resort voice via pyttsx3/espeak; engine built lazily."""
    global _pyttsx3_engine
    if _pyttsx3_engine is None:
        import pyttsx3
        _pyttsx3_engine = pyttsx3.init()
        _pyttsx3_engine.setProperty("rate", 165)
    _pyttsx3_engine.say(text)
    _pyttsx3_engine.runAndWait()


def speak(text):
    """Say text aloud. Prefer Piper neural TTS, then AIY, then pyttsx3."""
    if _piper_voice is not None:
        try:
            _speak_piper(text)
            return
        except Exception as e:
            print(f"  [Piper TTS failed: {e}]")
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
    if not os.environ.get("GEMINI_API_KEY"):
        print("ERROR: GEMINI_API_KEY is not set. See the setup steps.", file=sys.stderr)
        sys.exit(1)

    # The wake word is optional. It turns on automatically once a Picovoice key
    # and the "Hello Claude" keyword file are both present; until then Scout runs
    # button-only. Force it either way with SCOUT_WAKE_WORD=on / off.
    wake_on = config.wake_word_enabled()
    if wake_on:
        if not config.PICOVOICE_ACCESS_KEY or not os.path.exists(config.WAKE_KEYWORD_PATH):
            print("ERROR: wake word is on but the Picovoice key or 'Hello Claude' "
                  "keyword file is missing.", file=sys.stderr)
            sys.exit(1)
    else:
        print("Wake word OFF (no Picovoice key/keyword file) -- press the button to talk.")

    with open(config.SYSTEM_PROMPT_PATH, encoding="utf-8") as f:
        system_prompt = f.read()

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    # Speech-to-text runs in the cloud via Gemini (see assistant.transcribe) --
    # far faster and more accurate on a Pi 3B than loading Whisper locally.

    if not voice_id.has_voiceprint():
        print("NOTE: no voiceprint found -- speaker lock is OFF. Run enroll.py to lock it to your voice.")

    # Resume the most recent conversation so "continue" feels natural.
    current = chats.latest_or_new()

    listener = Listener()
    button_event = threading.Event()

    # How to tell Scout to listen again -- phrased to match the active trigger.
    retry_hint = "Say Hello Claude to try again." if wake_on else "Press the button to try again."

    with Board() as board:
        start_button_thread(board, button_event)
        if wake_on:
            speak("Scout is online. Say Hello Claude, or press the button.")
            print("Idle. Say 'Hello Claude' or press the button. Ctrl+C to quit.")
        else:
            speak("Scout is online. Press the button to talk to me.")
            print("Idle. Press the button to talk. Ctrl+C to quit.")

        try:
            while True:
                # ---- IDLE: pulse the LED to show we're available. ----
                board.led.state = Led.PULSE_SLOW
                button_event.clear()              # ignore any stale button press
                if wake_on:
                    listener.start()              # mic on for wake-word detection
                trigger = listener.wait_for_trigger(button_event)
                if wake_on:
                    listener.stop()               # mic off so the greeting isn't recorded

                # ---- GREET, then LISTEN for the question ----
                board.led.state = Led.ON
                speak(random.choice(GREETINGS))
                print(f"\n[{trigger}] Listening...")
                listener.start()                  # fresh buffer -> no greeting echo
                audio = listener.capture_utterance()
                listener.stop()                   # mic off during thinking + speaking

                if audio is None:
                    speak(f"I didn't hear a question. {retry_hint}")
                    continue

                # ---- THINKING: pulse quickly. ----
                board.led.state = Led.PULSE_QUICK

                # ---- VOICE CHECK: only the owner gets answers. ----
                if not voice_id.is_owner(audio):
                    print("Voice did not match the owner -- refusing.")
                    board.led.state = Led.BLINK
                    speak(REFUSAL)
                    continue

                # ---- If the free quota is already spent, don't hit the API. ----
                # (Both transcription and the answer are Gemini calls now.)
                if usage.is_exhausted():
                    speak("You're still out of free Gemini credits for today. "
                          "They reset tomorrow, so try me again then.")
                    continue

                # ---- TRANSCRIBE with Gemini, then ASK Gemini (web search + tools). ----
                ctx = ToolContext()
                try:
                    question = transcribe(client, audio, config.SAMPLE_RATE)
                    if not question:
                        speak(f"I didn't catch that. {retry_hint}")
                        continue
                    print(f"You said: {question}")
                    answer = respond(client, system_prompt, current.messages, question, ctx)
                except errors.APIError as e:
                    print(f"[API ERROR] code={getattr(e, 'code', None)} message={e}")
                    err_str = str(e).lower()
                    if getattr(e, "code", None) == 429 or "resource_exhausted" in err_str:
                        # Distinguish daily quota (RPD) from per-minute rate limit (RPM).
                        # RPD message contains "quota" or "daily"; RPM contains "rate".
                        is_daily = "daily" in err_str or (
                            "quota" in err_str and "rate" not in err_str
                        )
                        if is_daily:
                            usage.mark_exhausted()
                            print("Gemini free daily quota exhausted (429).")
                            speak("You've used all of today's free Gemini credits. "
                                  "They reset tomorrow, so I can't answer until then.")
                        else:
                            print("Gemini rate limit (RPM) hit — waiting 60 s.")
                            speak("I'm being asked questions too quickly. Give me a moment.")
                            import time
                            time.sleep(60)
                    else:
                        print(f"Gemini API error: {e}")
                        speak("I had trouble reaching the assistant. Please try again.")
                    continue

                # Save this Q&A into the active conversation.
                current.add_turn(question, answer)
                chats.save(current)

                # ---- SPEAK the answer. ----
                print(f"Scout: {answer}")
                board.led.state = Led.ON
                speak(clean_for_speech(answer))

                # ---- Heads-up as the free daily quota runs low. ----
                if usage.should_announce_warning():
                    pct = int(usage.fraction_used() * 100)
                    speak(f"Quick heads-up: you've used about {pct} percent "
                          "of today's free Gemini requests.")

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
