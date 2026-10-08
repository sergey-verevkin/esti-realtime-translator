import sys
from pathlib import Path
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vad import SileroVAD
from streaming import StreamProcessor, Word


def fake_vad():
    vad = SileroVAD.__new__(SileroVAD)
    vad.threshold = .5; vad.release_threshold = .35; vad.start_frames = 3
    vad.reset()
    vad.probabilities = []
    def probability(frame):
        value = float(frame[0]); vad.probabilities.append(value); return value
    vad._probability = probability
    return vad


class VADTests(unittest.TestCase):
    def test_short_spike_does_not_activate_and_release_has_hysteresis(self):
        vad = fake_vad()
        self.assertFalse(vad._classify(.9))
        self.assertFalse(vad._classify(.1))
        self.assertFalse(vad._classify(.9))
        self.assertFalse(vad._classify(.9))
        self.assertTrue(vad._classify(.9))
        self.assertTrue(vad._classify(.4))
        self.assertFalse(vad._classify(.2))

    def test_framing_independent_of_capture_chunk_boundaries(self):
        audio = np.concatenate([np.full(512, p, dtype=np.float32) for p in [.1, .9, .9, .9, .4, .2, .1]])
        expected = fake_vad(); expected(audio)
        actual = fake_vad()
        for start in range(0, len(audio), 137): actual(audio[start:start + 137])
        self.assertEqual(actual.probabilities, expected.probabilities)
        self.assertEqual(actual.speaking, expected.speaking)
        self.assertEqual(len(actual.buffer), 0)

    def test_every_frame_processed_after_activation_and_remainder_bounded(self):
        vad = fake_vad()
        audio = np.concatenate([np.full(512, p) for p in [.9, .9, .9, .1, .1, .1]])
        self.assertTrue(vad(audio))
        self.assertEqual(len(vad.probabilities), 6)
        self.assertFalse(vad.speaking)
        self.assertFalse(vad(np.zeros(256)))
        self.assertEqual(len(vad.buffer), 256)
        with self.assertRaises(ValueError): vad(np.array([float('nan')]))

    def test_noisy_non_speech_does_not_call_recognizer(self):
        calls = []
        processor = StreamProcessor(lambda *args: calls.append(args) or [], lambda _: None, speech_detector=lambda _: False)
        for _ in range(300): processor.feed(np.full(3200, .2))
        processor.finish()
        self.assertEqual(calls, [])
        self.assertLessEqual(len(processor.audio), 6400)

    def test_quiet_speech_passes_and_noisy_pause_closes_phrase(self):
        activity = iter([True, True, True, False, False, False, False])
        events = []
        processor = StreamProcessor(lambda audio, offset: [Word('Tere!', offset, offset + .2)], events.append,
            speech_detector=lambda _: next(activity), interval=3)
        for _ in range(3): processor.feed(np.full(3200, .0001))  # Below the former energy threshold.
        for _ in range(4): processor.feed(np.full(3200, .2))  # Loud non-speech is a pause now.
        self.assertFalse(processor.active)
        self.assertEqual([(e['text'], e['reason']) for e in events], [('Tere!', 'pause')])


if __name__ == '__main__': unittest.main()
