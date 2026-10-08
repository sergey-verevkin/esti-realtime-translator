"""Incremental TalTech Zipformer: each captured sample enters the decoder once."""
import time
import re
import numpy as np
from download_zipformer import MODEL_DIR, FILES
from streaming import SAMPLE_RATE


def load_recognizer(threads=3, *, large=False, english=False):
    model_dir, files = MODEL_DIR, FILES
    if large:
        from download_zipformer_large import MODEL_DIR as large_dir, FILES as large_files
        model_dir, files = large_dir, large_files
    if english:
        from download_zipformer_en import MODEL_DIR as en_dir, FILES as en_files
        model_dir, files = en_dir, en_files
    if not all((model_dir / name).is_file() for name in files):
        raise RuntimeError('Zipformer is missing. Run capture-transcription/setup-zipformer' + ('-en' if english else '-large' if large else '') + '.sh')
    import sherpa_onnx
    return sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=str(model_dir / 'tokens.txt'),
        encoder=str(model_dir / 'encoder.int8.onnx'),
        decoder=str(model_dir / 'decoder.int8.onnx'),
        joiner=str(model_dir / 'joiner.int8.onnx'),
        num_threads=threads, sample_rate=SAMPLE_RATE, feature_dim=80,
        decoding_method='greedy_search', enable_endpoint_detection=False, provider='cpu',
    )


class ZipformerProcessor:
    def __init__(self, recognizer, emit, *, source='system', silence=.8,
                 threshold=.003, max_window=16, speech_detector=None, engine='zipformer', punctuator=None):
        self.recognizer, self.emit, self.source = recognizer, emit, source
        self.engine = engine
        self.punctuator = punctuator
        self.silence, self.threshold, self.max_window = silence, threshold, max_window
        self.speech_detector = speech_detector
        self.stream = None
        self.pre_roll = np.empty(0, dtype=np.float32)
        self.seen = 0
        self.start = 0.0
        self.quiet = 0.0
        self.committed = ''
        self.segment = 1
        self.revision = 0
        self.last_partial = None
        self.calls = 0
        self.inference_seconds = []
        self.last_ms = 0.0

    @property
    def audio_time(self):
        return self.seen / SAMPLE_RATE

    def _decode(self, samples, final=False):
        started = time.monotonic()
        self.stream.accept_waveform(SAMPLE_RATE, samples)
        if final:
            self.stream.input_finished()
        decoded = False
        while self.recognizer.is_ready(self.stream):
            self.recognizer.decode_stream(self.stream)
            decoded = True
        if decoded:
            elapsed = time.monotonic() - started
            self.last_ms = elapsed * 1000
            self.calls += 1
            self.inference_seconds = (self.inference_seconds + [elapsed])[-200:]
        return self.recognizer.get_result(self.stream).strip()

    def _event(self, text, status, reason):
        if status == 'partial' and (text == self.last_partial or not text and self.last_partial is None):
            return
        self.revision += 1
        self.emit(dict(version=1, type='transcript', source=self.source,
                       segment_id=self.segment, revision=self.revision, status=status, text=text,
                       audio_start=round(self.start, 3), audio_end=round(self.audio_time, 3),
                       audio_received_until=round(self.audio_time, 3), emitted_at=time.time(),
                       reason=reason, inference_ms=round(self.last_ms, 1),
                       inference_scope='stream_chunk', asr_engine=self.engine,
                       punctuation_ms=round(getattr(self.punctuator, 'last_ms', 0.0), 1)))
        if status == 'final':
            self.segment += 1
            self.last_partial = None
        else:
            self.last_partial = text

    def _publish(self, text, final=False, reason='agreement'):
        # Greedy transducer decoding extends its token sequence; retain the last
        # two words so a following subword/punctuation token cannot change a final.
        if not text.startswith(self.committed):
            raise RuntimeError('Zipformer changed a committed prefix')
        tail = text[len(self.committed):].strip()
        if self.punctuator is not None:
            self._publish_punctuated(text, tail, final, reason)
            return
        if final:
            self._event(tail, 'final', reason)  # Empty boundary also flushes MT.
            return
        words = tail.split()
        if len(words) > 2:
            # Locate the exact source prefix; preserve original whitespace.
            boundary = list(re.finditer(r'\S+', tail))[-3].end()
            prefix = tail[:boundary]
            self._event(prefix, 'final', 'agreement')
            end = text.find(tail, len(self.committed)) + boundary
            self.committed = text[:end]
            tail = text[end:].strip()
        self._event(tail, 'partial', 'hypothesis')

    def _publish_punctuated(self, text, tail, final, reason):
        from punctuation import word_spans, word_keys
        formatted = self.punctuator(tail)
        if final:
            if formatted and reason in ('pause', 'stop') and not re.search(r'[.!?][\"»”)]*$', formatted):
                formatted += '.'
            self._event(formatted, 'final', reason)
            return
        raw_words = word_spans(tail)
        # Only commit a predicted sentence if at least two following words
        # have arrived. Terminal punctuation at a growing tail is provisional.
        boundary = None
        for match in re.finditer(r'[.!?]+["»”)]*(?:\s+|$)', formatted):
            prefix = formatted[:match.end()].strip()
            before = re.search(r'(\w+)$', formatted[:match.start()])
            if match.group().startswith('.') and before and before.group(1).casefold() in {'mr', 'mrs', 'ms', 'dr', 'prof', 'sr', 'jr', 'vs', 'etc'}:
                continue
            count = len(word_spans(prefix))
            if 0 < count <= len(raw_words) - 2 and word_keys(prefix) == word_keys(tail)[:count]:
                boundary = (match.end(), count)
        if boundary:
            end, count = boundary
            self._event(formatted[:end].strip(), 'final', 'agreement')
            raw_end = raw_words[count - 1].end()
            self.committed = text[:text.find(tail, len(self.committed)) + raw_end]
            formatted = formatted[end:].strip()
        self._event(formatted, 'partial', 'hypothesis')

    def _close(self, reason):
        if self.stream is None:
            return
        # Flush the encoder's right context. Padding is not captured audio and
        # must not advance user-visible timestamps or enter the next stream.
        text = self._decode(np.zeros(SAMPLE_RATE, dtype=np.float32), final=True)
        self._publish(text, final=True, reason=reason)
        self.stream = None
        self.committed = ''
        self.quiet = 0.0

    def feed(self, samples):
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim != 1 or len(samples) > SAMPLE_RATE or not np.all(np.isfinite(samples)):
            raise ValueError('Feed finite mono chunks no larger than one second')
        if not len(samples):
            return
        self.seen += len(samples)
        speech = bool(self.speech_detector(samples)) if self.speech_detector is not None else float(np.sqrt(np.mean(samples * samples))) >= self.threshold
        if self.stream is None:
            if not speech:
                self.pre_roll = np.concatenate((self.pre_roll, samples))[-6400:]
                return
            audio = np.concatenate((self.pre_roll, samples))
            self.pre_roll = np.empty(0, dtype=np.float32)
            self.start = self.audio_time - len(audio) / SAMPLE_RATE
            self.stream = self.recognizer.create_stream()
        else:
            audio = samples
        self.quiet = 0.0 if speech else self.quiet + len(samples) / SAMPLE_RATE
        text = self._decode(audio)
        self._publish(text)
        if self.quiet >= self.silence:
            self._close('pause')
        elif self.audio_time - self.start >= self.max_window:
            self._close('window_limit')

    def finish(self):
        self._close('stop')
        self.pre_roll = np.empty(0, dtype=np.float32)
