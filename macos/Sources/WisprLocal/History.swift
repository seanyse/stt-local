import AppKit
import SwiftUI

final class HistoryStore: ObservableObject {
    @Published var entries: [HistoryEntry] = []
    private var player: NSSound?

    init() { reload() }

    func reload() {
        guard let text = try? String(contentsOf: AppConfig.historyFile, encoding: .utf8) else { entries = []; return }
        entries = text.split(separator: "\n").compactMap { line in
            guard let d = line.data(using: .utf8),
                  let obj = try? JSONSerialization.jsonObject(with: d) as? [String: Any] else { return nil }
            return HistoryEntry(json: obj)
        }.reversed()
    }

    func append(_ e: HistoryEntry) { entries.insert(e, at: 0) }

    func copy(_ s: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(s, forType: .string)
    }

    func play(_ path: String) {
        player?.stop()
        player = NSSound(contentsOfFile: path, byReference: true)
        player?.play()
    }
}

struct HistoryView: View {
    @EnvironmentObject var state: AppState
    @State private var query = ""
    @State private var expanded: Set<String> = []

    var filtered: [HistoryEntry] {
        let q = query.trimmingCharacters(in: .whitespaces).lowercased()
        return q.isEmpty ? state.history.entries
            : state.history.entries.filter { $0.clean.lowercased().contains(q) || $0.raw.lowercased().contains(q) }
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                TextField("Search transcriptions", text: $query).textFieldStyle(.roundedBorder)
                Button { state.history.reload() } label: { Image(systemName: "arrow.clockwise") }
                Button("Logs folder") { NSWorkspace.shared.open(AppConfig.logsDir) }
            }
            .padding(12)
            Divider()
            if filtered.isEmpty {
                Spacer()
                Text(query.isEmpty ? "No dictations yet. Hold \(state.config.hotkeyLabel) and talk." : "No matches")
                    .foregroundStyle(.secondary)
                Spacer()
            } else {
                List(filtered) { e in row(e) }
                .listStyle(.inset)
            }
        }
        .frame(minWidth: 560, minHeight: 360)
    }

    @ViewBuilder
    private func row(_ e: HistoryEntry) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(e.ts, format: .dateTime.month(.abbreviated).day().hour().minute())
                    .font(.caption).foregroundStyle(.secondary)
                Text("\(e.audioSeconds, specifier: "%.0f")s · \(e.totalMs) ms")
                    .font(.caption).foregroundStyle(.tertiary)
                Spacer()
                Button { state.history.copy(e.clean) } label: { Label("Copy", systemImage: "doc.on.doc") }
                if let w = e.wav, FileManager.default.fileExists(atPath: w) {
                    Button { state.history.play(w) } label: { Label("Play", systemImage: "play.fill") }
                    Button { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: w)]) } label: { Image(systemName: "folder") }
                        .help("Reveal wav in Finder")
                }
                Button { toggle(e.id) } label: { Image(systemName: expanded.contains(e.id) ? "chevron.up" : "chevron.down") }
                    .help("Show raw transcript")
            }
            .buttonStyle(.borderless)
            Text(e.clean).textSelection(.enabled)
            if expanded.contains(e.id) && e.raw != e.clean {
                Text("Raw: " + e.raw).font(.callout).foregroundStyle(.secondary).textSelection(.enabled)
            }
        }
        .padding(.vertical, 6)
    }

    private func toggle(_ id: String) {
        if expanded.contains(id) { expanded.remove(id) } else { expanded.insert(id) }
    }
}
