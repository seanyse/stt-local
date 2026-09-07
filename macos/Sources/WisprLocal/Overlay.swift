import AppKit
import SwiftUI

/// The floating pill at the bottom of the screen while listening / transcribing.
final class OverlayController {
    private var panel: NSPanel?
    private let model = OverlayModel()
    private var hideWork: DispatchWorkItem?

    func update(status: EngineStatus) {
        switch status {
        case .recording: show(text: "Listening", pulsing: true)
        case .processing: show(text: "Transcribing…", pulsing: false)
        default: scheduleHide()
        }
    }

    private func show(text: String, pulsing: Bool) {
        hideWork?.cancel()
        model.text = text; model.pulsing = pulsing
        if panel == nil { panel = makePanel() }
        position()
        panel?.orderFrontRegardless()
    }

    private func scheduleHide() {
        hideWork?.cancel()
        let w = DispatchWorkItem { [weak self] in self?.panel?.orderOut(nil) }
        hideWork = w
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25, execute: w)
    }

    private func makePanel() -> NSPanel {
        let p = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 200, height: 44),
                        styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        p.level = .statusBar
        p.isOpaque = false
        p.backgroundColor = .clear
        p.hasShadow = true
        p.ignoresMouseEvents = true
        p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        p.contentView = NSHostingView(rootView: OverlayView(model: model))
        return p
    }

    private func position() {
        guard let p = panel, let screen = NSScreen.main else { return }
        let f = screen.visibleFrame
        p.setFrameOrigin(NSPoint(x: f.midX - p.frame.width / 2, y: f.minY + 24))
    }
}

final class OverlayModel: ObservableObject {
    @Published var text = "Listening"
    @Published var pulsing = true
}

struct OverlayView: View {
    @ObservedObject var model: OverlayModel
    @State private var pulse = false

    var body: some View {
        HStack(spacing: 10) {
            Circle()
                .fill(model.pulsing ? Color.red : Color.orange)
                .frame(width: 10, height: 10)
                .scaleEffect(pulse && model.pulsing ? 1.35 : 1)
                .opacity(pulse && model.pulsing ? 0.6 : 1)
                .animation(.easeInOut(duration: 0.7).repeatForever(autoreverses: true), value: pulse)
            Text(model.text).font(.system(size: 13, weight: .medium)).foregroundStyle(.white)
        }
        .padding(.horizontal, 16).padding(.vertical, 10)
        .background(.black.opacity(0.82), in: Capsule())
        .frame(width: 200, height: 44)
        .onAppear { pulse = true }
    }
}
