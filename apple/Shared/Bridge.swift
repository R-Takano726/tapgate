import Foundation
import WatchConnectivity
import UserNotifications

@MainActor final class Bridge: NSObject, WCSessionDelegate {
    static let shared = Bridge()
    var reachable: Bool { WCSession.isSupported() && WCSession.default.isReachable }
    func start() {
        guard WCSession.isSupported() else { return }
        WCSession.default.delegate = self
        WCSession.default.activate()
    }
    nonisolated func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState, error: Error?) {
        Task { @MainActor in self.handshake() }
    }
    nonisolated func sessionReachabilityDidChange(_ session: WCSession) {
        Task { @MainActor in self.handshake() }
    }
    #if os(iOS)
    nonisolated func sessionDidBecomeInactive(_ session: WCSession) {}
    nonisolated func sessionDidDeactivate(_ session: WCSession) { session.activate() }
    #endif
    func handshake() {
        #if os(watchOS)
        guard reachable else { return }
        WCSession.default.sendMessage(["kind":"provision"], replyHandler: { value in
            Task { @MainActor in
                guard let data = value["credentials"] as? Data,
                      let credentials = try? JSONDecoder().decode(Credentials.self, from: data) else { return }
                do { try Vault.save(credentials); NotificationCenter.default.post(name: .gateConnection, object: nil) }
                catch { NotificationCenter.default.post(name: .gateError, object: error.localizedDescription) }
            }
        }, errorHandler: { _ in })
        #endif
    }
    nonisolated func session(_ session: WCSession, didReceiveMessage message: [String : Any], replyHandler: @escaping ([String : Any]) -> Void) {
        Task { @MainActor in
            #if os(iOS)
            do {
                if message["kind"] as? String == "provision" {
                    guard let phone = Vault.load() else { throw GateError.message("iPhoneで接続してください") }
                    var watch = Vault.load("watch")
                    if watch == nil || watch?.url != phone.url {
                        let data = try await GateAPI.direct("/api/watch-token", body: [:], credentials: phone)
                        let token = try JSONDecoder().decode(TokenResult.self, from: data).token
                        watch = Credentials(url: phone.url, token: token)
                        try Vault.save(watch!, "watch")
                    }
                    replyHandler(["credentials": try JSONEncoder().encode(watch!)])
                } else if message["kind"] as? String == "relay",
                          let path = message["path"] as? String,
                          let credentialsData = message["credentials"] as? Data {
                    let credentials = try JSONDecoder().decode(Credentials.self, from: credentialsData)
                    guard let known = Vault.load("watch"), credentials.token == known.token, credentials.url == known.url,
                          path == "/api/inbox" || path.range(of: #"^/api/requests/[A-Za-z0-9_-]+/decision$"#, options: .regularExpression) != nil else {
                        throw GateError.message("この接続では操作できません")
                    }
                    var body = message["body"] as? [String: Any]
                    // A Watch relay can never masquerade as an iPhone detail review.
                    if body != nil { body?["surface"] = "watch" }
                    let data = try await GateAPI.direct(path, body: body, credentials: credentials)
                    replyHandler(["data":data])
                } else if message["kind"] as? String == "openPhone", let id = message["id"] as? String {
                    GateRoute.shared.requestID = id
                    let content = UNMutableNotificationContent()
                    content.title = "TapGate"
                    content.body = "内容を確認してください"
                    content.categoryIdentifier = "TAPGATE_REVIEW"
                    content.userInfo = ["request_id":id]
                    content.sound = .default
                    try await UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: id, content: content, trigger: nil))
                    replyHandler(["ok":true])
                } else { replyHandler(["error":"未対応の操作です"]) }
            } catch { replyHandler(["error":error.localizedDescription]) }
            #else
            replyHandler(["error":"未対応の操作です"])
            #endif
        }
    }
    func relay(path: String, body: [String: Any]?, credentials: Credentials) async throws -> Data {
        try await withCheckedThrowingContinuation { continuation in
            var message: [String: Any] = ["kind":"relay", "path":path]
            do { message["credentials"] = try JSONEncoder().encode(credentials) }
            catch { continuation.resume(throwing: error); return }
            if let body { message["body"] = body }
            WCSession.default.sendMessage(message, replyHandler: { result in
                if let data = result["data"] as? Data { continuation.resume(returning: data) }
                else { continuation.resume(throwing: GateError.message(result["error"] as? String ?? "iPhoneへ接続できません")) }
            }, errorHandler: { continuation.resume(throwing: $0) })
        }
    }
    func openPhone(_ id: String) async throws {
        guard reachable else { throw GateError.message("iPhoneでTapGateを開いてください") }
        let _: Bool = try await withCheckedThrowingContinuation { continuation in
            WCSession.default.sendMessage(["kind":"openPhone","id":id], replyHandler: { result in
                if result["ok"] as? Bool == true { continuation.resume(returning: true) }
                else { continuation.resume(throwing: GateError.message(result["error"] as? String ?? "iPhoneで確認してください")) }
            }, errorHandler: { continuation.resume(throwing: $0) })
        }
    }
}
extension Notification.Name {
    static let gateConnection = Notification.Name("gateConnection")
    static let gateSelect = Notification.Name("gateSelect")
    static let gateError = Notification.Name("gateError")
}
