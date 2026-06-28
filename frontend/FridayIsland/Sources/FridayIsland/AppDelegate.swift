import AppKit

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private let store = AssistantStore()
    private var panelController: IslandPanelController?
    private var statusItem: NSStatusItem?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let panelController = IslandPanelController(store: store)
        self.panelController = panelController
        panelController.show()

        configureMenuBar()
        store.start()
    }

    func applicationWillTerminate(_ notification: Notification) {
        store.stop()
    }

    private func configureMenuBar() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.title = "FRIDAY"

        let menu = NSMenu()
        menu.addItem(NSMenuItem(title: "Show Island", action: #selector(showIsland), keyEquivalent: ""))
        menu.addItem(NSMenuItem(title: "Hide Island", action: #selector(hideIsland), keyEquivalent: ""))
        menu.addItem(NSMenuItem(title: "Reconnect", action: #selector(reconnect), keyEquivalent: "r"))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "Quit", action: #selector(quit), keyEquivalent: "q"))
        item.menu = menu

        statusItem = item
    }

    @objc private func showIsland() {
        panelController?.show()
    }

    @objc private func hideIsland() {
        panelController?.hide()
    }

    @objc private func reconnect() {
        store.reconnect()
    }

    @objc private func quit() {
        NSApp.terminate(nil)
    }
}
