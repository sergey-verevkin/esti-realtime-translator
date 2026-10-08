import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from zipformer_backend import ZipformerProcessor


class Stream:
    def __init__(self):
        self.audio = []
        self.ready = False
        self.finished = False
        self.text = ''
    def accept_waveform(self, rate, samples):
        self.audio.extend(samples.tolist())
        self.ready = True
    def input_finished(self):
        self.finished = True


class Recognizer:
    def __init__(self, texts):
        self.texts = iter(texts)
        self.streams = []
    def create_stream(self):
        s = Stream(); self.streams.append(s); return s
    def is_ready(self, s):
        return s.ready
    def decode_stream(self, s):
        s.ready = False
        s.text = next(self.texts, s.text)
    def get_result(self, s):
        return s.text


class ZipformerTests(unittest.TestCase):
    def make(self, texts, **kwargs):
        events = []
        r = Recognizer(texts)
        p = ZipformerProcessor(r, events.append, **kwargs)
        return p, r, events

    def test_incremental_samples_and_final_text_are_not_duplicated(self):
        p, r, events = self.make(['Tere', 'Tere hommik', 'Tere hommikust kõigile.', 'Tere hommikust kõigile.'])
        for value in [.1, .2, .3]:
            p.feed(np.full(3200, value, dtype=np.float32))
        p.finish(); p.finish()
        self.assertEqual(len(r.streams), 1)
        self.assertEqual(len(r.streams[0].audio), 9600 + 16000)
        self.assertAlmostEqual(r.streams[0].audio[3200], .2)
        self.assertEqual(' '.join(e['text'] for e in events if e['status'] == 'final'), 'Tere hommikust kõigile.')
        self.assertEqual(events[-1]['audio_end'], .6)
        self.assertEqual(events[-1]['reason'], 'stop')
        self.assertTrue(r.streams[0].finished)

    def test_noise_gate_preroll_pause_and_new_stream(self):
        p, r, events = self.make(['Üks.', 'Üks.', 'Üks.', 'Üks.', 'Kaks.', 'Kaks.'],
                                speech_detector=lambda x: x[0] > .5, silence=.4)
        for _ in range(8):
            p.feed(np.full(3200, .1, dtype=np.float32))
        self.assertEqual(r.streams, [])
        p.feed(np.ones(3200, dtype=np.float32))
        p.feed(np.zeros(3200, dtype=np.float32))
        p.feed(np.zeros(3200, dtype=np.float32))
        self.assertIsNone(p.stream)
        self.assertEqual(events[-1]['reason'], 'pause')
        self.assertEqual(events[-1]['audio_start'], 1.2)
        p.feed(np.ones(3200, dtype=np.float32)); p.finish()
        self.assertEqual(len(r.streams), 2)
        self.assertEqual([e['text'] for e in events if e['status'] == 'final'], ['Üks.', 'Kaks.'])
        ids = [e['segment_id'] for e in events if e['status'] == 'final']
        self.assertEqual(ids, [1, 2])

    def test_long_speech_bounded_and_empty_finish(self):
        p, r, events = self.make(['Tere'] * 12, max_window=1)
        for _ in range(10): p.feed(np.ones(3200, dtype=np.float32))
        p.finish()
        self.assertEqual(len(r.streams), 2)
        self.assertEqual([e['reason'] for e in events if e['status'] == 'final'], ['window_limit', 'window_limit'])
        p, r, events = self.make([])
        p.finish(); self.assertEqual(events, [])

    def test_punctuation_survives_across_committed_fragments(self):
        p, r, events = self.make(['Tere kõigile. Hello', 'Tere kõigile. Hello world!',
                                  'Tere kõigile. Hello world! Kuidas läheb?',
                                  'Tere kõigile. Hello world! Kuidas läheb?'], engine='zipformer-large')
        for _ in range(3): p.feed(np.ones(3200, dtype=np.float32))
        p.finish()
        text = ' '.join(e['text'] for e in events if e['status'] == 'final')
        self.assertEqual(text, 'Tere kõigile. Hello world! Kuidas läheb?')
        self.assertTrue(all(e['asr_engine'] == 'zipformer-large' for e in events))

    def test_empty_pause_still_emits_boundary(self):
        p, r, events = self.make([''], silence=.2)
        p.feed(np.ones(3200, dtype=np.float32))
        p.feed(np.zeros(3200, dtype=np.float32))
        self.assertEqual(events[-1]['text'], '')
        self.assertEqual(events[-1]['reason'], 'pause')


if __name__ == '__main__': unittest.main()
