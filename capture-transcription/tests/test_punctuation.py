import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from punctuation import EnglishPunctuation, word_keys
from zipformer_backend import ZipformerProcessor
from test_zipformer import Recognizer


class Model:
    def __init__(self, result): self.result = result; self.calls = 0
    def add_punctuation_with_case(self, text): self.calls += 1; return self.result


def formatter(result):
    p = EnglishPunctuation.__new__(EnglishPunctuation)
    p.model = Model(result); p.last_input = None; p.last_output = ''
    p.seconds = 0.; p.calls = 0; p.last_ms = 0.
    return p


class PunctuationTests(unittest.TestCase):
    def test_words_preserved_and_cached(self):
        p = formatter("I don't know. Is John coming?")
        source = "I DON'T KNOW IS JOHN COMING"
        self.assertEqual(word_keys(p(source)), word_keys(source))
        self.assertEqual(p(source), "I don't know. Is John coming?")
        self.assertEqual(p.model.calls, 1)
        p = formatter('Hello.')
        self.assertEqual(p('HELLO EVERYONE'), 'HELLO EVERYONE')

    def test_context_and_pause_preserve_all_words_and_punctuation(self):
        outputs = {
            'HOW ARE YOU': 'How are you?',
            'HOW ARE YOU I AM': 'How are you? I am',
            'I AM FINE THANK YOU': 'I am fine. Thank you.',
            'THANK YOU': 'Thank you.',
        }
        events = []
        r = Recognizer(['HOW ARE YOU', 'HOW ARE YOU I AM', 'HOW ARE YOU I AM FINE THANK YOU',
                        'HOW ARE YOU I AM FINE THANK YOU'])
        p = ZipformerProcessor(r, events.append, punctuator=lambda t: outputs[t], engine='zipformer-en')
        p.feed(np.ones(3200, dtype=np.float32))
        self.assertFalse(any(e['status'] == 'final' for e in events))
        p.feed(np.ones(3200, dtype=np.float32))
        self.assertEqual(events[-2]['text'], 'How are you?')
        p.feed(np.ones(3200, dtype=np.float32)); p.finish(); p.finish()
        finals = [e for e in events if e['status'] == 'final']
        self.assertEqual([e['text'] for e in finals], ['How are you?', 'I am fine.', 'Thank you.'])
        self.assertEqual(word_keys(' '.join(e['text'] for e in finals)), word_keys('HOW ARE YOU I AM FINE THANK YOU'))
        self.assertEqual([e['segment_id'] for e in finals], [1, 2, 3])

    def test_unpunctuated_long_tail_flushed_at_limit(self):
        events = []
        r = Recognizer(['NO BOUNDARY HERE', 'NO BOUNDARY HERE'])
        p = ZipformerProcessor(r, events.append, max_window=.2, punctuator=lambda s: s.lower())
        p.feed(np.ones(3200, dtype=np.float32))
        self.assertEqual(events[-1]['status'], 'final')
        self.assertEqual(events[-1]['reason'], 'window_limit')
        self.assertEqual(events[-1]['text'], 'no boundary here')


if __name__ == '__main__': unittest.main()
