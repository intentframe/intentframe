import EventKit
import Foundation

actor RemindersService {
    private let store = EKEventStore()

    func requestAccess() async -> Bool {
        do {
            return try await store.requestFullAccessToReminders()
        } catch {
            return false
        }
    }

    func checkAccess() -> Bool {
        EKEventStore.authorizationStatus(for: .reminder) == .fullAccess
    }

    private func ensureAccess() -> ExecuteResponse? {
        guard checkAccess() else {
            return .failure(.accessDenied(
                "Reminders access not granted. Grant in System Settings > Privacy & Security > Reminders"
            ))
        }
        return nil
    }

    func execute(action: String, params: [String: AnyCodableValue]) async -> ExecuteResponse {
        if let denied = ensureAccess() { return denied }

        switch action {
        case "LIST_REMINDER_LISTS":
            return listLists()
        case "LIST_REMINDERS":
            return await listReminders(params)
        case "CREATE_REMINDER":
            return createReminder(params)
        case "COMPLETE_REMINDER":
            return completeReminder(params)
        case "UPDATE_REMINDER":
            return updateReminder(params)
        case "DELETE_REMINDER":
            return deleteReminder(params)
        default:
            return .failure(.unknownAction(action, adapter: "reminders"))
        }
    }

    func rollback(rollbackId: String) async -> ExecuteResponse {
        if let denied = ensureAccess() { return denied }
        guard rollbackId.hasPrefix("reminder:") else {
            return .failure("Invalid rollback ID")
        }
        let reminderId = String(rollbackId.dropFirst("reminder:".count))
        guard let reminder = store.calendarItem(withIdentifier: reminderId) as? EKReminder else {
            return .failure(.notFound("Reminder not found for rollback"))
        }
        do {
            try store.remove(reminder, commit: true)
            return .success(data: [
                "reminder_id": .string(reminderId),
                "rolled_back": .bool(true),
            ])
        } catch {
            return .failure(.operationFailed("Rollback failed: \(error.localizedDescription)"))
        }
    }

    // MARK: - Actions

    private func listLists() -> ExecuteResponse {
        let lists = store.calendars(for: .reminder).map { listToDict($0) }
        return .success(data: [
            "lists": .array(lists.map { .object($0) }),
            "count": .int(lists.count),
        ])
    }

    private func listReminders(_ params: [String: AnyCodableValue]) async -> ExecuteResponse {
        let listName = params["list"]?.stringValue
        let includeCompleted = params["include_completed"]?.boolValue ?? false
        let limit = params["limit"]?.intValue ?? 20

        var calendars: [EKCalendar]?
        if let name = listName, !name.isEmpty {
            calendars = store.calendars(for: .reminder).filter { $0.title == name }
            if calendars?.isEmpty == true {
                return .failure(.notFound("Reminder list not found: \(name)"))
            }
        }

        let predicate: NSPredicate
        if includeCompleted {
            predicate = store.predicateForReminders(in: calendars)
        } else {
            predicate = store.predicateForIncompleteReminders(
                withDueDateStarting: nil, ending: nil, calendars: calendars
            )
        }

        let reminders: [EKReminder] = await withCheckedContinuation { continuation in
            store.fetchReminders(matching: predicate) { result in
                continuation.resume(returning: result ?? [])
            }
        }

        let data = reminders.prefix(limit).map { reminderToDict($0) }

        return .success(data: [
            "reminders": .array(data.map { .object($0) }),
            "count": .int(data.count),
        ])
    }

    private func createReminder(_ params: [String: AnyCodableValue]) -> ExecuteResponse {
        guard let title = params["title"]?.stringValue, !title.isEmpty else {
            return .failure(.invalidInput("Reminder title required"))
        }

        let rawListName = params["list"]?.stringValue
        let listName = (rawListName?.isEmpty == false) ? rawListName! : "Reminders"

        let reminder = EKReminder(eventStore: store)
        reminder.title = title

        if let list = store.calendars(for: .reminder).first(where: { $0.title == listName }) {
            reminder.calendar = list
        } else {
            reminder.calendar = store.defaultCalendarForNewReminders()
        }
        guard reminder.calendar != nil else {
            return .failure(.notFound("No reminder list found"))
        }

        if let notes = params["notes"]?.stringValue, !notes.isEmpty { reminder.notes = notes }
        if let priority = params["priority"]?.intValue, priority != 0 { reminder.priority = priority }

        if let dueStr = params["due_date"]?.stringValue, let dueDate = DateParsing.parse(dueStr) {
            reminder.dueDateComponents = Calendar.current.dateComponents(
                [.year, .month, .day, .hour, .minute], from: dueDate
            )
        }

        if let urlStr = params["url"]?.stringValue, let url = URL(string: urlStr) {
            reminder.url = url
        }

        if let recurrenceJSON = params["recurrence"]?.stringValue,
           let data = recurrenceJSON.data(using: .utf8),
           let input = try? JSONDecoder().decode(RecurrenceInput.self, from: data),
           let rule = RecurrenceHelpers.buildRule(from: input) {
            reminder.addRecurrenceRule(rule)
        }

        do {
            try store.save(reminder, commit: true)
        } catch {
            return .failure(.operationFailed("Failed to save reminder: \(error.localizedDescription)"))
        }

        return .success(
            data: reminderToDict(reminder),
            rollbackId: "reminder:\(reminder.calendarItemIdentifier)"
        )
    }

    private func completeReminder(_ params: [String: AnyCodableValue]) -> ExecuteResponse {
        let reminderId = params["reminder_id"]?.stringValue
        let title = params["title"]?.stringValue
        let undo = params["undo"]?.boolValue ?? false

        if let reminderId,
           let reminder = store.calendarItem(withIdentifier: reminderId) as? EKReminder {
            reminder.isCompleted = !undo
            reminder.completionDate = undo ? nil : Date()
            do {
                try store.save(reminder, commit: true)
                return .success(data: reminderToDict(reminder))
            } catch {
                return .failure(.operationFailed("Complete failed: \(error.localizedDescription)"))
            }
        }

        guard let title else {
            return .failure(.invalidInput("reminder_id or title required"))
        }

        return .failure(.notFound("Active reminder not found: \(title)"))
    }

    private func updateReminder(_ params: [String: AnyCodableValue]) -> ExecuteResponse {
        guard let reminderId = params["reminder_id"]?.stringValue else {
            return .failure(.invalidInput("reminder_id is required"))
        }
        guard let reminder = store.calendarItem(withIdentifier: reminderId) as? EKReminder else {
            return .failure(.notFound("Reminder not found: \(reminderId)"))
        }

        if let title = params["title"]?.stringValue, !title.isEmpty { reminder.title = title }
        if let notes = params["notes"]?.stringValue, !notes.isEmpty { reminder.notes = notes }
        if let priority = params["priority"]?.intValue, priority != 0 { reminder.priority = priority }

        if let dueStr = params["due_date"]?.stringValue, let dueDate = DateParsing.parse(dueStr) {
            reminder.dueDateComponents = Calendar.current.dateComponents(
                [.year, .month, .day, .hour, .minute], from: dueDate
            )
        }

        do {
            try store.save(reminder, commit: true)
        } catch {
            return .failure(.operationFailed("Update failed: \(error.localizedDescription)"))
        }

        return .success(data: reminderToDict(reminder))
    }

    private func deleteReminder(_ params: [String: AnyCodableValue]) -> ExecuteResponse {
        guard let reminderId = params["reminder_id"]?.stringValue else {
            return .failure(.invalidInput("reminder_id is required"))
        }
        guard let reminder = store.calendarItem(withIdentifier: reminderId) as? EKReminder else {
            return .failure(.notFound("Reminder not found: \(reminderId)"))
        }

        let info = reminderToDict(reminder)
        do {
            try store.remove(reminder, commit: true)
            return .success(data: info)
        } catch {
            return .failure(.operationFailed("Delete failed: \(error.localizedDescription)"))
        }
    }

    // MARK: - Serialization

    private func listToDict(_ list: EKCalendar) -> [String: AnyCodableValue] {
        [
            "id": .string(list.calendarIdentifier),
            "title": .string(list.title),
            "allows_modifications": .bool(list.allowsContentModifications),
            "source": .string(list.source?.title ?? "Unknown"),
        ]
    }

    private func reminderToDict(_ reminder: EKReminder) -> [String: AnyCodableValue] {
        var dict: [String: AnyCodableValue] = [
            "reminder_id": .string(reminder.calendarItemIdentifier),
            "title": .string(reminder.title ?? ""),
            "completed": .bool(reminder.isCompleted),
            "list": .string(reminder.calendar?.title ?? ""),
            "priority": .int(reminder.priority),
        ]

        if let completionDate = reminder.completionDate {
            dict["completion_date"] = .string(DateParsing.toISO(completionDate))
        }
        if let dueComps = reminder.dueDateComponents,
           let dueDate = Calendar.current.date(from: dueComps) {
            dict["due_date"] = .string(DateParsing.toISO(dueDate))
        }
        if let notes = reminder.notes, !notes.isEmpty { dict["notes"] = .string(notes) }
        if let url = reminder.url { dict["url"] = .string(url.absoluteString) }

        if reminder.hasRecurrenceRules, let rules = reminder.recurrenceRules {
            dict["recurrence"] = .array(rules.map { .object(RecurrenceHelpers.ruleToDict($0)) })
        }

        return dict
    }
}
