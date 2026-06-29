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
    var brain: String?
    var streamingReply: String?
    var activity: [AssistantActivity] = []

    /// True when the active turn is being handled by the cloud brain (Groq) —
    /// either FRIDAY_BRAIN=cloud or a deep code follow-up routed to the cloud.
    var usesCloudBrain: Bool { brain == "cloud" }

    static let idle = AssistantEvent(
        state: .idle,
        outcome: .neutral,
        message: "Ready when you are.",
        transcript: nil,
        replyPreview: nil,
        tool: nil,
        requiresApproval: false,
        pendingCommand: nil,
        amplitude: nil,
        brain: nil,
        streamingReply: nil,
        activity: []
    )
}

enum AssistantActivityKind: String, Codable, Identifiable {
    case userMessage = "user_message"
    case assistantMessage = "assistant_message"
    case status
    case toolCall = "tool_call"
    case fileRead = "file_read"
    case codeSnippet = "code_snippet"
    case fileWrite = "file_write"
    case diff
    case approval
    case error

    var id: String { rawValue }
}

struct AssistantActivity: Identifiable, Codable, Equatable {
    var id: String
    var date: Date
    var kind: AssistantActivityKind
    var text: String
    var path: String?
    var language: String?
    var code: String?
    var diff: String?
    var tool: String?

    enum CodingKeys: String, CodingKey {
        case id
        case ts
        case kind
        case text
        case path
        case language
        case code
        case diff
        case tool
    }

    init(
        kind: AssistantActivityKind,
        text: String,
        date: Date = Date(),
        id: String = UUID().uuidString,
        path: String? = nil,
        language: String? = nil,
        code: String? = nil,
        diff: String? = nil,
        tool: String? = nil
    ) {
        self.id = id
        self.kind = kind
        self.text = text
        self.date = date
        self.path = path
        self.language = language
        self.code = code
        self.diff = diff
        self.tool = tool
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        let timestamp = try container.decodeIfPresent(Double.self, forKey: .ts)
        date = timestamp.map { Date(timeIntervalSince1970: $0) } ?? Date()
        kind = try container.decode(AssistantActivityKind.self, forKey: .kind)
        text = try container.decodeIfPresent(String.self, forKey: .text) ?? ""
        path = try container.decodeIfPresent(String.self, forKey: .path)
        language = try container.decodeIfPresent(String.self, forKey: .language)
        code = try container.decodeIfPresent(String.self, forKey: .code)
        diff = try container.decodeIfPresent(String.self, forKey: .diff)
        tool = try container.decodeIfPresent(String.self, forKey: .tool)
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(id, forKey: .id)
        try container.encode(date.timeIntervalSince1970, forKey: .ts)
        try container.encode(kind, forKey: .kind)
        try container.encode(text, forKey: .text)
        try container.encodeIfPresent(path, forKey: .path)
        try container.encodeIfPresent(language, forKey: .language)
        try container.encodeIfPresent(code, forKey: .code)
        try container.encodeIfPresent(diff, forKey: .diff)
        try container.encodeIfPresent(tool, forKey: .tool)
    }
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
