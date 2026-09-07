import AppKit
import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var state: AppState
    @State private var recording = false
    @State private var recordMonitor: Any?
    @State private var dirty = false
    @State private var applied = false

    // Local copies of the fields so typing doesn't reload models on every keystroke.
    @State private var sttModel = ""
    @State private var formatter = ""
    @State private var llmMode = ""
    @State private var llmModel = ""
    @State private var claudeModel = ""
    @State private var pasteMode = ""
    @State private var saveAudio = true
    @State private var warmOnStart = true
    @State private var vocabulary = ""
    @State private var replacements = ""
    @State private var minWords = 4

    var body: some View {
        Form {
            Section("Hotkey") {
                HStack {
                    Text("Hold to talk:")
                    Text(state.config.hotkeyLabel).font(.headline)
                        .padding(.horizontal, 10).padding(.vertical, 4)
                        .background(.quaternary, in: RoundedRectangle(cornerRadius: 6))
                    Spacer()
                    Button(recording ? "Press a key…" : "Change") { recording ? stopRecord() : startRecord() }
                }
                Text("Hold and speak, release to insert. A quick tap locks hands-free mode until the next tap. Pressing another key while holding cancels, so shortcuts keep working.")
                    .font(.caption).foregroundStyle(.secondary)
                if !state.accessibilityGranted {
                    Label("Accessibility access is required for the hotkey and for pasting.", systemImage: "exclamationmark.triangle")
                        .foregroundStyle(.orange)
                    Button("Open Privacy & Security…") {
                        NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")!)
                    }
                }
            }
            Section("Speech to text") {
                Picker("Model", selection: $sttModel) {
                    Text("Whisper large-v3-turbo (accurate, ~1 s)").tag("mlx-community/whisper-large-v3-turbo")
                    Text("Parakeet TDT 0.6B v3 (fast, ~0.2 s)").tag("mlx-community/parakeet-tdt-0.6b-v3")
                    Text("Parakeet TDT 0.6B v2 (English only)").tag("mlx-community/parakeet-tdt-0.6b-v2")
                }
                TextField("Vocabulary (comma separated names and jargon)", text: $vocabulary)
                Toggle("Warm up the GPU when the key goes down", isOn: $warmOnStart)
            }
            Section("Cleanup") {
                Picker("LLM pass", selection: $formatter) {
                    Text("Off – dictionary and rules only").tag("none")
                    Text("Local model").tag("local")
                    Text("Claude (needs ANTHROPIC_API_KEY)").tag("claude")
                }
                if formatter != "none" {
                    Picker("Run it", selection: $llmMode) {
                        Text("Only on self-corrections / formatting phrases").tag("triggers")
                        Text("On every dictation").tag("always")
                    }
                    if formatter == "local" { TextField("Local model", text: $llmModel) }
                    if formatter == "claude" { TextField("Claude model", text: $claudeModel) }
                    Stepper("Skip dictations shorter than \(minWords) words", value: $minWords, in: 1...20)
                }
                VStack(alignment: .leading) {
                    Text("Dictionary – one per line, `heard => replacement`")
                    TextEditor(text: $replacements).font(.system(.body, design: .monospaced)).frame(height: 110)
                }
            }
            Section("Output") {
                Picker("Insert text by", selection: $pasteMode) {
                    Text("Paste (Cmd+V, clipboard restored)").tag("clipboard")
                    Text("Typing keystrokes").tag("type")
                    Text("Copy to clipboard only").tag("copy")
                }
                Toggle("Keep a recording of each dictation (logs folder)", isOn: $saveAudio)
            }
            Section("Engine") {
                HStack {
                    Text(statusLine).foregroundStyle(.secondary)
                    Spacer()
                    Button("Restart") { state.backend.start() }
                }
                Text("Python: \(Backend.pythonPath)").font(.caption).foregroundStyle(.tertiary).textSelection(.enabled)
                DisclosureGroup("Engine log") {
                    ScrollView {
                        Text(state.backend.logLines.suffix(60).joined(separator: "\n"))
                            .font(.system(size: 11, design: .monospaced)).textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }.frame(height: 160)
                }
            }
            HStack {
                if applied { Text("Applied").foregroundStyle(.green) }
                Spacer()
                Button("Apply") { apply() }.keyboardShortcut(.defaultAction).disabled(!dirty)
            }
        }
        .formStyle(.grouped)
        .frame(width: 560)
        .onAppear(perform: loadFields)
        .onChange(of: [sttModel, formatter, llmMode, llmModel, claudeModel, pasteMode, vocabulary, replacements]) { _, _ in markDirty() }
        .onChange(of: [saveAudio, warmOnStart]) { _, _ in markDirty() }
        .onChange(of: minWords) { _, _ in markDirty() }
    }

    private var statusLine: String {
        switch state.backend.status {
        case .starting: return "Loading models…"
        case .idle: return "Ready"
        case .recording: return "Listening"
        case .processing: return "Transcribing"
        case .stopped: return "Stopped"
        case .error(let m): return "Error: \(m)"
        }
    }

    private func markDirty() { dirty = true; applied = false }

    private func loadFields() {
        let c = state.config
        sttModel = c.string("stt_model", "mlx-community/whisper-large-v3-turbo")
        formatter = c.string("formatter", "none")
        llmMode = c.string("llm_mode", "triggers")
        llmModel = c.string("llm_model", "mlx-community/Qwen2.5-3B-Instruct-4bit")
        claudeModel = c.string("claude_model", "claude-opus-5")
        pasteMode = c.string("paste_mode", "clipboard")
        saveAudio = c.bool("save_audio", true)
        warmOnStart = c.bool("warm_on_start", true)
        vocabulary = c.strings("vocabulary").joined(separator: ", ")
        replacements = c.dict("replacements").sorted { $0.key < $1.key }.map { "\($0.key) => \($0.value)" }.joined(separator: "\n")
        minWords = c.int("min_words_for_llm", 4)
        DispatchQueue.main.async { dirty = false }
    }

    private func apply() {
        let c = state.config
        c.set("stt_model", sttModel); c.set("formatter", formatter); c.set("llm_mode", llmMode)
        c.set("llm_model", llmModel); c.set("claude_model", claudeModel); c.set("paste_mode", pasteMode)
        c.set("save_audio", saveAudio); c.set("warm_on_start", warmOnStart); c.set("min_words_for_llm", minWords)
        c.set("vocabulary", vocabulary.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty })
        var dict: [String: String] = [:]
        for line in replacements.split(separator: "\n") {
            let parts = line.components(separatedBy: "=>")
            guard parts.count == 2 else { continue }
            let k = parts[0].trimmingCharacters(in: .whitespaces), v = parts[1].trimmingCharacters(in: .whitespaces)
            if !k.isEmpty { dict[k] = v }
        }
        c.set("replacements", dict)
        c.save()
        state.backend.reload()
        dirty = false; applied = true
    }

    private func startRecord() {
        recording = true
        state.hotkey?.enabled = false
        recordMonitor = NSEvent.addLocalMonitorForEvents(matching: [.keyDown, .flagsChanged]) { e in
            if e.type == .flagsChanged, HotkeyMonitor.modifierFlag(for: e.keyCode) == nil { return e }
            if e.type == .flagsChanged {
                // only accept the press, not the release
                guard let f = HotkeyMonitor.modifierFlag(for: e.keyCode), e.modifierFlags.contains(f) else { return e }
            }
            setHotkey(code: e.keyCode, label: KeyNames.name(for: e))
            return nil
        }
    }

    private func stopRecord() {
        recording = false
        state.hotkey?.enabled = true
        if let m = recordMonitor { NSEvent.removeMonitor(m); recordMonitor = nil }
    }

    private func setHotkey(code: UInt16, label: String) {
        stopRecord()
        state.config.set("hotkey_keycode", Int(code))
        state.config.set("hotkey_label", label)
        state.config.save()
        state.hotkey?.keyCode = code
    }
}
