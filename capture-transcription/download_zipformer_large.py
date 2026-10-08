"""Install the pinned INT8 TalTech Zipformer Large alongside the smaller model."""
from download_zipformer import MODEL_DIR as SMALL_DIR, FILES as SMALL_FILES, main as download

MODEL_DIR = SMALL_DIR.parent / 'zipformer-large-taltech'
REPO = 'TalTechNLP/streaming-zipformer-large.et-en'
REVISION = '2812262bd4fd5d4327dc09ca0e6c19e8a32a03d6'
FILES = {
    'encoder.int8.onnx': (154895904, '4249db3c9a9a66dc368b169cccb39088fe2f4d3f62d19907f110daea8a2d387f'),
    'decoder.int8.onnx': (796689, '75293b68a6a391f926e9c8a62680c447ba9a97e885aef7dcba0cbfa5433a6198'),
    'joiner.int8.onnx': (517416, 'cfa4a072813c4ae140d3604eb16f875fd13f5bbcedb32a673815dc12fa17521b'),
    'tokens.txt': SMALL_FILES['tokens.txt'],
}

if __name__ == '__main__':
    download(model_dir=MODEL_DIR, repo=REPO, revision=REVISION, files=FILES)
