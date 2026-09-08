import CoreAudio
import Foundation

/// Lowers the system output volume while dictating, if anything is playing, and puts it back.
final class AudioDucker {
    private var savedVolume: Float32?
    private var duckedTo: Float32?

    /// Default output device, or nil.
    private func outputDevice() -> AudioDeviceID? {
        var dev = AudioDeviceID(0)
        var size = UInt32(MemoryLayout<AudioDeviceID>.size)
        var addr = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyDefaultOutputDevice,
                                              mScope: kAudioObjectPropertyScopeGlobal,
                                              mElement: kAudioObjectPropertyElementMain)
        let st = AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size, &dev)
        return st == noErr && dev != 0 ? dev : nil
    }

    /// True when some process is currently playing audio through the device.
    func isPlaying() -> Bool {
        guard let dev = outputDevice() else { return false }
        var running = UInt32(0)
        var size = UInt32(MemoryLayout<UInt32>.size)
        var addr = AudioObjectPropertyAddress(mSelector: kAudioDevicePropertyDeviceIsRunningSomewhere,
                                              mScope: kAudioObjectPropertyScopeGlobal,
                                              mElement: kAudioObjectPropertyElementMain)
        return AudioObjectGetPropertyData(dev, &addr, 0, nil, &size, &running) == noErr && running != 0
    }

    private func volumeAddress() -> AudioObjectPropertyAddress {
        AudioObjectPropertyAddress(mSelector: AudioObjectPropertySelector(0x766D_7663), // 'vmvc' virtual main volume
                                   mScope: kAudioDevicePropertyScopeOutput,
                                   mElement: kAudioObjectPropertyElementMain)
    }

    func volume() -> Float32? {
        guard let dev = outputDevice() else { return nil }
        var addr = volumeAddress()
        guard AudioObjectHasProperty(dev, &addr) else { return nil }
        var v = Float32(0)
        var size = UInt32(MemoryLayout<Float32>.size)
        return AudioObjectGetPropertyData(dev, &addr, 0, nil, &size, &v) == noErr ? v : nil
    }

    @discardableResult
    func setVolume(_ v: Float32) -> Bool {
        guard let dev = outputDevice() else { return false }
        var addr = volumeAddress()
        var settable = DarwinBoolean(false)
        guard AudioObjectIsPropertySettable(dev, &addr, &settable) == noErr, settable.boolValue else { return false }
        var value = max(0, min(1, v))
        return AudioObjectSetPropertyData(dev, &addr, 0, nil, UInt32(MemoryLayout<Float32>.size), &value) == noErr
    }

    /// Lower the volume to `level` (fraction of current, 0…1) if audio is playing. Returns a log line.
    func duck(to level: Float32) -> String {
        guard savedVolume == nil else { return "duck: already ducked" }
        guard isPlaying() else { return "duck: nothing playing" }
        guard let v = volume() else { return "duck: no volume control on output device" }
        let target = v * level
        guard setVolume(target) else { return "duck: could not set volume" }
        savedVolume = v
        duckedTo = target
        return String(format: "duck: %.0f%% → %.0f%%", v * 100, target * 100)
    }

    /// Restore the pre-duck volume, unless the user changed it in the meantime.
    func restore() -> String? {
        guard let saved = savedVolume else { return nil }
        defer { savedVolume = nil; duckedTo = nil }
        if let now = volume(), let ducked = duckedTo, abs(now - ducked) > 0.02 {
            return "duck: volume changed while ducked, leaving it"
        }
        setVolume(saved)
        return String(format: "duck: restored to %.0f%%", saved * 100)
    }
}
