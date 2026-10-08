"""Fetch a pinned community INT8 conversion; verify sizes and SHA256 hashes."""
import hashlib
import json
from pathlib import Path
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
MODEL_DIR = ROOT / "models/nllb-600m-int8"
BASE_MODEL = "facebook/nllb-200-distilled-600M"
REPO = "osa911/nllb-200-distilled-600M-ct2-int8"
REVISION = "46858753dbaf8eb5e21bb6f0037c3b90851e090a"
FILES = {
    "config.json": (223, "8f6496adfc930cbfecbe8281112197705c488fab47d34b4829b06d7f478909af"),
    "sentencepiece.bpe.model": (4852054, "14bb8dfb35c0ffdea7bc01e56cea38b9e3d5efcdcb9c251d6b40538e1aab555a"),
    "shared_vocabulary.json": (5921176, "af53bfd0e6f726209e7325e45b87ab3b14e5856f7d42d7b9be91de3287c45267"),
    "model.bin": (619704329, "ca3362e6e81906c0cf9c33bd6917674222c71d69617d0afb18507ce0b6c2e2e8"),
}


def verified(path, size, expected):
    if not path.is_file() or path.stat().st_size != size:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest() == expected


def main():
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name, (size, digest) in FILES.items():
        target = MODEL_DIR / name
        if verified(target, size, digest):
            print(f"Verified existing {name}", flush=True)
            continue
        partial = target.with_name(name + ".partial")
        for attempt in range(3):
            try:
                offset = partial.stat().st_size if partial.exists() else 0
                request = urllib.request.Request(
                    f"https://huggingface.co/{REPO}/resolve/{REVISION}/{name}?download=true",
                    headers={"Range": f"bytes={offset}-"} if offset else {},
                )
                with urllib.request.urlopen(request, timeout=45) as response:
                    resume = offset > 0 and response.status == 206
                    received = offset if resume else 0
                    last_report = 0
                    with partial.open("ab" if resume else "wb") as stream:
                        while block := response.read(1024 * 1024):
                            stream.write(block)
                            received += len(block)
                            if time.monotonic() - last_report > 5:
                                print(f"{name}: {received / size:.0%} ({received // 1048576}/{size // 1048576} MiB)", flush=True)
                                last_report = time.monotonic()
                if not verified(partial, size, digest):
                    partial.unlink(missing_ok=True)
                    raise RuntimeError(f"Checksum mismatch for {name}")
                partial.replace(target)
                print(f"Verified {name}", flush=True)
                break
            except Exception as exc:
                if attempt == 2:
                    raise
                print(f"Retrying {name}: {type(exc).__name__}", flush=True)
                time.sleep(1)
    (MODEL_DIR / "provenance.json").write_text(json.dumps({
        "base_model": BASE_MODEL,
        "conversion_repo": REPO, "revision": REVISION,
        "license": "CC-BY-NC-4.0", "sha256": {n: v[1] for n, v in FILES.items()},
    }, indent=2) + "\n")
    print(f"Ready: {MODEL_DIR}", flush=True)


if __name__ == "__main__":
    main()
