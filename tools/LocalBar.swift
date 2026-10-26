import Cocoa
import Foundation

final class AppDelegate: NSObject, NSApplicationDelegate {
    var statusItem: NSStatusItem!
    var menu: NSMenu!
    var timer: Timer?
    var gateway = false
    var localOnly = false
    var ui = false
    var chatgptLocal = false
    var claudeLocal = false
    var resident = ""
    var freeMemory = ""
    var latency = ""
    let home = FileManager.default.homeDirectoryForCurrentUser.path

    var localAI: String { "\(home)/Documents/sovereign-code/runtime" }
    var sovereign: String { "\(home)/Documents/sovereign-code/bin/sovereign" }

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.title = "◌ local"
        menu = NSMenu()
        statusItem.menu = menu
        refresh()
        timer = Timer.scheduledTimer(
            timeInterval: 5.0, target: self, selector: #selector(refresh), userInfo: nil, repeats: true
        )
    }

    // MARK: - probes

    func get(_ url: String, timeout: Double = 2.0) -> (Data?, HTTPURLResponse?) {
        guard let u = URL(string: url) else { return (nil, nil) }
        var request = URLRequest(url: u)
        request.timeoutInterval = timeout
        request.cachePolicy = .reloadIgnoringLocalCacheData
        let sem = DispatchSemaphore(value: 0)
        var body: Data?
        var response: HTTPURLResponse?
        URLSession.shared.dataTask(with: request) { data, res, _ in
            body = data
            response = res as? HTTPURLResponse
            sem.signal()
        }.resume()
        _ = sem.wait(timeout: .now() + timeout + 1.0)
        return (body, response)
    }

    func probe(_ url: String) -> Bool {
        let (_, response) = get(url)
        return response?.statusCode == 200
    }

    func json(_ url: String) -> [String: Any]? {
        let (body, response) = get(url)
        guard response?.statusCode == 200, let body,
            let parsed = try? JSONSerialization.jsonObject(with: body) as? [String: Any]
        else { return nil }
        return parsed
    }

    func run(_ command: String) -> String? {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = ["-lc", command]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = Pipe()
        do {
            try process.run()
        } catch {
            return nil
        }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        return String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    // MARK: - state

    /// The ChatGPT app is local when its config points at the tier gateway and
    /// needs no OpenAI credentials to do so.
    func codexForcedLocal() -> Bool {
        let path = home + "/.codex/config.toml"
        guard let text = try? String(contentsOfFile: path, encoding: .utf8) else { return false }
        return text.contains("model_provider = \"sovereign-tier\"")
            && text.contains("openai_base_url = \"http://127.0.0.1:4010/v1\"")
            && !text.contains("requires_openai_auth = true")
            && !text.contains("env_key = \"SOVEREIGN_API_KEY\"")
    }

    /// Claude Code/Cowork is local when its settings point at the local bridge.
    func claudeIsLocal() -> Bool {
        let path = home + "/.claude/settings.json"
        guard let data = try? Data(contentsOf: URL(fileURLWithPath: path)),
            let parsed = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let env = parsed["env"] as? [String: Any]
        else { return false }
        return env["ANTHROPIC_BASE_URL"] as? String == "http://127.0.0.1:4001"
    }

    /// The app rewrites its own config when settings change in its UI, which
    /// can send it back to the cloud. A saved cloud copy means it was local
    /// before, so a config that is no longer local has drifted.
    func chatgptDrifted() -> Bool {
        let backup = home + "/.codex/config.toml.sovereign-cloud"
        guard FileManager.default.fileExists(atPath: backup) else { return false }
        return !codexForcedLocal()
    }

    func residentModels() -> String {
        guard let payload = json("http://127.0.0.1:11434/api/ps"),
            let models = payload["models"] as? [[String: Any]], !models.isEmpty
        else { return "" }
        let names = models.compactMap { $0["name"] as? String }
        let gb = models.reduce(0.0) { total, model in
            total + Double(model["size"] as? Int ?? 0) / 1_000_000_000
        }
        return "\(names.joined(separator: ", ")) · \(String(format: "%.1f", gb)) GB"
    }

    func freeMemoryGB() -> String? {
        guard let vm = run("/usr/bin/vm_stat"),
            let pageSize = run("/usr/bin/sysctl -n hw.pagesize").flatMap({ Double($0) })
        else { return nil }
        var pages = 0.0
        for line in vm.split(separator: "\n") {
            let name = line.split(separator: ":").first.map(String.init) ?? ""
            let value = line.split(separator: ":").last.map(String.init) ?? ""
            let number = Double(value.components(separatedBy: ".").first ?? "0") ?? 0
            if name.hasPrefix("Pages free") || name.hasPrefix("Pages inactive")
                || name.hasPrefix("Pages speculative") || name.hasPrefix("Pages purgeable")
            {
                pages += number
            }
        }
        let gb = pages * pageSize / 1_000_000_000
        return String(format: "%.1f GB free", gb)
    }

    func tierLatency() -> String {
        guard let payload = json("http://127.0.0.1:4010/metrics"),
            let byTier = payload["by_tier"] as? [String: Any]
        else { return "" }
        var parts: [String] = []
        for tier in ["fast", "balanced", "deep", "ultra"] {
            guard let stats = byTier[tier] as? [String: Any],
                let p50 = stats["p50_ms"] as? Double
            else { continue }
            parts.append("\(tier) \(Int(p50))ms")
        }
        return parts.joined(separator: " · ")
    }

    @objc func refresh() {
        let health = json("http://127.0.0.1:4010/health")
        gateway = health != nil
        localOnly = (health?["local_only"] as? Bool) ?? false
        ui = probe("http://127.0.0.1:4020/api/health")
        chatgptLocal = codexForcedLocal()
        claudeLocal = claudeIsLocal()
        resident = residentModels()
        freeMemory = freeMemoryGB() ?? ""
        latency = tierLatency()
        let marks = (gateway ? 1 : 0) + (chatgptLocal ? 1 : 0) + (claudeLocal ? 1 : 0)
        statusItem.button?.title = marks >= 2 ? "● local" : (marks == 1 ? "◐ local" : "◌ local")
        rebuild()
    }

    // MARK: - menu

    func rebuild() {
        menu.removeAllItems()
        menu.addItem(disabled(gateway
            ? (localOnly ? "Tier gateway · local-only" : "Tier gateway · cloud allowed")
            : "Tier gateway · offline"))
        if !latency.isEmpty { menu.addItem(disabled("Latency · " + latency)) }
        menu.addItem(disabled(ui ? "ChatGPT Local · running" : "ChatGPT Local · stopped"))
        if chatgptDrifted() {
            menu.addItem(disabled("ChatGPT desktop · drifted from local"))
        } else {
            menu.addItem(disabled(chatgptLocal
                ? "ChatGPT desktop · local, no sign-in"
                : "ChatGPT desktop · cloud (needs sign-in)"))
        }
        menu.addItem(disabled(claudeLocal
            ? "Claude · local bridge"
            : "Claude · cloud"))
        if !resident.isEmpty { menu.addItem(disabled("Resident · " + resident)) }
        if !freeMemory.isEmpty { menu.addItem(disabled("Memory · " + freeMemory)) }
        menu.addItem(NSMenuItem.separator())

        menu.addItem(item("Open ChatGPT Local", #selector(openChat), "c"))
        menu.addItem(item("Open ChatGPT desktop", #selector(openDesktop), "d"))
        menu.addItem(item("Start local Codex", #selector(openCodex), "k"))
        menu.addItem(item("Start local Claude", #selector(openClaude), "l"))
        menu.addItem(NSMenuItem.separator())

        let force = item("Force local ChatGPT (no sign-in)", #selector(forceLocal), "f")
        force.isEnabled = !chatgptLocal
        menu.addItem(force)
        let repair = item("Repair ChatGPT local config", #selector(repairLocal), "p")
        repair.isEnabled = chatgptDrifted()
        menu.addItem(repair)
        let restore = item("Restore cloud ChatGPT", #selector(restoreCloud), "g")
        restore.isEnabled = chatgptLocal
        menu.addItem(restore)
        let claudeLocalItem = item("Point Claude at local bridge", #selector(claudeLocalMode), "j")
        claudeLocalItem.isEnabled = !claudeLocal
        menu.addItem(claudeLocalItem)
        let claudeCloudItem = item("Restore cloud Claude", #selector(claudeCloudMode), "h")
        claudeCloudItem.isEnabled = claudeLocal
        menu.addItem(claudeCloudItem)
        menu.addItem(NSMenuItem.separator())

        menu.addItem(item("Unload resident models", #selector(freeModels), "u"))
        menu.addItem(item("Restart local stack", #selector(restartStack), "r"))
        menu.addItem(item("Run local-only audit", #selector(audit), "a"))
        menu.addItem(item("Verify ChatGPT is local", #selector(verify), "v"))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(item("Quit", #selector(quit), "q"))
    }

    func disabled(_ title: String) -> NSMenuItem {
        let it = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        it.isEnabled = false
        return it
    }

    func item(_ title: String, _ action: Selector, _ key: String) -> NSMenuItem {
        let it = NSMenuItem(title: title, action: action, keyEquivalent: key)
        it.target = self
        return it
    }

    // MARK: - actions

    func shell(_ command: String) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = ["-lc", command]
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:\(home)/.local/bin:\(localAI)/bin"
        env["SOVEREIGN_LOCAL_ONLY"] = "1"
        process.environment = env
        try? process.run()
    }

    func terminal(_ command: String) {
        let escaped = command.replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
        shell("/usr/bin/osascript -e 'tell application \"Terminal\" to do script \"\(escaped)\"'")
    }

    @objc func openChat() {
        shell("\(sovereign) chat-web --start --port 4020")
        if let url = URL(string: "http://127.0.0.1:4020") {
            NSWorkspace.shared.open(url)
        }
    }

    @objc func openDesktop() {
        shell("open -a ChatGPT")
    }

    @objc func openCodex() {
        terminal("cd ~ && \(localAI)/bin/chatgpt-local")
    }

    @objc func openClaude() {
        terminal("cd ~ && \(localAI)/bin/claude-local")
    }

    @objc func restartStack() {
        // The stack is a set of launchd services now, so a restart means a
        // kickstart of each one. Restarting them by hand would leave them
        // outside launchd, and a reboot would not bring them back.
        shell("\(sovereign) autostart --restart")
    }

    @objc func forceLocal() {
        // Rewrites ~/.codex/config.toml so the app's model calls go to the
        // tier gateway on this Mac, then restarts the app. No sign-in needed.
        shell("\(sovereign) chatgpt --local")
    }

    @objc func restoreCloud() {
        shell("\(sovereign) chatgpt --cloud")
    }

    @objc func repairLocal() {
        // Puts the app config back on the local provider without restarting
        // the app, for when the app's own settings changed it.
        shell("\(sovereign) chatgpt --repair")
    }

    @objc func claudeLocalMode() {
        shell("\(sovereign) claude --local")
    }

    @objc func claudeCloudMode() {
        shell("\(sovereign) claude --cloud")
    }

    @objc func freeModels() {
        shell("\(sovereign) free")
    }

    @objc func audit() {
        terminal("\(sovereign) local --strict; echo; read -n 1 -s -r -p 'Press any key'")
    }

    @objc func verify() {
        terminal("\(sovereign) chatgpt --verify; echo; read -n 1 -s -r -p 'Press any key'")
    }

    @objc func quit() {
        NSApp.terminate(nil)
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
