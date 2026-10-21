import SwiftUI
import WatchKit
import UserNotifications

@main struct TapGateWatchApp: App {
    @WKApplicationDelegateAdaptor(WatchDelegate.self) private var delegate
    var body: some Scene { WindowGroup { InboxView() } }
}
@MainActor final class WatchDelegate: NSObject, WKApplicationDelegate, UNUserNotificationCenterDelegate {
    func applicationDidFinishLaunching() {
        UNUserNotificationCenter.current().delegate = self
        NotificationActions.register()
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse) async {
        await NotificationActions.handle(response)
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification) async -> UNNotificationPresentationOptions { [.banner, .sound] }
}
