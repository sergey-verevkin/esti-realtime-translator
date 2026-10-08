"""Offline NLLB inference; SentencePiece token strings match the CT2 vocabulary."""
from pathlib import Path
import time

MODEL_DIR = Path(__file__).resolve().parent / "models/nllb-600m-int8"
LANGUAGES = {"et": "est_Latn", "en": "eng_Latn", "ru": "rus_Cyrl"}


class NLLB:
    def __init__(self, model_dir=MODEL_DIR, *, threads=2, beam_size=4):
        import ctranslate2
        import sentencepiece as spm
        model_dir = Path(model_dir)
        for name in ["model.bin", "config.json", "sentencepiece.bpe.model"]:
            if not (model_dir / name).is_file():
                raise FileNotFoundError(f"Missing {model_dir / name}. Install the selected translation model first.")
        if not any((model_dir / name).is_file() for name in ["shared_vocabulary.json", "shared_vocabulary.txt"]):
            raise FileNotFoundError(f"Missing vocabulary in {model_dir}")
        self.tokenizer = spm.SentencePieceProcessor(model_file=str(model_dir / "sentencepiece.bpe.model"))
        self.translator = ctranslate2.Translator(str(model_dir), device="cpu",
            compute_type="int8", inter_threads=1, intra_threads=threads)
        self.beam_size = beam_size

    def translate(self, text, source_lang="et", target_lang="ru"):
        if not text.strip():
            return "", 0.0
        if source_lang == target_lang:
            return text, 0.0
        pieces = self.tokenizer.encode(text, out_type=str)
        if len(pieces) > 480:
            raise ValueError("Input is too long for one translation; split it into shorter phrases")
        # NLLB's current tokenizer format: source language prefix, text, EOS.
        source = [LANGUAGES[source_lang], *pieces, "</s>"]
        started = time.monotonic()
        result = self.translator.translate_batch([source],
            target_prefix=[[LANGUAGES[target_lang]]], beam_size=self.beam_size,
            max_input_length=512, max_decoding_length=256,
            return_end_token=True)[0].hypotheses[0]
        elapsed = (time.monotonic() - started) * 1000
        if "</s>" not in result:
            raise RuntimeError("Translation reached the decoding limit without completing")
        special = {LANGUAGES[target_lang], "</s>", "<s>", "<pad>"}
        translated = self.tokenizer.decode([piece for piece in result if piece not in special]).strip()
        if not translated:
            raise RuntimeError("Model returned an empty translation")
        return translated, elapsed
