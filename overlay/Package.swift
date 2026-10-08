// swift-tools-version: 5.9
import PackageDescription
let package = Package(name: "RealtimeOverlay", platforms: [.macOS(.v13)], targets: [.executableTarget(name: "realtime-overlay", path: "Sources/Overlay")])
