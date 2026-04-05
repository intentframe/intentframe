import AppKit
import CoreGraphics
import Foundation

private typealias DSGetBrightness = @convention(c) (CGDirectDisplayID, UnsafeMutablePointer<Float>) -> Int32
private typealias DSSetBrightness = @convention(c) (CGDirectDisplayID, Float) -> Int32

actor SystemService {

    private static let dsHandle: UnsafeMutableRawPointer? = dlopen(
        "/System/Library/PrivateFrameworks/DisplayServices.framework/DisplayServices",
        RTLD_LAZY
    )

    private static let dsGetBrightness: DSGetBrightness? = {
        guard let h = dsHandle, let sym = dlsym(h, "DisplayServicesGetBrightness") else { return nil }
        return unsafeBitCast(sym, to: DSGetBrightness.self)
    }()

    private static let dsSetBrightness: DSSetBrightness? = {
        guard let h = dsHandle, let sym = dlsym(h, "DisplayServicesSetBrightness") else { return nil }
        return unsafeBitCast(sym, to: DSSetBrightness.self)
    }()

    func execute(action: String, params: [String: AnyCodableValue]) async -> ExecuteResponse {
        switch action {
        case "SET_BRIGHTNESS":
            return setBrightness(params)
        case "GET_BRIGHTNESS":
            return getBrightness()
        case "SET_VOLUME":
            return setVolume(params)
        case "GET_VOLUME":
            return getVolume()
        case "TOGGLE_MUTE":
            return toggleMute()
        case "GET_MUTE":
            return getMute()
        case "TOGGLE_DARK_MODE":
            return await toggleDarkMode()
        case "GET_DARK_MODE":
            return getDarkMode()
        default:
            return .failure(.unknownAction(action, adapter: "system"))
        }
    }

    func rollback(rollbackId: String) async -> ExecuteResponse {
        return .failure("System changes are not rollbackable")
    }

    // MARK: - Brightness (DisplayServices private framework — works on Apple Silicon + Intel)

    private func getBrightnessLevel() -> Float? {
        guard let getter = Self.dsGetBrightness else { return nil }
        var brightness: Float = 0
        let rc = getter(CGMainDisplayID(), &brightness)
        return rc == 0 ? brightness : nil
    }

    private func setBrightness(_ params: [String: AnyCodableValue]) -> ExecuteResponse {
        guard let rawLevel = params["level"]?.doubleValue else {
            return .failure(.invalidInput("level (0.0–1.0) is required"))
        }
        let level = Float(min(1.0, max(0.0, rawLevel)))

        guard let setter = Self.dsSetBrightness else {
            return .failure(.operationFailed("DisplayServices framework not available"))
        }

        let rc = setter(CGMainDisplayID(), level)
        guard rc == 0 else {
            return .failure(.operationFailed("DisplayServicesSetBrightness failed (\(rc))"))
        }

        return .success(data: ["brightness": .double(Double(level))])
    }

    private func getBrightness() -> ExecuteResponse {
        guard let level = getBrightnessLevel() else {
            return .failure(.operationFailed("Could not read display brightness"))
        }
        return .success(data: ["brightness": .double(Double(level))])
    }

    // MARK: - Volume (NSAppleScript — no subprocess, runs in-process)

    private func runAppleScript(_ source: String) -> (NSAppleEventDescriptor?, NSDictionary?) {
        let script = NSAppleScript(source: source)
        var errorInfo: NSDictionary?
        let result = script?.executeAndReturnError(&errorInfo)
        return (result, errorInfo)
    }

    private func getVolume() -> ExecuteResponse {
        let (result, err) = runAppleScript("output volume of (get volume settings)")
        if let err = err {
            return .failure(.operationFailed("Could not read volume: \(err)"))
        }
        let volume = result?.int32Value ?? 0
        return .success(data: ["volume": .int(Int(volume))])
    }

    private func setVolume(_ params: [String: AnyCodableValue]) -> ExecuteResponse {
        guard let rawLevel = params["level"]?.doubleValue else {
            return .failure(.invalidInput("level (0–100) is required"))
        }
        let level = Int(min(100, max(0, rawLevel)))
        let (_, err) = runAppleScript("set volume output volume \(level)")
        if let err = err {
            return .failure(.operationFailed("Could not set volume: \(err)"))
        }
        return .success(data: ["volume": .int(level)])
    }

    private func getMute() -> ExecuteResponse {
        let (result, err) = runAppleScript("output muted of (get volume settings)")
        if let err = err {
            return .failure(.operationFailed("Could not read mute state: \(err)"))
        }
        let muted = result?.booleanValue ?? false
        return .success(data: ["muted": .bool(muted)])
    }

    private func toggleMute() -> ExecuteResponse {
        let (current, err1) = runAppleScript("output muted of (get volume settings)")
        if let err1 = err1 {
            return .failure(.operationFailed("Could not read mute state: \(err1)"))
        }
        let wasMuted = current?.booleanValue ?? false
        let keyword = wasMuted ? "without" : "with"
        let (_, err2) = runAppleScript("set volume \(keyword) output muted")
        if let err2 = err2 {
            return .failure(.operationFailed("Could not toggle mute: \(err2)"))
        }
        return .success(data: ["muted": .bool(!wasMuted)])
    }

    // MARK: - Dark Mode (NSAppearance / defaults)

    private func toggleDarkMode() async -> ExecuteResponse {
        let isDark = await MainActor.run {
            NSApp.effectiveAppearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
        }

        // Toggle via AppleScript on main thread — the most reliable cross-version approach
        let script = """
            tell application "System Events"
                tell appearance preferences
                    set dark mode to \(!isDark)
                end tell
            end tell
        """
        let appleScript = NSAppleScript(source: script)
        var errorInfo: NSDictionary?
        appleScript?.executeAndReturnError(&errorInfo)

        if let err = errorInfo {
            let code = err["NSAppleScriptErrorNumber"] as? Int
            let hint = (code == -1743 || code == -1744)
                ? "Grant Automation permission: System Settings > Privacy & Security > Automation"
                : ""
            let msg = hint.isEmpty
                ? "Failed to toggle dark mode (code \(code ?? 0))"
                : "Failed to toggle dark mode — \(hint)"
            return .failure(.operationFailed(msg))
        }

        return .success(data: [
            "dark_mode": .bool(!isDark),
            "toggled": .bool(true),
        ])
    }

    private func getDarkMode() -> ExecuteResponse {
        // Read the global AppleInterfaceStyle default (set/absent == light/dark)
        let isDark = UserDefaults.standard.string(forKey: "AppleInterfaceStyle") == "Dark"
        return .success(data: ["dark_mode": .bool(isDark)])
    }
}
