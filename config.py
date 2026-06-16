"""
All of Scout's settings in one place.

Most things can be overridden with environment variables (handy for systemd),
but the defaults are sensible for an AIY Voice Kit V1 on a Raspberry Pi 3B.
"""

import os

# Folder this file lives in. All data files sit next to the code.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Google Gemini (gemini-2.5-flash) -------------------------------------
# Override with SCOUT_MODEL if you want a different Gemini model string.
MODEL = os.environ.get("SCOUT_MODEL", "gemini-2.5-flash")
# Ceiling on output tokens for one answer (answers are only a few bullets).
MAX_TOKENS = int(os.environ.get("SCOUT_MAX_TOKENS", "2000"))

# --- Free-tier usage tracking (Gemini daily request quota) ----------------
# Google's free tier is a daily REQUEST limit, not a dollar balance, and it has
# moved around a lot through 2026 (roughly 250-1500 requests/day). Set this to
# match what your key shows in Google AI Studio so the early "about to run out"
# warning is accurate. The real "you're out" alert is driven by the API's own
# 429, so this number only affects the proactive heads-up.
FREE_TIER_DAILY_LIMIT = int(os.environ.get("SCOUT_FREE_DAILY_LIMIT", "250"))
# Speak a heads-up once this fraction of the daily limit has been used.
FREE_WARN_FRACTION = float(os.environ.get("SCOUT_FREE_WARN_FRACTION", "0.9"))
# Where the local daily request counter lives.
USAGE_PATH = os.path.join(BASE_DIR, "usage.json")

# --- Whisper (local speech-to-text) ---------------------------------------
# "tiny" = fastest, "base" = more accurate. Override with SCOUT_WHISPER_MODEL.
WHISPER_MODEL = os.environ.get("SCOUT_WHISPER_MODEL", "base")

# --- Wake word (Picovoice Porcupine) --------------------------------------
PICOVOICE_ACCESS_KEY = os.environ.get("PICOVOICE_ACCESS_KEY", "")
# Path to the custom "Hello Claude" keyword file you download from Picovoice.
WAKE_KEYWORD_PATH = os.environ.get(
    "SCOUT_WAKE_KEYWORD_PATH", os.path.join(BASE_DIR, "Hello-Claude.ppn")
)
# Microphone device index for PvRecorder. -1 = default device (usually correct).
MIC_DEVICE_INDEX = int(os.environ.get("SCOUT_MIC_INDEX", "-1"))
# Frame size used when the wake word is OFF (Porcupine picks its own otherwise).
# 512 samples @ 16 kHz = 32 ms per read, the same cadence Porcupine uses.
DEFAULT_FRAME_LENGTH = 512


def wake_word_enabled():
    """Whether to run the "Hello Claude" wake word, or fall back to button-only.

    Defaults to "auto": the wake word turns itself on the moment BOTH a
    Picovoice access key and the keyword (.ppn) file are present, so you can
    enable it later just by adding them -- no code change needed. Force it
    either way with SCOUT_WAKE_WORD=on / off.
    """
    setting = os.environ.get("SCOUT_WAKE_WORD", "auto").strip().lower()
    if setting in ("on", "true", "1", "yes"):
        return True
    if setting in ("off", "false", "0", "no"):
        return False
    return bool(PICOVOICE_ACCESS_KEY) and os.path.exists(WAKE_KEYWORD_PATH)

# --- Audio capture / end-of-speech detection ------------------------------
SAMPLE_RATE = 16000           # Porcupine + Whisper + Resemblyzer all want 16 kHz
# Loudness (RMS of 16-bit samples) above which we consider a frame "speech".
# Raise it in a noisy room, lower it if it cuts you off. Tune with the number
# the program prints while listening.
ENERGY_THRESHOLD = float(os.environ.get("SCOUT_ENERGY_THRESHOLD", "350"))
SILENCE_SECONDS = 1.0         # this much trailing quiet = you're done talking
MAX_UTTERANCE_SECONDS = 15    # hard cap on one question
START_TIMEOUT_SECONDS = 6     # if you say nothing this long after the wake word, give up

# --- Speaker verification (Resemblyzer voiceprint) ------------------------
VOICEPRINT_PATH = os.path.join(BASE_DIR, "owner_voiceprint.npy")
# Cosine similarity needed to count as the owner. Higher = stricter.
SPEAKER_THRESHOLD = float(os.environ.get("SCOUT_SPEAKER_THRESHOLD", "0.75"))

# --- Google Sheets (saving found opportunities) ---------------------------
GOOGLE_CREDENTIALS_PATH = os.path.join(BASE_DIR, "google_credentials.json")
GOOGLE_TOKEN_PATH = os.path.join(BASE_DIR, "google_token.json")
GOOGLE_SHEET_ID = os.environ.get("SCOUT_GOOGLE_SHEET_ID", "")

# --- Conversation memory --------------------------------------------------
CONVERSATIONS_DIR = os.path.join(BASE_DIR, "conversations")

# --- The spoken personality / rules ---------------------------------------
SYSTEM_PROMPT_PATH = os.path.join(BASE_DIR, "system_prompt.txt")

# --- Piper neural TTS (much better voice than pico2wave / espeak) ---------
# Drop en_US-lessac-medium.onnx + its .json sidecar into ~/scout/piper-voices/
# and pip install piper-tts, then Scout will use it automatically.
# Override the model path with SCOUT_PIPER_MODEL.
PIPER_MODEL_PATH = os.environ.get(
    "SCOUT_PIPER_MODEL",
    os.path.join(BASE_DIR, "piper-voices", "en_US-lessac-medium.onnx")
)
