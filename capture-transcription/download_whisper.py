#!/usr/bin/env python3
"""Download the author's GGML checkpoint; verify the full file before use."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess

FOLDER = Path(__file__).resolve().parent / "models/whisper-taltech"
REPOSITORY = "TalTechNLP/whisper-large-v3-turbo-et-verbatim-2604"
REVISION = "310c550922fc1d1bebf3fad41f9b33ede6652bdc"
SIZE = 1624555275
SHA256 = "4e231f931f029850d7ca497efe4223f85c495a27d986d955f9a577ac1cd02edb"
URL = f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/ggml/ggml-model.bin"
PART_SIZE = 64_000_000


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while data := source.read(4 * 1024 * 1024):
            digest.update(data)
    return digest.hexdigest()


def provenance():
    (FOLDER / "provenance.json").write_text(json.dumps({
        "repository": REPOSITORY, "revision": REVISION,
        "file": "ggml/ggml-model.bin", "sha256": SHA256, "license": "MIT",
    }, indent=2))


def main():
    FOLDER.mkdir(parents=True, exist_ok=True)
    target = FOLDER / "ggml-model.bin"
    if target.exists() and target.stat().st_size == SIZE and file_hash(target) == SHA256:
        provenance()
        print("TalTech Whisper already installed and verified")
        return
    parts = [(i, start, min(SIZE - 1, start + PART_SIZE - 1))
             for i, start in enumerate(range(0, SIZE, PART_SIZE))]

    def download(spec):
        index, start, end = spec
        path = FOLDER / f"part-{index:02d}"
        if path.exists() and path.stat().st_size == end - start + 1:
            return path
        subprocess.run([
            "curl", "-Ls", "--fail", "--retry", "3", "--max-time", "900",
            "-r", f"{start}-{end}", "-o", str(path), f"{URL}?part={index}",
        ], check=True)
        if path.stat().st_size != end - start + 1:
            raise RuntimeError(f"Wrong size for part {index}")
        print(f"Part {index + 1}/{len(parts)} complete", flush=True)
        return path

    with ThreadPoolExecutor(max_workers=8) as pool:
        files = list(pool.map(download, parts))
    temporary = FOLDER / "assembled.partial"
    with temporary.open("wb") as output:
        for path in files:
            with path.open("rb") as source:
                while data := source.read(4 * 1024 * 1024):
                    output.write(data)
    if file_hash(temporary) != SHA256:
        raise RuntimeError("Model SHA256 mismatch; checkpoint was not installed")
    temporary.replace(target)
    provenance()
    for path in files:
        path.unlink()
    (FOLDER / "ggml-model.bin.partial").unlink(missing_ok=True)
    print("Model downloaded and SHA256 verified", flush=True)


if __name__ == "__main__":
    main()
