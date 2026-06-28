import SwiftUI

struct FridayControlWindowView: View {
    @EnvironmentObject private var store: AssistantStore
    @State private var prompt = ""

    private var event: AssistantEvent { store.event }

    var body: some View {
        VStack(spacing: 0) {
            header

            Divider()
                .overlay(WindowPalette.stroke)

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 10) {
                        ForEach(store.activity) { item in
                            ActivityBubble(item: item)
                                .id(item.id)
                        }
                    }
                    .padding(.horizontal, 18)
                    .padding(.vertical, 14)
                }
                .scrollIndicators(.hidden)
                .onChange(of: store.activity) { _, activity in
                    guard let last = activity.last else { return }
                    withAnimation(.easeOut(duration: 0.2)) {
                        proxy.scrollTo(last.id, anchor: .bottom)
                    }
                }
            }

            footer
        }
        .frame(minWidth: 520, minHeight: 360)
        .background(WindowPalette.background)
    }

    private var header: some View {
        HStack(spacing: 14) {
            ZStack {
                Circle()
                    .fill(statusColor.opacity(0.2))
                    .frame(width: 38, height: 38)
                    .blur(radius: 6)

                FaceView(
                    state: event.state,
                    outcome: event.outcome,
                    expression: event.state.expression,
                    amplitude: event.amplitude ?? 0,
                    pulse: true
                )
                .frame(width: 58, height: 38)
            }
            .frame(width: 58, height: 42)

            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Text("FRIDAY")
                        .font(.system(size: 18, weight: .semibold, design: .rounded))
                        .foregroundStyle(WindowPalette.primaryText)

                    StatusPill(title: event.state.title, color: statusColor)
                }

                Text(primaryMessage)
                    .font(.system(size: 12, weight: .medium, design: .rounded))
                    .foregroundStyle(WindowPalette.secondaryText)
                    .lineLimit(1)
            }

            Spacer()

            connectionBadge
        }
        .padding(.horizontal, 18)
        .padding(.top, 18)
        .padding(.bottom, 12)
    }

    private var footer: some View {
        VStack(spacing: 10) {
            if event.state == .approvalRequired {
                approvalControls
            }

            HStack(spacing: 10) {
                TextField("Ask FRIDAY...", text: $prompt)
                    .textFieldStyle(.plain)
                    .font(.system(size: 13, weight: .medium, design: .rounded))
                    .foregroundStyle(WindowPalette.primaryText)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 11)
                    .background(WindowPalette.inputBackground, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                    .overlay {
                        RoundedRectangle(cornerRadius: 12, style: .continuous)
                            .stroke(WindowPalette.stroke, lineWidth: 1)
                    }
                    .onSubmit(sendPrompt)
                    .disabled(!store.inputAvailable)

                Button(action: sendPrompt) {
                    Image(systemName: store.inputAvailable ? "arrow.up" : "arrow.clockwise")
                        .font(.system(size: 14, weight: .bold))
                        .frame(width: 36, height: 36)
                }
                .buttonStyle(WindowIconButtonStyle(color: WindowPalette.accent))
                .disabled(store.inputAvailable && prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }

            if let error = store.lastActionError {
                footerNote(error, color: WindowPalette.warning)
            } else if let reason = store.inputDisabledReason {
                footerNote(reason, color: WindowPalette.secondaryText)
            }
        }
        .padding(14)
        .background(WindowPalette.footerBackground)
    }

    private var approvalControls: some View {
        HStack(spacing: 10) {
            Button {
                store.approve(false)
            } label: {
                Text("Deny")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(WindowButtonStyle(kind: .secondary))

            Button {
                store.approve(true)
            } label: {
                Text("Approve")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(WindowButtonStyle(kind: .primary))
        }
    }

    private var connectionBadge: some View {
        HStack(spacing: 7) {
            Circle()
                .fill(connectionColor)
                .frame(width: 8, height: 8)
                .shadow(color: connectionColor.opacity(0.7), radius: 6)

            Text(store.connectionStatus.title)
                .font(.system(size: 12, weight: .semibold, design: .rounded))
                .foregroundStyle(WindowPalette.secondaryText)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .background(WindowPalette.inputBackground, in: Capsule())
    }

    private var primaryMessage: String {
        event.message
            ?? event.replyPreview
            ?? event.transcript
            ?? "Ready when you are."
    }

    private var statusColor: Color {
        switch event.state {
        case .idle: WindowPalette.mutedAccent
        case .listening: WindowPalette.listen
        case .transcribing: WindowPalette.blue
        case .thinking: WindowPalette.purple
        case .toolRunning: WindowPalette.amber
        case .speaking: WindowPalette.rose
        case .approvalRequired: WindowPalette.warning
        case .error: WindowPalette.error
        }
    }

    private var connectionColor: Color {
        switch store.connectionStatus {
        case .connected: WindowPalette.listen
        case .connecting: WindowPalette.amber
        case .disconnected: WindowPalette.error
        case .mock: WindowPalette.purple
        }
    }

    private func footerNote(_ text: String, color: Color) -> some View {
        Text(text)
            .font(.system(size: 11, weight: .medium, design: .rounded))
            .foregroundStyle(color)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func sendPrompt() {
        guard store.inputAvailable else {
            store.retryTypedInput()
            return
        }
        store.submitInput(prompt)
        prompt = ""
    }
}

private struct ActivityBubble: View {
    let item: AssistantActivity

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            icon

            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.system(size: 11, weight: .semibold, design: .rounded))
                    .foregroundStyle(WindowPalette.secondaryText)

                Text(item.text)
                    .font(.system(size: 13, weight: .medium, design: .rounded))
                    .foregroundStyle(WindowPalette.primaryText)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .background(background, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .stroke(WindowPalette.stroke.opacity(item.kind == .friday ? 1 : 0.65), lineWidth: 1)
            }
            .frame(maxWidth: bubbleWidth, alignment: alignment)
        }
        .frame(maxWidth: .infinity, alignment: rowAlignment)
    }

    private var icon: some View {
        Image(systemName: symbol)
            .font(.system(size: 12, weight: .bold))
            .foregroundStyle(color)
            .frame(width: 24, height: 24)
            .background(color.opacity(0.12), in: Circle())
    }

    private var title: String {
        switch item.kind {
        case .user: "You"
        case .friday: "FRIDAY"
        case .status: "Status"
        case .tool: "Agent"
        case .approval: "Approval"
        case .error: "Attention"
        }
    }

    private var symbol: String {
        switch item.kind {
        case .user: "person.fill"
        case .friday: "sparkles"
        case .status: "waveform.path.ecg"
        case .tool: "hammer.fill"
        case .approval: "checkmark.seal.fill"
        case .error: "exclamationmark.triangle.fill"
        }
    }

    private var color: Color {
        switch item.kind {
        case .user: WindowPalette.blue
        case .friday: WindowPalette.rose
        case .status: WindowPalette.mutedAccent
        case .tool: WindowPalette.amber
        case .approval: WindowPalette.warning
        case .error: WindowPalette.error
        }
    }

    private var background: Color {
        switch item.kind {
        case .user: WindowPalette.userBubble
        case .friday: WindowPalette.fridayBubble
        default: WindowPalette.inputBackground
        }
    }

    private var rowAlignment: Alignment {
        item.kind == .user ? .trailing : .leading
    }

    private var alignment: Alignment {
        item.kind == .user ? .trailing : .leading
    }

    private var bubbleWidth: CGFloat? {
        item.kind == .status || item.kind == .tool ? nil : 440
    }
}

private struct StatusPill: View {
    let title: String
    let color: Color

    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(color)
                .frame(width: 7, height: 7)

            Text(title)
                .font(.system(size: 11, weight: .semibold, design: .rounded))
        }
        .foregroundStyle(WindowPalette.primaryText)
        .padding(.horizontal, 9)
        .padding(.vertical, 5)
        .background(color.opacity(0.14), in: Capsule())
    }
}

private struct WindowIconButtonStyle: ButtonStyle {
    let color: Color

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(.white)
            .background(color.opacity(configuration.isPressed ? 0.65 : 0.95), in: Circle())
            .scaleEffect(configuration.isPressed ? 0.96 : 1)
    }
}

private struct WindowButtonStyle: ButtonStyle {
    enum Kind {
        case primary
        case secondary
    }

    let kind: Kind

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .semibold, design: .rounded))
            .foregroundStyle(kind == .primary ? .white : WindowPalette.primaryText)
            .padding(.vertical, 10)
            .background(background(configuration), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .stroke(WindowPalette.stroke, lineWidth: 1)
            }
            .scaleEffect(configuration.isPressed ? 0.985 : 1)
    }

    private func background(_ configuration: Configuration) -> Color {
        switch kind {
        case .primary:
            WindowPalette.listen.opacity(configuration.isPressed ? 0.72 : 0.92)
        case .secondary:
            WindowPalette.inputBackground.opacity(configuration.isPressed ? 0.7 : 1)
        }
    }
}

private enum WindowPalette {
    static let background = Color(red: 0.055, green: 0.058, blue: 0.066)
    static let footerBackground = Color(red: 0.075, green: 0.078, blue: 0.09)
    static let inputBackground = Color.white.opacity(0.055)
    static let stroke = Color.white.opacity(0.095)
    static let primaryText = Color(red: 0.96, green: 0.94, blue: 0.95)
    static let secondaryText = Color(red: 0.67, green: 0.67, blue: 0.72)
    static let userBubble = Color(red: 0.08, green: 0.13, blue: 0.18)
    static let fridayBubble = Color(red: 0.15, green: 0.09, blue: 0.12)
    static let mutedAccent = Color(red: 0.48, green: 0.62, blue: 0.68)
    static let listen = Color(red: 0.34, green: 0.86, blue: 0.62)
    static let blue = Color(red: 0.36, green: 0.68, blue: 1.0)
    static let purple = Color(red: 0.68, green: 0.55, blue: 1.0)
    static let amber = Color(red: 1.0, green: 0.67, blue: 0.28)
    static let rose = Color(red: 1.0, green: 0.42, blue: 0.58)
    static let warning = Color(red: 1.0, green: 0.78, blue: 0.32)
    static let error = Color(red: 1.0, green: 0.34, blue: 0.34)
    static let accent = Color(red: 0.92, green: 0.38, blue: 0.56)
}
