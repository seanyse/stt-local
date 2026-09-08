import AppKit
import Foundation

enum EngineStatus: Equatable {
    case starting, idle, recording, processing, stopped
    case error(String)
}

struct HistoryEntry: Identifiable, Hashable {
    let id: String
    let ts: Date
    let raw: String
    let clean: String
    let audioSeconds: Double
    let sttMs: Int
    let formatMs: Int
    let totalMs: Int
    let wav: String?

    init?(json: [String: Any]) {
        guard let ts = json["ts"] as? String, let clean = json["clean"] as? String else { return nil }
        self.id = ts + "|" + clean.prefix(24)
        let f = ISO8601DateFormatter(); f.formatOptions = [.withFullDate, .withTime, .withColonSeparatorInTime, .withDashSeparatorInDate]
        self.ts = f.date(from: ts) ?? Date()
        self.clean = clean
        self.raw = json["raw"] as? String ?? clean
        self.audioSeconds = json["audio_seconds"] as? Double ?? 0
        self.sttMs = Int(json["stt_ms"] as? Double ?? 0)
        self.formatMs = Int(json["format_ms"] as? Double ?? 0)
        self.totalMs = Int(json["total_ms"] as? Double ?? 0)
        self.wav = json["wav"] as? String
    }
}

/// Runs `python -m wispr.server` and speaks its JSON-lines protocol.
final class Backend: ObservableObject {
    @Published var status: EngineStatus = .starting
    @Published var logLines: [String] = []
    var onResult: ((HistoryEntry) -> Void)?

    private var process: Process?
    private var stdin: FileHandle?
    private var buffer = Data()

    static var pythonPath: String {
        if let p = ProcessInfo.processInfo.environment["WISPR_PYTHON"] { return p }
        if let p = Bundle.main.object(forInfoDictionaryKey: "WisprBackendPython") as? String { return p }
        return "python3"
    }
    static var backendDir: String {
        if let p = ProcessInfo.processInfo.environment["WISPR_BACKEND_DIR"] { return p }
        if let p = Bundle.main.object(forInfoDictionaryKey: "WisprBackendDir") as? String { return p }
        return FileManager.default.currentDirectoryPath
    }

    func start() {
        stop()
        status = .starting
        let p = Process()
        p.executableURL = URL(fileURLWithPath: Self.pythonPath)
        p.arguments = ["-m", "wispr.server"]
        p.currentDirectoryURL = URL(fileURLWithPath: Self.backendDir)
        var env = ProcessInfo.processInfo.environment
        env["PYTHONUNBUFFERED"] = "1"
        env["WISPR_CONFIG_DIR"] = AppConfig.dir.path
        p.environment = env

        let inPipe = Pipe(), outPipe = Pipe(), errPipe = Pipe()
        p.standardInput = inPipe; p.standardOutput = outPipe; p.standardError = errPipe
        stdin = inPipe.fileHandleForWriting

        outPipe.fileHandleForReading.readabilityHandler = { [weak self] h in
            let d = h.availableData
            guard !d.isEmpty else { return }
            DispatchQueue.main.async { self?.consume(d) }
        }
        errPipe.fileHandleForReading.readabilityHandler = { [weak self] h in
            guard let s = String(data: h.availableData, encoding: .utf8), !s.isEmpty else { return }
            DispatchQueue.main.async { self?.log(s) }
        }
        p.terminationHandler = { [weak self] proc in
            DispatchQueue.main.async {
                guard let self, self.process === proc else { return }
                self.status = proc.terminationStatus == 0 ? .stopped : .error("engine exited (\(proc.terminationStatus)) – see log")
                self.process = nil
                self.log("[app] engine exited with status \(proc.terminationStatus); restarting in 2 s")
                DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in
                    if let self, self.process == nil { self.start() }
                }
            }
        }
        do { try p.run(); process = p } catch { status = .error("cannot launch \(Self.pythonPath): \(error.localizedDescription)") }
    }

    func stop() {
        guard let p = process else { return }
        send(["cmd": "quit"])
        process = nil
        let deadline = Date().addingTimeInterval(1.5)
        while p.isRunning && Date() < deadline { usleep(50_000) }
        if p.isRunning { p.terminate() }
    }

    func send(_ msg: [String: Any]) {
        guard let d = try? JSONSerialization.data(withJSONObject: msg) else { return }
        stdin?.write(d); stdin?.write("\n".data(using: .utf8)!)
    }

    func startRecording() { send(["cmd": "start"]) }
    func stopRecording() { send(["cmd": "stop"]) }
    func cancelRecording() { send(["cmd": "cancel"]) }
    func reload() { send(["cmd": "reload"]) }

    private func consume(_ d: Data) {
        buffer.append(d)
        while let nl = buffer.firstIndex(of: 0x0A) {
            let line = buffer[buffer.startIndex..<nl]
            buffer.removeSubrange(buffer.startIndex...nl)
            guard let obj = try? JSONSerialization.jsonObject(with: line) as? [String: Any],
                  let event = obj["event"] as? String else { continue }
            switch event {
            case "ready": status = .idle
            case "status":
                switch obj["status"] as? String {
                case "recording": status = .recording
                case "processing": status = .processing
                default: status = .idle
                }
            case "result":
                if let e = HistoryEntry(json: obj) {
                    let cfg = AppConfig(); // re-read so Settings changes apply immediately
                    var mode = cfg.string("paste_mode", "clipboard")
                    let trusted = AXIsProcessTrusted()
                    if !trusted && mode != "copy" && mode != "none" {
                        mode = "copy"
                        Notifier.show(title: "Copied to clipboard", body: "Grant Wispr Local Accessibility access to paste automatically.")
                    }
                    Paster.insert(e.clean, mode: mode)
                    log("[app] result \(e.clean.count) chars → \(mode) (accessibility trusted: \(trusted), front app: \(NSWorkspace.shared.frontmostApplication?.localizedName ?? "?"))")
                    onResult?(e)
                }
            case "dropped":
                log("[app] no speech detected (\(obj["reason"] as? String ?? "")) – if this keeps happening, check Microphone access for Wispr Local")
            case "error": status = .error(obj["message"] as? String ?? "unknown error")
            default: break
            }
        }
    }

    func log(_ s: String) {
        for l in s.split(separator: "\n") where !l.contains("it/s]") && !l.contains("0.00B") {
            logLines.append(String(l))
            Self.appendToFile(String(l))
        }
        if logLines.count > 400 { logLines.removeFirst(logLines.count - 400) }
    }

    private static let logFile = AppConfig.logsDir.appendingPathComponent("app.log")
    private static func appendToFile(_ line: String) {
        try? FileManager.default.createDirectory(at: AppConfig.logsDir, withIntermediateDirectories: true)
        let stamp = ISO8601DateFormatter().string(from: Date())
        guard let d = (stamp + " " + line + "\n").data(using: .utf8) else { return }
        if let h = try? FileHandle(forWritingTo: logFile) { h.seekToEndOfFile(); h.write(d); try? h.close() }
        else { try? d.write(to: logFile) }
    }
}
