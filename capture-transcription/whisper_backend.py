"""TalTech Whisper via persistent whisper.cpp context and Apple Metal."""
from pathlib import Path
import numpy as np
from streaming import Word, SAMPLE_RATE

MODEL_PATH = Path(__file__).resolve().parent / "models/whisper-taltech/ggml-model.bin"

class WhisperRecognizer:
    def __init__(self, path=MODEL_PATH, *, language="et", threads=4):
        path = Path(path)
        if not path.is_file():
            raise RuntimeError("TalTech Whisper is not installed. Run capture-transcription/setup-whisper.sh")
        from pywhispercpp.model import Model
        self.model = Model(str(path), context_params={"use_gpu": True, "flash_attn": True},
                           n_threads=threads, language=language, translate=False,
                           no_context=True, print_progress=False, print_realtime=False,
                           print_timestamps=False, token_timestamps=True,
                           max_len=1, split_on_word=True, temperature=0.0,
                           temperature_inc=0.0)

    def __call__(self, audio, offset):
        # whisper.cpp word segments use 10ms units. Keep a persistent GPU context.
        duration = len(audio) / SAMPLE_RATE
        segments = self.model.transcribe(np.asarray(audio, dtype=np.float32))
        words = []
        for segment in segments:
            text = segment.text.strip()
            if not text:
                continue
            start = max(0.0, min(duration, segment.t0 / 100))
            end = max(start, min(duration, segment.t1 / 100))
            words.append(Word(text, offset + start, offset + end))
        return words
