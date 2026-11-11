# Changelog

[简体中文](CHANGELOG.zh-CN.md)

## 0.6.1-dot.2 — 2026-11-11

Changes since `v0.6.1-dot.1`.

### Added

- Dot can list this computer's Codex chats and send a message to a selected chat, including a `codex://threads/…` link. Mac and Windows entries identify the target computer.
- Dot appears in the agent order controls, shows its connection state in the HUD and expanded panel, and uses paper-plane animations for messages and replies.
- A **Stop connection** button pauses Dot. Turning **Enabled** back on reconnects using saved settings, and enabled connections restore when HUD restarts.
- Separate [English](docs/dot-connection-guide.md) and [Chinese](docs/Dot连接指南.md) usage guides cover setup, messaging and unsubscribing.

### Improved

- Dot messages and replies automatically steer a running Codex Desktop chat and queue while idle. Native DeepSeek Harness → Codex messages and replies now use the same busy/idle policy.
- Dot delivery confirmations are generated automatically after HUD verifies the actual receiving input. Messages no longer include the manual confirmation footer.
- English setup prompts and task names are fully English, using **Dot-HUD Communication · Mac / Windows**. The interface consistently uses the name **Dot**.
- The expanded Dot card displays connection status instead of an empty quota. Guide links follow the README language.

### Fixed

- Improved recognition of native Codex inputs when confirming Dot delivery.
- Restored discovery of existing DeepSeek Harness messaging targets outside the recent-session display window.
- Clarified the local HUD and remote Dot tool descriptions and reply-direction errors.
- Made macOS development packaging repeatable and preserved nested runtime layout and signing requirements.
- Sealed public macOS testing bundles and all nested runtimes with explicit ad-hoc signatures, verified before packaging.

### Installation

- Packages: Windows x86_64 installer and macOS Apple Silicon app ZIP / DMG, with bundled runtimes and checksums.
- These are testing builds without Windows publisher signing or macOS Developer ID signing/notarization. macOS may require **System Settings → Privacy & Security → Open Anyway** on first launch. See [Apple's instructions](https://support.apple.com/en-us/102445).
- Existing connection settings can be reused. Use a separate tunnel and plugin for each computer.
- Dot has automatic recipient-confirmed delivery receipts. Native Codex ↔ DeepSeek Harness messaging continues to expose delivery, execution and reply status.
