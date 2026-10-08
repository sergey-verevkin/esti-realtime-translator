# Third-party components and model weights

The MIT license in this repository covers original project code. Downloaded model weights, dependencies, and upstream projects retain their licenses. Models, runtimes and vendored checkouts are excluded from Git.

## Models

| Model | Source | Upstream license |
| --- | --- | --- |
| TalTech streaming Zipformer | [TalTechNLP/streaming-zipformer.et-en](https://huggingface.co/TalTechNLP/streaming-zipformer.et-en) | MIT |
| TalTech streaming Zipformer Large | [TalTechNLP/streaming-zipformer-large.et-en](https://huggingface.co/TalTechNLP/streaming-zipformer-large.et-en) | MIT |
| English streaming Zipformer | [csukuangfj/sherpa-onnx-streaming-zipformer-en-2023-06-26](https://huggingface.co/csukuangfj/sherpa-onnx-streaming-zipformer-en-2023-06-26) | Apache-2.0 |
| English punctuation/casing | [Edge-Punct-Casing](https://github.com/frankyoujian/Edge-Punct-Casing), [sherpa-onnx conversion](https://k2-fsa.github.io/sherpa/onnx/punctuation/pretrained_models.html) | Apache-2.0 |
| Silero VAD | [snakers4/silero-vad](https://github.com/snakers4/silero-vad) | MIT |
| TalTech Whisper Turbo | [TalTechNLP/whisper-large-v3-turbo-et-verbatim-2604](https://huggingface.co/TalTechNLP/whisper-large-v3-turbo-et-verbatim-2604) | MIT |
| Parakeet TDT V3 | [nvidia/parakeet-tdt-0.6b-v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) | CC BY 4.0 |
| NLLB distilled 600M | [Meta model](https://huggingface.co/facebook/nllb-200-distilled-600M), [CT2 conversion](https://huggingface.co/osa911/nllb-200-distilled-600M-ct2-int8) | CC BY-NC 4.0 |
| NLLB distilled 1.3B | [Meta model](https://huggingface.co/facebook/nllb-200-distilled-1.3B), [CT2 conversion](https://huggingface.co/JustFrederik/nllb-200-distilled-1.3B-ct2-int8) | CC BY-NC 4.0 |

NLLB's non-commercial condition applies to use of its weights; an MIT application license does not remove that condition. Refer to the linked upstream terms before redistributing weights or changing the use case. Installers pin model revisions or release archives, validate SHA256 and save local provenance.

## Libraries

- [AudioTee](https://github.com/makeusabrew/audiotee) — MIT. Downloaded at pinned revision during capture setup, with its upstream license.
- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) and [icefall](https://github.com/k2-fsa/icefall) — Apache-2.0.
- [ONNX Runtime](https://github.com/microsoft/onnxruntime) — MIT.
- [Silero VAD](https://github.com/snakers4/silero-vad) — MIT.
- [CTranslate2](https://github.com/OpenNMT/CTranslate2) and [SentencePiece](https://github.com/google/sentencepiece) — MIT and Apache-2.0, respectively.
- [whisper.cpp](https://github.com/ggml-org/whisper.cpp) and [pywhispercpp](https://github.com/absadiki/pywhispercpp) — MIT.
- [onnx-asr](https://github.com/istupakov/onnx-asr) — MIT.
- [NumPy](https://github.com/numpy/numpy) — BSD-3-Clause.

FFmpeg is an external dependency for file replay; its distribution license depends on build configuration. macOS frameworks and developer tools are supplied by Apple.
