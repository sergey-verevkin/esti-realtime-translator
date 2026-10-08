import AppKit
let image = NSImage(size: NSSize(width: 1024, height: 1024))
image.lockFocus()
NSColor(calibratedRed: 0.09, green: 0.20, blue: 0.28, alpha: 1).setFill()
NSBezierPath(roundedRect: NSRect(x: 32, y: 32, width: 960, height: 960), xRadius: 215, yRadius: 215).fill()
let attributes: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 360, weight: .semibold), .foregroundColor: NSColor.white]
let text = "ET" as NSString
let size = text.size(withAttributes: attributes)
text.draw(at: NSPoint(x: (1024-size.width)/2, y: 390), withAttributes: attributes)
NSColor(calibratedRed: 0.60, green: 0.83, blue: 0.93, alpha: 1).setFill()
for (y, width) in [(310.0, 590.0), (200.0, 420.0)] {
    NSBezierPath(roundedRect: NSRect(x: 217, y: y, width: width, height: 48), xRadius: 24, yRadius: 24).fill()
}
image.unlockFocus()
let bitmap = NSBitmapImageRep(data: image.tiffRepresentation!)!
try bitmap.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
