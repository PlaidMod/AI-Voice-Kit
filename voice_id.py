"""
Speaker verification ("is this really the owner talking?").

We use Resemblyzer to turn a clip of speech into a 256-number "voiceprint."
During setup you run enroll.py to record YOUR voice and save your voiceprint.
After that, every question is compared to it; if it doesn't match closely
enough, Scout refuses to answer.

If Resemblyzer isn't installed, or you haven't enrolled yet, verification is
treated as "off" (everyone is allowed) so the device still works -- run
enroll.py to actually lock it to your voice.
"""

import os

import numpy as np

from config import SAMPLE_RATE, SPEAKER_THRESHOLD, VOICEPRINT_PATH

try:
    from resemblyzer import VoiceEncoder, preprocess_wav
    AVAILABLE = True
except Exception:  # library missing or failed to import
    AVAILABLE = False

_encoder = None      # the (heavy) model, loaded once on first use
_owner = None        # the owner's saved voiceprint, loaded once


def _get_encoder():
    global _encoder
    if _encoder is None:
        _encoder = VoiceEncoder()   # downloads/loads the model the first time
    return _encoder


def embed(audio_float32):
    """Turn a 16 kHz float32 audio clip into a normalized voiceprint vector."""
    processed = preprocess_wav(audio_float32, source_sr=SAMPLE_RATE)
    return _get_encoder().embed_utterance(processed)


def save_voiceprint(embeddings):
    """Average several enrollment clips into one voiceprint and save it."""
    mean = np.mean(np.stack(embeddings), axis=0)
    mean = mean / np.linalg.norm(mean)        # keep it unit-length
    np.save(VOICEPRINT_PATH, mean)


def has_voiceprint():
    return os.path.exists(VOICEPRINT_PATH)


def _get_owner():
    global _owner
    if _owner is None and has_voiceprint():
        _owner = np.load(VOICEPRINT_PATH)
    return _owner


def is_owner(audio_float32):
    """
    Return True if this audio sounds like the enrolled owner.

    If verification is unavailable or not enrolled, return True (feature off).
    """
    if not AVAILABLE or not has_voiceprint():
        return True
    try:
        voiceprint = embed(audio_float32)
        owner = _get_owner()
        # Both vectors are unit-length, so the dot product is the cosine
        # similarity (1.0 = identical voice, ~0 = totally different).
        similarity = float(np.dot(voiceprint, owner))
        print(f"  [voice match: {similarity:.2f} / need {SPEAKER_THRESHOLD:.2f}]")
        return similarity >= SPEAKER_THRESHOLD
    except Exception as e:
        # If something goes wrong, fail OPEN (answer anyway) rather than lock
        # the owner out. Flip this to `return False` if you prefer fail-closed.
        print(f"  [voice check error: {e}]")
        return True
