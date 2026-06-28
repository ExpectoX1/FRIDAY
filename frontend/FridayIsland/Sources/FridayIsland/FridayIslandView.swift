import AppKit
import SwiftUI

struct FridayIslandView: View {
    @EnvironmentObject private var store: AssistantStore
    @State private var expanded = false
    @State private var prompt = ""
    @State private var pulse = false

    let collapsedWidth: CGFloat

    init(collapsedWidth: CGFloat = 216) {
        self.collapsedWidth = collapsedWidth
    }

    private var event: AssistantEvent { store.event }
    private var shouldExpandForState: Bool {
        event.state == .approvalRequired || event.state == .toolRunning || event.state == .error
    }

    private var isExpanded: Bool {
        expanded || shouldExpandForState
    }

    private var tunedCollapsedWidth: CGFloat {
        max(120, collapsedWidth - 1.12)
    }

    private var tunedCompactHeight: CGFloat {
        72.82
    }

    private var tunedCompactTopPadding: CGFloat {
        18.18
    }

    private var tunedCornerRadius: CGFloat {
        11.23
    }

    private var expandedWidth: CGFloat {
        switch event.state {
        case .approvalRequired:
            380
        case .speaking:
            392
        default:
            348
        }
    }

    private var expandedHeight: CGFloat {
        switch event.state {
        case .approvalRequired:
            224
        case .speaking:
            210
        case .toolRunning:
            184
        case .error:
            132
        default:
            150
        }
    }

    private var activeTopPadding: CGFloat {
        isExpanded ? tunedCompactTopPadding + 12 : tunedCompactTopPadding
    }

    private var tunerTopPadding: CGFloat {
        if isExpanded {
            return activeTopPadding + expandedHeight + 14
        }

        return activeTopPadding + tunedCompactHeight + 14
    }

    var body: some View {
        ZStack(alignment: .top) {
            Color.clear

            island
                .padding(.top, activeTopPadding)
                .animation(.spring(response: 0.42, dampingFraction: 0.82), value: isExpanded)
                .animation(.spring(response: 0.38, dampingFraction: 0.86), value: event.state)
        }
        .frame(width: 560, height: 300, alignment: .top)
        .onAppear {
            pulse = true
        }
    }

    private var island: some View {
        VStack(spacing: isExpanded ? expandedSpacing : 0) {
            HStack(spacing: isExpanded ? 12 : 10) {
                FaceView(
                    state: event.state,
                    outcome: event.outcome,
                    expression: event.state.expression,
                    amplitude: event.amplitude ?? 0,
                    pulse: pulse
                )
                .frame(width: isExpanded ? 68 : 128, height: isExpanded ? 50 : 42)

                if isExpanded {
                    statusBlock
                        .transition(.opacity.combined(with: .move(edge: .trailing)))
                }
            }

            if isExpanded {
                expandedContent
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .padding(.horizontal, isExpanded ? 16 : 14)
        .padding(.top, isExpanded ? expandedTopPadding : 8)
        .padding(.bottom, isExpanded ? 14 : 8)
        .frame(width: isExpanded ? expandedWidth : tunedCollapsedWidth, height: isExpanded ? expandedHeight : tunedCompactHeight)
        .background {
            if isExpanded {
                NotchBackground(cornerRadius: tunedCornerRadius, borderOpacity: 0.045)
            } else {
                CollapsedNotchBackground(cornerRadius: tunedCornerRadius)
            }
        }
        .overlay {
            if isExpanded {
                RoundedRectangle(cornerRadius: tunedCornerRadius, style: .continuous)
                    .strokeBorder(.white.opacity(0.06), lineWidth: 1)
            }
        }
        .shadow(color: .black.opacity(isExpanded ? 0.18 : 0), radius: isExpanded ? 8 : 0, x: 0, y: isExpanded ? 3 : 0)
        .contentShape(Rectangle())
        .onTapGesture {
            if !isExpanded {
                expanded = true
            }
        }
    }

    private var expandedSpacing: CGFloat {
        switch event.state {
        case .error:
            16
        case .speaking:
            12
        default:
            14
        }
    }

    private var expandedTopPadding: CGFloat {
        switch event.state {
        case .speaking:
            18
        default:
            20
        }
    }

    private var statusBlock: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                connectionDot
                Text(event.state.title)
                    .font(.system(size: 13, weight: .semibold, design: .rounded))
                    .foregroundStyle(IslandPalette.cream)

                Spacer(minLength: 8)

                Text(store.connectionStatus.title)
                    .font(.system(size: 9, weight: .medium, design: .rounded))
                    .foregroundStyle(IslandPalette.cream.opacity(0.64))
                    .padding(.horizontal, 7)
                    .padding(.vertical, 3)
                    .background(.white.opacity(0.08), in: Capsule())
            }

            Text(primaryMessage)
                .font(.system(size: 11, weight: .medium, design: .rounded))
                .foregroundStyle(IslandPalette.cream.opacity(0.78))
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var expandedContent: some View {
        VStack(spacing: 8) {
            detailRows

            if event.state == .approvalRequired {
                approvalControls
            } else {
                inputRow
            }

            if let error = store.lastActionError {
                Text(error)
                    .font(.system(size: 10, weight: .medium, design: .rounded))
                    .foregroundStyle(.orange.opacity(0.92))
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else if let inputReason = store.inputDisabledReason {
                Text(inputReason)
                    .font(.system(size: 10, weight: .medium, design: .rounded))
                    .foregroundStyle(IslandPalette.cream.opacity(0.62))
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    private var detailRows: some View {
        VStack(spacing: 5) {
            if shouldShowTranscript, let transcript = event.transcript, !transcript.isEmpty {
                DetailPill(label: "Heard", value: transcript)
            }

            if let tool = event.tool, !tool.isEmpty {
                DetailPill(label: "Tool", value: tool)
            }

            if let reply = event.replyPreview, !reply.isEmpty {
                DetailPill(label: "Reply", value: reply)
            }

            if let command = event.pendingCommand, !command.isEmpty {
                DetailPill(label: "Command", value: command)
            }
        }
    }

    private var shouldShowTranscript: Bool {
        event.state != .error
    }

    private var approvalControls: some View {
        HStack(spacing: 10) {
            Button {
                store.approve(false)
            } label: {
                Text("Deny")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(IslandButtonStyle(role: .secondary))

            Button {
                store.approve(true)
            } label: {
                Text("Approve")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(IslandButtonStyle(role: .primary))
        }
    }

    private var inputRow: some View {
        HStack(spacing: 8) {
            TextField("Tell FRIDAY...", text: $prompt)
                .textFieldStyle(.plain)
                .font(.system(size: 12, weight: .medium, design: .rounded))
                .foregroundStyle(IslandPalette.cream)
                .padding(.horizontal, 11)
                .padding(.vertical, 7)
                .background(IslandPalette.cream.opacity(0.04), in: Capsule())
                .overlay {
                    Capsule()
                        .strokeBorder(.white.opacity(0.12), lineWidth: 1)
                }
                .onSubmit(sendPrompt)
                .disabled(!store.inputAvailable)

            Button(action: sendPrompt) {
                Image(systemName: store.inputAvailable ? "arrow.up" : "arrow.clockwise")
                    .font(.system(size: 12, weight: .bold))
                    .frame(width: 28, height: 28)
            }
            .buttonStyle(IslandIconButtonStyle())
            .disabled(store.inputAvailable && prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        }
    }

    private var connectionDot: some View {
        Circle()
            .fill(connectionColor)
            .frame(width: 8, height: 8)
            .shadow(color: connectionColor.opacity(0.7), radius: 6)
    }

    private var connectionColor: Color {
        switch store.connectionStatus {
        case .connected: IslandPalette.mint
        case .connecting: IslandPalette.roseGold
        case .disconnected: IslandPalette.rose
        case .mock: IslandPalette.lavender
        }
    }

    private var primaryMessage: String {
        event.message
            ?? event.replyPreview
            ?? event.transcript
            ?? "Ready when you are."
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

private struct DetailPill: View {
    let label: String
    let value: String

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(label)
                .font(.system(size: 10, weight: .bold, design: .rounded))
                .foregroundStyle(IslandPalette.cream.opacity(0.48))
                .frame(width: 58, alignment: .leading)

            Text(value)
                .font(.system(size: 12, weight: .medium, design: .rounded))
                .foregroundStyle(IslandPalette.cream.opacity(0.84))
                .lineLimit(1)
                .truncationMode(.tail)

            Spacer(minLength: 0)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .background(IslandPalette.cream.opacity(0.065), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

private struct NotchBackground: View {
    let cornerRadius: CGFloat
    let borderOpacity: Double

    var body: some View {
        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            .fill(IslandPalette.notchBlack)
            .overlay {
                if borderOpacity > 0 {
                    RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                        .strokeBorder(.white.opacity(borderOpacity), lineWidth: 1)
                        .blendMode(.plusLighter)
                }
            }
    }
}

private struct CollapsedNotchBackground: View {
    let cornerRadius: CGFloat

    var body: some View {
        BottomRoundedRectangle(cornerRadius: cornerRadius)
            .fill(IslandPalette.notchBlack)
    }
}

private struct BottomRoundedRectangle: InsettableShape {
    let cornerRadius: CGFloat
    var insetAmount: CGFloat = 0

    func path(in rect: CGRect) -> Path {
        let rect = rect.insetBy(dx: insetAmount, dy: insetAmount)
        let radius = min(cornerRadius, rect.width / 2, rect.height)

        var path = Path()
        path.move(to: CGPoint(x: rect.minX, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY - radius))
        path.addQuadCurve(
            to: CGPoint(x: rect.maxX - radius, y: rect.maxY),
            control: CGPoint(x: rect.maxX, y: rect.maxY)
        )
        path.addLine(to: CGPoint(x: rect.minX + radius, y: rect.maxY))
        path.addQuadCurve(
            to: CGPoint(x: rect.minX, y: rect.maxY - radius),
            control: CGPoint(x: rect.minX, y: rect.maxY)
        )
        path.addLine(to: CGPoint(x: rect.minX, y: rect.minY))
        path.closeSubpath()
        return path
    }

    func inset(by amount: CGFloat) -> BottomRoundedRectangle {
        var shape = self
        shape.insetAmount += amount
        return shape
    }
}

private enum IslandPalette {
    static let notchBlack = Color(nsColor: NSColor(deviceWhite: 0, alpha: 1))
    static let cream = Color(red: 1.0, green: 0.94, blue: 0.96)
    static let rose = Color(red: 1.0, green: 0.36, blue: 0.52)
    static let roseGold = Color(red: 1.0, green: 0.66, blue: 0.56)
    static let lavender = Color(red: 0.74, green: 0.62, blue: 1.0)
    static let mint = Color(red: 0.58, green: 0.95, blue: 0.76)
}

private struct IslandButtonStyle: ButtonStyle {
    enum Role {
        case primary
        case secondary
    }

    let role: Role

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .semibold, design: .rounded))
            .foregroundStyle(IslandPalette.cream)
            .padding(.vertical, 9)
            .background(background.opacity(configuration.isPressed ? 0.64 : 0.9), in: Capsule())
            .overlay {
                Capsule().strokeBorder(.white.opacity(0.14), lineWidth: 1)
            }
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
    }

    private var background: Color {
        switch role {
        case .primary: IslandPalette.mint
        case .secondary: IslandPalette.rose.opacity(0.22)
        }
    }
}

private struct IslandIconButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(IslandPalette.cream)
            .background(.white.opacity(configuration.isPressed ? 0.22 : 0.14), in: Circle())
            .overlay {
                Circle().strokeBorder(.white.opacity(0.16), lineWidth: 1)
            }
            .scaleEffect(configuration.isPressed ? 0.94 : 1)
    }
}
