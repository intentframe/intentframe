// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "macos-appkit-server",
    platforms: [.macOS(.v14)],
    dependencies: [
        .package(url: "https://github.com/vapor/vapor.git", from: "4.89.0"),
    ],
    targets: [
        .executableTarget(
            name: "macos-appkit-server",
            dependencies: [
                .product(name: "Vapor", package: "vapor"),
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
