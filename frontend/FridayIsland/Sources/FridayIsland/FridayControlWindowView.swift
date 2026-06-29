import SwiftUI
import AppKit

struct FridayControlWindowView: View {
    @EnvironmentObject private var store: AssistantStore
    @State private var prompt = ""
    @State private var selectedFilter: ActivityFilter = .all

    private var event: AssistantEvent { store.event }
    private var visibleActivity: [AssistantActivity] {
        store.activity.filter { selectedFilter.includes($0) }
    }
    private var shouldShowStreamingReply: Bool {
        !store.streamingReply.isEmpty && (selectedFilter == .all || selectedFilter == .chat)
    }
    private var shouldShowWorkIndicator: Bool {
        guard store.streamingReply.isEmpty else { return false }
        return event.state == .thinking || event.state == .toolRunning
    }
    private var workIndicatorText: String {
        switch event.state {
        case .thinking:
            return "Thinking"
        case .toolRunning:
            return cleanedStatusText(event.message)
                ?? event.tool.map { "Running \($0)" }
                ?? "Working"
        default:
            return ""
        }
    }
    private var workIndicatorSymbol: String {
        event.state == .toolRunning ? "hammer.fill" : "sparkle.magnifyingglass"
    }
    private var workIndicatorScrollKey: String {
        "\(event.state.rawValue):\(event.message ?? ""):\(event.tool ?? "")"
    }
    private var streamingActivity: AssistantActivity {
        AssistantActivity(
            kind: .assistantMessage,
            text: store.streamingReply,
            id: "streaming-reply"
        )
    }
    private var latestToolActivityID: String? {
        store.activity.last(where: { $0.kind == .toolCall })?.id
    }
    private var latestCodeActivityID: String? {
        store.activity.last(where: { $0.kind == .codeSnippet })?.id
    }

    var body: some View {
        VStack(spacing: 0) {
            header

            ActiveStateRail(color: statusColor, isActive: isWorkAnimationActive)

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 10) {
                        filterBar

                        ForEach(visibleActivity) { item in
                            ActivityBubble(
                                item: item,
                                isActiveTool: event.state == .toolRunning && item.id == latestToolActivityID,
                                isActiveCode: event.state == .toolRunning && item.id == latestCodeActivityID
                            )
                                .id(item.id)
                                .transition(.asymmetric(
                                    insertion: .scale(scale: 0.985, anchor: .top).combined(with: .opacity),
                                    removal: .opacity
                                ))
                        }

                        if shouldShowStreamingReply {
                            ActivityBubble(
                                item: streamingActivity,
                                isActiveTool: false,
                                isActiveCode: false,
                                isStreaming: true
                            )
                                .id("streaming-reply")
                                .transition(.opacity.combined(with: .move(edge: .bottom)))
                        } else if shouldShowWorkIndicator {
                            WorkIndicatorBubble(
                                text: workIndicatorText,
                                symbol: workIndicatorSymbol,
                                color: statusColor
                            )
                                .id("work-indicator")
                                .transition(.opacity.combined(with: .move(edge: .bottom)))
                        }
                    }
                    .padding(.horizontal, 22)
                    .padding(.vertical, 14)
                }
                .scrollIndicators(.hidden)
                .onChange(of: visibleActivity) { _, activity in
                    guard let last = activity.last else { return }
                    withAnimation(.snappy(duration: 0.28)) {
                        proxy.scrollTo(last.id, anchor: .bottom)
                    }
                }
                .onChange(of: store.streamingReply) { _, text in
                    guard !text.isEmpty, shouldShowStreamingReply else { return }
                    withAnimation(.snappy(duration: 0.18)) {
                        proxy.scrollTo("streaming-reply", anchor: .bottom)
                    }
                }
                .onChange(of: workIndicatorScrollKey) { _, _ in
                    guard shouldShowWorkIndicator else { return }
                    withAnimation(.snappy(duration: 0.22)) {
                        proxy.scrollTo("work-indicator", anchor: .bottom)
                    }
                }
            }

            footer
        }
        .frame(minWidth: 720, minHeight: 500)
        .background(WindowPalette.background)
    }

    private var header: some View {
        HStack(spacing: 12) {
            StatusOrb(color: statusColor, state: event.state)

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

            if isWorkAnimationActive {
                ActivityWave(color: statusColor)
                    .padding(.leading, 4)
            }

            Spacer()

            headerActions
            connectionBadge
        }
        .padding(.horizontal, 22)
        .padding(.top, 18)
        .padding(.bottom, 12)
    }

    private var headerActions: some View {
        HStack(spacing: 8) {
            Button {
                store.clearActivity()
            } label: {
                Image(systemName: "trash")
                    .frame(width: 30, height: 30)
            }
            .buttonStyle(WindowPlainIconButtonStyle())
            .help("Clear window")

            Button {
                store.reconnect()
            } label: {
                Image(systemName: "arrow.clockwise")
                    .frame(width: 30, height: 30)
            }
            .buttonStyle(WindowPlainIconButtonStyle())
            .help("Reconnect to FRIDAY")
        }
    }

    private var filterBar: some View {
        HStack(spacing: 8) {
            ForEach(ActivityFilter.allCases) { filter in
                Button {
                    selectedFilter = filter
                } label: {
                    Label(filter.title, systemImage: filter.symbol)
                        .font(.system(size: 11, weight: .semibold, design: .rounded))
                        .padding(.horizontal, 10)
                        .padding(.vertical, 7)
                }
                .buttonStyle(FilterButtonStyle(isSelected: selectedFilter == filter, color: filter.color))
            }

            Spacer()
        }
        .padding(.bottom, 2)
    }

    private var footer: some View {
        VStack(spacing: 10) {
            if event.state == .approvalRequired {
                approvalControls
            }

            quickActions

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
        .padding(.horizontal, 18)
        .padding(.vertical, 14)
        .background(WindowPalette.footerBackground)
    }

    private var quickActions: some View {
        HStack(spacing: 8) {
            QuickPromptButton(title: "Review", symbol: "doc.text.magnifyingglass") {
                sendQuickPrompt("Review the current project code")
            }

            QuickPromptButton(title: "Explain", symbol: "text.book.closed") {
                sendQuickPrompt("Explain the current file")
            }

            QuickPromptButton(title: "Tests", symbol: "checklist") {
                sendQuickPrompt("Write tests for these functions")
            }

            QuickPromptButton(title: "Downloads", symbol: "folder") {
                sendQuickPrompt("List out whatever is in my download folder")
            }

            Spacer(minLength: 0)
        }
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

    private var isWorkAnimationActive: Bool {
        switch event.state {
        case .listening, .transcribing, .thinking, .toolRunning:
            return true
        case .idle, .speaking, .approvalRequired, .error:
            return false
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

    private func sendQuickPrompt(_ text: String) {
        guard store.inputAvailable else {
            store.retryTypedInput()
            return
        }
        store.submitInput(text)
    }

    private func cleanedStatusText(_ text: String?) -> String? {
        var result = (text ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        while result.hasSuffix(".") || result.hasSuffix("…") {
            result.removeLast()
            result = result.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return result.isEmpty ? nil : result
    }
}

private enum ActivityFilter: String, CaseIterable, Identifiable {
    case all
    case chat
    case code
    case tools
    case issues

    var id: String { rawValue }

    var title: String {
        switch self {
        case .all: "All"
        case .chat: "Chat"
        case .code: "Code"
        case .tools: "Tools"
        case .issues: "Issues"
        }
    }

    var symbol: String {
        switch self {
        case .all: "tray.full"
        case .chat: "bubble.left.and.bubble.right"
        case .code: "chevron.left.forwardslash.chevron.right"
        case .tools: "hammer"
        case .issues: "exclamationmark.triangle"
        }
    }

    var color: Color {
        switch self {
        case .all: WindowPalette.mutedAccent
        case .chat: WindowPalette.rose
        case .code: WindowPalette.purple
        case .tools: WindowPalette.amber
        case .issues: WindowPalette.error
        }
    }

    func includes(_ item: AssistantActivity) -> Bool {
        switch self {
        case .all:
            return true
        case .chat:
            return item.kind == .userMessage || item.kind == .assistantMessage
        case .code:
            return item.kind == .fileRead || item.kind == .codeSnippet || item.kind == .fileWrite || item.kind == .diff
        case .tools:
            return item.kind == .toolCall || item.kind == .status
        case .issues:
            return item.kind == .approval || item.kind == .error
        }
    }
}

private struct ActivityBubble: View {
    @EnvironmentObject private var store: AssistantStore
    let item: AssistantActivity
    let isActiveTool: Bool
    let isActiveCode: Bool
    var isStreaming = false
    @State private var isHovering = false
    @State private var cursorVisible = true

    var body: some View {
        rowContent
            .frame(maxWidth: .infinity, alignment: rowAlignment)
            .scaleEffect(isHovering ? 1.006 : 1)
            .offset(y: isHovering ? -1 : 0)
            .animation(.snappy(duration: 0.18), value: isHovering)
            .onHover { isHovering = $0 }
    }

    @ViewBuilder
    private var rowContent: some View {
        switch item.kind {
        case .userMessage, .assistantMessage:
            HStack(alignment: .top, spacing: 10) {
                if item.kind != .userMessage {
                    icon
                }

                messageCard

                if item.kind == .userMessage {
                    icon
                }
            }

        case .codeSnippet:
            HStack(alignment: .top, spacing: 10) {
                icon
                codeCard
            }

        case .fileRead, .fileWrite:
            HStack(alignment: .top, spacing: 10) {
                icon
                fileCard
            }

        case .approval:
            HStack(alignment: .top, spacing: 10) {
                icon
                approvalCard
            }

        case .status, .toolCall, .error, .diff:
            HStack(alignment: .top, spacing: 10) {
                icon
                stepCard
            }
        }
    }

    private var messageCard: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title)
                .font(.system(size: 11, weight: .semibold, design: .rounded))
                .foregroundStyle(WindowPalette.secondaryText)

            messageText
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
                .stroke(WindowPalette.stroke.opacity(item.kind == .assistantMessage ? 1 : 0.65), lineWidth: 1)
        }
        .frame(maxWidth: item.kind == .userMessage ? 560 : 680, alignment: alignment)
        .onAppear {
            guard isStreaming else { return }
            withAnimation(.easeInOut(duration: 0.62).repeatForever(autoreverses: true)) {
                cursorVisible = false
            }
        }
    }

    private var messageText: Text {
        guard isStreaming else {
            return Text(item.text)
        }
        return Text(item.text) + Text(cursorVisible ? " |" : "  ")
    }

    private var stepCard: some View {
        HStack(alignment: .center, spacing: 8) {
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.system(size: 11, weight: .semibold, design: .rounded))
                    .foregroundStyle(WindowPalette.secondaryText)

                Text(item.text)
                    .font(.system(size: 12, weight: .medium, design: .rounded))
                    .foregroundStyle(item.kind == .error ? WindowPalette.error : WindowPalette.primaryText)
                    .textSelection(.enabled)
                    .lineLimit(3)
            }

            Spacer(minLength: 0)

            if let tool = item.tool, !tool.isEmpty {
                Text(tool)
                    .font(.system(size: 10, weight: .semibold, design: .monospaced))
                    .foregroundStyle(WindowPalette.secondaryText)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 4)
                    .background(WindowPalette.inputBackground, in: Capsule())
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 9)
        .background(WindowPalette.inputBackground, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(WindowPalette.stroke, lineWidth: 1)
        }
        .overlay(alignment: .bottomLeading) {
            if isActiveTool {
                AnimatedProgressLine(color: color)
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
        }
    }

    private var fileCard: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Image(systemName: item.kind == .fileWrite ? "square.and.pencil" : "doc.text")
                    .foregroundStyle(color)

                Text(item.kind == .fileWrite ? "Wrote \(item.text)" : item.text)
                    .font(.system(size: 13, weight: .semibold, design: .rounded))
                    .foregroundStyle(WindowPalette.primaryText)

                Spacer(minLength: 0)

                if let path = item.path {
                    Button {
                        copy(path)
                    } label: {
                        Image(systemName: "link")
                            .frame(width: 28, height: 28)
                    }
                    .buttonStyle(WindowPlainIconButtonStyle())
                    .help("Copy path")

                    Button {
                        reveal(path)
                    } label: {
                        Image(systemName: "arrow.up.forward.square")
                            .frame(width: 28, height: 28)
                    }
                    .buttonStyle(WindowPlainIconButtonStyle())
                    .help("Reveal in Finder")
                }
            }

            if let path = item.path {
                Text(path)
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                    .foregroundStyle(WindowPalette.secondaryText)
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .textSelection(.enabled)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(WindowPalette.fileCard, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(WindowPalette.stroke, lineWidth: 1)
        }
    }

    private var codeCard: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(spacing: 8) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(item.text)
                        .font(.system(size: 13, weight: .semibold, design: .rounded))
                        .foregroundStyle(WindowPalette.primaryText)

                    HStack(spacing: 6) {
                        if let language = item.language, !language.isEmpty {
                            Text(language)
                                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                                .foregroundStyle(WindowPalette.secondaryText)
                        }

                        if let path = item.path {
                            Text(path)
                                .font(.system(size: 10, weight: .medium, design: .monospaced))
                                .foregroundStyle(WindowPalette.secondaryText)
                                .lineLimit(1)
                                .truncationMode(.middle)
                        }
                    }
                }

                Spacer(minLength: 0)

                Button {
                    copy(item.code ?? item.text)
                } label: {
                    Image(systemName: "doc.on.doc")
                        .font(.system(size: 12, weight: .semibold))
                        .frame(width: 28, height: 28)
                }
                .buttonStyle(WindowPlainIconButtonStyle())
                .help("Copy code")

                if let path = item.path {
                    Button {
                        copy(path)
                    } label: {
                        Image(systemName: "link")
                            .font(.system(size: 12, weight: .semibold))
                            .frame(width: 28, height: 28)
                    }
                    .buttonStyle(WindowPlainIconButtonStyle())
                    .help("Copy path")

                    Button {
                        reveal(path)
                    } label: {
                        Image(systemName: "arrow.up.forward.square")
                            .font(.system(size: 12, weight: .semibold))
                            .frame(width: 28, height: 28)
                    }
                    .buttonStyle(WindowPlainIconButtonStyle())
                    .help("Reveal in Finder")
                }
            }

            ScrollView(.horizontal, showsIndicators: false) {
                HighlightedCodeView(
                    code: item.code ?? item.text,
                    language: item.language
                )
                    .textSelection(.enabled)
                    .padding(11)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .background(WindowPalette.codeBackground, in: RoundedRectangle(cornerRadius: 9, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 9, style: .continuous)
                    .stroke(WindowPalette.stroke.opacity(0.8), lineWidth: 1)
            }
            .overlay {
                if isActiveCode {
                    CodeScanLine(color: color)
                        .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
                }
            }
        }
        .padding(12)
        .background(WindowPalette.fileCard, in: RoundedRectangle(cornerRadius: 13, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 13, style: .continuous)
                .stroke(WindowPalette.stroke, lineWidth: 1)
        }
    }

    private var approvalCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Approval Needed")
                .font(.system(size: 13, weight: .semibold, design: .rounded))
                .foregroundStyle(WindowPalette.primaryText)

            Text(item.text)
                .font(.system(size: 12, weight: .medium, design: .monospaced))
                .foregroundStyle(WindowPalette.primaryText)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: 10) {
                Button("Deny") {
                    store.approve(false)
                }
                .buttonStyle(WindowButtonStyle(kind: .secondary))

                Button("Approve") {
                    store.approve(true)
                }
                .buttonStyle(WindowButtonStyle(kind: .primary))
            }
        }
        .padding(12)
        .background(WindowPalette.approvalCard, in: RoundedRectangle(cornerRadius: 13, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 13, style: .continuous)
                .stroke(WindowPalette.warning.opacity(0.35), lineWidth: 1)
        }
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
        case .userMessage: "You"
        case .assistantMessage: isStreaming ? "FRIDAY is replying" : "FRIDAY"
        case .status: "Status"
        case .toolCall: "Agent"
        case .fileRead: "File Read"
        case .codeSnippet: "Code"
        case .fileWrite: "File Write"
        case .diff: "Diff"
        case .approval: "Approval"
        case .error: "Attention"
        }
    }

    private var symbol: String {
        switch item.kind {
        case .userMessage: "person.fill"
        case .assistantMessage: "sparkles"
        case .status: "waveform.path.ecg"
        case .toolCall: "hammer.fill"
        case .fileRead: "doc.text.fill"
        case .codeSnippet: "chevron.left.forwardslash.chevron.right"
        case .fileWrite: "square.and.pencil"
        case .diff: "plusminus"
        case .approval: "checkmark.seal.fill"
        case .error: "exclamationmark.triangle.fill"
        }
    }

    private var color: Color {
        switch item.kind {
        case .userMessage: WindowPalette.blue
        case .assistantMessage: WindowPalette.rose
        case .status: WindowPalette.mutedAccent
        case .toolCall: WindowPalette.amber
        case .fileRead, .codeSnippet, .fileWrite, .diff: WindowPalette.purple
        case .approval: WindowPalette.warning
        case .error: WindowPalette.error
        }
    }

    private var background: Color {
        switch item.kind {
        case .userMessage: WindowPalette.userBubble
        case .assistantMessage: WindowPalette.fridayBubble
        default: WindowPalette.inputBackground
        }
    }

    private var rowAlignment: Alignment {
        item.kind == .userMessage ? .trailing : .leading
    }

    private var alignment: Alignment {
        item.kind == .userMessage ? .trailing : .leading
    }

    private func copy(_ text: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }

    private func reveal(_ path: String) {
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
    }
}

private struct WorkIndicatorBubble: View {
    let text: String
    let symbol: String
    let color: Color
    @State private var glow = false

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            ZStack {
                Circle()
                    .fill(color.opacity(glow ? 0.22 : 0.1))
                    .frame(width: 30, height: 30)
                    .blur(radius: 6)

                Circle()
                    .fill(color.opacity(0.12))
                    .frame(width: 24, height: 24)

                Image(systemName: symbol)
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(color)
            }
            .frame(width: 26, height: 26)
            .scaleEffect(glow ? 1.05 : 0.98)

            VStack(alignment: .leading, spacing: 7) {
                Text("FRIDAY")
                    .font(.system(size: 11, weight: .semibold, design: .rounded))
                    .foregroundStyle(WindowPalette.secondaryText)

                HStack(spacing: 8) {
                    Text(text)
                        .font(.system(size: 13, weight: .semibold, design: .rounded))
                        .foregroundStyle(WindowPalette.primaryText)
                        .lineLimit(2)

                    ThinkingDots(color: color)
                }
            }
            .padding(.horizontal, 13)
            .padding(.vertical, 11)
            .background(
                LinearGradient(
                    colors: [
                        WindowPalette.fridayBubble,
                        color.opacity(0.08),
                        WindowPalette.inputBackground
                    ],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                ),
                in: RoundedRectangle(cornerRadius: 14, style: .continuous)
            )
            .overlay {
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .stroke(color.opacity(0.22), lineWidth: 1)
            }
            .overlay(alignment: .bottomLeading) {
                AnimatedProgressLine(color: color)
                    .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            }
            .frame(maxWidth: 680, alignment: .leading)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .onAppear {
            withAnimation(.easeInOut(duration: 0.9).repeatForever(autoreverses: true)) {
                glow = true
            }
        }
    }
}

private struct ThinkingDots: View {
    let color: Color

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 30)) { timeline in
            let t = timeline.date.timeIntervalSinceReferenceDate
            HStack(spacing: 4) {
                ForEach(0..<3, id: \.self) { index in
                    let phase = (sin(t * 4.2 + Double(index) * 0.82) + 1) / 2
                    Circle()
                        .fill(color.opacity(0.35 + phase * 0.55))
                        .frame(width: 5, height: 5)
                        .scaleEffect(0.72 + phase * 0.42)
                }
            }
            .frame(width: 28, height: 12)
        }
    }
}

private struct StatusOrb: View {
    let color: Color
    let state: AssistantState
    @State private var pulse = false

    var body: some View {
        ZStack {
            if isActive {
                Circle()
                    .stroke(color.opacity(pulse ? 0.05 : 0.38), lineWidth: 1.2)
                    .frame(width: pulse ? 48 : 34, height: pulse ? 48 : 34)
            }

            Circle()
                .fill(color.opacity(pulse && isActive ? 0.28 : 0.18))
                .frame(width: 38, height: 38)
                .blur(radius: 5)

            Circle()
                .fill(WindowPalette.inputBackground)
                .frame(width: 34, height: 34)
                .overlay {
                    Circle()
                        .stroke(WindowPalette.stroke, lineWidth: 1)
                }

            Image(systemName: symbol)
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(color)
        }
        .frame(width: 42, height: 42)
        .onAppear {
            withAnimation(.easeInOut(duration: 1.45).repeatForever(autoreverses: true)) {
                pulse = true
            }
        }
    }

    private var isActive: Bool {
        switch state {
        case .listening, .transcribing, .thinking, .toolRunning:
            return true
        case .idle, .speaking, .approvalRequired, .error:
            return false
        }
    }

    private var symbol: String {
        switch state {
        case .idle: "circle"
        case .listening: "waveform"
        case .transcribing: "text.bubble"
        case .thinking: "sparkle.magnifyingglass"
        case .toolRunning: "terminal"
        case .speaking: "quote.bubble"
        case .approvalRequired: "checkmark.seal"
        case .error: "exclamationmark.triangle"
        }
    }
}

private struct ActiveStateRail: View {
    let color: Color
    let isActive: Bool
    @State private var sweep = false

    var body: some View {
        ZStack(alignment: .leading) {
            Rectangle()
                .fill(WindowPalette.stroke)
                .frame(height: 1)

            if isActive {
                GeometryReader { proxy in
                    Capsule()
                        .fill(
                            LinearGradient(
                                colors: [.clear, color.opacity(0.8), .clear],
                                startPoint: .leading,
                                endPoint: .trailing
                            )
                        )
                        .frame(width: max(96, proxy.size.width * 0.28), height: 2)
                        .offset(x: sweep ? proxy.size.width : -proxy.size.width * 0.32)
                        .animation(.linear(duration: 1.45).repeatForever(autoreverses: false), value: sweep)
                }
                .frame(height: 2)
            }
        }
        .frame(height: 2)
        .onAppear { sweep = true }
    }
}

private struct AnimatedProgressLine: View {
    let color: Color
    @State private var sweep = false

    var body: some View {
        GeometryReader { proxy in
            Capsule()
                .fill(
                    LinearGradient(
                        colors: [.clear, color.opacity(0.9), .clear],
                        startPoint: .leading,
                        endPoint: .trailing
                    )
                )
                .frame(width: max(70, proxy.size.width * 0.24), height: 2)
                .offset(x: sweep ? proxy.size.width : -proxy.size.width * 0.24)
                .animation(.linear(duration: 1.1).repeatForever(autoreverses: false), value: sweep)
        }
        .frame(height: 2)
        .onAppear { sweep = true }
    }
}

private struct ActivityWave: View {
    let color: Color

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 30)) { timeline in
            let t = timeline.date.timeIntervalSinceReferenceDate
            HStack(alignment: .center, spacing: 3) {
                ForEach(0..<5, id: \.self) { index in
                    Capsule()
                        .fill(color.opacity(0.45 + 0.12 * Double(index % 2)))
                        .frame(width: 3, height: waveHeight(time: t, index: index))
                }
            }
            .frame(width: 26, height: 22)
        }
    }

    private func waveHeight(time: TimeInterval, index: Int) -> CGFloat {
        let value = sin(time * 4.6 + Double(index) * 0.72)
        return 6 + CGFloat((value + 1) * 4.5)
    }
}

private struct CodeScanLine: View {
    let color: Color
    @State private var sweep = false

    var body: some View {
        GeometryReader { proxy in
            Rectangle()
                .fill(
                    LinearGradient(
                        colors: [.clear, color.opacity(0.08), .clear],
                        startPoint: .leading,
                        endPoint: .trailing
                    )
                )
                .frame(width: max(90, proxy.size.width * 0.18))
                .offset(x: sweep ? proxy.size.width : -proxy.size.width * 0.2)
                .animation(.easeInOut(duration: 2.4).repeatForever(autoreverses: false), value: sweep)
        }
        .allowsHitTesting(false)
        .onAppear { sweep = true }
    }
}

private struct HighlightedCodeView: View {
    let code: String
    let language: String?

    var body: some View {
        Text(highlighted)
            .font(.system(size: 12, weight: .regular, design: .monospaced))
            .lineSpacing(2)
    }

    private var highlighted: AttributedString {
        var result = AttributedString(code)
        result.foregroundColor = WindowPalette.codeText

        apply(pattern: #""(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'"#, color: WindowPalette.syntaxString, to: &result)
        apply(pattern: #"\b(?:class|struct|enum|func|def|return|if|else|elif|for|while|try|catch|except|guard|let|var|import|from|async|await|throws|public|private|static|final|case|switch|in|as|self|None|nil|true|false|True|False)\b"#, color: WindowPalette.syntaxKeyword, to: &result)
        apply(pattern: #"\b[A-Z][A-Za-z0-9_]*\b"#, color: WindowPalette.syntaxType, to: &result)
        apply(pattern: #"\b\d+(?:\.\d+)?\b"#, color: WindowPalette.syntaxNumber, to: &result)
        apply(pattern: #"(?m)//.*$|#.*$"#, color: WindowPalette.syntaxComment, to: &result)

        return result
    }

    private func apply(pattern: String, color: Color, to attributed: inout AttributedString) {
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return }
        let nsRange = NSRange(code.startIndex..<code.endIndex, in: code)

        for match in regex.matches(in: code, range: nsRange) {
            guard let stringRange = Range(match.range, in: code),
                  let lower = AttributedString.Index(stringRange.lowerBound, within: attributed),
                  let upper = AttributedString.Index(stringRange.upperBound, within: attributed) else {
                continue
            }
            attributed[lower..<upper].foregroundColor = color
        }
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

private struct QuickPromptButton: View {
    let title: String
    let symbol: String
    let action: () -> Void
    @State private var isHovering = false

    var body: some View {
        Button(action: action) {
            Label(title, systemImage: symbol)
                .font(.system(size: 12, weight: .semibold, design: .rounded))
                .lineLimit(1)
                .padding(.horizontal, 10)
                .padding(.vertical, 7)
        }
        .buttonStyle(QuickPromptButtonStyle())
        .offset(y: isHovering ? -1 : 0)
        .animation(.snappy(duration: 0.16), value: isHovering)
        .onHover { isHovering = $0 }
    }
}

private struct FilterButtonStyle: ButtonStyle {
    let isSelected: Bool
    let color: Color

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(isSelected ? WindowPalette.primaryText : WindowPalette.secondaryText)
            .background(
                isSelected
                ? color.opacity(configuration.isPressed ? 0.22 : 0.16)
                : WindowPalette.inputBackground.opacity(configuration.isPressed ? 0.95 : 0.55),
                in: Capsule()
            )
            .overlay {
                Capsule()
                    .stroke(isSelected ? color.opacity(0.42) : WindowPalette.stroke, lineWidth: 1)
            }
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
    }
}

private struct QuickPromptButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(WindowPalette.primaryText)
            .background(WindowPalette.quickAction.opacity(configuration.isPressed ? 0.72 : 1), in: Capsule())
            .overlay {
                Capsule()
                    .stroke(WindowPalette.stroke, lineWidth: 1)
            }
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
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

private struct WindowPlainIconButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(WindowPalette.secondaryText)
            .background(WindowPalette.inputBackground.opacity(configuration.isPressed ? 0.7 : 1), in: Circle())
            .overlay {
                Circle()
                    .stroke(WindowPalette.stroke, lineWidth: 1)
            }
            .scaleEffect(configuration.isPressed ? 0.94 : 1)
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
    static let quickAction = Color.white.opacity(0.07)
    static let fileCard = Color.white.opacity(0.04)
    static let approvalCard = Color(red: 0.18, green: 0.13, blue: 0.06)
    static let codeBackground = Color.black.opacity(0.34)
    static let stroke = Color.white.opacity(0.095)
    static let primaryText = Color(red: 0.96, green: 0.94, blue: 0.95)
    static let secondaryText = Color(red: 0.67, green: 0.67, blue: 0.72)
    static let codeText = Color(red: 0.86, green: 0.9, blue: 0.92)
    static let syntaxKeyword = Color(red: 0.71, green: 0.56, blue: 1.0)
    static let syntaxString = Color(red: 0.58, green: 0.86, blue: 0.63)
    static let syntaxComment = Color(red: 0.45, green: 0.5, blue: 0.55)
    static let syntaxNumber = Color(red: 1.0, green: 0.74, blue: 0.45)
    static let syntaxType = Color(red: 0.49, green: 0.78, blue: 1.0)
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
