"""
All of Scout's settings in one place.

Most things can be overridden with environment variables (handy for systemd),
but the defaults are sensible for an AIY Voice Kit V1 on a Raspberry Pi 3B.
"""

import os

# Folder this file lives in. All data files sit next to the code.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- OpenAI (GPT-5.5) -----------------------------------------------------
# Override the model with SCOUT_MODEL if your OpenAI account exposes a different
# string (e.g. a dated or "pro" variant). gpt-5.5 has a 1M-token context window
# and supports the server-side web_search tool.
MODEL = os.environ.get("SCOUT_MODEL", "gpt-5.5")
# Ceiling for one answer. NOTE: on GPT-5 reasoning models this budget also
# covers the model's hidden reasoning tokens, so keep generous headroom above
# the few spoken bullets we want, or the visible answer can come back empty.
MAX_TOKENS = int(os.environ.get("SCOUT_MAX_TOKENS", "2000"))

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
