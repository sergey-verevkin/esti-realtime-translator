#!/usr/bin/env python3
"""Local system-audio / file transcription. JSONL on stdout, diagnostics on stderr."""
import argparse
import json
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import uuid

import numpy as np

from streaming import SAMPLE_RATE, StreamProcessor, aligned_words

ROOT = Path(__file__).resolve().parent
CHUNK_BYTES = 3200 * 2  # 200ms int16 mono


def diagnostic(message):
    print(message, file=sys.stderr, flush=True)


class PCMSource:
    """Drain capture independently; overload is fatal and never silently drops audio."""
    def __init__(self, command, *, live, capacity=100):
        self.live = live
        self.capacity = capacity
        self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.error = None
        self.stop = threading.Event()
        self.done = threading.Event()
        self.chunks = queue.Queue(maxsize=capacity)
        self.threads = [threading.Thread(target=self._logs, daemon=True)]
        if live:
            self.threads.append(threading.Thread(target=self._reader, daemon=True))
        for thread in self.threads:
            thread.start()

    def _logs(self):
        for line in self.process.stderr:
            message = line.decode("utf-8", errors="replace").strip()
            if message.startswith("FORMAT "):
                try:
                    fmt = json.loads(message[7:])
                    if (fmt["sample_rate"], fmt["channels_per_frame"], fmt["bits_per_channel"], fmt["is_float"]) != (16000, 1, 16, False):
                        self.error = "Capture format mismatch"
                except (ValueError, KeyError) as exc:
                    self.error = f"Invalid capture metadata: {exc}"
            log_type = None
            if message.startswith("{"):
                try:
                    log_type = json.loads(message).get("message_type")
                except ValueError:
                    pass
            if log_type == "error" or message.startswith("Capture failed:"):
                self.error = message
            if message and log_type != "debug":
                diagnostic(message)

    def _reader(self):
        try:
            while not self.stop.is_set():
                data = self.process.stdout.read(CHUNK_BYTES)
                if not data:
                    break
                if len(data) % 2:
                    self.error = "Truncated int16 audio frame"
                    break
                try:
                    self.chunks.put_nowait((data, time.monotonic()))
                except queue.Full:
                    self.error = f"Audio queue exceeded {self.capacity * .2:g} seconds: processing cannot keep up. Try a longer --interval."
                    break
        except (OSError, ValueError) as exc:
            if not self.stop.is_set():
                self.error = str(exc)
        finally:
            self.done.set()

    def next(self):
        if self.error:
            raise RuntimeError(self.error)
        if not self.live:
            data = self.process.stdout.read(CHUNK_BYTES)
            if not data:
                code = self.process.wait()
                if code:
                    raise RuntimeError(f"Audio decoder exited with code {code}")
                return None
            return data, time.monotonic()
        try:
            return self.chunks.get(timeout=0.5)
        except queue.Empty:
            if self.done.is_set():
                code = self.process.poll()
                if code is None:
                    raise RuntimeError("Capture audio stream closed unexpectedly")
                raise RuntimeError(f"Capture stopped unexpectedly (exit {code}); check audio permission")
            return b"", time.monotonic()

    def close(self):
        self.stop.set()
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process.stdout.close()
        for thread in self.threads:
            thread.join(timeout=1)
        self.process.stderr.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, help="Replay an audio file through the same stream processor")
    parser.add_argument("--realtime", action="store_true", help="Pace file playback at its original speed")
    parser.add_argument("--pid", type=int, action="append", default=[], help="Capture only this PID (repeatable)")
    parser.add_argument("--model", default="mlx-community/parakeet-tdt-0.6b-v3")
    parser.add_argument("--engine", choices=["onnx", "mlx", "whisper", "zipformer", "zipformer-large", "zipformer-en"], default="onnx")
    parser.add_argument("--model-dir", type=Path, default=Path.home() / "Library/Application Support/com.pais.handy/models/parakeet-tdt-0.6b-v3-int8",
                        help="Existing Parakeet V3 INT8 directory (read only)")
    parser.add_argument("--whisper-model", type=Path, help="Local GGML TalTech Whisper file")
    parser.add_argument("--language", choices=["et", "en", "ru", "auto"], default="et", help="Language for Whisper; Parakeet detects automatically")
    parser.add_argument("--threads", type=int, default=4, help="CPU threads for ONNX")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds of new audio between ASR updates")
    parser.add_argument("--silence", type=float, default=0.8, help="Quiet duration before finalizing")
    parser.add_argument("--vad", choices=["energy", "silero"], default="energy", help="Speech detection mode")
    parser.add_argument("--threshold", type=float, default=0.003, help="RMS energy gate; not a speech classifier")
    parser.add_argument("--max-window", type=float, default=16.0)
    parser.add_argument("--duration", type=float, help="Stop capture after this many wall-clock seconds")
    parser.add_argument("--format", choices=["text", "jsonl"], default="text")
    parser.add_argument("--output", type=Path, help="Optional JSONL event file")
    parser.add_argument("--capture-only", action="store_true", help="Measure captured audio without loading an ASR model")
    args = parser.parse_args()
    if args.file and args.pid:
        parser.error("--pid cannot be used with --file")
    if args.file and not args.file.is_file():
        parser.error("Audio file does not exist")
    if args.duration is not None and args.duration <= 0:
        parser.error("--duration must be positive")
    if args.interval <= 0 or args.silence <= 0 or args.threshold < 0 or args.max_window < 2 * args.interval:
        parser.error("Invalid stream parameters")
    if any(pid <= 0 for pid in args.pid):
        parser.error("PID must be positive")
    if args.threads < 1:
        parser.error("--threads must be positive")

    output = None
    source = None
    processor = None
    detector = None
    stopping = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    drafts = [False]
    session_id = str(uuid.uuid4())

    def emit(event):
        event["session_id"] = session_id
        event["vad"] = args.vad
        encoded = json.dumps(event, ensure_ascii=False)
        if output:
            output.write(encoded + "\n")
            output.flush()
        if args.format == "jsonl":
            print(encoded, flush=True)
        elif event["status"] == "final":
            if drafts[0] and sys.stdout.isatty():
                print("\r\033[2K", end="")
            if event["text"]:
                print(f"[{event['audio_start']:7.2f}–{event['audio_end']:7.2f}] {event['text']}", flush=True)
            drafts[0] = False
        elif sys.stdout.isatty():
            text = event["text"][:180]
            print("\r\033[2K… " + text, end="", flush=True)
            drafts[0] = True

    try:
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            output = args.output.open("w", encoding="utf-8")
        if not args.capture_only:
            if args.engine == "onnx":
                # A generic model type plus an existing directory keeps the resolver offline.
                required = ["config.json", "encoder-model.int8.onnx", "decoder_joint-model.int8.onnx", "vocab.txt"]
                if not all((args.model_dir / name).is_file() for name in required):
                    raise RuntimeError("Parakeet V3 INT8 files not found. Set --model-dir to an existing model directory.")
                diagnostic(f"Loading existing Parakeet V3 INT8 (CPU, {args.threads} threads): {args.model_dir}")
                import onnx_asr
                import onnxruntime as rt
                options = rt.SessionOptions()
                options.intra_op_num_threads = args.threads
                options.inter_op_num_threads = 1
                model = onnx_asr.load_model("nemo-conformer-tdt", args.model_dir,
                    quantization="int8", sess_options=options,
                    providers=["CPUExecutionProvider"]).with_timestamps()

                def recognize(audio, offset):
                    result = model.recognize(audio, sample_rate=SAMPLE_RATE)
                    if result.tokens is None or result.timestamps is None:
                        raise RuntimeError("ASR did not return token timestamps")
                    # ONNX supplies onset timestamps, not measured word endings.
                    # One encoder frame (80ms) is an approximation for each token's end.
                    tokens = [SimpleNamespace(text=text, start=stamp, end=stamp + .08)
                              for text, stamp in zip(result.tokens, result.timestamps)]
                    return aligned_words(tokens, offset)
            elif args.engine in ("zipformer", "zipformer-large", "zipformer-en"):
                from zipformer_backend import load_recognizer, ZipformerProcessor
                diagnostic(f"Loading streaming {args.engine} INT8 (CPU)")
                zipformer = load_recognizer(args.threads, large=args.engine == "zipformer-large", english=args.engine == "zipformer-en")
            elif args.engine == "whisper":
                from whisper_backend import WhisperRecognizer, MODEL_PATH
                diagnostic(f"Loading TalTech Whisper Turbo via Metal: {args.whisper_model or MODEL_PATH}")
                recognize = WhisperRecognizer(args.whisper_model or MODEL_PATH, language=args.language, threads=args.threads)
            else:
                diagnostic(f"Loading MLX Parakeet V3: {args.model}. First launch may download 2.5 GB.")
                import mlx.core as mx
                from parakeet_mlx import from_pretrained
                from parakeet_mlx.audio import get_logmel
                model = from_pretrained(args.model)
                if model.preprocessor_config.sample_rate != SAMPLE_RATE:
                    raise RuntimeError("Model sample rate is not 16 kHz")

                def recognize(audio, offset):
                    result = model.generate(get_logmel(mx.array(audio), model.preprocessor_config))[0]
                    return aligned_words(result.tokens, offset)

            if args.engine not in ("zipformer", "zipformer-large", "zipformer-en"):
                diagnostic("Warming up the model…")
                recognize(np.zeros(SAMPLE_RATE, dtype=np.float32), 0)
            if args.vad == "silero":
                from vad import SileroVAD
                detector = SileroVAD()
                diagnostic("Speech detection: Silero VAD CPU (onset 96ms; pause 0.8s)")
            else:
                diagnostic("Speech detection: energy threshold")
            options = dict(source="file" if args.file else "system", silence=args.silence,
                           threshold=args.threshold, max_window=args.max_window, speech_detector=detector)
            if args.engine in ("zipformer", "zipformer-large", "zipformer-en"):
                punctuator = None
                if args.engine == "zipformer-en":
                    from punctuation import EnglishPunctuation
                    punctuator = EnglishPunctuation()
                    diagnostic("English punctuation and casing: Edge-Punct-Casing INT8")
                processor = ZipformerProcessor(zipformer, emit, engine=args.engine, punctuator=punctuator, **options)
            else:
                processor = StreamProcessor(recognize, emit, interval=args.interval, **options)
        if stopping.is_set():
            return 0
        if args.file:
            command = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(args.file),
                       "-f", "s16le", "-ac", "1", "-ar", "16000", "pipe:1"]
        else:
            binary = ROOT / ".build/release/realtime-capture"
            if not binary.exists():
                raise RuntimeError("Capture component missing. Run ./setup.sh first.")
            command = [str(binary)]
            for pid in args.pid:
                command += ["--pid", str(pid)]
        source = PCMSource(command, live=not bool(args.file))
        started = time.monotonic()
        received = 0
        peak = 0.0
        last_data = started
        last_report = started
        max_queue_age = 0.0
        diagnostic("Listening. Ctrl+C stops capture and finalizes the remaining text.")
        while not stopping.is_set():
            now = time.monotonic()
            if args.duration and now - started >= args.duration:
                break
            item = source.next()
            if item is None:
                break
            data, captured_at = item
            if not data:
                if now - last_data > 12:
                    raise RuntimeError("No audio buffers for 12 seconds. Check permission, output device and PID.")
                continue
            last_data = time.monotonic()
            samples = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
            received += len(samples)
            peak = max(peak, float(np.max(np.abs(samples))))
            max_queue_age = max(max_queue_age, time.monotonic() - captured_at)
            if processor:
                processor.feed(samples)
            if args.file and args.realtime:
                wait = started + received / SAMPLE_RATE - time.monotonic()
                if wait > 0:
                    stopping.wait(wait)
            if time.monotonic() - last_report >= 5:
                diagnostic(f"audio={received / SAMPLE_RATE:.1f}s peak={peak:.4f} queue={source.chunks.qsize() * .2:.1f}s")
                last_report = time.monotonic()
        # Stop the producer, then drain the bounded queue before final ASR.
        source.stop.set()
        if source.live:
            if source.process.poll() is None:
                source.process.terminate()
                source.process.wait(timeout=3)
            for thread in source.threads:
                thread.join(timeout=1)
            while not source.chunks.empty():
                data, captured_at = source.chunks.get_nowait()
                samples = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
                received += len(samples)
                if processor:
                    processor.feed(samples)
        if processor:
            processor.finish()
        elapsed = time.monotonic() - started
        diagnostic(f"Finished: audio={received / SAMPLE_RATE:.2f}s wall={elapsed:.2f}s peak={peak:.4f} max_queue_age={max_queue_age:.2f}s")
        if processor and processor.inference_seconds:
            diagnostic(f"ASR calls={processor.calls}; recent p50={np.percentile(processor.inference_seconds, 50):.2f}s p95={np.percentile(processor.inference_seconds, 95):.2f}s")
        punctuator = getattr(processor, "punctuator", None)
        if punctuator and punctuator.calls:
            diagnostic(f"Punctuation calls={punctuator.calls}; average={punctuator.seconds * 1000 / punctuator.calls:.2f}ms; total={punctuator.seconds:.3f}s")
        if detector and detector.frames:
            diagnostic(f"VAD frames={detector.frames}; average={detector.seconds * 1000 / detector.frames:.3f}ms/frame; total={detector.seconds:.3f}s")
        if peak < 0.0001:
            diagnostic("Captured digital silence. This does not verify audio permission or speech recognition.")
        return 0
    except Exception as exc:
        diagnostic(f"ERROR: {exc}")
        if processor:
            try:
                processor.finish()
            except Exception as final_exc:
                diagnostic(f"Could not finalize remaining text: {final_exc}")
        return 1
    finally:
        if source:
            source.close()
        if output:
            output.close()


if __name__ == "__main__":
    raise SystemExit(main())
