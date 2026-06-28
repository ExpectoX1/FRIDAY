import SwiftUI

struct FaceView: View {
    let state: AssistantState
    let outcome: Outcome?
    let expression: FaceExpression
    let amplitude: Double
    let pulse: Bool

    @State private var blink = false
    @State private var talkPhase = false
    @State private var thinkingPhase = 0
    @State private var idlePhase = 0
    @State private var wigglePhase = 0
    @State private var shakePhase = 0

    private var isBusy: Bool {
        state == .thinking || state == .toolRunning || state == .transcribing
    }

    private var isLoveMode: Bool {
        outcome == .success && state == .speaking
    }

    private var bitmapAnimationName: String? {
        if isLoveMode {
            return "love01"
        }

        if state == .idle {
            return "idle01"
        }

        return nil
    }

    var body: some View {
        ZStack {
            faceScreen

            if let bitmapAnimationName, BitmapAnimation.exists(named: bitmapAnimationName) {
                BitmapAnimationView(name: bitmapAnimationName, tint: .white.opacity(0.94))
                    .padding(.horizontal, 2)
                    .transition(.opacity.animation(.easeInOut(duration: 0.18)))
            } else {
                proceduralFace
            }
        }
        .offset(x: faceOffset.width, y: faceOffset.height)
        .rotationEffect(.degrees(faceTilt))
        .task(id: state) {
            blink = false
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(expression.blinkInterval))
                blink = true
                try? await Task.sleep(for: .milliseconds(120))
                blink = false
            }
        }
        .task(id: state == .speaking) {
            talkPhase = false
            guard state == .speaking else { return }
            while !Task.isCancelled {
                talkPhase.toggle()
                try? await Task.sleep(for: .milliseconds(170))
            }
        }
        .task(id: state == .idle) {
            idlePhase = 0
            guard state == .idle else { return }
            while !Task.isCancelled {
                idlePhase = (idlePhase + 1) % 8
                try? await Task.sleep(for: .milliseconds(650))
            }
        }
        .task(id: isBusy) {
            thinkingPhase = 0
            guard isBusy else { return }
            while !Task.isCancelled {
                thinkingPhase = (thinkingPhase + 1) % 3
                try? await Task.sleep(for: .milliseconds(340))
            }
        }
        .task(id: isLoveMode) {
            wigglePhase = 0
            guard isLoveMode else { return }
            while !Task.isCancelled {
                wigglePhase = (wigglePhase + 1) % 5
                try? await Task.sleep(for: .milliseconds(180))
            }
        }
        .task(id: state == .error) {
            shakePhase = 0
            guard state == .error else { return }
            while !Task.isCancelled {
                shakePhase = (shakePhase + 1) % 5
                try? await Task.sleep(for: .milliseconds(95))
            }
        }
    }

    private var proceduralFace: some View {
        ZStack {
            faceGlow

            blushCheeks
                .offset(y: 7)

            VStack(spacing: 7) {
                eyes
                mouth
            }
            .offset(y: (isBusy ? 1 : 0) + idleBreathOffset)

            stateMotionCue

            if isBusy {
                thinkingDots
                    .offset(y: -25)
            }

            if isLoveMode {
                loveSparkles
            }
        }
    }

    @ViewBuilder
    private var stateMotionCue: some View {
        switch state {
        case .listening:
            ListeningRings(phase: idlePhase)
                .offset(y: -3)
        case .transcribing:
            TranscribingSweep(phase: thinkingPhase)
                .offset(y: -1)
        case .toolRunning:
            ToolBrows(phase: thinkingPhase)
                .offset(y: -17)
        case .approvalRequired:
            ApprovalPulse(phase: idlePhase)
                .offset(y: 20)
        default:
            EmptyView()
        }
    }

    private var faceScreen: some View {
        RoundedRectangle(cornerRadius: 18, style: .continuous)
            .fill(Color.black.opacity(0.001))
            .overlay {
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .strokeBorder(.white.opacity(0.0), lineWidth: 1)
            }
            .overlay {
                LinearGradient(
                    colors: [
                        .white.opacity(0.0),
                        .clear,
                        .clear
                    ],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )
                .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                .animation(.easeInOut(duration: 1.8).repeatForever(autoreverses: true), value: pulse)
            }
    }

    private var faceGlow: some View {
        Ellipse()
            .fill(
                RadialGradient(
                    colors: [
                        FacePalette.rose.opacity(state == .speaking ? 0.28 : 0.18),
                        FacePalette.lavender.opacity(0.12),
                        .clear
                    ],
                    center: .center,
                    startRadius: 2,
                    endRadius: 48
                )
            )
            .frame(width: 104, height: 58)
            .opacity(state == .error ? 0.35 : 1)
            .offset(y: -1 + idleBreathOffset)
    }

    private var blushCheeks: some View {
        HStack(spacing: 47) {
            cheek
            cheek
        }
        .opacity(state == .error ? 0.18 : 0.46)
    }

    private var cheek: some View {
        Ellipse()
            .fill(FacePalette.blush.opacity(0.34))
            .frame(width: 15, height: 7)
            .blur(radius: 1.1)
    }

    private var eyes: some View {
        HStack(spacing: eyeSpacing) {
            TabbieEye(
                blink: blink,
                state: state,
                outcome: outcome,
                left: true,
                thinkingPhase: thinkingPhase,
                idlePhase: idlePhase,
                wigglePhase: wigglePhase
            )
            TabbieEye(
                blink: blink,
                state: state,
                outcome: outcome,
                left: false,
                thinkingPhase: thinkingPhase,
                idlePhase: idlePhase,
                wigglePhase: wigglePhase
            )
        }
        .animation(.spring(response: 0.22, dampingFraction: 0.78), value: state)
        .animation(.easeInOut(duration: 0.26), value: thinkingPhase)
        .animation(.easeInOut(duration: 0.5), value: idlePhase)
        .animation(.spring(response: 0.16, dampingFraction: 0.62), value: wigglePhase)
    }

    private var eyeSpacing: CGFloat {
        switch state {
        case .approvalRequired:
            21
        case .error:
            17
        default:
            20
        }
    }

    @ViewBuilder
    private var mouth: some View {
        if state == .speaking {
            SpeakingMouth(amplitude: amplitude, talkPhase: talkPhase)
                .frame(width: 31, height: 15)
        } else {
            LineMouth(expression: expression, state: state)
                .frame(width: 32, height: 13)
        }
    }

    private var thinkingDots: some View {
        HStack(spacing: 4) {
            ForEach(0..<3) { index in
                Circle()
                    .fill(FacePalette.cream.opacity(index == thinkingPhase ? 0.9 : 0.26))
                    .frame(width: index == thinkingPhase ? 4.5 : 3.5, height: index == thinkingPhase ? 4.5 : 3.5)
                    .offset(y: index == thinkingPhase ? -1 : 0)
                    .animation(.easeInOut(duration: 0.22), value: thinkingPhase)
            }
        }
    }

    private var loveSparkles: some View {
        ZStack {
            heart(x: -41, y: -8, delayIndex: 0)
            heart(x: 39, y: -12, delayIndex: 1)
            heart(x: -30, y: 24, delayIndex: 2)
        }
        .opacity(0.82)
    }

    private func heart(x: CGFloat, y: CGFloat, delayIndex: Int) -> some View {
        Image(systemName: "heart.fill")
            .font(.system(size: delayIndex == wigglePhase ? 8 : 6, weight: .bold))
            .foregroundStyle(FacePalette.rose.opacity(delayIndex == wigglePhase ? 0.92 : 0.38))
            .offset(x: x, y: y - (delayIndex == wigglePhase ? 2 : 0))
            .animation(.spring(response: 0.2, dampingFraction: 0.58), value: wigglePhase)
    }

    private var faceOffset: CGSize {
        if isLoveMode {
            let offsets: [CGFloat] = [0, -2, 2, -1, 0]
            return CGSize(width: offsets[wigglePhase], height: 0)
        }

        if state == .error {
            let offsets: [CGFloat] = [0, -2, 2, -2, 0]
            return CGSize(width: offsets[shakePhase], height: 0)
        }

        return .zero
    }

    private var faceTilt: Double {
        if isLoveMode {
            let tilts: [Double] = [0, -1.2, 1.2, -0.8, 0]
            return tilts[wigglePhase]
        }

        if state == .error {
            let tilts: [Double] = [0, -1.4, 1.4, -1.2, 0]
            return tilts[shakePhase]
        }

        return 0
    }

    private var idleBreathOffset: CGFloat {
        guard state == .idle else { return 0 }
        return idlePhase < 4 ? -1.2 : 0.8
    }
}

private struct ListeningRings: View {
    let phase: Int

    var body: some View {
        HStack(spacing: 62) {
            ring(delay: 0)
            ring(delay: 1)
        }
    }

    private func ring(delay: Int) -> some View {
        Circle()
            .stroke(FacePalette.rose.opacity(phase % 2 == delay ? 0.42 : 0.16), lineWidth: 1.4)
            .frame(width: phase % 2 == delay ? 17 : 11, height: phase % 2 == delay ? 17 : 11)
            .animation(.easeInOut(duration: 0.42), value: phase)
    }
}

private struct TranscribingSweep: View {
    let phase: Int

    var body: some View {
        Capsule()
            .fill(
                LinearGradient(
                    colors: [.clear, FacePalette.lavender.opacity(0.72), .clear],
                    startPoint: .leading,
                    endPoint: .trailing
                )
            )
            .frame(width: 34, height: 2)
            .offset(x: [-11, 0, 11][phase])
            .blur(radius: 0.2)
            .animation(.easeInOut(duration: 0.32), value: phase)
    }
}

private struct ToolBrows: View {
    let phase: Int

    var body: some View {
        HStack(spacing: 26) {
            brow(rotation: -14)
            brow(rotation: 14)
        }
        .offset(y: phase == 1 ? -1 : 0)
        .animation(.easeInOut(duration: 0.28), value: phase)
    }

    private func brow(rotation: Double) -> some View {
        Capsule()
            .fill(FacePalette.cream.opacity(0.72))
            .frame(width: 13, height: 2)
            .rotationEffect(.degrees(rotation))
    }
}

private struct ApprovalPulse: View {
    let phase: Int

    var body: some View {
        Image(systemName: "heart.fill")
            .font(.system(size: phase % 2 == 0 ? 7 : 9, weight: .semibold))
            .foregroundStyle(FacePalette.rose.opacity(phase % 2 == 0 ? 0.48 : 0.86))
            .offset(y: phase % 2 == 0 ? 0 : -1.5)
            .animation(.spring(response: 0.32, dampingFraction: 0.62), value: phase)
    }
}

private struct TabbieEye: View {
    let blink: Bool
    let state: AssistantState
    let outcome: Outcome?
    let left: Bool
    let thinkingPhase: Int
    let idlePhase: Int
    let wigglePhase: Int

    var body: some View {
        ZStack {
            Capsule()
                .fill(eyeFill)
                .frame(width: eyeSize.width, height: blink ? 3 : eyeSize.height)
                .shadow(color: FacePalette.rose.opacity(state == .speaking ? 0.32 : 0.18), radius: state == .speaking ? 6 : 3)

            if !blink && state != .error {
                Circle()
                    .fill(.white.opacity(0.92))
                    .frame(width: max(3.5, eyeSize.width * 0.28), height: max(3.5, eyeSize.width * 0.28))
                    .offset(x: left ? -eyeSize.width * 0.17 : -eyeSize.width * 0.1, y: -eyeSize.height * 0.24)
                    .shadow(color: .white.opacity(0.28), radius: 2)

                eyelashes
            }
        }
        .frame(width: eyeSize.width, height: max(eyeSize.height, 3), alignment: .center)
        .offset(eyeOffset)
        .rotationEffect(.degrees(tilt))
        .animation(.spring(response: 0.18, dampingFraction: 0.72), value: blink)
    }

    private var eyeFill: Color {
        switch state {
        case .error:
            FacePalette.cream.opacity(0.66)
        case .idle:
            FacePalette.cream.opacity(0.86)
        default:
            FacePalette.cream.opacity(0.96)
        }
    }

    private var eyeSize: CGSize {
        if outcome == .success && state == .speaking {
            return CGSize(width: 14, height: wigglePhase % 2 == 0 ? 20 : 23)
        }

        switch state {
        case .idle:
            return CGSize(width: 15, height: 18)
        case .listening, .approvalRequired:
            return CGSize(width: 16, height: 24)
        case .speaking:
            return CGSize(width: 15, height: 22)
        case .thinking, .toolRunning, .transcribing:
            return CGSize(width: 14, height: 21)
        case .error:
            return CGSize(width: 15, height: 8)
        }
    }

    private var cornerRadius: CGFloat {
        state == .error ? 6 : 12
    }

    private var eyelashes: some View {
        ZStack {
            lash(angle: left ? -30 : 30, x: left ? -8.6 : 8.6, y: -7.5)
            lash(angle: left ? -16 : 16, x: left ? -9.7 : 9.7, y: -3.5)
        }
        .opacity(state == .toolRunning ? 0.5 : 0.78)
    }

    private func lash(angle: Double, x: CGFloat, y: CGFloat) -> some View {
        Capsule()
            .fill(FacePalette.cream.opacity(0.78))
            .frame(width: 1.4, height: 5)
            .rotationEffect(.degrees(angle))
            .offset(x: x, y: y)
    }

    private var eyeOffset: CGSize {
        if outcome == .success && state == .speaking {
            let offsets: [CGFloat] = [0, left ? -1.5 : 1.5, left ? 1.5 : -1.5, 0, 0]
            return CGSize(width: offsets[wigglePhase], height: wigglePhase == 1 ? -1 : 0)
        }

        switch state {
        case .idle:
            return idleEyeOffset
        case .thinking:
            return CGSize(width: thinkingPhase == 1 ? (left ? -1.5 : 1.5) : 0, height: thinkingPhase == 2 ? -1 : 0)
        case .transcribing:
            return CGSize(width: thinkingPhase == 1 ? -1.2 : thinkingPhase == 2 ? 1.2 : 0, height: 0)
        case .toolRunning:
            return CGSize(width: left ? 1.1 : -1.1, height: 0.8)
        case .error:
            return CGSize(width: left ? 0.9 : -0.9, height: 1.5)
        default:
            return .zero
        }
    }

    private var tilt: Double {
        switch state {
        case .error:
            left ? 11 : -11
        case .toolRunning:
            left ? -4 : 4
        default:
            0
        }
    }

    private var idleEyeOffset: CGSize {
        switch idlePhase {
        case 2:
            CGSize(width: -1.5, height: 0)
        case 4:
            CGSize(width: 1.5, height: 0)
        case 6:
            CGSize(width: 0, height: -1)
        default:
            .zero
        }
    }
}

private struct LineMouth: View {
    let expression: FaceExpression
    let state: AssistantState

    var body: some View {
        Path { path in
            let width: CGFloat = 32
            let height: CGFloat = 13
            let midY = height / 2
            let curve = mouthCurve

            path.move(to: CGPoint(x: 7.5, y: midY))
            path.addQuadCurve(
                to: CGPoint(x: width - 7.5, y: midY),
                control: CGPoint(x: width / 2, y: midY + curve)
            )
        }
        .stroke(FacePalette.cream.opacity(0.92), style: StrokeStyle(lineWidth: 2.1, lineCap: .round))
    }

    private var mouthCurve: CGFloat {
        switch state {
        case .toolRunning:
            0.8
        case .transcribing, .thinking:
            1.4
        default:
            max(1.2, expression.smileAmount * 6.2)
        }
    }
}

private struct SpeakingMouth: View {
    let amplitude: Double
    let talkPhase: Bool

    var body: some View {
        ZStack {
            Capsule()
                .fill(FacePalette.cream.opacity(0.92))
                .frame(width: width, height: outerHeight)
                .shadow(color: FacePalette.rose.opacity(0.22), radius: 5)

            Capsule()
                .fill(.black.opacity(0.72))
                .frame(width: max(7, width * 0.62), height: innerHeight)

            Capsule()
                .fill(FacePalette.blush.opacity(0.42))
                .frame(width: max(5, width * 0.42), height: 1.2)
                .offset(y: outerHeight * 0.22)
        }
            .animation(.easeInOut(duration: 0.14), value: talkPhase)
            .animation(.easeInOut(duration: 0.14), value: amplitude)
    }

    private var width: CGFloat {
        17 + CGFloat(effectiveAmplitude) * 7
    }

    private var outerHeight: CGFloat {
        8 + CGFloat(effectiveAmplitude) * 4
    }

    private var innerHeight: CGFloat {
        2.4 + CGFloat(effectiveAmplitude) * 5.6
    }

    private var effectiveAmplitude: Double {
        max(clampedAmplitude, talkPhase ? 0.72 : 0.24)
    }

    private var clampedAmplitude: Double {
        min(max(amplitude, 0), 1)
    }
}

private enum FacePalette {
    static let cream = Color(red: 1.0, green: 0.94, blue: 0.96)
    static let blush = Color(red: 1.0, green: 0.45, blue: 0.58)
    static let rose = Color(red: 1.0, green: 0.36, blue: 0.52)
    static let lavender = Color(red: 0.74, green: 0.62, blue: 1.0)
}
