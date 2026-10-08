import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from streaming import Assembler
from translate import EventInput
import io


def event(number, text, *, status="final", session="s", reason="agreement"):
    return {"version": 1, "type": "transcript", "status": status,
        "session_id": session, "source": "system", "segment_id": number,
        "revision": number, "text": text, "reason": reason,
        "audio_start": number, "audio_end": number + .5}


class AssemblyTests(unittest.TestCase):
    def test_drafts_ignored_and_final_fragments_grouped(self):
        a = Assembler()
        self.assertEqual(a.accept(event(1, "vale", status="partial"), 0), [])
        a.accept(event(1, "Tere"), 0)
        a.accept(event(2, "hommikust"), 1)
        self.assertFalse(a.due(2))
        self.assertTrue(a.due(2.5))
        self.assertEqual(len(a.preview(2.5)), 2)
        self.assertFalse(a.due(10))
        self.assertEqual([e["text"] for e in a.take()], ["Tere", "hommikust"])

    def test_timer_does_not_separate_number_from_its_sentence(self):
        a = Assembler()
        a.accept(event(1, "Good morning. The meeting starts tomorrow at"), 0)
        preview = a.preview(2.5)
        self.assertEqual(len(preview), 1)
        groups = a.accept(event(2, "10. Please send me the documents before Friday.", reason="stop"), 3)
        self.assertIn("at 10.", " ".join(e["text"] for e in groups[0]))

    def test_pause_stop_and_eof_preserve_remaining_words(self):
        for reason in ("pause", "stop", "window_limit"):
            a = Assembler()
            a.accept(event(1, "Tere"), 0)
            groups = a.accept(event(2, "hommikust", reason=reason), 1)
            self.assertEqual(len(groups[0]), 2)
            self.assertIsNone(a.take())
        a = Assembler()
        a.accept(event(1, "Lühike fraas"), 0)
        self.assertEqual(len(a.take()), 1)

    def test_duplicate_final_not_translated_twice(self):
        a = Assembler()
        a.accept(event(1, "Tere"), 0)
        a.accept(event(1, "Tere"), 1)
        self.assertEqual(len(a.take()), 1)
        with self.assertRaisesRegex(ValueError, "changed"):
            a.accept(event(1, "Muutunud"), 2)

    def test_out_of_order_is_explicit(self):
        a = Assembler()
        a.accept(event(2, "Teine"), 0)
        with self.assertRaisesRegex(ValueError, "out of order"):
            a.accept(event(1, "Esimene"), 1)

    def test_sessions_are_never_mixed(self):
        a = Assembler()
        a.accept(event(1, "Esimene", session="a"), 0)
        ready = a.accept(event(1, "Teine", session="b"), 1)
        self.assertEqual(ready[0][0]["session_id"], "a")
        self.assertEqual(a.take()[0]["session_id"], "b")

    def test_word_limit_and_sentence_boundary(self):
        a = Assembler(max_words=3)
        self.assertEqual(len(a.accept(event(1, "üks kaks kolm"), 0)[0]), 1)
        a = Assembler()
        self.assertTrue(a.accept(event(1, "Täna räägime sellest kuidas meie projekt edeneb."), 0))

    def test_cancelled_hypothesis_not_translated(self):
        a = Assembler()
        self.assertEqual(a.accept(event(1, "", reason="stop"), 0), [])
        self.assertIsNone(a.take())

    def test_invalid_protocol_and_nonfinite_times_rejected(self):
        a = Assembler()
        with self.assertRaises(ValueError):
            a.accept({"version": 2}, 0)
        bad = event(1, "Tere")
        bad["audio_end"] = float("nan")
        with self.assertRaises(ValueError):
            a.accept(bad, 0)

    def test_session_tracking_bounded(self):
        a = Assembler()
        for i in range(100):
            a.accept(event(1, "Tere", session=str(i)), i)
        self.assertLessEqual(len(a.seen), 16)


class SentenceCardTests(unittest.TestCase):
    def text(self, group):
        return " ".join(e["text"] for e in group)

    def test_multiple_sentences_and_unfinished_tail(self):
        a = Assembler(sentence_cards=True)
        groups = a.accept(event(1, "Tere hommikust! Täna õpime eesti keelt. Homme"), 0)
        self.assertEqual([self.text(g) for g in groups], ["Tere hommikust!", "Täna õpime eesti keelt."])
        self.assertEqual(self.text(a.pending), "Homme")
        groups = a.accept(event(2, "räägime edasi.", reason="pause"), 1)
        self.assertEqual([self.text(g) for g in groups], ["Homme räägime edasi."])
        self.assertIsNone(a.take())

    def test_preview_tail_number_and_duplicate(self):
        a = Assembler(sentence_cards=True)
        groups = a.accept(event(1, "Good morning. The meeting starts tomorrow at"), 0)
        self.assertEqual(self.text(groups[0]), "Good morning.")
        self.assertTrue(a.due(2.5))
        self.assertEqual(self.text(a.preview(2.5)), "The meeting starts tomorrow at")
        self.assertEqual(a.accept(event(1, "Good morning. The meeting starts tomorrow at"), 3), [])
        groups = a.accept(event(2, "10. Please send me the documents before Friday.", reason="stop"), 4)
        self.assertEqual([self.text(g) for g in groups], ["The meeting starts tomorrow at 10.", "Please send me the documents before Friday."])

    def test_abbreviations_and_decimals(self):
        a = Assembler(sentence_cards=True)
        groups = a.accept(event(1, 'Nt. kell 11.45. „Tere!” Järgmine'), 0)
        self.assertEqual([self.text(g) for g in groups], ['Nt. kell 11.45.', '„Tere!”'])
        self.assertEqual(self.text(a.pending), 'Järgmine')

    def test_hard_limit_preserves_every_word(self):
        for punctuation in ("", "."):
            a = Assembler(sentence_cards=True, max_words=3)
            text = "üks kaks kolm neli viis kuus seitse" + punctuation
            groups = a.accept(event(1, text), 0)
            self.assertEqual([self.text(g) for g in groups[:2]], ["üks kaks kolm", "neli viis kuus"])
            tail = a.take()
            if tail: groups.append(tail)
            self.assertEqual(" ".join(self.text(g) for g in groups), text)

    def test_empty_pause_and_new_session_flush_tail(self):
        a = Assembler(sentence_cards=True)
        a.accept(event(1, "Pooleli"), 0)
        groups = a.accept(event(2, "", reason="pause"), 1)
        self.assertEqual(self.text(groups[0]), "Pooleli")
        a.accept(event(1, "Esimene", session="a"), 2)
        groups = a.accept(event(1, "Teine.", session="b"), 3)
        self.assertEqual([self.text(g) for g in groups], ["Esimene", "Teine."])


class ReaderTests(unittest.TestCase):
    def test_overflow_visible(self):
        stream = io.BytesIO(b'{"version":1}\n' * 10)
        reader = EventInput(stream, capacity=1)
        self.assertTrue(reader.done.wait(1))
        self.assertIsInstance(reader.error, RuntimeError)
        self.assertEqual(reader.events.qsize(), 1)

    def test_long_line_rejected(self):
        reader = EventInput(io.BytesIO(b"x" * 65537))
        self.assertTrue(reader.done.wait(1))
        self.assertIsInstance(reader.error, ValueError)

    def test_recorded_file_uses_bounded_backpressure(self):
        reader = EventInput(io.BytesIO(b'{"version":1}\n' * 1000), capacity=1, backpressure=True)
        count = 0
        while count < 1000:
            reader.events.get(timeout=1)
            count += 1
        self.assertTrue(reader.done.wait(1))
        self.assertIsNone(reader.error)


if __name__ == "__main__":
    unittest.main()
