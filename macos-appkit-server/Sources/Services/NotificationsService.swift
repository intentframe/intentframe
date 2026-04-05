import Foundation
import UserNotifications

actor NotificationsService {

    func requestAccess() async -> Bool {
        do {
            return try await UNUserNotificationCenter.current().requestAuthorization(
                options: [.alert, .sound, .badge]
            )
        } catch {
            return false
        }
    }

    func checkAccess() async -> Bool {
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        return settings.authorizationStatus == .authorized
    }

    func execute(action: String, params: [String: AnyCodableValue]) async -> ExecuteResponse {
        switch action {
        case "SHOW_NOTIFICATION":
            return await showNotification(params)
        default:
            return .failure(.unknownAction(action, adapter: "notifications"))
        }
    }

    // MARK: - Show Notification (UNUserNotificationCenter)

    private func showNotification(_ params: [String: AnyCodableValue]) async -> ExecuteResponse {
        let title = params["title"]?.stringValue ?? "IntentFrame"
        let message = params["message"]?.stringValue ?? ""
        let subtitle = params["subtitle"]?.stringValue ?? ""
        let soundName = params["sound"]?.stringValue ?? "default"

        // Ensure authorized
        let authorized = await checkAccess()
        if !authorized {
            // Request on-demand if not yet asked
            let granted = await requestAccess()
            if !granted {
                return .failure(.accessDenied(
                    "Notification permission not granted. Grant in System Settings > Notifications > IntentFrame Platform Server."
                ))
            }
        }

        let content = UNMutableNotificationContent()
        content.title = title
        content.body = message
        if !subtitle.isEmpty {
            content.subtitle = subtitle
        }
        if soundName == "default" {
            content.sound = .default
        } else if !soundName.isEmpty {
            content.sound = UNNotificationSound(named: UNNotificationSoundName(soundName))
        }

        let identifier = UUID().uuidString
        let request = UNNotificationRequest(identifier: identifier, content: content, trigger: nil)

        do {
            try await UNUserNotificationCenter.current().add(request)
            return .success(data: [
                "shown": .bool(true),
                "title": .string(title),
                "identifier": .string(identifier),
            ])
        } catch {
            return .failure(.operationFailed("Failed to show notification: \(error.localizedDescription)"))
        }
    }
}
