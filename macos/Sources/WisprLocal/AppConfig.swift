import Foundation

/// The same config.json the Python engine reads. Kept as a loose dictionary so keys the
/// UI doesn't know about survive a round trip.
final class AppConfig: ObservableObject {
    static let dir: URL = {
        if let env = ProcessInfo.processInfo.environment["WISPR_CONFIG_DIR"] { return URL(fileURLWithPath: env) }
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/wispr-local")
    }()
    static var file: URL { dir.appendingPathComponent("config.json") }
    static var logsDir: URL { dir.appendingPathComponent("logs") }
    static var historyFile: URL { logsDir.appendingPathComponent("history.jsonl") }

    @Published var raw: [String: Any] = [:]

    init() { load() }

    func load() {
        if let data = try? Data(contentsOf: Self.file),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            raw = obj
        }
    }

    func save() {
        try? FileManager.default.createDirectory(at: Self.dir, withIntermediateDirectories: true)
        if let data = try? JSONSerialization.data(withJSONObject: raw, options: [.prettyPrinted, .sortedKeys]) {
            try? data.write(to: Self.file)
        }
    }

    // Typed accessors with the engine's defaults.
    func string(_ k: String, _ d: String) -> String { raw[k] as? String ?? d }
    func int(_ k: String, _ d: Int) -> Int { raw[k] as? Int ?? d }
    func bool(_ k: String, _ d: Bool) -> Bool { raw[k] as? Bool ?? d }
    func strings(_ k: String) -> [String] { raw[k] as? [String] ?? [] }
    func dict(_ k: String) -> [String: String] { raw[k] as? [String: String] ?? [:] }
    func set(_ k: String, _ v: Any) { raw[k] = v; objectWillChange.send() }

    var hotkeyCode: UInt16 { UInt16(int("hotkey_keycode", 59)) }
    var hotkeyLabel: String { string("hotkey_label", "Control") }
    var tapSeconds: Double { raw["tap_seconds"] as? Double ?? 0.25 }
}
