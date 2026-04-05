import AppKit
import Foundation
import Vapor

@main
enum PlatformServer {
    static func main() async throws {
        ProcessInfo.processInfo.setValue("platform-server", forKey: "processName")

        let nsApp = NSApplication.shared
        nsApp.setActivationPolicy(.accessory)

        let socketPath = ProcessInfo.processInfo.environment["PLATFORM_SOCKET"]
            ?? NSHomeDirectory() + "/.intentframe/run/platform.sock"

        let runDir = (socketPath as NSString).deletingLastPathComponent
        let pidPath = runDir + "/platform-server.pid"
        let logDir = NSHomeDirectory() + "/.intentframe/logs"
        let logFile = logDir + "/platform-server.log"

        try FileManager.default.createDirectory(
            atPath: runDir, withIntermediateDirectories: true
        )
        try FileManager.default.createDirectory(
            atPath: logDir, withIntermediateDirectories: true
        )

        setupFileLogging(logFile)

        try? FileManager.default.removeItem(atPath: socketPath)

        try "\(ProcessInfo.processInfo.processIdentifier)"
            .write(toFile: pidPath, atomically: true, encoding: .utf8)
        log("[platform-server] PID \(ProcessInfo.processInfo.processIdentifier) written to \(pidPath)")

        var env = try Environment.detect()
        try LoggingSystem.bootstrap(from: &env)

        let app = try await Application.make(env)
        app.http.server.configuration.address = .unixDomainSocket(path: socketPath)

        let dispatcher = ServiceDispatcher()
        log("[platform-server] Requesting permissions...")
        await dispatcher.requestAllAccess()
        log("[platform-server] Permissions done, registering routes...")

        try registerRoutes(app, dispatcher: dispatcher)
        log("[platform-server] Routes registered, starting server...")

        log("[platform-server] Listening on \(socketPath)")
        try await app.execute()
        log("[platform-server] Server stopped")
        try await app.asyncShutdown()
        try? FileManager.default.removeItem(atPath: pidPath)
    }

    /// Redirect stdout/stderr to both the terminal (if attached) AND a log file.
    /// When launched via `open .app`, there is no terminal — the file is the only output.
    private static func setupFileLogging(_ path: String) {
        FileManager.default.createFile(atPath: path, contents: nil)
        guard let fileHandle = FileHandle(forWritingAtPath: path) else { return }
        fileHandle.seekToEndOfFile()

        let header = "[\(ISO8601DateFormatter().string(from: Date()))] platform-server starting\n"
        fileHandle.write(header.data(using: .utf8)!)

        // Duplicate stdout/stderr to the log file
        let fd = fileHandle.fileDescriptor
        dup2(fd, STDOUT_FILENO)
        dup2(fd, STDERR_FILENO)
    }

    private static func log(_ message: String) {
        let ts = ISO8601DateFormatter().string(from: Date())
        print("[\(ts)] \(message)")
    }
}
