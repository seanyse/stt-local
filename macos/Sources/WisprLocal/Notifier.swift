import AppKit
import SwiftUI

/// Small transient message in the overlay position (no notification entitlements needed).
enum Notifier {
    private static var panel: NSPanel?
    static func show(title: String, body: String, seconds: Double = 4) {
        DispatchQueue.main.async {
            let p = panel ?? {
                let p = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 360, height: 64),
                                styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
                p.level = .statusBar; p.isOpaque = false; p.backgroundColor = .clear; p.hasShadow = true
                p.ignoresMouseEvents = true
                p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
                panel = p
                return p
            }()
            p.contentView = NSHostingView(rootView:
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(.system(size: 13, weight: .semibold)).foregroundStyle(.white)
                    Text(body).font(.system(size: 12)).foregroundStyle(.white.opacity(0.85))
                }
                .padding(.horizontal, 16).padding(.vertical, 10)
                .frame(width: 360, alignment: .leading)
                .background(.black.opacity(0.85), in: RoundedRectangle(cornerRadius: 12))
            )
            if let screen = NSScreen.main {
                let f = screen.visibleFrame
                p.setFrameOrigin(NSPoint(x: f.midX - 180, y: f.minY + 80))
            }
            p.orderFrontRegardless()
            DispatchQueue.main.asyncAfter(deadline: .now() + seconds) { p.orderOut(nil) }
        }
    }
}
