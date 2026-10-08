# Contributing

This is a small personal project tested on Apple Silicon macOS. Bug reports and focused improvements are welcome. Keep the main experience simple: system audio, readable captions, local translation, history and vocabulary.

Use the installation and checks in README.md. For processing changes, add regression tests for real failure modes: dropped words, changed final fragments, queue overflow, sentence boundaries or backwards-compatible history. For UI changes, use the native preview mode and verify both narrow and wide windows.

Do not commit models, audio recordings, lesson transcripts, vocabulary, credentials, Python environments or compiled bundles. Use artificial examples for screenshots and tests. Model installers should pin sources and verify checksums.

When proposing a Windows/Linux port, separate system capture and UI from the versioned JSONL processing protocol. Platform support should be described as experimental until capture, packaging and model runtimes have been tested on that platform.
