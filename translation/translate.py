#!/usr/bin/env python3
"""Translate Estonian text or finalized transcript JSONL, completely offline."""
import argparse
import json
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time

from approaches import load_engine
from streaming import Assembler

ROOT = Path(__file__).resolve().parent


def diagnostic(message):
    print(message, file=sys.stderr, flush=True)


class EventInput:
    def __init__(self, stream, capacity=128, *, backpressure=False):
        self.stream = stream
        self.events = queue.Queue(maxsize=capacity)
        self.done = threading.Event()
        self.error = None
        self.backpressure = backpressure
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        try:
            while not self.stop.is_set():
                line = self.stream.readline(65537)
                if not line:
                    break
                if len(line) > 65536:
                    raise ValueError("Input JSONL line exceeds 64 KB")
                if not line.strip():
                    continue
                event = json.loads(line)
                if self.backpressure:
                    while not self.stop.is_set():
                        try:
                            self.events.put((event, time.monotonic()), timeout=.1)
                            break
                        except queue.Full:
                            pass
                    continue
                try:
                    self.events.put_nowait((event, time.monotonic()))
                except queue.Full:
                    raise RuntimeError("Translation queue is full; stopping instead of dropping finalized text")
        except Exception as exc:
            self.error = exc
        finally:
            self.done.set()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", help="Translate one prepared phrase")
    parser.add_argument("--input", type=Path, help="Transcript JSONL file; default is stdin")
    parser.add_argument("--capture", action="store_true", help="Start the separate capture/transcription process")
    parser.add_argument("--audio-file", type=Path, help="File source for the capture process, paced in real time")
    parser.add_argument("--duration", type=float, help="Capture duration in seconds")
    parser.add_argument("--pid", type=int, action="append", default=[])
    parser.add_argument("--asr-engine", choices=["onnx", "whisper", "zipformer", "zipformer-large", "zipformer-en"], default="onnx")
    parser.add_argument("--vad", choices=["energy", "silero"], default="energy")
    parser.add_argument("--asr-interval", type=float, default=1.0)
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--translation-engine", choices=["nllb", "nllb-1.3b"], default="nllb")
    parser.add_argument("--translation-style", choices=["sentences", "block"], default="sentences")
    parser.add_argument("--source-lang", choices=["et", "en", "ru"], default="et")
    parser.add_argument("--target-lang", choices=["et", "en", "ru"], default="ru")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--beam-size", type=int, choices=[1, 2, 4], default=4)
    parser.add_argument("--card-layout", choices=["sentences", "groups"], default="sentences")
    parser.add_argument("--max-wait", type=float, default=2.5)
    parser.add_argument("--max-words", type=int, default=24)
    parser.add_argument("--format", choices=["text", "jsonl"], default="text")
    parser.add_argument("--forward-transcripts", action="store_true", help="Forward ASR events to JSONL consumers")
    parser.add_argument("--output", type=Path, help="Save translation JSONL (overwrites this file)")
    args = parser.parse_args()
    if args.asr_engine == "zipformer-en":
        args.source_lang = "en"
    if sum([args.text is not None, args.input is not None, args.capture]) > 1:
        parser.error("Choose --text, --input or --capture")
    if args.threads < 1 or args.max_wait <= 0 or args.max_words < 1:
        parser.error("Thread count, max wait and max words must be positive")
    if (args.audio_file or args.duration is not None or args.pid) and not args.capture:
        parser.error("Audio options require --capture")
    if args.duration is not None and args.duration <= 0:
        parser.error("--duration must be positive")
    if args.asr_interval <= 0 or any(pid <= 0 for pid in args.pid):
        parser.error("Invalid ASR interval or PID")
    if args.forward_transcripts and args.format != "jsonl":
        parser.error("--forward-transcripts requires --format jsonl")
    stopping = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    capture = None
    stream = None
    output = None
    reader = None
    assembler = Assembler(max_wait=args.max_wait, max_words=args.max_words, sentence_cards=args.card_layout == "sentences")
    group_number = 0
    revision = 0

    def emit(event):
        encoded = json.dumps(event, ensure_ascii=False)
        if output:
            output.write(encoded + "\n")
            output.flush()
        if args.format == "jsonl":
            print(encoded, flush=True)
        else:
            result = event["translation"] if event["status"] != "error" else f"[ERROR: {event['error']}]"
            marker = " (предварительно)" if event["status"] == "partial" else ""
            print(f"{args.source_lang.upper()}{marker}: {event['original']}\n{args.target_lang.upper()}{marker}: {result}\n", flush=True)

    try:
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            output = args.output.open("w", encoding="utf-8")
        started = time.monotonic()
        diagnostic(f"Loading local {args.translation_engine} INT8, {args.threads} CPU threads…")
        model = load_engine(args.translation_engine, model_dir=args.model_dir, threads=args.threads, beam_size=args.beam_size, style=args.translation_style)
        diagnostic(f"Model loaded in {time.monotonic() - started:.2f}s")

        def translate_group(events, status="final"):
            nonlocal group_number, revision
            if not events:
                return
            original = " ".join(event["text"].strip() for event in events)
            revision += 1
            event = {"version": 1, "type": "translation", "status": status,
                "session_id": events[0]["session_id"], "source": events[0]["source"],
                "group_id": group_number + 1, "revision": revision,
                "segment_ids": [e["segment_id"] for e in events],
                "source_lang": args.source_lang, "target_lang": args.target_lang,
                "translation_engine": args.translation_engine, "translation_style": args.translation_style, "beam_size": args.beam_size,
                "translation_input": original,
                "original": original,
                "audio_start": events[0]["audio_start"], "audio_end": events[-1]["audio_end"],
                "emitted_at": time.time()}
            try:
                translated, ms = model.translate(original, args.source_lang, args.target_lang)
            except Exception as exc:
                event.update(status="error", translation=None, error=str(exc))
                emit(event)
                raise
            event.update(translation=translated, translation_ms=round(ms, 1), emitted_at=time.time())
            if "emitted_at" in events[0]:
                event["since_first_asr_final_ms"] = round((time.time() - events[0]["emitted_at"]) * 1000, 1)
            if "inference_ms" in events[-1]:
                # Last ASR pass, not a sum: overlapping passes may emit several fragments.
                event["asr_last_inference_ms"] = events[-1]["inference_ms"]
                event["asr_inference_scope"] = events[-1].get("inference_scope", "window")
            if status == "final" and assembler.sentence_cards:
                # An ASR fragment can span several cards: preserve its untranslated tail in the UI.
                event["remaining_transcripts"] = [{"segment_id": e["segment_id"], "text": e["text"]}
                    for e in assembler.pending if e["session_id"] == event["session_id"]]
            emit(event)
            if status == "final":
                group_number += 1
            diagnostic(f"Translated {len(original.split())} words in {ms:.0f}ms")

        if args.text is not None:
            translate_group([{"session_id": "prepared-text", "source": "text", "segment_id": 1,
                "text": args.text, "audio_start": 0, "audio_end": 0}])
            return 0
        diagnostic("Warming up translation…")
        model.translate("Good morning!" if args.source_lang == "en" else "Tere hommikust!", args.source_lang, args.target_lang)
        if stopping.is_set():
            return 0
        if args.capture:
            command = [str(ROOT.parent / "capture-transcription/run.sh"), "--format", "jsonl", "--threads", "3", "--interval", str(args.asr_interval)]
            command += ["--engine", args.asr_engine, "--language", args.source_lang, "--vad", args.vad]
            if args.audio_file:
                command += ["--file", str(args.audio_file.resolve()), "--realtime"]
            if args.duration is not None:
                command += ["--duration", str(args.duration)]
            for pid in args.pid:
                command += ["--pid", str(pid)]
            capture = subprocess.Popen(command, stdout=subprocess.PIPE)
            stream = capture.stdout
        elif args.input:
            stream = args.input.open("rb")
        else:
            stream = sys.stdin.buffer
        reader = EventInput(stream, backpressure=bool(args.input))
        capture_stop_time = None
        diagnostic(f"Ready: {args.source_lang} → {args.target_lang}. Ctrl+C stops and drains pending text.")
        while True:
            if reader.error:
                raise reader.error
            if stopping.is_set():
                if capture and capture.poll() is None and capture_stop_time is None:
                    capture.terminate()
                    capture_stop_time = time.monotonic()
                elif not capture and reader.events.empty():
                    break
            if capture_stop_time and capture.poll() is None and time.monotonic() - capture_stop_time > 10:
                capture.kill()
                raise RuntimeError("Capture did not finish within 10 seconds after stop")
            try:
                event, arrived = reader.events.get(timeout=.1)
            except queue.Empty:
                if assembler.due(time.monotonic()):
                    translate_group(assembler.preview(time.monotonic()), status="partial")
                if reader.done.is_set() and reader.events.empty():
                    break
                continue
            if args.forward_transcripts:
                print(json.dumps(event, ensure_ascii=False), flush=True)
            # A timer produces an updatable preview, preserving context for numbers
            # and sentence endings that may arrive in the following ASR fragment.
            if assembler.due(arrived):
                translate_group(assembler.preview(arrived), status="partial")
            for group in assembler.accept(event, arrived):
                translate_group(group)
        translate_group(assembler.take())
        if capture:
            code = capture.wait(timeout=3)
            if code:
                raise RuntimeError(f"Capture/transcription exited with code {code}")
        return 0
    except (Exception, BrokenPipeError) as exc:
        diagnostic(f"ERROR: {exc}")
        return 1
    finally:
        if reader:
            reader.stop.set()
        if capture and capture.poll() is None:
            capture.terminate()
            try:
                capture.wait(timeout=3)
            except subprocess.TimeoutExpired:
                capture.kill()
                capture.wait()
        if reader and stream is not sys.stdin.buffer:
            reader.thread.join(timeout=1)
        if stream is not None and stream is not sys.stdin.buffer:
            stream.close()
        if output:
            output.close()


if __name__ == "__main__":
    raise SystemExit(main())
