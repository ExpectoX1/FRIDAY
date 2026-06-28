import Foundation
import SwiftUI

enum AssistantState: String, Codable, CaseIterable {
    case idle
    case listening
    case transcribing
    case thinking
    case toolRunning = "tool_running"
    case speaking
    case approvalRequired = "approval_required"
    case error

    var title: String {
        switch self {
        case .idle: "Idle"
        case .listening: "Listening"
        case .transcribing: "Transcribing"
        case .thinking: "Thinking"
        case .toolRunning: "Using Tool"
        case .speaking: "Speaking"
        case .approvalRequired: "Approval Needed"
        case .error: "Needs Attention"
        }
    }

    var expression: FaceExpression {
        switch self {
        case .idle: .sleepy
        case .listening: .attentive
        case .transcribing: .focused
        case .thinking: .curious
        case .toolRunning: .determined
        case .speaking: .warm
        case .approvalRequired: .expectant
        case .error: .concerned
        }
    }

    var glowColors: [Color] {
        switch self {
        case .idle:
            [.mint.opacity(0.45), .cyan.opacity(0.28)]
        case .listening:
            [.cyan.opacity(0.75), .green.opacity(0.45)]
        case .transcribing:
            [.teal.opacity(0.65), .blue.opacity(0.35)]
        case .thinking:
            [.indigo.opacity(0.65), .cyan.opacity(0.45), .pink.opacity(0.25)]
        case .toolRunning:
            [.orange.opacity(0.65), .yellow.opacity(0.35)]
        case .speaking:
            [.pink.opacity(0.7), .cyan.opacity(0.55), .green.opacity(0.3)]
        case .approvalRequired:
            [.yellow.opacity(0.7), .orange.opacity(0.4)]
        case .error:
            [.red.opacity(0.7), .orange.opacity(0.4)]
        }
    }
}

enum Outcome: String, Codable {
    case success
    case error
    case neutral
}

enum ConnectionStatus {
    case connecting
    case connected
    case disconnected
    case mock

    var title: String {
        switch self {
        case .connecting: "Connecting"
        case .connected: "Live"
        case .disconnected: "Offline"
        case .mock: "Mock"
        }
    }
}

struct AssistantEvent: Codable, Equatable {
    var state: AssistantState
    var outcome: Outcome?
    var message: String?
    var transcript: String?
    var replyPreview: String?
    var tool: String?
    var requiresApproval: Bool?
    var pendingCommand: String?
    var amplitude: Double?

    static let idle = AssistantEvent(
        state: .idle,
        outcome: .neutral,
        message: "Ready when you are.",
        transcript: nil,
        replyPreview: nil,
        tool: nil,
        requiresApproval: false,
        pendingCommand: nil,
        amplitude: nil
    )
}

enum FaceExpression {
    case sleepy
    case attentive
    case focused
    case curious
    case determined
    case warm
    case expectant
    case concerned

    var blinkInterval: Double {
        switch self {
        case .sleepy: 3.5
        case .concerned: 2.2
        default: 4.2
        }
    }

    var eyeScale: CGFloat {
        switch self {
        case .sleepy: 0.48
        case .focused, .determined: 0.72
        case .concerned: 0.68
        default: 1.0
        }
    }

    var eyeYOffset: CGFloat {
        switch self {
        case .curious: -2
        case .concerned: 2
        default: 0
        }
    }

    var smileAmount: CGFloat {
        switch self {
        case .warm: 1.0
        case .attentive, .expectant: 0.72
        case .sleepy: 0.44
        case .focused, .curious, .determined: 0.28
        case .concerned: -0.45
        }
    }
}
