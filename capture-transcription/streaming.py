"""Bounded audio windows and local-agreement events, independent of MLX and capture."""
from dataclasses import dataclass
import re
import time

import numpy as np

SAMPLE_RATE = 16000


@dataclass
class Word:
    text: str
    start: float
    end: float

    @property
    def key(self):
        return self.text.casefold().strip(".,!?;:–—\"'()[]")


def aligned_words(tokens, offset=0.0):
    """Join subword tokens before finding whole words; retain audio timestamps."""
    text = "".join(token.text for token in tokens)
    spans = []
    for token in tokens:
        spans.extend([(offset + token.start, offset + token.end)] * len(token.text))
    return [
        Word(match.group(), spans[match.start()][0], spans[match.end() - 1][1])
        for match in re.finditer(r"\S+", text)
    ]


class StreamProcessor:
    def __init__(self, recognize, emit, *, source="system", interval=1.0,
                 silence=0.8, threshold=0.003, max_window=16.0, speech_detector=None):
        if interval <= 0 or silence <= 0 or max_window < 2 * interval or threshold < 0:
            raise ValueError("Invalid stream parameters")
        self.speech_detector = speech_detector
        self.recognize = recognize
        self.emit = emit
        self.source = source
        self.interval = interval
        self.silence = silence
        self.threshold = threshold
        self.max_window = max_window
        self.audio = np.empty(0, dtype=np.float32)
        self.offset = 0.0
        self.seen = 0
        self.last_run = 0.0
        self.quiet = 0.0
        self.active = False
        self.previous = []
        self.committed_until = -1.0
        self.committed_words = []
        self.segment = 1
        self.revision = 0
        self.last_partial = None
        self.inference_seconds = []
        self.calls = 0

    @property
    def audio_time(self):
        return self.seen / SAMPLE_RATE

    def _event(self, words, status, reason, inference_ms):
        text = " ".join(word.text for word in words)
        if status == "partial" and text == self.last_partial:
            return
        if status == "partial" and not text and self.last_partial is None:
            return
        self.revision += 1
        self.emit({
            "version": 1, "type": "transcript", "source": self.source,
            "segment_id": self.segment, "revision": self.revision,
            "status": status, "text": text,
            "audio_start": round(words[0].start if words else self.audio_time, 3),
            "audio_end": round(words[-1].end if words else self.audio_time, 3),
            "audio_received_until": round(self.audio_time, 3),
            "emitted_at": time.time(), "reason": reason,
            "inference_ms": round(inference_ms, 1),
        })
        if status == "final":
            self.segment += 1
            self.last_partial = None
        else:
            self.last_partial = text

    def _run(self, final=False, reason="agreement"):
        if not len(self.audio):
            return
        started = time.monotonic()
        words = self.recognize(self.audio, self.offset)
        duration = time.monotonic() - started
        self.calls += 1
        self.inference_seconds.append(duration)
        # Only a bounded sample is needed for diagnostics on long meetings.
        self.inference_seconds = self.inference_seconds[-200:]
        inference_ms = duration * 1000
        words = self._uncommitted(words)
        if final:
            if words or self.last_partial is not None:
                self._event(words, "final", reason, inference_ms)
            if words:
                self.committed_until = words[-1].end
                self.committed_words = (self.committed_words + words)[-32:]
            self.previous = []
        else:
            stable = 0
            for old, new in zip(self.previous, words):
                if (old.key != new.key or abs(old.end - new.end) > 0.6
                        or new.end > self.audio_time - 0.8):
                    break
                stable += 1
            # Keep two trailing words provisional to avoid committing truncated words.
            stable = min(stable, max(0, len(words) - 2))
            if stable:
                self._event(words[:stable], "final", reason, inference_ms)
                self.committed_until = words[stable - 1].end
                self.committed_words = (self.committed_words + words[:stable])[-32:]
                words = words[stable:]
            self._event(words, "partial", "hypothesis", inference_ms)
            self.previous = words
        self.last_run = self.audio_time

    def _uncommitted(self, words):
        if not self.committed_words:
            return words
        # Timing can drift between overlapping passes. Match a textual suffix of
        # committed words before falling back to time, rather than trusting end times.
        for count in range(min(8, len(self.committed_words)), 0, -1):
            tail = self.committed_words[-count:]
            candidates = []
            for start in range(len(words) - count + 1):
                candidate = words[start:start + count]
                if (all(a.key == b.key for a, b in zip(tail, candidate))
                        and abs(candidate[-1].end - tail[-1].end) < .6):
                    candidates.append((abs(candidate[-1].end - tail[-1].end), start + count))
            if candidates:
                return words[min(candidates)[1]:]
        last = self.committed_words[-1]
        midpoint = (last.start + last.end) / 2
        return [word for word in words if (word.start + word.end) / 2 > midpoint + .03]

    def _trim(self):
        # Retain left audio context. Absolute timestamps suppress already committed words.
        target = self.committed_until - 1.2
        samples = min(len(self.audio), max(0, int((target - self.offset) * SAMPLE_RATE)))
        if samples:
            self.audio = self.audio[samples:].copy()
            self.offset += samples / SAMPLE_RATE

    def feed(self, samples):
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim != 1 or len(samples) > SAMPLE_RATE:
            raise ValueError("Feed mono chunks no larger than one second")
        if not len(samples):
            return
        before = self.audio_time
        self.seen += len(samples)
        rms = float(np.sqrt(np.mean(samples * samples)))
        speech = bool(self.speech_detector(samples)) if self.speech_detector is not None else rms >= self.threshold
        if not self.active:
            if not speech:
                # Keep a short pre-roll so word onsets are not discarded by the gate.
                self.audio = np.concatenate((self.audio, samples))[-int(0.4 * SAMPLE_RATE):]
                self.offset = self.audio_time - len(self.audio) / SAMPLE_RATE
                return
            self.active = True
            self.quiet = 0.0
            self.last_run = before
        self.audio = np.concatenate((self.audio, samples))
        self.quiet = 0.0 if speech else self.quiet + len(samples) / SAMPLE_RATE
        if self.quiet >= self.silence:
            self._run(final=True, reason="pause")
            self.audio = np.empty(0, dtype=np.float32)
            self.offset = self.audio_time
            self.active = False
            self.quiet = 0.0
        elif len(self.audio) / SAMPLE_RATE >= self.max_window:
            self._run(final=True, reason="window_limit")
            self._trim()
            # If the model produces no words, there is no boundary to trim at.
            # Close this bounded window explicitly instead of growing memory forever.
            if len(self.audio) / SAMPLE_RATE >= self.max_window:
                self.audio = self.audio[-int(0.6 * SAMPLE_RATE):].copy()
                self.offset = self.audio_time - len(self.audio) / SAMPLE_RATE
        elif self.audio_time - self.last_run >= self.interval:
            self._run()
            # Keep utterance context until a pause or the bounded window limit.
            # Trimming on every live pass can change lexical choices mid-sentence.

    def finish(self):
        if self.active:
            self._run(final=True, reason="stop")
            self.active = False
        self.audio = np.empty(0, dtype=np.float32)
