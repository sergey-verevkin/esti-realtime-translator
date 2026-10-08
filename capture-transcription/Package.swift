// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "RealtimeCapture",
    platforms: [.macOS("14.2")],
    dependencies: [.package(path: "vendor/audiotee")],
    targets: [.executableTarget(
        name: "realtime-capture",
        dependencies: [.product(name: "AudioTeeCore", package: "audiotee")],
        path: "Sources/Capture"
    )]
)
