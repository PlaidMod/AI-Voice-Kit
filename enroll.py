#!/usr/bin/env python3
"""
Enroll YOUR voice (run this once during setup).

It records three short clips of you talking, builds your "voiceprint," and
saves it. After this, Scout will only answer questions that sound like you.

    python3 enroll.py

Speak naturally for the full few seconds each time. Re-run it anytime to redo
your voiceprint (e.g. if your mic placement changes).
"""

import sys
import time

from pvrecorder import PvRecorder

import config
import voice_id
from listener import record_seconds

# What to say for each clip. Say the whole thing, naturally.
PROMPTS = [
    "Hello Claude, it's me. Find me some rocketry programs.",
    "I'm looking for coding internships and research for high schoolers.",
    "Let's debug a Python problem together this weekend.",
]
CLIP_SECONDS = 5


def main():
    if not voice_id.AVAILABLE:
        print("Resemblyzer isn't installed, so voice enrollment can't run.")
        print("Install it with:  pip3 install resemblyzer")
        sys.exit(1)

    recorder = PvRecorder(frame_length=512, device_index=config.MIC_DEVICE_INDEX)
    recorder.start()
    print("Voice enrollment. You'll record 3 short clips.\n")

    embeddings = []
    try:
        for i, prompt in enumerate(PROMPTS, start=1):
            print(f"Clip {i} of {len(PROMPTS)}. Get ready to say:")
            print(f'   "{prompt}"')
            for n in (3, 2, 1):
                print(f"   recording in {n}...")
                time.sleep(1)
            print("   >>> SPEAK NOW <<<")
            audio = record_seconds(recorder, CLIP_SECONDS)
            print("   got it.\n")
            embeddings.append(voice_id.embed(audio))
    finally:
        recorder.stop()
        recorder.delete()

    voice_id.save_voiceprint(embeddings)
    print(f"Done! Saved your voiceprint to {config.VOICEPRINT_PATH}")
    print("Scout will now only answer questions in your voice.")


if __name__ == "__main__":
    main()
