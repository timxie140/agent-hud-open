# 更新日志

[English](CHANGELOG.md)

## 0.6.1-dot.2 — 2026-11-11

以下为相对 `v0.6.1-dot.1` 的更新。

### 新增

- Dot 可列出这台电脑上的 Codex 聊天，并向选定聊天发送消息，支持 `codex://threads/…` 链接。Mac、Windows 入口会标明目标电脑。
- Dot 纳入智能体顺序调整，在 HUD 和展开面板中显示连接状态，收发消息使用纸飞机动画。
- 新增“停止连接”按钮；重新开启“启用”即使用已保存配置连接，HUD 重启也会恢复已启用的连接。
- 提供独立的[中文](docs/Dot连接指南.md)和[英文](docs/dot-connection-guide.md)使用指南，说明配置、收发消息和退订步骤。

### 改进

- Dot 消息及回信在 Codex Desktop 运行中自动 steer，空闲时 queued；原生 DeepSeek Harness → Codex 的主动消息和回信也采用相同策略。
- HUD 核实真实收件输入后自动生成 Dot 送达回执，消息正文不再附带手动确认尾注。
- 英文设置提示词与任务名改为纯英文，使用 **Dot-HUD Communication · Mac / Windows**；界面统一使用通用名称 **Dot**。
- Dot 展开卡片以连接状态替代空白额度；README 按所选语言链接对应指南。

### 修复

- 改进 Dot 自动回执对原生 Codex 收件输入的识别。
- 恢复对近期显示范围之外的已有 DeepSeek Harness 通信会话的发现。
- 明确本机 HUD 与远程 Dot 的工具说明，改善回复方向错误提示。
- 改进 macOS 开发版重复打包，保留嵌套运行时结构与签名要求。

### 安装

- 提供 Windows x86_64 安装程序，以及 macOS Apple Silicon 的 app ZIP / DMG，包含运行时与校验文件。
- 本版为测试构建，未配置 Windows 发布者签名，也未进行 macOS Developer ID 分发签名和公证。Mac 首次打开可能需要在“系统设置 → 隐私与安全性”点击“仍要打开”。参见 [Apple 说明](https://support.apple.com/en-us/102445)。
- 可继续使用已保存的连接配置；每台电脑分别使用自己的 Tunnel 和插件。
- Dot 支持自动实收回执；原生 Codex ↔ DeepSeek Harness 继续提供投递、执行和回复状态跟踪。
