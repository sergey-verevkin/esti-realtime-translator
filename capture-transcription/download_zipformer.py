"""Download TalTech's streaming INT8 model from a pinned, verified revision."""
import hashlib
import json
from pathlib import Path
import subprocess

MODEL_DIR = Path(__file__).resolve().parent / 'models/zipformer-taltech'
REPO = 'TalTechNLP/streaming-zipformer.et-en'
REVISION = '7edbacc1d13a4bc8fba21307753569e8334938a0'
FILES = {
    'encoder.int8.onnx': (70107780, '37b1eff8127447f192e3f8eae29fe3893be45a39283e444c9154b489bba6bbde'),
    'decoder.int8.onnx': (796689, '9ef6b41fd1552ded37acb3b7805264d7650ea5d737846eeef1b3feda54b6e267'),
    'joiner.int8.onnx': (517416, '7c8d02c85ea42ee6ff13b5a5207e935d001d98a561763ebbfd7a7a127ad374dd'),
    'tokens.txt': (11493, 'cbe23ea2ef76303d874ab45ef8471b570e565b9048ab0aeda1c7adf2c663ee97'),
}


def verified(path, size, digest):
    return path.is_file() and path.stat().st_size == size and hashlib.sha256(path.read_bytes()).hexdigest() == digest


def main(*, model_dir=MODEL_DIR, repo=REPO, revision=REVISION, files=FILES, remote_names=None, license_name="MIT"):
    model_dir.mkdir(parents=True, exist_ok=True)
    for name, (size, digest) in files.items():
        path = model_dir / name
        if verified(path, size, digest):
            continue
        partial = path.with_suffix(path.suffix + '.partial')
        subprocess.run(['curl', '-fL', '--retry', '3', '--connect-timeout', '30', '--max-time', '600',
                        f'https://huggingface.co/{repo}/resolve/{revision}/{(remote_names or {}).get(name, name)}', '-o', str(partial)], check=True)
        if not verified(partial, size, digest):
            raise RuntimeError(f'Checksum mismatch: {name}')
        partial.replace(path)
    (model_dir / 'provenance.json').write_text(json.dumps({
        'repository': repo, 'revision': revision, 'license': license_name, 'files': files, 'remote_names': remote_names or {},
    }, indent=2) + '\n')
    print(f'Zipformer installed and verified: {model_dir}')


if __name__ == '__main__':
    main()
