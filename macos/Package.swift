// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "WisprLocal",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "WisprLocal",
            path: "Sources/WisprLocal",
            swiftSettings: [.unsafeFlags(["-parse-as-library"])]
        )
    ]
)
