import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from approaches import sentences, SentenceTranslator

class TranslationApproachTests(unittest.TestCase):
    def test_question_exclamation_and_time_are_all_kept(self):
        text = 'Kui palju kell on? Appi! Kell on juba kolmveerand kaksteist!'
        self.assertEqual(sentences(text), ['Kui palju kell on?', 'Appi!', 'Kell on juba kolmveerand kaksteist!'])

    def test_decimal_abbreviations_quotes_and_fragment(self):
        self.assertEqual(sentences('Nt. kell 11.45. „Tere!” Järgmine'), ['Nt. kell 11.45.', '„Tere!”', 'Järgmine'])
        self.assertEqual(sentences('See on nt. õpetaja näide.'), ['See on nt. õpetaja näide.'])

    def test_sentence_only_engine_does_not_drop_following_sentence(self):
        class FirstSentenceOnly:
            def translate(self, text, *args): return text.split('!')[0] + '!', 1
        engine = SentenceTranslator(FirstSentenceOnly())
        self.assertEqual(engine.translate('Esimene! Teine!')[0], 'Esimene! Teine!')
        self.assertEqual(SentenceTranslator(FirstSentenceOnly(), style='block').translate('Esimene! Teine!')[0], 'Esimene!')
