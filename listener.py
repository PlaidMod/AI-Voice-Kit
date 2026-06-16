"""
The ears. Handles the microphone, the "Hello Claude" wake word, and capturing a
spoken question.

ONE library owns the mic the whole time: PvRecorder. The idle loop feeds frames
to Porcupine (the wake-word detector). When the wake word fires (or the button
is pressed), we keep reading from the same recorder to capture the question,
stopping when we hear about a second of silence.

The wake word is OPTIONAL. If no Picovoice key/keyword file is present (see
config.wake_word_enabled), Scout skips Porcupine entirely and you trigger it
with the button instead -- everything else works exactly the same.
"""

import math
from collections import deque

import numpy as np
from pvrecorder import PvRecorder

import config


def _rms(frame):
    """Loudness of one frame (list of 16-bit ints) as a single number."""
    if not frame:
        return 0.0
    acc = sum(sample * sample for sample in frame)
    return math.sqrt(acc / len(frame))


def record_seconds(recorder, seconds):
    """Record a fixed number of seconds and return float32 audio in [-1, 1].

    Used by enroll.py. `recorder` must already be started.
    """
    frames = []
    num_reads = int(seconds * config.SAMPLE_RATE / recorder.frame_length)
    for _ in range(num_reads):
        frames.extend(recorder.read())
    return np.array(frames, dtype=np.int16).astype(np.float32) / 32768.0


class Listener:
    def __init__(self):
        # Porcupine listens for the custom "Hello Claude" keyword -- but only if
        # it's available. With no key/keyword file we run button-only and the
        # mic just feeds the question capture.
        self.porcupine = None
        if config.wake_word_enabled():
            import pvporcupine
            self.porcupine = pvporcupine.create(
                access_key=config.PICOVOICE_ACCESS_KEY,
                keyword_paths=[config.WAKE_KEYWORD_PATH],
            )
            self.frame_length = self.porcupine.frame_length
        else:
            self.frame_length = config.DEFAULT_FRAME_LENGTH

        # PvRecorder feeds frames of exactly the size we expect. We do NOT start
        # it here. main.py starts the mic only during the two windows where we
        # actually listen (waiting for the trigger, and capturing a question).
        # Stopping it the rest of the time means the greeting/answer audio never
        # gets buffered and mistaken for speech, and a fresh buffer each time
        # avoids stale-audio false triggers.
        self.recorder = PvRecorder(
            frame_length=self.frame_length,
            device_index=config.MIC_DEVICE_INDEX,
        )
        self._running = False
        self.frame_seconds = self.frame_length / config.SAMPLE_RATE

    def start(self):
        """Begin (or restart with a clean buffer) microphone capture."""
        if self._running:
            self.recorder.stop()
        self.recorder.start()
        self._running = True

    def stop(self):
        """Stop the microphone so nothing is buffered while we talk/think."""
        if self._running:
            self.recorder.stop()
            self._running = False

    def wait_for_trigger(self, button_event):
        """
        Block until the wake word is heard OR the button is pressed.

        Returns "wake" or "button". `button_event` is a threading.Event set by
        the button thread in main.py. When the wake word is off, we just drain
        the mic (so the buffer stays current) and wait for the button.
        """
        while True:
            frame = self.recorder.read()           # blocks ~32 ms per frame
            if self.porcupine is not None and self.porcupine.process(frame) >= 0:
                return "wake"                       # >= 0 means keyword detected
            if button_event.is_set():
                button_event.clear()
                return "button"

    def capture_utterance(self):
        """
        Record the user's question. Returns float32 audio, or None if they
        never started speaking (just silence after the wake word).

        We keep a tiny rolling pre-buffer so the first word isn't clipped.
        """
        silence_limit = int(config.SILENCE_SECONDS / self.frame_seconds)
        start_limit = int(config.START_TIMEOUT_SECONDS / self.frame_seconds)
        max_frames = int(config.MAX_UTTERANCE_SECONDS / self.frame_seconds)

        prebuffer = deque(maxlen=4)   # last few frames before speech starts
        frames = []
        started = False
        silent_run = 0
        waited = 0

        while True:
            frame = self.recorder.read()
            loudness = _rms(frame)

            if not started:
                prebuffer.append(frame)
                if loudness >= config.ENERGY_THRESHOLD:
                    started = True
                    for buffered in prebuffer:       # include the lead-in
                        frames.extend(buffered)
                else:
                    waited += 1
                    if waited >= start_limit:
                        return None                  # nobody spoke
            else:
                frames.extend(frame)
                if loudness < config.ENERGY_THRESHOLD:
                    silent_run += 1
                else:
                    silent_run = 0
                if silent_run >= silence_limit or len(frames) >= max_frames * self.frame_length:
                    break

        return np.array(frames, dtype=np.int16).astype(np.float32) / 32768.0

    def close(self):
        try:
            if self._running:
                self.recorder.stop()
            self.recorder.delete()
        finally:
            if self.porcupine is not None:
                self.porcupine.delete()
