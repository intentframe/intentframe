// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "macos-appkit-server",
    platforms: [.macOS(.v14)],
    dependencies: [
        .package(url: "https://github.com/vapor/vapor.git", from: "4.89.0"),
        .package(url: "https://github.com/loopwork-ai/Madrid.git", from: "0.4.0"),
    ],
    targets: [
        .executableTarget(
            name: "macos-appkit-server",
            dependencies: [
                .product(name: "Vapor", package: "vapor"),
                .product(name: "TypedStream", package: "Madrid"),
            ],
            path: "Sources",
            linkerSettings: [
                .linkedFramework("EventKit"),
                .linkedFramework("Contacts"),
                .linkedFramework("AppKit"),
                .linkedFramework("UserNotifications"),
            ]
        ),
    ]
)
