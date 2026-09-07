import AppKit

/// Hold-to-talk on a single key (modifier or regular). Quick tap toggles hands-free
/// lock; any other key pressed while held cancels (so Ctrl+C keeps working).
final class HotkeyMonitor {
    var keyCode: UInt16
    var tapSeconds: Double
    var onStart: () -> Void = {}
    var onStop: () -> Void = {}
    var onCancel: () -> Void = {}
    var enabled = true

    private var monitors: [Any] = []
    private var downAt: Date?
    private var chorded = false
    private(set) var locked = false

    init(keyCode: UInt16, tapSeconds: Double) {
        self.keyCode = keyCode
        self.tapSeconds = tapSeconds
        let mask: NSEvent.EventTypeMask = [.keyDown, .keyUp, .flagsChanged]
        monitors.append(NSEvent.addGlobalMonitorForEvents(matching: mask) { [weak self] e in self?.handle(e) } as Any)
        monitors.append(NSEvent.addLocalMonitorForEvents(matching: mask) { [weak self] e in self?.handle(e); return e } as Any)
    }

    static func isModifier(_ code: UInt16) -> Bool { modifierFlag(for: code) != nil }

    static func modifierFlag(for code: UInt16) -> NSEvent.ModifierFlags? {
        switch code {
        case 59, 62: return .control
        case 58, 61: return .option
        case 55, 54: return .command
        case 56, 60: return .shift
        case 63: return .function
        case 57: return .capsLock
        default: return nil
        }
    }

    private func handle(_ e: NSEvent) {
        guard enabled else { return }
        if e.type == .flagsChanged {
            if e.keyCode == keyCode, let flag = Self.modifierFlag(for: keyCode) {
                e.modifierFlags.contains(flag) ? pressed() : released()
            } else if downAt != nil {
                chord()  // another modifier joined while our key is held
            }
            return
        }
        if e.keyCode == keyCode && !Self.isModifier(keyCode) {
            if e.type == .keyDown { if !e.isARepeat { pressed() } } else { released() }
            return
        }
        if e.type == .keyDown && downAt != nil { chord() }
    }

    private func pressed() {
        guard downAt == nil else { return }
        downAt = Date(); chorded = false
        if !locked { onStart() }
    }

    private func chord() {
        guard !chorded else { return }
        chorded = true
        if !locked { onCancel() }
    }

    private func released() {
        guard let t = downAt else { return }
        downAt = nil
        if chorded { chorded = false; return }
        if locked { locked = false; onStop(); return }
        if Date().timeIntervalSince(t) < tapSeconds { locked = true; return }
        onStop()
    }

    func unlock() { if locked { locked = false; onStop() } }

    deinit { monitors.forEach { NSEvent.removeMonitor($0) } }
}

enum KeyNames {
    static func name(for e: NSEvent) -> String {
        if let m = HotkeyMonitor.modifierFlag(for: e.keyCode) {
            let side = [62, 61, 54, 60].contains(Int(e.keyCode)) ? "Right " : ""
            switch m {
            case .control: return side + "Control"
            case .option: return side + "Option"
            case .command: return side + "Command"
            case .shift: return side + "Shift"
            case .function: return "Fn"
            case .capsLock: return "Caps Lock"
            default: break
            }
        }
        let special: [UInt16: String] = [49: "Space", 36: "Return", 48: "Tab", 53: "Escape", 51: "Delete",
            122: "F1", 120: "F2", 99: "F3", 118: "F4", 96: "F5", 97: "F6", 98: "F7", 100: "F8", 101: "F9",
            109: "F10", 103: "F11", 111: "F12", 105: "F13", 107: "F14", 113: "F15", 106: "F16"]
        if let s = special[e.keyCode] { return s }
        return (e.charactersIgnoringModifiers ?? "key \(e.keyCode)").uppercased()
    }
}
