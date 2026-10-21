import SwiftUI
import UserNotifications
import UIKit

@main struct TapGateApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    var body: some Scene { WindowGroup { InboxView() } }
}
@MainActor final class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    private var connectionObserver: NSObjectProtocol?
    private var pendingToken: String?
    func application(_ application: UIApplication, didFinishLaunchingWithOptions options: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        NotificationActions.register()
        connectionObserver = NotificationCenter.default.addObserver(forName: .gateConnection, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in
                guard let self else { return }
                do {
                    let granted = try await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])
                    if granted { UIApplication.shared.registerForRemoteNotifications() }
                    else { NotificationCenter.default.post(name: .gateError, object: "設定でTapGateの通知を許可してください") }
                    await self.registerToken()
                } catch { NotificationCenter.default.post(name: .gateError, object: error.localizedDescription) }
            }
        }
        if Vault.load() != nil { application.registerForRemoteNotifications() }
        return true
    }
    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        pendingToken = deviceToken.map { String(format: "%02x", $0) }.joined()
        Task { await registerToken() }
    }
    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
        NotificationCenter.default.post(name: .gateError, object: error.localizedDescription)
    }
    private func registerToken() async {
        guard let pendingToken, Vault.load() != nil else { return }
        do { _ = try await GateAPI.request("/api/device", body: ["token":pendingToken]) }
        catch { NotificationCenter.default.post(name: .gateError, object: error.localizedDescription) }
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse) async {
        await NotificationActions.handle(response)
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification) async -> UNNotificationPresentationOptions { [.banner, .sound] }
}
