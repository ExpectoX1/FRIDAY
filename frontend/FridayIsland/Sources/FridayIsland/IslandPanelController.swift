import AppKit
import SwiftUI

@MainActor
final class IslandPanelController {
    private let panel: IslandPanel
    private let screenMetrics: IslandScreenMetrics

    init(store: AssistantStore) {
        screenMetrics = Self.makeScreenMetrics()
        let frame = Self.panelFrame(metrics: screenMetrics)
        panel = IslandPanel(contentRect: frame)
        panel.contentView = NSHostingView(
            rootView: FridayIslandView(collapsedWidth: screenMetrics.notchWidth)
                .environmentObject(store)
        )
        panel.orderFrontRegardless()
    }

    func show() {
        positionPanel()
        panel.orderFrontRegardless()
    }

    func hide() {
        panel.orderOut(nil)
    }

    private func positionPanel() {
        panel.setFrame(Self.panelFrame(metrics: Self.makeScreenMetrics()), display: true)
    }

    private static func makeScreenMetrics() -> IslandScreenMetrics {
        let screen = NSScreen.main ?? NSScreen.screens.first
        let screenFrame = screen?.frame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let notchWidth = screen.flatMap(Self.notchWidth) ?? 216

        return IslandScreenMetrics(screenFrame: screenFrame, notchWidth: notchWidth)
    }

    private static func panelFrame(metrics: IslandScreenMetrics) -> NSRect {
        let screenFrame = metrics.screenFrame
        let width: CGFloat = 560
        let height: CGFloat = 300
        let x = screenFrame.midX - width / 2
        let y = screenFrame.maxY - height - 8
        return NSRect(x: x, y: y, width: width, height: height)
    }

    private static func notchWidth(on screen: NSScreen) -> CGFloat? {
        guard let leftArea = screen.auxiliaryTopLeftArea,
              let rightArea = screen.auxiliaryTopRightArea,
              !leftArea.isEmpty,
              !rightArea.isEmpty
        else {
            return nil
        }

        let measuredWidth = rightArea.minX - leftArea.maxX
        guard measuredWidth >= 120, measuredWidth <= 360 else {
            return nil
        }

        return measuredWidth.rounded()
    }
}

private struct IslandScreenMetrics {
    let screenFrame: NSRect
    let notchWidth: CGFloat
}

final class IslandPanel: NSPanel {
    init(contentRect: NSRect) {
        super.init(
            contentRect: contentRect,
            styleMask: [.borderless, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )

        isOpaque = false
        backgroundColor = .clear
        hasShadow = false
        level = .statusBar
        hidesOnDeactivate = false
        isMovableByWindowBackground = true
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
    }

    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }
}
