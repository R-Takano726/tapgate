import Foundation
import UserNotifications

@MainActor enum NotificationActions {
    static func register() {
        // Review is first: the Watch's system Double Tap gesture must never grant permission.
        let review = UNNotificationAction(identifier: "review", title: "内容を確認", options: [.foreground, .authenticationRequired])
        let approve = UNNotificationAction(identifier: "approve", title: "許可", options: [.authenticationRequired])
        let deny = UNNotificationAction(identifier: "deny", title: "拒否", options: [.authenticationRequired, .destructive])
        UNUserNotificationCenter.current().setNotificationCategories([
            UNNotificationCategory(identifier: "TAPGATE_REVIEW", actions: [review], intentIdentifiers: []),
            UNNotificationCategory(identifier: "TAPGATE_QUICK", actions: [review, approve, deny], intentIdentifiers: [])])
    }
    static func handle(_ response: UNNotificationResponse) async {
        let info = response.notification.request.content.userInfo
        guard let id = info["request_id"] as? String else { return }
        GateRoute.shared.requestID = id
        guard ["approve", "deny"].contains(response.actionIdentifier) else { return }
        do {
            let data = try await GateAPI.request("/api/inbox")
            let inbox = try JSONDecoder().decode(Inbox.self, from: data)
            guard let item = inbox.requests.first(where: { $0.id == id }),
                  item.payloadHash == info["payload_hash"] as? String,
                  item.version == info["version"] as? Int,
                  !item.phoneRequired, !item.informational,
                  response.notification.request.content.categoryIdentifier == "TAPGATE_QUICK" else {
                throw GateError.message("内容を確認してください")
            }
            // Force the Watch gate even when iOS handles the mirrored notification action.
            _ = try await GateAPI.request("/api/requests/\(id)/decision", body: [
                "decision":response.actionIdentifier == "approve" ? "approved" : "denied",
                "surface":"watch", "version":item.version, "payload_hash":item.payloadHash])
            UNUserNotificationCenter.current().removeDeliveredNotifications(withIdentifiers: [response.notification.request.identifier])
        } catch {
            GateRoute.shared.error = error.localizedDescription
            // A background action must visibly report failure; never show a success guess.
            let content = UNMutableNotificationContent()
            content.title = "TapGate"
            content.body = error.localizedDescription
            content.categoryIdentifier = "TAPGATE_REVIEW"
            content.userInfo = ["request_id":id]
            try? await UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: "error-"+id, content: content, trigger: nil))
        }
    }
}
