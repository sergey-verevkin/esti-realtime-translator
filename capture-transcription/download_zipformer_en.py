from download_zipformer import MODEL_DIR as BASE_DIR, main as download
MODEL_DIR = BASE_DIR.parent / "zipformer-en"
REPO = "csukuangfj/sherpa-onnx-streaming-zipformer-en-2023-06-26"
REVISION = '672fbf1b30579d6585301139bb363f42a0ad4a24'
FILES = {'encoder.int8.onnx': (71083163, '563fde436d16cf7607cf408cd6b30909819d03162652ef389c2450ced3f45ac1'), 'decoder.int8.onnx': (1307236, '98da299f471e38bb4e1a8df579b8cc9122d6039576a77e357b3c60f17dd83b02'), 'joiner.int8.onnx': (259335, 'd944208d660d67c8d72cd2acaeac971fa5ceb8c80e76c1968148846fedd6e297'), 'tokens.txt': (5048, '49e3c2646595fd907228b3c6787069658f67b17377c60aeb8619c4551b2316fb')}
REMOTE_NAMES = {'encoder.int8.onnx': 'encoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx', 'decoder.int8.onnx': 'decoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx', 'joiner.int8.onnx': 'joiner-epoch-99-avg-1-chunk-16-left-128.int8.onnx'}
if __name__ == "__main__":
    download(model_dir=MODEL_DIR, repo=REPO, revision=REVISION, files=FILES, remote_names=REMOTE_NAMES, license_name="Apache-2.0")
