"""
Speaker volume, stored as a software gain that main.py applies to TTS output.

Kept in a tiny JSON file so the level Kartigan sets by voice survives restarts.
The gain multiplies the audio samples just before playback: 1.0 is normal, 0.0
is silent, and values above 1.0 boost (with some clipping distortion). We do it
in software instead of via ALSA's mixer because the Voice HAT's mixer control
name is unreliable across OS versions, while a sample gain always works.
"""

import json

import config


def get():
    """Current gain (float). Falls back to the configured default."""
    try:
        with open(config.VOLUME_PATH, encoding="utf-8") as f:
            value = float(json.load(f).get("volume", config.DEFAULT_VOLUME))
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, ValueError):
        return config.DEFAULT_VOLUME
    return max(0.0, min(config.MAX_VOLUME, value))


def set(level):
    """Clamp `level` to [0, MAX_VOLUME], persist it, and return what was saved."""
    level = max(0.0, min(config.MAX_VOLUME, float(level)))
    try:
        with open(config.VOLUME_PATH, "w", encoding="utf-8") as f:
            json.dump({"volume": level}, f)
    except OSError:
        pass
    return level
