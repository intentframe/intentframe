import Foundation

enum PlatformError: Error, LocalizedError {
    case accessDenied(String)
    case notFound(String)
    case invalidInput(String)
    case unknownAdapter(String)
    case unknownAction(String, adapter: String)
    case operationFailed(String)

    var errorCode: String {
        switch self {
        case .accessDenied: return "access_denied"
        case .notFound: return "not_found"
        case .invalidInput: return "invalid_input"
        case .unknownAdapter: return "unknown_adapter"
        case .unknownAction: return "unknown_action"
        case .operationFailed: return "operation_failed"
        }
    }

    var errorDescription: String? {
        switch self {
        case .accessDenied(let msg): return msg
        case .notFound(let msg): return msg
        case .invalidInput(let msg): return msg
        case .unknownAdapter(let name): return "Unknown adapter: \(name)"
        case .unknownAction(let action, let adapter): return "Unknown action '\(action)' for adapter '\(adapter)'"
        case .operationFailed(let msg): return msg
        }
    }
}

extension ExecuteResponse {
    static func success(data: [String: AnyCodableValue], rollbackId: String? = nil) -> ExecuteResponse {
        ExecuteResponse(
            success: true,
            data: data,
            rollback_available: rollbackId != nil,
            rollback_id: rollbackId
        )
    }

    static func failure(_ error: PlatformError) -> ExecuteResponse {
        ExecuteResponse(
            success: false,
            error: error.localizedDescription,
            error_code: error.errorCode
        )
    }

    static func failure(_ message: String, code: String = "operation_failed") -> ExecuteResponse {
        ExecuteResponse(
            success: false,
            error: message,
            error_code: code
        )
    }
}
