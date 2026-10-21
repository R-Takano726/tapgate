import Foundation

struct Approval: Codable, Identifiable, Equatable {
    let id: String
    let task: String
    let operation: String
    let source: String
    let host: String
    let reason: String
    let state: String
    let version: Int
    let payloadHash: String
    let phoneRequired: Bool
    let informational: Bool
    let live: Bool
    let delivered: Bool
    enum CodingKeys: String, CodingKey {
        case id, task, operation, source, host, reason, state, version, informational, live, delivered
        case phoneRequired = "phone_required", payloadHash = "payload_hash"
    }
    var pending: Bool { state == "pending" }
    var stateLabel: String {
        switch state {
        case "approved": return "許可済み"
        case "denied": return "拒否済み"
        case "expired": return "期限切れ"
        case "cancelled": return "取り消し済み"
        default: return "承認待ち"
        }
    }
}
struct Inbox: Decodable { let requests: [Approval]; let demo: Bool }
struct Credentials: Codable { let url: String; let token: String }
struct PairResult: Decodable { let token: String; let role: String }
struct TokenResult: Decodable { let token: String }
enum GateError: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let value) = self { return value }; return nil }
}
