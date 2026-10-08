"""Measure prepared phrases, save outputs for human review; not an accuracy score."""
import argparse
import json
from pathlib import Path
import statistics
import time

from approaches import load_engine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--beam-size", type=int, default=4)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument('--engine', choices=['nllb', 'nllb-1.3b'], default='nllb')
    parser.add_argument('--style', choices=['sentences', 'block'], default='sentences')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    cases = json.loads((root / "examples/estonian-phrases.json").read_text())
    started = time.monotonic()
    model = load_engine(args.engine, threads=args.threads, beam_size=args.beam_size, style=args.style)
    load_seconds = time.monotonic() - started
    _, cold_ms = model.translate("Tere hommikust!")
    rows = []
    for case in cases:
        translated, ms = model.translate(case["text"])
        rows.append({**case, "translation": translated, "translation_ms": round(ms, 1)})
        print(f"{case['text']}\n→ {translated} ({ms:.0f}ms)", flush=True)
    times = sorted(row["translation_ms"] for row in rows)
    summary = {"load_seconds": round(load_seconds, 3), "first_translation_ms": round(cold_ms, 1),
        "p50_ms": statistics.median(times), "p95_ms": times[round(.95 * (len(times) - 1))],
        "threads": args.threads, "beam_size": args.beam_size, "engine": args.engine, "style": args.style,
        "quality_status": "Outputs require human review; expected meanings are illustrative"}
    output = root / "output"
    output.mkdir(exist_ok=True)
    (output / f"benchmark-{args.engine}-{args.style}-beam{args.beam_size}.json").write_text(json.dumps({"summary":summary,"cases":rows}, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
