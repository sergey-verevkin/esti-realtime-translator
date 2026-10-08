import AppKit
import SwiftUI

/// Equal-width language columns; both texts keep natural, unlimited wrapping.
struct CaptionTextPair: View {
    let original: String
    let translation: String
    let originalFirst: Bool
    let columns: Bool
    let size: Double
    let openWord: (String, String, String) -> Void
    private let secondary = Color(red: 0.73, green: 0.87, blue: 0.96)
    private var originalView: some View {
        WordText(text: original, translation: translation, open: openWord)
            .font(.system(size: originalFirst ? size : size * 0.83, weight: originalFirst ? .medium : .regular))
            .foregroundColor(originalFirst ? .white : secondary).tint(originalFirst ? .white : secondary)
            .fixedSize(horizontal: false, vertical: true).frame(maxWidth: .infinity, alignment: .topLeading)
    }
    private var translatedView: some View {
        Text(translation).font(.system(size: originalFirst ? size * 0.83 : size, weight: originalFirst ? .regular : .medium))
            .foregroundColor(originalFirst ? secondary : .white)
            .fixedSize(horizontal: false, vertical: true).frame(maxWidth: .infinity, alignment: .topLeading)
    }
    var body: some View {
        let layout = columns ? AnyLayout(HStackLayout(alignment: .top, spacing: 20)) : AnyLayout(VStackLayout(alignment: .leading, spacing: 6))
        layout {
            if originalFirst {
                originalView
                if columns || !translation.isEmpty { translatedView }
            } else {
                if columns || !translation.isEmpty { translatedView }
                originalView
            }
        }
    }
}
final class WidthHandleView: NSView {
    var left = false
    private var startingFrame = NSRect.zero
    private var startingPoint = NSPoint.zero
    override var mouseDownCanMoveWindow: Bool { false }
    override func resetCursorRects() { addCursorRect(bounds, cursor: .resizeLeftRight) }
    override func mouseDown(with event: NSEvent) {
        guard let window else { return }
        startingFrame = window.frame; startingPoint = NSEvent.mouseLocation
    }
    static func resized(_ frame: NSRect, delta: CGFloat, left: Bool, minimum: CGFloat, screen: NSRect) -> NSRect {
        let available = left ? frame.maxX - screen.minX : screen.maxX - frame.minX
        let width = min(max(minimum, available), max(minimum, frame.width + (left ? -delta : delta)))
        return NSRect(x: left ? frame.maxX - width : frame.minX, y: frame.minY, width: width, height: frame.height)
    }
    override func mouseDragged(with event: NSEvent) {
        guard let window, let screen = window.screen?.visibleFrame else { return }
        window.setFrame(Self.resized(startingFrame, delta: NSEvent.mouseLocation.x - startingPoint.x,
                                    left: left, minimum: window.minSize.width, screen: screen), display: true)
    }
    override func mouseUp(with event: NSEvent) { window?.saveFrame(usingName: "RealtimeOverlay") }
}
struct WidthHandle: NSViewRepresentable {
    let left: Bool
    func makeNSView(context: Context) -> WidthHandleView { let view = WidthHandleView(); view.left = left; return view }
    func updateNSView(_ nsView: WidthHandleView, context: Context) { nsView.left = left }
}
struct WidthGrip: View {
    let left: Bool
    var body: some View {
        ZStack {
            WidthHandle(left: left).frame(width: 14, height: 100)
                .help("Потяните влево или вправо, чтобы изменить ширину")
            Capsule().fill(Color.white.opacity(0.35)).frame(width: 3, height: 42).allowsHitTesting(false)
        }
    }
}
