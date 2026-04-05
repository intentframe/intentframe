import EventKit
import Foundation

struct RecurrenceInput: Codable {
    let frequency: String?
    let interval: Int?
    let endDate: String?
    let occurrenceCount: Int?
    let daysOfTheWeek: [String]?
    let daysOfTheMonth: [Int]?
}

enum RecurrenceHelpers {
    static func buildRule(from input: RecurrenceInput) -> EKRecurrenceRule? {
        guard let freqStr = input.frequency?.lowercased(), freqStr != "none" else {
            return nil
        }

        let frequency: EKRecurrenceFrequency
        switch freqStr {
        case "daily": frequency = .daily
        case "weekly": frequency = .weekly
        case "monthly": frequency = .monthly
        case "yearly": frequency = .yearly
        default: return nil
        }

        let interval = input.interval ?? 1

        var recurrenceEnd: EKRecurrenceEnd?
        if let endDateStr = input.endDate, let endDate = DateParsing.parse(endDateStr) {
            recurrenceEnd = EKRecurrenceEnd(end: endDate)
        } else if let count = input.occurrenceCount {
            recurrenceEnd = EKRecurrenceEnd(occurrenceCount: count)
        }

        var daysOfTheWeek: [EKRecurrenceDayOfWeek]?
        if let days = input.daysOfTheWeek {
            daysOfTheWeek = days.compactMap { dayStringToEKDay($0) }
            if daysOfTheWeek?.isEmpty == true { daysOfTheWeek = nil }
        }

        var daysOfTheMonth: [NSNumber]?
        if let days = input.daysOfTheMonth {
            daysOfTheMonth = days.map { NSNumber(value: $0) }
            if daysOfTheMonth?.isEmpty == true { daysOfTheMonth = nil }
        }

        return EKRecurrenceRule(
            recurrenceWith: frequency,
            interval: interval,
            daysOfTheWeek: daysOfTheWeek,
            daysOfTheMonth: daysOfTheMonth,
            monthsOfTheYear: nil,
            weeksOfTheYear: nil,
            daysOfTheYear: nil,
            setPositions: nil,
            end: recurrenceEnd
        )
    }

    static func ruleToDict(_ rule: EKRecurrenceRule) -> [String: AnyCodableValue] {
        var dict: [String: AnyCodableValue] = [
            "frequency": .string(frequencyString(rule.frequency)),
            "interval": .int(rule.interval),
        ]
        if let end = rule.recurrenceEnd {
            if let endDate = end.endDate {
                dict["endDate"] = .string(DateParsing.toISO(endDate))
            } else {
                dict["occurrenceCount"] = .int(end.occurrenceCount)
            }
        }
        if let days = rule.daysOfTheWeek, !days.isEmpty {
            dict["daysOfTheWeek"] = .array(days.map { .string(weekdayString($0.dayOfTheWeek)) })
        }
        if let days = rule.daysOfTheMonth, !days.isEmpty {
            dict["daysOfTheMonth"] = .array(days.map { .int($0.intValue) })
        }
        return dict
    }

    private static func frequencyString(_ freq: EKRecurrenceFrequency) -> String {
        switch freq {
        case .daily: return "daily"
        case .weekly: return "weekly"
        case .monthly: return "monthly"
        case .yearly: return "yearly"
        @unknown default: return "unknown"
        }
    }

    private static func weekdayString(_ weekday: EKWeekday) -> String {
        switch weekday {
        case .sunday: return "sunday"
        case .monday: return "monday"
        case .tuesday: return "tuesday"
        case .wednesday: return "wednesday"
        case .thursday: return "thursday"
        case .friday: return "friday"
        case .saturday: return "saturday"
        @unknown default: return "unknown"
        }
    }

    private static func dayStringToEKDay(_ day: String) -> EKRecurrenceDayOfWeek? {
        switch day.lowercased() {
        case "sunday", "sun": return EKRecurrenceDayOfWeek(.sunday)
        case "monday", "mon": return EKRecurrenceDayOfWeek(.monday)
        case "tuesday", "tue": return EKRecurrenceDayOfWeek(.tuesday)
        case "wednesday", "wed": return EKRecurrenceDayOfWeek(.wednesday)
        case "thursday", "thu": return EKRecurrenceDayOfWeek(.thursday)
        case "friday", "fri": return EKRecurrenceDayOfWeek(.friday)
        case "saturday", "sat": return EKRecurrenceDayOfWeek(.saturday)
        default: return nil
        }
    }
}
