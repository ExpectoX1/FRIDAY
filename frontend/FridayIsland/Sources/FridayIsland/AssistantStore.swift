import Combine
import Foundation

@MainActor
final class AssistantStore: ObservableObject {
    @Published private(set) var event: AssistantEvent = .idle
    @Published private(set) var connectionStatus: ConnectionStatus = .connecting
    @Published private(set) var activity: [AssistantActivity] = [
        AssistantActivity(kind: .status, text: "FRIDAY is starting up.")
    ]
    @Published private(set) var streamingReply = ""
    @Published private(set) var inputAvailable = true
    @Published private(set) var inputDisabledReason: String?
    @Published var lastActionError: String?

    private let client = BackendClient()
    private var mockTask: Task<Void, Never>?
    private var connectionTask: Task<Void, Never>?
    private var lastTranscript: String?
    private var lastReplyPreview: String?
    private var lastStatusKey: String?
    private var seenActivityIDs = Set<String>()

    var state: AssistantState { event.state }

    func start() {
        reconnect()
    }

    func stop() {
        mockTask?.cancel()
        connectionTask?.cancel()
        client.disconnect()
    }

    func reconnect() {
        mockTask?.cancel()
        connectionTask?.cancel()
        client.disconnect()
        connectionStatus = .connecting
        lastActionError = nil
        seenActivityIDs.removeAll()
        streamingReply = ""

        connectionTask = Task { [weak self] in
            await self?.connectLoop()
        }
    }

    func submitInput(_ text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        Task {
            do {
                try await client.sendInput(trimmed)
                lastActionError = nil
                inputDisabledReason = nil
            } catch {
                if case BackendClientError.httpStatus(503) = error {
                    inputAvailable = false
                    inputDisabledReason = "Typed input is waiting on backend Phase 3."
                    lastActionError = nil
                } else {
                    inputAvailable = false
                    inputDisabledReason = "Typed input could not reach FRIDAY."
                    lastActionError = nil
                }
            }
        }
    }

    func retryTypedInput() {
        inputAvailable = true
        inputDisabledReason = nil
        lastActionError = nil
    }

    func clearActivity() {
        activity.removeAll()
        seenActivityIDs.removeAll()
        lastTranscript = nil
        lastReplyPreview = nil
        lastStatusKey = nil
        streamingReply = ""
        append(.status, "Cleared the window.")
    }

    func approve(_ approved: Bool) {
        Task {
            do {
                try await client.sendApproval(approved)
                lastActionError = nil
            } catch {
                lastActionError = approved ? "Approval failed." : "Denial failed."
            }
        }
    }

    private func connectLoop() async {
        do {
            try await client.healthCheck()
            inputAvailable = true
            inputDisabledReason = nil
            try await client.connect { [weak self] event in
                Task { @MainActor in
                    self?.connectionStatus = .connected
                    self?.apply(event)
                    self?.lastActionError = nil
                }
            }
        } catch {
            connectionStatus = .mock
            append(.status, "Backend unavailable. Showing mock state.")
            startMockTimeline()
        }
    }

    private func apply(_ newEvent: AssistantEvent) {
        event = newEvent
        applyStreamingReply(from: newEvent)

        if !newEvent.activity.isEmpty {
            appendBackendActivity(newEvent.activity)
            return
        }

        if !seenActivityIDs.isEmpty {
            return
        }

        if let transcript = clean(newEvent.transcript), transcript != lastTranscript {
            append(.userMessage, transcript)
            lastTranscript = transcript
        }

        if newEvent.state == .approvalRequired,
           let command = clean(newEvent.pendingCommand) {
            append(.approval, "Approval needed: \(command)")
        } else if newEvent.state == .toolRunning {
            let message = clean(newEvent.message) ?? "Running \(newEvent.tool ?? "tool")"
            append(.toolCall, message, tool: newEvent.tool)
        } else if newEvent.state == .error {
            append(.error, clean(newEvent.message) ?? "Something needs attention.")
        } else if let message = clean(newEvent.message), newEvent.state != .speaking {
            appendStatusOnce("\(newEvent.state.rawValue):\(message)", message)
        }

        if let reply = clean(newEvent.replyPreview), reply != lastReplyPreview {
            append(.assistantMessage, reply)
            lastReplyPreview = reply
        }
    }

    private func applyStreamingReply(from event: AssistantEvent) {
        let incoming = event.streamingReply ?? ""
        if !incoming.isEmpty {
            streamingReply = incoming
            return
        }

        if event.activity.contains(where: { $0.kind == .assistantMessage }) {
            streamingReply = ""
            return
        }

        switch event.state {
        case .idle, .listening, .transcribing, .toolRunning, .approvalRequired, .error:
            streamingReply = ""
        case .thinking, .speaking:
            break
        }
    }

    private func appendBackendActivity(_ events: [AssistantActivity]) {
        if seenActivityIDs.isEmpty {
            activity.removeAll()
        }

        for event in events where !seenActivityIDs.contains(event.id) {
            seenActivityIDs.insert(event.id)
            activity.append(event)
        }

        if activity.count > 120 {
            let overflow = activity.count - 120
            let removed = activity.prefix(overflow).map(\.id)
            activity.removeFirst(overflow)
            seenActivityIDs.subtract(removed)
        }
    }

    private func appendStatusOnce(_ key: String, _ text: String) {
        guard key != lastStatusKey else { return }
        lastStatusKey = key
        append(.status, text)
    }

    private func append(_ kind: AssistantActivityKind, _ text: String, tool: String? = nil) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        if activity.last?.kind == kind && activity.last?.text == trimmed {
            return
        }
        activity.append(AssistantActivity(kind: kind, text: trimmed, tool: tool))
        if activity.count > 60 {
            activity.removeFirst(activity.count - 60)
        }
    }

    private func clean(_ text: String?) -> String? {
        let trimmed = (text ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    private func startMockTimeline() {
        mockTask?.cancel()
        mockTask = Task { [weak self] in
            let events: [AssistantEvent] = [
                .idle,
                AssistantEvent(state: .listening, outcome: .neutral, message: "Listening...", transcript: nil, replyPreview: nil, tool: nil, requiresApproval: false, pendingCommand: nil, amplitude: nil),
                AssistantEvent(state: .transcribing, outcome: .neutral, message: "Catching that...", transcript: "review the main.py in my teenyurl project", replyPreview: nil, tool: nil, requiresApproval: false, pendingCommand: nil, amplitude: nil),
                AssistantEvent(state: .toolRunning, outcome: .neutral, message: "Reading main.py", transcript: nil, replyPreview: nil, tool: "read_project_file", requiresApproval: false, pendingCommand: nil, amplitude: nil, activity: [
                    AssistantActivity(kind: .userMessage, text: "review the main.py in my teenyurl project"),
                    AssistantActivity(kind: .toolCall, text: "Reading main.py", tool: "read_project_file"),
                    AssistantActivity(kind: .fileRead, text: "main.py", path: "/Users/siddharthkumar/Projects/teenyurl/main.py"),
                    AssistantActivity(kind: .codeSnippet, text: "main.py", path: "/Users/siddharthkumar/Projects/teenyurl/main.py", language: "python", code: "from fastapi import FastAPI, HTTPException\n\napp = FastAPI()\n\n@app.post(\"/shorten\")\ndef shorten_url(url: str):\n    return {\"short\": \"abc123\"}\n")
                ]),
                AssistantEvent(state: .speaking, outcome: .success, message: "Answering...", transcript: nil, replyPreview: "This is a small FastAPI URL shortener. It exposes a shorten endpoint and raises HTTP errors for invalid lookups.", tool: nil, requiresApproval: false, pendingCommand: nil, amplitude: 0.45, activity: [
                    AssistantActivity(kind: .assistantMessage, text: "This is a small FastAPI URL shortener. It exposes a shorten endpoint and raises HTTP errors for invalid lookups.")
                ]),
                AssistantEvent(state: .approvalRequired, outcome: .neutral, message: "Permission needed", transcript: nil, replyPreview: nil, tool: "run_shell", requiresApproval: true, pendingCommand: "git -C /Users/siddharthkumar/Projects/FRIDAY push", amplitude: nil, activity: [
                    AssistantActivity(kind: .approval, text: "git -C /Users/siddharthkumar/Projects/FRIDAY push", tool: "run_shell")
                ]),
                AssistantEvent(state: .error, outcome: .error, message: "Backend disconnected.", transcript: nil, replyPreview: nil, tool: nil, requiresApproval: false, pendingCommand: nil, amplitude: nil, activity: [
                    AssistantActivity(kind: .error, text: "Backend disconnected.")
                ])
            ]

            var index = 0
            while !Task.isCancelled {
                await MainActor.run {
                    self?.apply(events[index % events.count])
                }
                index += 1
                try? await Task.sleep(for: .seconds(2.4))
            }
        }
    }
}
