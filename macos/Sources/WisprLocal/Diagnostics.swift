import AppKit
import AVFoundation
import SwiftUI

struct Check: Identifiable {
    let id = UUID()
    let name: String
    let ok: Bool?
    let detail: String
}

enum DiagnosticsProbe {
    static func run(state: AppState) -> [Check] {
        var out: [Check] = []
        out.append(Check(name: "Accessibility (AXIsProcessTrusted)", ok: AXIsProcessTrusted(),
                         detail: "Needed to paste with Cmd+V and for the global hotkey."))
        out.append(Check(name: "Can post keyboard events", ok: CGPreflightPostEventAccess(),
                         detail: "CGPreflightPostEventAccess – the actual check macOS makes when we send Cmd+V."))
        out.append(Check(name: "Can listen to global keys", ok: CGPreflightListenEventAccess(),
                         detail: "CGPreflightListenEventAccess – hold-to-talk hotkey."))
        let mic = AVCaptureDevice.authorizationStatus(for: .audio)
        let micText: String
        switch mic {
        case .authorized: micText = "authorized"
        case .denied: micText = "denied – enable in Privacy & Security → Microphone"
        case .restricted: micText = "restricted"
        case .notDetermined: micText = "not asked yet – click Request microphone"
        @unknown default: micText = "unknown"
        }
        out.append(Check(name: "Microphone", ok: mic == .authorized, detail: micText))

        let sig = signingInfo()
        out.append(Check(name: "Code signature", ok: sig.stable,
                         detail: sig.text))
        let engineOK: Bool? = {
            switch state.backend.status {
            case .idle, .recording, .processing: return true
            case .starting: return nil
            default: return false
            }
        }()
        out.append(Check(name: "Engine", ok: engineOK, detail: engineText(state.backend.status)))
        out.append(Check(name: "Python", ok: FileManager.default.isExecutableFile(atPath: Backend.pythonPath),
                         detail: Backend.pythonPath))
        out.append(Check(name: "Engine source", ok: FileManager.default.fileExists(atPath: Backend.backendDir + "/wispr/server.py"),
                         detail: Backend.backendDir))
        out.append(Check(name: "App bundle", ok: nil, detail: Bundle.main.bundlePath))
        out.append(Check(name: "Config", ok: FileManager.default.fileExists(atPath: AppConfig.file.path), detail: AppConfig.file.path))
        return out
    }

    static func engineText(_ s: EngineStatus) -> String {
        switch s {
        case .starting: return "loading models…"
        case .idle: return "ready"
        case .recording: return "listening"
        case .processing: return "transcribing"
        case .stopped: return "stopped"
        case .error(let m): return m
        }
    }

    static func signingInfo() -> (stable: Bool, text: String) {
        var code: SecStaticCode?
        guard SecStaticCodeCreateWithPath(Bundle.main.bundleURL as CFURL, [], &code) == errSecSuccess, let code else {
            return (false, "unsigned")
        }
        var info: CFDictionary?
        guard SecCodeCopySigningInformation(code, SecCSFlags(rawValue: kSecCSSigningInformation), &info) == errSecSuccess,
              let d = info as? [String: Any] else { return (false, "unsigned") }
        if let team = d[kSecCodeInfoTeamIdentifier as String] as? String {
            return (true, "signed with team \(team) – permissions persist across rebuilds")
        }
        if d[kSecCodeInfoIdentifier as String] != nil {
            return (false, "ad-hoc – every rebuild is a new identity to macOS; re-grant Accessibility after each build")
        }
        return (false, "unsigned")
    }

    static func report(_ checks: [Check], log: [String]) -> String {
        var s = "Wispr Local diagnostics \(Date())\n"
        for c in checks { s += "[\(c.ok == true ? "OK" : c.ok == false ? "FAIL" : "--")] \(c.name): \(c.detail)\n" }
        s += "\n--- log (last 80 lines)\n" + log.suffix(80).joined(separator: "\n")
        return s
    }
}

struct DiagnosticsView: View {
    @EnvironmentObject var state: AppState
    @State private var checks: [Check] = []
    @State private var timer: Timer?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Permissions and engine").font(.headline)
                Spacer()
                Button("Refresh") { refresh() }
                Button("Copy report") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(DiagnosticsProbe.report(checks, log: state.backend.logLines), forType: .string)
                }
            }
            ForEach(checks) { c in
                HStack(alignment: .top, spacing: 8) {
                    Image(systemName: c.ok == true ? "checkmark.circle.fill" : c.ok == false ? "xmark.circle.fill" : "circle")
                        .foregroundStyle(c.ok == true ? .green : c.ok == false ? .red : .secondary)
                        .frame(width: 18)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(c.name).fontWeight(.medium)
                        Text(c.detail).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                    }
                }
            }
            HStack {
                Button("Request Accessibility") {
                    let opts = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
                    _ = AXIsProcessTrustedWithOptions(opts)
                    _ = CGRequestPostEventAccess()
                    NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")!)
                }
                Button("Request microphone") {
                    AVCaptureDevice.requestAccess(for: .audio) { _ in DispatchQueue.main.async { refresh() } }
                }
                Button("Restart engine") { state.backend.start() }
            }
            Text("If Accessibility shows enabled in System Settings but fails here, remove Wispr Local from that list with the – button and add it again: the entry belongs to an older build.")
                .font(.caption).foregroundStyle(.secondary)
            Divider()
            Text("Log").font(.headline)
            ScrollViewReader { proxy in
                ScrollView {
                    Text(state.backend.logLines.joined(separator: "\n"))
                        .font(.system(size: 11, design: .monospaced))
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .id("end")
                }
                .onChange(of: state.backend.logLines.count) { _, _ in proxy.scrollTo("end", anchor: .bottom) }
            }
            .frame(minHeight: 160)
        }
        .padding(16)
        .frame(minWidth: 640, minHeight: 560)
        .onAppear {
            refresh()
            timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { _ in refresh() }
        }
        .onDisappear { timer?.invalidate() }
    }

    private func refresh() { checks = DiagnosticsProbe.run(state: state) }
}
