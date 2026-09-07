import AppKit
import SwiftUI

@main
struct WisprLocalApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate

    var body: some Scene {
        MenuBarExtra {
            MenuContent().environmentObject(delegate.state)
        } label: {
            MenuBarLabel().environmentObject(delegate.state)
        }
        .menuBarExtraStyle(.menu)

        Window("History", id: "history") {
            HistoryView().environmentObject(delegate.state)
        }
        .defaultSize(width: 720, height: 520)

        Settings {
            SettingsView().environmentObject(delegate.state)
        }
    }
}

/// Everything the views need, owned by the app delegate so it outlives any window.
final class AppState: ObservableObject {
    let config = AppConfig()
    let backend = Backend()
    let history = HistoryStore()
    @Published var accessibilityGranted = AXIsProcessTrusted()
    var hotkey: HotkeyMonitor?
    let overlay = OverlayController()
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    let state = AppState()
    private var statusSink: Any?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        let opts = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
        state.accessibilityGranted = AXIsProcessTrustedWithOptions(opts)

        state.backend.onResult = { [state] entry in
            state.history.append(entry)
        }
        state.backend.start()
        installHotkey()

        statusSink = state.backend.$status.sink { [state] s in
            state.overlay.update(status: s)
        }
        // Accessibility can be granted after launch; poll cheaply.
        Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [state] _ in
            let now = AXIsProcessTrusted()
            if now != state.accessibilityGranted { state.accessibilityGranted = now }
        }
    }

    func installHotkey() {
        let cfg = state.config
        let hk = HotkeyMonitor(keyCode: cfg.hotkeyCode, tapSeconds: cfg.tapSeconds)
        hk.onStart = { [state] in state.backend.startRecording() }
        hk.onStop = { [state] in state.backend.stopRecording() }
        hk.onCancel = { [state] in state.backend.cancelRecording() }
        state.hotkey = hk
    }

    func applicationWillTerminate(_ notification: Notification) {
        state.backend.stop()
    }
}

struct MenuBarLabel: View {
    @EnvironmentObject var state: AppState
    var body: some View {
        let s = state.backend.status
        switch s {
        case .recording: Image(systemName: "record.circle.fill")
        case .processing: Image(systemName: "ellipsis.circle")
        case .starting: Image(systemName: "mic.slash")
        case .error, .stopped: Image(systemName: "exclamationmark.triangle")
        case .idle: Image(systemName: "mic")
        }
    }
}

struct MenuContent: View {
    @EnvironmentObject var state: AppState
    @Environment(\.openWindow) private var openWindow

    var statusText: String {
        switch state.backend.status {
        case .starting: return "Loading models…"
        case .idle: return "Hold \(state.config.hotkeyLabel) to talk · tap to lock"
        case .recording: return "Listening…"
        case .processing: return "Transcribing…"
        case .stopped: return "Engine stopped"
        case .error(let m): return "Error: \(m)"
        }
    }

    var body: some View {
        Text(statusText)
        if !state.accessibilityGranted {
            Button("Grant Accessibility access…") {
                NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")!)
            }
        }
        Divider()
        Button("History") { NSApp.activate(ignoringOtherApps: true); openWindow(id: "history") }
            .keyboardShortcut("h")
        SettingsLink { Text("Settings…") }
            .keyboardShortcut(",")
        Divider()
        Button("Restart engine") { state.backend.start() }
        Button("Open logs folder") { NSWorkspace.shared.open(AppConfig.logsDir) }
        Divider()
        Button("Quit Wispr Local") { NSApp.terminate(nil) }.keyboardShortcut("q")
    }
}
