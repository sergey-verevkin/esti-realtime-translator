"""Interchangeable offline engines and conservative sentence-level translation."""
from pathlib import Path
import re
import time
from engine import NLLB, MODEL_DIR

ABBREVIATIONS = {"nt", "jne", "dr", "hr", "pr", "prof", "s.t", "s.o", "st", "nr", "lk", "a", "e", "vt"}


def sentence_parts(text):
    """Keep punctuation, decimals and common Estonian abbreviations intact."""
    chunks = []
    start = 0
    for match in re.finditer(r'[.!?]+["»”)]*(?:\s+|$)', text):
        punctuation = match.group().lstrip()
        if punctuation.startswith('.'):
            word = re.search(r'([\w.]+)$', text[:match.start()])
            if word and word.group(1).casefold() in ABBREVIATIONS:
                continue
            next_text = text[match.end():].lstrip('„“"«(')
            if next_text and not next_text[0].isupper():
                continue
        chunk = text[start:match.end()].strip()
        if chunk:
            chunks.append((chunk, True))
        start = match.end()
    remainder = text[start:].strip()
    if remainder:
        chunks.append((remainder, False))
    return chunks


def sentences(text):
    return [chunk for chunk, _ in sentence_parts(text)]


class SentenceTranslator:
    def __init__(self, engine, *, style='sentences'):
        self.engine = engine
        self.style = style

    def translate(self, text, source_lang='et', target_lang='ru'):
        if self.style == 'block':
            return self.engine.translate(text, source_lang, target_lang)
        started = time.monotonic()
        outputs = [self.engine.translate(sentence, source_lang, target_lang)[0] for sentence in sentences(text)]
        return ' '.join(outputs), (time.monotonic() - started) * 1000


def load_engine(name='nllb', *, threads=2, beam_size=4, style='sentences', model_dir=None):
    directories = {'nllb': MODEL_DIR, 'nllb-1.3b': MODEL_DIR.parent / 'nllb-1.3b-int8'}
    if name not in directories:
        raise ValueError(f'Unknown translation engine: {name}')
    directory = model_dir if model_dir is not None else directories[name]
    return SentenceTranslator(NLLB(directory, threads=threads, beam_size=beam_size), style=style)
