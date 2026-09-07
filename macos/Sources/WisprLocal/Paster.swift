import AppKit

/// Inserts text into the focused app. Lives in the Swift app (not the Python engine)
/// because Accessibility is granted to this bundle, and CGEvent posting from a child
/// process is not covered by it.
enum Paster {
    static func insert(_ text: String, mode: String) {
        guard !text.isEmpty else { return }
        switch mode {
        case "none": return
        case "copy": setClipboard(text)
        case "type": type(text)
        default: pasteViaClipboard(text)
        }
    }

    private static func setClipboard(_ s: String) {
        let pb = NSPasteboard.general
        pb.clearContents()
        pb.setString(s, forType: .string)
    }

    private static func pasteViaClipboard(_ text: String) {
        let pb = NSPasteboard.general
        let previous = pb.string(forType: .string)
        setClipboard(text)
        postKey(9, flags: .maskCommand)  // kVK_ANSI_V
        if let previous {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
                if pb.string(forType: .string) == text { setClipboard(previous) }
            }
        }
    }

    private static func postKey(_ code: CGKeyCode, flags: CGEventFlags) {
        let src = CGEventSource(stateID: .hidSystemState)
        for down in [true, false] {
            guard let e = CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: down) else { continue }
            e.flags = flags
            e.post(tap: .cghidEventTap)
        }
    }

    private static func type(_ text: String) {
        let src = CGEventSource(stateID: .hidSystemState)
        let chars = Array(text.utf16)
        var i = 0
        while i < chars.count {
            let chunk = Array(chars[i..<min(i + 20, chars.count)])
            for down in [true, false] {
                guard let e = CGEvent(keyboardEventSource: src, virtualKey: 0, keyDown: down) else { continue }
                e.keyboardSetUnicodeString(stringLength: chunk.count, unicodeString: chunk)
                e.post(tap: .cghidEventTap)
            }
            i += 20
            usleep(5000)
        }
    }
}
