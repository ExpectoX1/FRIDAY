import Foundation

enum BackendClientError: Error, Equatable {
    case httpStatus(Int)
    case invalidResponse
}

@MainActor
final class BackendClient {
    private let baseURL = URL(string: "http://127.0.0.1:8767")!
    private let webSocketURL = URL(string: "ws://127.0.0.1:8767/ws/state")!
    private var webSocketTask: URLSessionWebSocketTask?

    func healthCheck() async throws {
        let url = baseURL.appending(path: "api/health")
        let (_, response) = try await URLSession.shared.data(from: url)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw BackendClientError.invalidResponse
        }
    }

    func connect(onEvent: @escaping (AssistantEvent) -> Void) async throws {
        let task = URLSession.shared.webSocketTask(with: webSocketURL)
        webSocketTask = task
        task.resume()
        try await receiveLoop(task: task, onEvent: onEvent)
    }

    func disconnect() {
        webSocketTask?.cancel(with: .goingAway, reason: nil)
        webSocketTask = nil
    }

    func sendApproval(_ approved: Bool) async throws {
        struct Payload: Encodable {
            let approved: Bool
        }
        try await postJSON(Payload(approved: approved), path: "api/approval")
    }

    func sendInput(_ text: String) async throws {
        struct Payload: Encodable {
            let text: String
        }
        try await postJSON(Payload(text: text), path: "api/input")
    }

    private func receiveLoop(
        task: URLSessionWebSocketTask,
        onEvent: @escaping (AssistantEvent) -> Void
    ) async throws {
        while true {
            let message = try await task.receive()
            let data: Data

            switch message {
            case .data(let raw):
                data = raw
            case .string(let string):
                data = Data(string.utf8)
            @unknown default:
                continue
            }

            let event = try JSONDecoder().decode(AssistantEvent.self, from: data)
            onEvent(event)
        }
    }

    private func postJSON<T: Encodable>(_ payload: T, path: String) async throws {
        var request = URLRequest(url: baseURL.appending(path: path))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(payload)

        let (_, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw BackendClientError.invalidResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            throw BackendClientError.httpStatus(http.statusCode)
        }
    }
}
