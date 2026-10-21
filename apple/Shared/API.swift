import Foundation

@MainActor enum GateAPI {
    static func direct(_ path: String, body: [String: Any]? = nil, credentials: Credentials) async throws -> Data {
        guard let base = URL(string: credentials.url), base.scheme == "https", base.host != nil,
              base.user == nil, base.password == nil, base.query == nil, base.fragment == nil,
              base.path.isEmpty || base.path == "/",
              let url = URL(string: path, relativeTo: base) else {
            throw GateError.message("HTTPSのサーバーURLを入力してください")
        }
        var request = URLRequest(url: url)
        request.timeoutInterval = 12
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("1", forHTTPHeaderField: "X-TapGate")
        if !credentials.token.isEmpty { request.setValue("Bearer \(credentials.token)", forHTTPHeaderField: "Authorization") }
        if let body { request.httpMethod = "POST"; request.httpBody = try JSONSerialization.data(withJSONObject: body) }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let response = response as? HTTPURLResponse else { throw GateError.message("応答を確認できません") }
        guard (200..<300).contains(response.statusCode) else {
            let error = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            throw GateError.message(error?["error"] as? String ?? "接続エラー \(response.statusCode)")
        }
        return data
    }
    static func request(_ path: String, body: [String: Any]? = nil) async throws -> Data {
        guard let credentials = Vault.load() else { throw GateError.message("iPhoneで接続してください") }
        #if os(watchOS)
        // A Watch cannot be assumed to have Tailscale. Prefer the iPhone relay.
        if Bridge.shared.reachable {
            return try await Bridge.shared.relay(path: path, body: body, credentials: credentials)
        }
        #endif
        return try await direct(path, body: body, credentials: credentials)
    }
}
