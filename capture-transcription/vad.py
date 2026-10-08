"""Stateful 16 kHz Silero ONNX inference, with bounded framing and speech onset confirmation.

ONNX input/state/context layout follows the upstream OnnxWrapper at the pinned
revision in download_vad.py. Uses NumPy and the existing ONNX Runtime; no Torch.
"""
from pathlib import Path
import time
import numpy as np

MODEL_PATH = Path(__file__).resolve().parent / 'models/silero-vad/silero_vad.onnx'


class SileroVAD:
    frame_samples = 512  # 32 ms at 16 kHz

    def __init__(self, path=MODEL_PATH, *, threshold=.5, release_threshold=.35, start_frames=3):
        if not 0 <= release_threshold <= threshold <= 1 or start_frames < 1:
            raise ValueError('Invalid VAD thresholds')
        import onnxruntime as ort
        if not Path(path).is_file():
            raise FileNotFoundError('Silero VAD is not installed. Run capture-transcription/download_vad.py')
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(path), sess_options=options, providers=['CPUExecutionProvider'])
        self.threshold = threshold
        self.release_threshold = release_threshold
        self.start_frames = start_frames
        self.frames = 0
        self.seconds = 0.0
        self.reset()

    def reset(self):
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.context = np.zeros((1, 64), dtype=np.float32)
        self.buffer = np.empty(0, dtype=np.float32)
        self.speaking = False
        self.onset_frames = 0
        self.last_probability = 0.0

    def _probability(self, frame):
        model_input = np.concatenate((self.context, frame.reshape(1, -1)), axis=1)
        started = time.monotonic()
        result, self.state = self.session.run(None, {
            'input': model_input, 'state': self.state, 'sr': np.array(16000, dtype=np.int64),
        })
        self.seconds += time.monotonic() - started
        self.frames += 1
        self.context = model_input[:, -64:].copy()
        probability = float(np.asarray(result).reshape(-1)[0])
        if not np.isfinite(probability):
            raise RuntimeError('VAD returned a non-finite probability')
        return probability

    def _classify(self, probability):
        self.last_probability = probability
        if self.speaking:
            if probability < self.release_threshold:
                self.speaking = False
                self.onset_frames = 0
        elif probability >= self.threshold:
            self.onset_frames += 1
            if self.onset_frames >= self.start_frames:
                self.speaking = True
        else:
            self.onset_frames = 0
        return self.speaking

    def __call__(self, samples):
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim != 1 or len(samples) > 16000 or not np.all(np.isfinite(samples)):
            raise ValueError('VAD expects finite mono chunks of at most one second')
        self.buffer = np.concatenate((self.buffer, samples))
        speech = False
        processed = 0
        while len(self.buffer) - processed >= self.frame_samples:
            frame = self.buffer[processed:processed + self.frame_samples]
            # Evaluate every frame to keep state continuous, even once speech is confirmed.
            detected = self._classify(self._probability(frame))
            speech = speech or detected
            processed += self.frame_samples
        self.buffer = self.buffer[processed:].copy()
        return speech if processed else self.speaking
