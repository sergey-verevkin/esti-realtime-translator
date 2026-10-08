import AudioTeeCore
import CoreAudio
import Foundation

func log(_ message: String) {
    FileHandle.standardError.write(Data((message + "\n").utf8))
}

final class PCMOutput: AudioOutputHandler {
    func handleAudioData(_ pointer: UnsafeRawPointer, count: Int) {
        FileHandle.standardOutput.write(Data(bytes: pointer, count: count))
    }
    func handleMetadata(_ metadata: AudioStreamMetadata) {
        if let data = try? JSONEncoder().encode(metadata) {
            log("FORMAT " + String(decoding: data, as: UTF8.self))
        }
    }
    func handleStreamStart() { log("CAPTURE_READY") }
    func handleStreamStop() { log("CAPTURE_STOPPED") }
}

let args = Array(CommandLine.arguments.dropFirst())
if args.contains("--help") {
    print("realtime-capture [--pid PID ...]\nOutputs mono 16 kHz signed int16 PCM on stdout.")
    exit(0)
}
var pids: [Int32] = []
var index = 0
while index < args.count {
    guard args[index] == "--pid", index + 1 < args.count,
          let pid = Int32(args[index + 1]), pid > 0 else {
        log("Invalid arguments. Use --pid PID for each process, or no arguments for system audio.")
        exit(2)
    }
    pids.append(pid)
    index += 2
}

do {
    let manager = AudioTapManager()
    try manager.setupAudioTap(with: TapConfiguration(
        processes: pids, muteBehavior: .unmuted,
        isExclusive: pids.isEmpty, isMono: true
    ))
    guard let device = manager.getDeviceID() else {
        log("Capture device could not be created.")
        exit(1)
    }
    let recorder = try AudioRecorder(
        deviceID: device, outputHandler: PCMOutput(),
        convertToSampleRate: 16000, chunkDuration: 0.2
    )
    let format = recorder.outputFormat
    guard recorder.isConverting, format.mSampleRate == 16000,
          format.mChannelsPerFrame == 1, format.mBitsPerChannel == 16,
          format.mFormatFlags & kAudioFormatFlagIsFloat == 0 else {
        log("Capture cannot produce the required mono 16 kHz int16 format.")
        exit(1)
    }
    signal(SIGINT, SIG_IGN)
    signal(SIGTERM, SIG_IGN)
    var stopping = false
    let interrupts = [SIGINT, SIGTERM].map { sig -> DispatchSourceSignal in
        let source = DispatchSource.makeSignalSource(signal: sig, queue: .main)
        source.setEventHandler { stopping = true }
        source.resume()
        return source
    }
    try recorder.startRecording()
    while !stopping {
        RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.1))
    }
    recorder.stopRecording()
    interrupts.forEach { $0.cancel() }
    withExtendedLifetime(manager) {}
} catch {
    log("Capture failed: \(error). Check system audio recording permission in macOS Settings.")
    exit(1)
}
