import Combine
import Foundation

@MainActor
final class AssistantStore: ObservableObject {
    @Published private(set) var event: AssistantEvent = .idle
    @Published private(set) var connectionStatus: ConnectionStatus = .connecting
    @Published private(set) var inputAvailable = true
    @Published private(set) var inputDisabledReason: String?
    @Published var lastActionError: String?

    private let client = BackendClient()
    private var mockTask: Task<Void, Never>?
    private var connectionTask: Task<Void, Never>?

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
                    self?.event = event
                    self?.lastActionError = nil
                }
            }
        } catch {
            connectionStatus = .mock
            startMockTimeline()
        }
    }

    private func startMockTimeline() {
        mockTask?.cancel()
        mockTask = Task { [weak self] in
            let events: [AssistantEvent] = [
                .idle,
                AssistantEvent(state: .listening, outcome: .neutral, message: "Listening...", transcript: nil, replyPreview: nil, tool: nil, requiresApproval: false, pendingCommand: nil, amplitude: nil),
                AssistantEvent(state: .transcribing, outcome: .neutral, message: "Catching that...", transcript: "open spotify and play something calm", replyPreview: nil, tool: nil, requiresApproval: false, pendingCommand: nil, amplitude: nil),
                AssistantEvent(state: .thinking, outcome: .neutral, message: "Thinking it through...", transcript: "open spotify and play something calm", replyPreview: nil, tool: nil, requiresApproval: false, pendingCommand: nil, amplitude: nil),
                AssistantEvent(state: .toolRunning, outcome: .neutral, message: "Opening Spotify", transcript: "open spotify and play something calm", replyPreview: nil, tool: "play_media", requiresApproval: false, pendingCommand: nil, amplitude: nil),
                AssistantEvent(state: .speaking, outcome: .success, message: "Answering...", transcript: "open spotify and play something calm", replyPreview: "On it, Sir. I found something calm for you.", tool: nil, requiresApproval: false, pendingCommand: nil, amplitude: 0.45),
                AssistantEvent(state: .approvalRequired, outcome: .neutral, message: "Permission needed", transcript: nil, replyPreview: nil, tool: "run_shell", requiresApproval: true, pendingCommand: "git -C /Users/siddharthkumar/Projects/FRIDAY push", amplitude: nil),
                AssistantEvent(state: .error, outcome: .error, message: "Backend disconnected.", transcript: nil, replyPreview: nil, tool: nil, requiresApproval: false, pendingCommand: nil, amplitude: nil)
            ]

            var index = 0
            while !Task.isCancelled {
                await MainActor.run {
                    self?.event = events[index % events.count]
                }
                index += 1
                try? await Task.sleep(for: .seconds(2.4))
            }
        }
    }
}
