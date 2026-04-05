import Foundation

enum DateParsing {
    private static let formatters: [DateFormatter] = {
        let formats = [
            "yyyy-MM-dd'T'HH:mm:ssZ",
            "yyyy-MM-dd'T'HH:mm:ss",
            "yyyy-MM-dd HH:mm",
            "yyyy-MM-dd",
        ]
        return formats.map { format in
            let f = DateFormatter()
            f.dateFormat = format
            f.locale = Locale(identifier: "en_US_POSIX")
            return f
        }
    }()

    private static let isoFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    private static let isoOutputFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    static func parse(_ string: String) -> Date? {
        let lowercased = string.lowercased().trimmingCharacters(in: .whitespaces)
        let calendar = Calendar.current
        let now = Date()

        switch lowercased {
        case "today":
            return calendar.startOfDay(for: now)
        case "tomorrow":
            return calendar.date(byAdding: .day, value: 1, to: calendar.startOfDay(for: now))
        case "yesterday":
            return calendar.date(byAdding: .day, value: -1, to: calendar.startOfDay(for: now))
        default:
            if lowercased.hasPrefix("next ") {
                let component = String(lowercased.dropFirst(5))
                switch component {
                case "week": return calendar.date(byAdding: .weekOfYear, value: 1, to: now)
                case "month": return calendar.date(byAdding: .month, value: 1, to: now)
                default: break
                }
            }
        }

        if let date = isoFormatter.date(from: string) {
            return date
        }

        for formatter in formatters {
            if let date = formatter.date(from: string) {
                return date
            }
        }

        // Natural language fallback via NSDataDetector
        if let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.date.rawValue),
           let match = detector.firstMatch(in: string, range: NSRange(string.startIndex..., in: string)),
           let date = match.date {
            return date
        }

        return nil
    }

    /// True when the raw input has no time component (day-only tokens or YYYY-MM-DD).
    static func isDayOnly(_ string: String) -> Bool {
        let s = string.lowercased().trimmingCharacters(in: .whitespaces)
        if ["today", "tomorrow", "yesterday"].contains(s) { return true }
        let dateOnlyRegex = try? NSRegularExpression(pattern: #"^\d{4}-\d{2}-\d{2}$"#)
        return dateOnlyRegex?.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)) != nil
    }

    /// Normalize a start/end pair so callers never get a zero-width range.
    ///
    /// - Day-only equal dates (e.g. "2026-03-26" / "2026-03-26", "today" / "today"):
    ///   expand end to start-of-next-day (full-day query).
    /// - Timestamped equal dates (e.g. "2026-03-23T23:34:00" / "2026-03-23T23:34:00"):
    ///   expand end by +1 minute so events active at that instant are returned.
    static func normalizeRange(
        startRaw: String?, endRaw: String?,
        startDate: Date, endDate: Date
    ) -> Date {
        guard startDate >= endDate else { return endDate }

        if let s = startRaw, let e = endRaw, isDayOnly(s) && isDayOnly(e) {
            return Calendar.current.date(byAdding: .day, value: 1, to: startDate)!
        }
        return Calendar.current.date(byAdding: .minute, value: 1, to: startDate)!
    }

    static func toISO(_ date: Date) -> String {
        isoOutputFormatter.string(from: date)
    }
}
