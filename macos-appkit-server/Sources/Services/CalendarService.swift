import EventKit
import Foundation

actor CalendarService {
    private let store = EKEventStore()

    func requestAccess() async -> Bool {
        do {
            return try await store.requestFullAccessToEvents()
        } catch {
            return false
        }
    }

    func checkAccess() -> Bool {
        EKEventStore.authorizationStatus(for: .event) == .fullAccess
    }

    private func ensureAccess() -> ExecuteResponse? {
        guard checkAccess() else {
            return .failure(.accessDenied(
                "Calendar access not granted. Grant in System Settings > Privacy & Security > Calendars"
            ))
        }
        return nil
    }

    func execute(action: String, params: [String: AnyCodableValue]) async -> ExecuteResponse {
        if let denied = ensureAccess() { return denied }

        switch action {
        case "LIST_CALENDARS":
            return listCalendars()
        case "LIST_EVENTS":
            return listEvents(params)
        case "CREATE_EVENT":
            return createEvent(params)
        case "UPDATE_EVENT":
            return updateEvent(params)
        case "DELETE_EVENT":
            return deleteEvent(params)
        case "SEARCH_EVENTS":
            return searchEvents(params)
        default:
            return .failure(.unknownAction(action, adapter: "calendar"))
        }
    }

    func rollback(rollbackId: String) async -> ExecuteResponse {
        if let denied = ensureAccess() { return denied }
        guard rollbackId.hasPrefix("calendar_event:") else {
            return .failure("Invalid rollback ID")
        }
        let eventId = String(rollbackId.dropFirst("calendar_event:".count))
        guard let event = store.event(withIdentifier: eventId) else {
            return .failure(.notFound("Event not found for rollback"))
        }
        do {
            try store.remove(event, span: .thisEvent)
            return .success(data: [
                "event_id": .string(eventId),
                "rolled_back": .bool(true),
            ])
        } catch {
            return .failure(.operationFailed("Rollback failed: \(error.localizedDescription)"))
        }
    }

    // MARK: - Actions

    private func listCalendars() -> ExecuteResponse {
        let calendars = store.calendars(for: .event).map { calendarToDict($0) }
        return .success(data: [
            "calendars": .array(calendars.map { .object($0) }),
            "count": .int(calendars.count),
        ])
    }

    private func listEvents(_ params: [String: AnyCodableValue]) -> ExecuteResponse {
        let calendarName = params["calendar"]?.stringValue
        let limit = params["limit"]?.intValue ?? 20

        let startRaw = params["start"]?.stringValue
        let endRaw = params["end"]?.stringValue
        let startDate = startRaw.flatMap { DateParsing.parse($0) } ?? Date()
        let rawEnd = endRaw.flatMap { DateParsing.parse($0) }
            ?? Calendar.current.date(byAdding: .day, value: 30, to: startDate)!
        let endDate = DateParsing.normalizeRange(
            startRaw: startRaw, endRaw: endRaw,
            startDate: startDate, endDate: rawEnd
        )

        var calendars: [EKCalendar]?
        if let name = calendarName, !name.isEmpty {
            calendars = store.calendars(for: .event).filter { $0.title == name }
            if calendars?.isEmpty == true {
                return .failure(.notFound("Calendar not found: \(name)"))
            }
        }

        let predicate = store.predicateForEvents(withStart: startDate, end: endDate, calendars: calendars)
        let events = store.events(matching: predicate)

        let eventsData: [[String: AnyCodableValue]] = Array(events.prefix(limit)).map { eventToDict($0) }

        return .success(data: [
            "events": .array(eventsData.map { .object($0) }),
            "count": .int(eventsData.count),
        ])
    }

    private func createEvent(_ params: [String: AnyCodableValue]) -> ExecuteResponse {
        guard let title = params["title"]?.stringValue, !title.isEmpty else {
            return .failure(.invalidInput("title is required"))
        }
        guard let startStr = params["start"]?.stringValue, let startDate = DateParsing.parse(startStr) else {
            return .failure(.invalidInput("Valid start date is required"))
        }

        let endDate: Date
        if let endStr = params["end"]?.stringValue, let parsed = DateParsing.parse(endStr) {
            endDate = parsed
        } else if let duration = params["duration"]?.intValue {
            endDate = Calendar.current.date(byAdding: .minute, value: duration, to: startDate) ?? startDate
        } else {
            endDate = Calendar.current.date(byAdding: .hour, value: 1, to: startDate)!
        }

        let event = EKEvent(eventStore: store)
        event.title = title
        event.startDate = startDate
        event.endDate = endDate

        if let calName = params["calendar"]?.stringValue,
           let cal = store.calendars(for: .event).first(where: { $0.title == calName }) {
            event.calendar = cal
        } else {
            event.calendar = store.defaultCalendarForNewEvents
        }

        if let location = params["location"]?.stringValue, !location.isEmpty { event.location = location }
        if let notes = params["notes"]?.stringValue, !notes.isEmpty { event.notes = notes }

        if let isAllDay = params["all_day"]?.boolValue { event.isAllDay = isAllDay }

        if let recurrenceJSON = params["recurrence"]?.stringValue,
           let data = recurrenceJSON.data(using: .utf8),
           let input = try? JSONDecoder().decode(RecurrenceInput.self, from: data),
           let rule = RecurrenceHelpers.buildRule(from: input) {
            event.addRecurrenceRule(rule)
        }

        do {
            try store.save(event, span: .thisEvent)
        } catch {
            return .failure(.operationFailed("Failed to save event: \(error.localizedDescription)"))
        }

        return .success(
            data: eventToDict(event),
            rollbackId: "calendar_event:\(event.eventIdentifier ?? "")"
        )
    }

    private func updateEvent(_ params: [String: AnyCodableValue]) -> ExecuteResponse {
        guard let eventId = params["event_id"]?.stringValue else {
            return .failure(.invalidInput("event_id is required"))
        }
        guard let event = store.event(withIdentifier: eventId) else {
            return .failure(.notFound("Event not found: \(eventId)"))
        }

        if let title = params["title"]?.stringValue, !title.isEmpty { event.title = title }
        if let startStr = params["start"]?.stringValue, let d = DateParsing.parse(startStr) { event.startDate = d }
        if let endStr = params["end"]?.stringValue, let d = DateParsing.parse(endStr) { event.endDate = d }
        if let loc = params["location"]?.stringValue, !loc.isEmpty { event.location = loc }
        if let notes = params["notes"]?.stringValue, !notes.isEmpty { event.notes = notes }

        let futureEvents = params["future_events"]?.boolValue ?? false
        let span: EKSpan = futureEvents ? .futureEvents : .thisEvent

        do {
            try store.save(event, span: span)
        } catch {
            return .failure(.operationFailed("Failed to update event: \(error.localizedDescription)"))
        }

        return .success(data: eventToDict(event))
    }

    private func deleteEvent(_ params: [String: AnyCodableValue]) -> ExecuteResponse {
        let eventId = params["event_id"]?.stringValue
        let title = params["title"]?.stringValue

        if let eventId, let event = store.event(withIdentifier: eventId) {
            let info = eventToDict(event)
            let futureEvents = params["future_events"]?.boolValue ?? false
            do {
                try store.remove(event, span: futureEvents ? .futureEvents : .thisEvent)
                return .success(data: info)
            } catch {
                return .failure(.operationFailed("Delete failed: \(error.localizedDescription)"))
            }
        }

        guard let title else {
            return .failure(.invalidInput("event_id or title required"))
        }

        let start = Date().addingTimeInterval(-30 * 86400)
        let end = Date().addingTimeInterval(365 * 86400)
        let predicate = store.predicateForEvents(withStart: start, end: end, calendars: nil)
        if let event = store.events(matching: predicate).first(where: { $0.title == title }) {
            let info = eventToDict(event)
            do {
                try store.remove(event, span: .thisEvent)
                return .success(data: info)
            } catch {
                return .failure(.operationFailed("Delete failed: \(error.localizedDescription)"))
            }
        }

        return .failure(.notFound("Event not found: \(title)"))
    }

    private func searchEvents(_ params: [String: AnyCodableValue]) -> ExecuteResponse {
        guard let query = params["query"]?.stringValue, !query.isEmpty else {
            return .failure(.invalidInput("Search query required"))
        }
        let limit = params["limit"]?.intValue ?? 50
        let startRaw = params["start"]?.stringValue
        let endRaw = params["end"]?.stringValue
        let startDate = startRaw.flatMap { DateParsing.parse($0) }
            ?? Calendar.current.date(byAdding: .day, value: -30, to: Date())!
        let rawEnd = endRaw.flatMap { DateParsing.parse($0) }
            ?? Calendar.current.date(byAdding: .year, value: 1, to: Date())!
        let endDate = DateParsing.normalizeRange(
            startRaw: startRaw, endRaw: endRaw,
            startDate: startDate, endDate: rawEnd
        )

        let predicate = store.predicateForEvents(withStart: startDate, end: endDate, calendars: nil)
        let queryLower = query.lowercased()

        let events = store.events(matching: predicate)
            .filter { event in
                let title = (event.title ?? "").lowercased()
                let notes = (event.notes ?? "").lowercased()
                let location = (event.location ?? "").lowercased()
                return title.contains(queryLower) || notes.contains(queryLower) || location.contains(queryLower)
            }
            .prefix(limit)
            .map { eventToDict($0) }

        return .success(data: [
            "events": .array(events.map { .object($0) }),
            "query": .string(query),
            "count": .int(events.count),
        ])
    }

    // MARK: - Serialization

    private func calendarToDict(_ calendar: EKCalendar) -> [String: AnyCodableValue] {
        [
            "id": .string(calendar.calendarIdentifier),
            "title": .string(calendar.title),
            "type": .string(calendarTypeString(calendar.type)),
            "allows_modifications": .bool(calendar.allowsContentModifications),
            "source": .string(calendar.source?.title ?? "Unknown"),
        ]
    }

    private func eventToDict(_ event: EKEvent) -> [String: AnyCodableValue] {
        var dict: [String: AnyCodableValue] = [
            "event_id": .string(event.eventIdentifier ?? ""),
            "title": .string(event.title ?? ""),
            "start": .string(DateParsing.toISO(event.startDate)),
            "end": .string(DateParsing.toISO(event.endDate)),
            "is_all_day": .bool(event.isAllDay),
            "calendar": .string(event.calendar?.title ?? ""),
        ]

        if let location = event.location, !location.isEmpty { dict["location"] = .string(location) }
        if let notes = event.notes, !notes.isEmpty { dict["notes"] = .string(notes) }
        if let url = event.url { dict["url"] = .string(url.absoluteString) }

        if event.hasRecurrenceRules, let rules = event.recurrenceRules {
            dict["recurrence"] = .array(rules.map { .object(RecurrenceHelpers.ruleToDict($0)) })
        }
        if event.hasAttendees, let attendees = event.attendees {
            dict["attendees"] = .array(attendees.map { attendee in
                .object([
                    "name": .string(attendee.name ?? ""),
                    "email": .string(attendee.url.absoluteString.replacingOccurrences(of: "mailto:", with: "")),
                    "status": .string(participantStatusString(attendee.participantStatus)),
                ])
            })
        }

        return dict
    }

    private func calendarTypeString(_ type: EKCalendarType) -> String {
        switch type {
        case .local: return "local"
        case .calDAV: return "caldav"
        case .exchange: return "exchange"
        case .subscription: return "subscription"
        case .birthday: return "birthday"
        @unknown default: return "unknown"
        }
    }

    private func participantStatusString(_ status: EKParticipantStatus) -> String {
        switch status {
        case .accepted: return "accepted"
        case .declined: return "declined"
        case .tentative: return "tentative"
        case .pending: return "pending"
        case .delegated: return "delegated"
        case .completed: return "completed"
        case .inProcess: return "in_process"
        default: return "unknown"
        }
    }
}
