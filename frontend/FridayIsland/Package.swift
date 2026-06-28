// swift-tools-version: 6.1

import PackageDescription

let package = Package(
    name: "FridayIsland",
    platforms: [
        .macOS(.v14)
    ],
    targets: [
        .executableTarget(
            name: "FridayIsland",
            path: "Sources/FridayIsland",
            resources: [
                .process("Resources")
            ]
        )
    ]
)
