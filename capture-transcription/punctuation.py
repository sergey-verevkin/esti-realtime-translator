"""English casing/punctuation; guard against changing recognized words."""
import re
import time
from download_punctuation import MODEL_DIR, FILES


def word_spans(text):
    return list(re.finditer(r"\w+(?:['’]\w+)*", text))


def word_keys(text):
    return [m.group().casefold().replace('’', "'") for m in word_spans(text)]


class EnglishPunctuation:
    def __init__(self):
        if not all((MODEL_DIR / name).is_file() for name in FILES):
            raise RuntimeError('English punctuation missing. Run capture-transcription/setup-zipformer-en.sh')
        import sherpa_onnx
        self.model = sherpa_onnx.OnlinePunctuation(sherpa_onnx.OnlinePunctuationConfig(
            sherpa_onnx.OnlinePunctuationModelConfig(cnn_bilstm=str(MODEL_DIR / 'model.int8.onnx'),
                bpe_vocab=str(MODEL_DIR / 'bpe.vocab'), num_threads=1, provider='cpu')))
        self.last_input = None
        self.last_output = ''
        self.seconds = 0.0
        self.calls = 0
        self.last_ms = 0.0

    def __call__(self, text):
        if text == self.last_input: return self.last_output
        started = time.monotonic()
        result = self.model.add_punctuation_with_case(text.lower()).strip() if text.strip() else ''
        elapsed = time.monotonic() - started
        self.seconds += elapsed; self.calls += 1; self.last_ms = elapsed * 1000
        # A formatter must not drop, add, or replace ASR words. Preserve input
        # on unexpected tokenizer behavior rather than silently losing speech.
        if word_keys(result) != word_keys(text):
            result = text
        self.last_input, self.last_output = text, result
        return result
