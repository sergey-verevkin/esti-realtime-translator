#!/usr/bin/env python3
"""Measure the installed TalTech model on one prepared audio file."""
import argparse
import json
from pathlib import Path
import resource
import sys
import subprocess
import time
import numpy as np
from whisper_backend import WhisperRecognizer

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("audio", type=Path)
parser.add_argument("--output", type=Path)
args = parser.parse_args()
pcm = subprocess.check_output(["ffmpeg", "-nostdin", "-v", "error", "-i", str(args.audio),
                               "-f", "f32le", "-ac", "1", "-ar", "16000", "pipe:1"])
audio = np.frombuffer(pcm, dtype="<f4").copy()
started = time.monotonic()
recognize = WhisperRecognizer()
load_seconds = time.monotonic() - started
records = []
for length in [1, 3, 6, 12]:
    if len(audio) < length * 16000:
        continue
    started = time.monotonic()
    words = recognize(audio[:length * 16000], 0)
    elapsed = time.monotonic() - started
    records.append({"audio_seconds": length, "inference_seconds": elapsed,
                    "text": " ".join(w.text for w in words),
                    "words": [{"text": w.text, "start": w.start, "end": w.end} for w in words]})
    print(f"{length}s audio → {elapsed:.2f}s inference", file=sys.stderr, flush=True)
result = {"model": "TalTechNLP/whisper-large-v3-turbo-et-verbatim-2604", "engine": "whisper.cpp Metal",
          "load_seconds": load_seconds, "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
          "runs": records}
if args.output:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
else:
    print(json.dumps(result, ensure_ascii=False, indent=2))
