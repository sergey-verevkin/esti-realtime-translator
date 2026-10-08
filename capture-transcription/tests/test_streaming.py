import sys
from pathlib import Path
import unittest
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from streaming import SAMPLE_RATE, StreamProcessor, Word, aligned_words


class StreamTests(unittest.TestCase):
    def test_live_passes_keep_sentence_context_until_window_limit(self):
        offsets = []
        events = []
        def recognize(audio, offset):
            offsets.append(offset)
            end = offset + len(audio) / SAMPLE_RATE
            return [Word(f"word{i}", i * .5, (i + 1) * .5)
                    for i in range(20) if (i + 1) * .5 <= end and i * .5 >= offset]
        processor = StreamProcessor(recognize, events.append, max_window=16)
        for _ in range(50):
            processor.feed(np.full(3200, .1))
        self.assertTrue(any(e["status"] == "final" for e in events))
        self.assertTrue(all(offset == 0 for offset in offsets))
        self.assertAlmostEqual(len(processor.audio) / SAMPLE_RATE, 10)

    def test_subword_timestamps(self):
        tokens = [SimpleNamespace(text=" Tere", start=.1, end=.3),
                  SimpleNamespace(text="mast", start=.3, end=.5),
                  SimpleNamespace(text=" maailm!", start=.5, end=.9)]
        words = aligned_words(tokens, 10)
        self.assertEqual([w.text for w in words], ["Teremast", "maailm!"])
        self.assertEqual((words[0].start, words[0].end), (10.1, 10.5))

    def test_agreement_and_eof_replace_same_fragment(self):
        events = []
        vocabulary = ["Tere", "täna", "me", "räägime", "eesti", "keeles."]
        def recognize(audio, offset):
            end = offset + len(audio) / SAMPLE_RATE
            return [Word(text, i * .6, (i + 1) * .6)
                    for i, text in enumerate(vocabulary)
                    if (i + 1) * .6 <= end and (i + 1) * .6 > offset]
        processor = StreamProcessor(recognize, events.append, interval=1)
        for _ in range(25):
            processor.feed(np.full(3200, .1, dtype=np.float32))
        processor.finish()
        finals = [e for e in events if e["status"] == "final"]
        self.assertEqual(" ".join(e["text"] for e in finals), " ".join(vocabulary))
        self.assertTrue(any(e["status"] == "partial" for e in events))
        self.assertEqual(finals[-1]["reason"], "stop")
        final_ids = [e["segment_id"] for e in finals]
        self.assertEqual(len(set(final_ids)), len(final_ids))
        for e in events:
            self.assertIn(e["segment_id"], final_ids)

    def test_corrected_draft_is_not_committed(self):
        calls = [0]
        events = []
        def recognize(audio, offset):
            calls[0] += 1
            text = "vale" if calls[0] == 1 else "õige"
            return [Word(text, 0, .4), Word("tekst", .5, .8), Word("siin", .8, 1)]
        processor = StreamProcessor(recognize, events.append, interval=1)
        for _ in range(15):
            processor.feed(np.full(3200, .1))
        processor.finish()
        self.assertNotIn("vale", " ".join(e["text"] for e in events if e["status"] == "final"))
        self.assertEqual(" ".join(e["text"] for e in events if e["status"] == "final"), "õige tekst siin")

    def test_pause_and_silence_do_not_repeat(self):
        events = []
        calls = [0]
        def recognize(audio, offset):
            calls[0] += 1
            return [Word("Tere!", offset, offset + .3)]
        processor = StreamProcessor(recognize, events.append, interval=1)
        for _ in range(3):
            processor.feed(np.full(3200, .1))
        for _ in range(30):
            processor.feed(np.zeros(3200))
        processor.finish()
        self.assertEqual(calls[0], 2)  # One live hypothesis and one pause finalization.
        self.assertEqual([(e["text"], e["reason"]) for e in events if e["status"] == "final"], [("Tere!", "pause")])

    def test_long_audio_is_bounded_without_hypotheses(self):
        processor = StreamProcessor(lambda *_: [], lambda _: None, max_window=4)
        for _ in range(1500):
            processor.feed(np.full(3200, .1))
            self.assertLessEqual(len(processor.audio), int(4.2 * SAMPLE_RATE))
        self.assertLessEqual(len(processor.inference_seconds), 200)

    def test_long_audio_commits_each_word_once_across_trims(self):
        events = []
        vocabulary = [f"word{i}" for i in range(100)]
        def recognize(audio, offset):
            end = offset + len(audio) / SAMPLE_RATE
            return [Word(text, i * .7, (i + 1) * .7)
                    for i, text in enumerate(vocabulary)
                    if (i + 1) * .7 <= end and (i + 1) * .7 > offset]
        processor = StreamProcessor(recognize, events.append, max_window=8)
        for _ in range(360):
            processor.feed(np.full(3200, .1))
            self.assertLessEqual(len(processor.audio), int(8.2 * SAMPLE_RATE))
        processor.finish()
        self.assertEqual(" ".join(e["text"] for e in events if e["status"] == "final"), " ".join(vocabulary))

    def test_cancel_disappearing_draft(self):
        events = []
        calls = [0]
        def recognize(*_):
            calls[0] += 1
            return [Word("draft", 0, .5)] if calls[0] == 1 else []
        processor = StreamProcessor(recognize, events.append)
        for _ in range(10):
            processor.feed(np.full(3200, .1))
        processor.finish()
        self.assertEqual(events[-1]["status"], "final")
        self.assertEqual(events[-1]["text"], "")

    def test_committed_word_timestamp_drift_does_not_duplicate(self):
        processor = StreamProcessor(lambda *_: [], lambda _: None)
        processor.committed_words = [Word("мы", .5, .64), Word("проверяем", .72, 1.2)]
        processor.committed_until = 1.2
        words = [Word("мы", .5, .64), Word("проверяем", .72, 1.28), Word("речь", 1.3, 1.8)]
        self.assertEqual([w.text for w in processor._uncommitted(words)], ["речь"])


if __name__ == "__main__":
    unittest.main()
