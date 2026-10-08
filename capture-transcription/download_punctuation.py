"""Install the pinned English Edge-Punct-Casing INT8 release."""
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile

MODEL_DIR = Path(__file__).resolve().parent / 'models/punctuation-en'
URL = 'https://github.com/k2-fsa/sherpa-onnx/releases/download/punctuation-models/sherpa-onnx-online-punct-en-2024-08-06.tar.bz2'
ARCHIVE_SHA = '9f5e5a72c7d2829635bd074fce92b6bbd5b78da8a52e7ad8ed1be933f366b99d'
FILES = {
    'model.int8.onnx': (7490500, '9d611f445fe4a46186080fe161be6059d87d72eb88d3a8cb00c1a06e83a6067e'),
    'bpe.vocab': (149430, 'e118b7ad88c54db562517df49e1cffd4836d166c34fb190fd311d7f34eb238f5'),
}


def valid(data, expected):
    return len(data) == expected[0] and hashlib.sha256(data).hexdigest() == expected[1]


def main(archive=None):
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if not all((MODEL_DIR / n).is_file() and valid((MODEL_DIR / n).read_bytes(), spec) for n, spec in FILES.items()):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(archive) if archive else Path(folder) / 'model.tar.bz2'
            if not archive:
                subprocess.run(['curl', '-fL', '--retry', '3', '--connect-timeout', '30', '--max-time', '300', URL, '-o', str(path)], check=True)
            if hashlib.sha256(path.read_bytes()).hexdigest() != ARCHIVE_SHA:
                raise RuntimeError('Punctuation archive checksum mismatch')
            with tarfile.open(path) as tar:
                for name, spec in FILES.items():
                    member = next(m for m in tar.getmembers() if m.name.removeprefix('./') == 'sherpa-onnx-online-punct-en-2024-08-06/' + name)
                    if not member.isfile() or member.size != spec[0]:
                        raise RuntimeError('Invalid punctuation archive member')
                    data = tar.extractfile(member).read()
                    if not valid(data, spec): raise RuntimeError('Punctuation file checksum mismatch')
                    partial = MODEL_DIR / (name + '.partial')
                    partial.write_bytes(data); partial.replace(MODEL_DIR / name)
    (MODEL_DIR / 'provenance.json').write_text(json.dumps(dict(url=URL, sha256=ARCHIVE_SHA, files=FILES, license='Apache-2.0', upstream='frankyoujian/Edge-Punct-Casing'), indent=2) + '\n')
    print(f'English punctuation installed: {MODEL_DIR}')


if __name__ == '__main__': main()
