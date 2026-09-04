import Foundation
import Security

let service = "crypto-auto-trading-system"
let account = "deepseek-api-key"

func findItem() -> (OSStatus, SecKeychainItem?, UnsafeMutableRawPointer?, UInt32) {
    var item: SecKeychainItem?
    var password: UnsafeMutableRawPointer?
    var length: UInt32 = 0
    let status = SecKeychainFindGenericPassword(
        nil,
        UInt32(service.utf8.count), service,
        UInt32(account.utf8.count), account,
        &length, &password, &item
    )
    return (status, item, password, length)
}

func deleteExisting() {
    let (status, item, password, _) = findItem()
    if let password { SecKeychainItemFreeContent(nil, password) }
    if status == errSecSuccess, let item { _ = SecKeychainItemDelete(item) }
}

guard let command = CommandLine.arguments.dropFirst().first else { exit(64) }
switch command {
case "save":
    let data = FileHandle.standardInput.readDataToEndOfFile()
    guard !data.isEmpty else { exit(65) }
    deleteExisting()
    let status = data.withUnsafeBytes { bytes -> OSStatus in
        guard let baseAddress = bytes.baseAddress else { return errSecParam }
        return SecKeychainAddGenericPassword(
            nil,
            UInt32(service.utf8.count), service,
            UInt32(account.utf8.count), account,
            UInt32(data.count), baseAddress, nil
        )
    }
    exit(status == errSecSuccess ? 0 : 1)
case "exists":
    let (status, _, password, _) = findItem()
    if let password { SecKeychainItemFreeContent(nil, password) }
    exit(status == errSecSuccess ? 0 : 1)
case "load":
    let (status, _, password, length) = findItem()
    guard status == errSecSuccess, let password else { exit(1) }
    defer { SecKeychainItemFreeContent(nil, password) }
    FileHandle.standardOutput.write(Data(bytes: password, count: Int(length)))
case "delete":
    deleteExisting()
default:
    exit(64)
}
