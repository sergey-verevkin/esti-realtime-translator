"""Assemble immutable ASR fragments into translation groups, with bounded state."""
from collections import OrderedDict
import re
import math
from approaches import sentence_parts


class Assembler:
    def __init__(self, *, max_wait=2.5, max_words=24, sentence_cards=False):
        self.sentence_cards = sentence_cards
        self.max_wait = max_wait
        self.max_words = max_words
        self.pending = []
        self.started = None
        self.preview_at = None
        self.preview_text = None
        self.seen = OrderedDict()

    def take(self):
        if not self.pending:
            return None
        events = self.pending
        self.pending = []
        self.started = None
        self.preview_at = None
        self.preview_text = None
        return events

    def due(self, now):
        text = " ".join(e["text"] for e in self.pending)
        return (bool(self.pending) and text != self.preview_text
                and now - (self.preview_at if self.preview_at is not None else self.started) >= self.max_wait)

    def preview(self, now):
        self.preview_at = now
        self.preview_text = " ".join(e["text"] for e in self.pending)
        return list(self.pending)

    def _prefix(self, count):
        """Remove characters from joined pending text, keeping source metadata on each slice."""
        taken = []
        while self.pending and count > 0:
            event = self.pending[0]
            text = event["text"].strip()
            if count >= len(text):
                taken.append({**event, "text": text})
                self.pending.pop(0)
                count -= len(text) + 1  # joining space
            else:
                taken.append({**event, "text": text[:count].strip()})
                self.pending[0] = {**event, "text": text[count:].strip()}
                count = 0
        self.preview_at = None
        self.preview_text = None
        if not self.pending:
            self.started = None
        return taken

    def _sentence_groups(self, now, force=False):
        groups = []
        while self.pending:
            text = " ".join(e["text"].strip() for e in self.pending)
            first, complete = sentence_parts(text)[0]
            if complete and len(first.split()) <= self.max_words:
                groups.append(self._prefix(len(first)))
            elif len(text.split()) >= self.max_words:
                # A strict fallback for long speech with missing punctuation.
                words = list(re.finditer(r"\S+", text))
                groups.append(self._prefix(words[self.max_words - 1].end()))
            elif force:
                groups.append(self.take())
            else:
                break
        if groups and self.pending:
            self.started = now
        return groups

    def accept(self, event, now):
        ready = []
        if not isinstance(event, dict) or event.get("version") != 1 or event.get("type") != "transcript":
            raise ValueError("Expected a version 1 transcript event")
        if event.get("status") not in ("partial", "final") or not isinstance(event.get("text"), str):
            raise ValueError("Invalid transcript status/text")
        # Source metadata is validated even on ignored hypotheses.
        for name in ("session_id", "source"):
            if not isinstance(event.get(name), str) or not event[name]:
                raise ValueError(f"Missing {name}")
        for name in ("segment_id", "revision"):
            if type(event.get(name)) is not int or event[name] < 1:
                raise ValueError(f"Invalid {name}")
        if event["status"] != "final":
            return ready
        key = (event["session_id"], event["source"])
        last_id, last_text = self.seen.get(key, (0, None))
        if event["segment_id"] < last_id:
            raise ValueError("Finalized transcript fragments arrived out of order")
        if event["segment_id"] == last_id:
            if event["text"] != last_text:
                raise ValueError("A finalized transcript fragment was changed")
            return ready
        self.seen[key] = (event["segment_id"], event["text"])
        self.seen.move_to_end(key)
        while len(self.seen) > 16:
            self.seen.popitem(last=False)
        if self.pending and (self.pending[0]["session_id"], self.pending[0]["source"]) != key:
            ready.append(self.take())
        if not event["text"].strip():
            if event.get("reason") in ("pause", "stop", "window_limit") and self.pending:
                ready.extend(self._sentence_groups(now, force=True) if self.sentence_cards else [self.take()])
            return ready
        for name in ("audio_start", "audio_end"):
            if type(event.get(name)) not in (int, float) or not math.isfinite(event[name]):
                raise ValueError(f"Invalid {name}")
        if event["audio_end"] < event["audio_start"]:
            raise ValueError("Invalid audio interval")
        if self.started is None:
            self.started = now
        self.pending.append(event)
        if self.sentence_cards:
            ready.extend(self._sentence_groups(now, force=event.get("reason") in ("pause", "stop", "window_limit")))
            return ready
        words = sum(len(item["text"].split()) for item in self.pending)
        if (event.get("reason") in ("pause", "stop", "window_limit")
                or words >= self.max_words
                or (words >= 6 and re.search(r"[.!?][\"»)]?$", event["text"].strip()))):
            ready.append(self.take())
        return ready
