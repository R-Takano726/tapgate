import SwiftUI
import UserNotifications

@MainActor final class InboxModel: ObservableObject {
    @Published var items: [Approval] = []
    @Published var selected: String?
    @Published var online = false
    @Published var connected = Vault.load() != nil
    @Published var busy = false
    @Published var error: String?
    @Published var demo = false
    @Published var result: Approval?
    @Published var history = false
    var current: Approval? { items.first { $0.id == selected } }
    func refresh() async {
        guard !busy else { return }
        do {
            let data = try await GateAPI.request("/api/inbox")
            let inbox = try JSONDecoder().decode(Inbox.self, from: data)
            items = inbox.requests
            demo = inbox.demo
            online = true
            connected = true
            if selected == nil { selected = items.first(where: \.pending)?.id }
            if let value = result, let fresh = items.first(where: { $0.id == value.id }) { result = fresh }
            let resolved = items.filter { ["approved", "denied", "expired", "cancelled"].contains($0.state) }.map(\.id)
            let delivered = await UNUserNotificationCenter.current().deliveredNotifications()
            let identifiers = delivered.filter {
                guard let id = $0.request.content.userInfo["request_id"] as? String else { return false }
                return resolved.contains(id)
            }.map { $0.request.identifier }
            UNUserNotificationCenter.current().removeDeliveredNotifications(withIdentifiers: identifiers)
        } catch { online = false; self.error = error.localizedDescription }
    }
    func decide(_ item: Approval, approve: Bool) async {
        guard !busy else { return }
        busy = true
        error = nil
        #if os(watchOS)
        let surface = "watch"
        #else
        let surface = "phone"
        #endif
        do {
            let data = try await GateAPI.request("/api/requests/\(item.id)/decision", body: [
                "decision":approve ? "approved" : "denied", "surface":surface,
                "version":item.version, "payload_hash":item.payloadHash])
            let value = try JSONDecoder().decode(Approval.self, from: data)
            if let index = items.firstIndex(where: { $0.id == value.id }) { items[index] = value }
            selected = value.id
            result = value
            // Matching resolved notifications are removed on the next refresh.
        } catch {
            self.error = error.localizedDescription
            online = false
        }
        busy = false
        await refresh() // Reconcile an uncertain POST; never assume success.
        if let reconciled = items.first(where: { $0.id == item.id }), !reconciled.pending {
            result = reconciled
            selected = reconciled.id
        }
    }
    func pair(url: String, code: String) async {
        guard !busy else { return }
        busy = true
        defer { busy = false }
        do {
            let credentials = Credentials(url: url.trimmingCharacters(in: .whitespacesAndNewlines), token: "")
            let data = try await GateAPI.direct("/api/pair", body: ["code":code, "native":true, "name":"iPhone"], credentials: credentials)
            let result = try JSONDecoder().decode(PairResult.self, from: data)
            guard result.role == "consumer" else { throw GateError.message("端末用の接続コードを使用してください") }
            try Vault.save(Credentials(url: credentials.url, token: result.token))
            Vault.delete("watch")
            connected = true
            error = nil
            NotificationCenter.default.post(name: .gateConnection, object: nil)
        } catch { self.error = error.localizedDescription }
    }
    func next() {
        result = nil
        selected = items.first(where: \.pending)?.id
    }
}
