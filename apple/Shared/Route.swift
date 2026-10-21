import Foundation
import Combine

@MainActor final class GateRoute: ObservableObject {
    static let shared = GateRoute()
    @Published var requestID: String?
    @Published var error: String?
}
