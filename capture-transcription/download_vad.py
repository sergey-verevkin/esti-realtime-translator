"""Install the pinned upstream Silero VAD ONNX model with SHA256 verification."""
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent
MODEL_DIR = ROOT / 'models/silero-vad'
MODEL_PATH = MODEL_DIR / 'silero_vad.onnx'
REVISION = '5cd7945676eb32225748052e2e6a0580e4686a08'
SIZE = 2327524
SHA256 = '1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3'
BASE = f'https://raw.githubusercontent.com/snakers4/silero-vad/{REVISION}'


def verified(path):
    return path.is_file() and path.stat().st_size == SIZE and hashlib.sha256(path.read_bytes()).hexdigest() == SHA256


def main():
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if not verified(MODEL_PATH):
        partial = MODEL_PATH.with_suffix('.partial')
        with urllib.request.urlopen(BASE + '/src/silero_vad/data/silero_vad.onnx', timeout=45) as response:
            partial.write_bytes(response.read(SIZE + 1))
        if not verified(partial):
            raise RuntimeError('Silero VAD checksum mismatch; model was not installed')
        partial.replace(MODEL_PATH)
    license_path = MODEL_DIR / 'LICENSE'
    if not license_path.exists():
        with urllib.request.urlopen(BASE + '/LICENSE', timeout=30) as response:
            license_path.write_bytes(response.read())
    (MODEL_DIR / 'provenance.json').write_text(json.dumps({
        'repository': 'snakers4/silero-vad', 'release': 'v6.2.3', 'revision': REVISION,
        'file': 'src/silero_vad/data/silero_vad.onnx', 'sha256': SHA256, 'license': 'MIT',
    }, indent=2) + '\n')
    print(f'Silero VAD installed and verified: {MODEL_PATH}')


if __name__ == '__main__':
    main()
