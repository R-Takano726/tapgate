import Foundation
import Security

enum Vault {
    static func load(_ account: String = "connection") -> Credentials? {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "TapGate", kSecAttrAccount as String: account,
            kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        return try? JSONDecoder().decode(Credentials.self, from: data)
    }
    static func save(_ value: Credentials, _ account: String = "connection") throws {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "TapGate", kSecAttrAccount as String: account]
        let values: [String: Any] = [kSecValueData as String: try JSONEncoder().encode(value),
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
        let status = SecItemUpdate(query as CFDictionary, values as CFDictionary)
        if status == errSecItemNotFound {
            guard SecItemAdd(query.merging(values) { _, new in new } as CFDictionary, nil) == errSecSuccess else {
                throw GateError.message("Keychainへ保存できません")
            }
        } else if status != errSecSuccess { throw GateError.message("Keychainへ保存できません") }
    }
    static func delete(_ account: String = "connection") {
        SecItemDelete([kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "TapGate", kSecAttrAccount as String: account] as CFDictionary)
    }
}
