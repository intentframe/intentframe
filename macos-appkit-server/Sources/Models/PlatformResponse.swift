import Vapor

struct ExecuteResponse: Content {
    let success: Bool
    var data: [String: AnyCodableValue]?
    var error: String?
    var error_code: String?
    var rollback_available: Bool = false
    var rollback_id: String?
}

struct HealthResponse: Content {
    let status: String
    let service: String
    let permissions: PermissionStatus
}

struct PermissionStatus: Content {
    let calendar: PermissionDetail
    let reminders: PermissionDetail
    let contacts: PermissionDetail
    let notifications: PermissionDetail
    let full_disk_access: PermissionDetail
    let accessibility: PermissionDetail
}

struct PermissionDetail: Content {
    let granted: Bool
    var hint: String?
}
