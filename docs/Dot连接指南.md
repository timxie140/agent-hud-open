# Dot连接指南

[English](dot-connection-guide.md)

将 ChatGPT 中的 Dot 连接到 Agent HUD，即可与这台电脑上的 Codex 聊天收发消息。支持 macOS 和 Windows。

## 1. 准备 Tunnel 和 API key

1. 打开 [OpenAI Platform → Tunnels](https://platform.openai.com/settings/organization/tunnels)，选择要使用的组织并创建隧道。
2. 将隧道关联到准备使用 Dot 的 ChatGPT 工作区，复制 **Tunnel ID**。
3. 打开 [OpenAI Platform → API keys](https://platform.openai.com/settings/organization/api-keys)，创建 **Restricted** 密钥。
4. 仅开启 **Tunnels → Read、Use**，其他权限保持 **None**。这个密钥稍后填入 HUD。

操作账号需要具有该组织的隧道使用权限。Tunnel 的设置说明见 [OpenAI 官方文档](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels#permissions-and-access)。

如果同时使用 Mac 和 Windows，为每台电脑分别创建 Tunnel 和插件：

| 电脑 | Tunnel 名称示例 | ChatGPT 插件名 |
| --- | --- | --- |
| Mac | Agent HUD Mac | `Dot-HUD-Mac` |
| Windows | Agent HUD Windows | `Dot-HUD-Win` |

## 2. 在 HUD 连接

1. 下载并启动[包含 Dot 功能的 Agent HUD](https://github.com/timxie140/agent-hud-open/releases/latest)。
2. 打开 **设置 → 智能体 → Dot**，开启“启用”。
3. 填入刚才的 **Tunnel ID** 和 **Runtime API key**。
4. 如果使用本机 HTTP 代理，填写代理地址，例如 `http://127.0.0.1:7890`；不使用代理时留空。
5. 点击 **保存并连接**，等待状态变为 **等待 Dot 订阅**。首次使用时，按系统提示完成授权。
6. 打开 **设置 → 智能体插件**，为 Codex 开启 HUD 工具，并开启“允许智能体互发消息”。

## 3. 在 ChatGPT 添加插件

设置期间保持 HUD 运行、Dot 已启用。

1. 在 ChatGPT 打开 **插件（Plugins）**，点击右上角 **＋ / 添加**，选择 **添加自定义 MCP 服务器（Add custom MCP server）**。
2. 填写插件名：Mac 使用 **Dot-HUD-Mac**，Windows 使用 **Dot-HUD-Win**。
3. 连接方式选择 **Tunnel**，在加载出的隧道列表中选择与 HUD 相同的 Tunnel。
4. 身份验证选择 **无需身份验证（No authentication）**。
5. 点击 **添加 / Create as a plugin**，完成安装，并在要使用的 Dot 聊天中启用插件。

插件添加流程也可参阅 [OpenAI 官方说明](https://developers.openai.com/api/docs/guides/custom-mcp-server)。

## 4. 让 Dot 接收 HUD 消息

在 HUD 的“首次连接 Dot”中点击 **复制提示词**，将提示词发给要使用的 Dot。HUD 会按本机系统自动填写 Mac 或 Windows 的插件名和任务名。

按提示允许 Dot 使用插件。Dot 完成订阅后，HUD 会显示 **已连接**，首次设置即完成。

也可以使用下面的 Mac 示例；Windows 将插件名改为 `Dot-HUD-Win`，任务名改为 `Dot-HUD 通信 · Windows`：

```text
请使用 Dot-HUD-Mac 连接这台 Mac，订阅 hud.message.created，mailbox 使用 dot。
将订阅任务命名为“Dot-HUD 通信 · Mac”；如果已有该入口的任务，继续使用它。
收到普通消息后确认收件，并按需要回复；送达回执只记录。
完成后告诉我订阅结果和任务名称。
```

## 5. 收发消息

**从 Dot 发给 Codex**：告诉 Dot 目标电脑和聊天链接，例如：

```text
请通过 Dot-HUD-Mac 给这个 Codex 聊天发消息：[粘贴聊天链接]
消息内容：请告诉我当前任务的进展。
```

也可以先让 Dot 列出这台电脑上的 Codex 聊天，再选择一个发送。目标聊天需要已在对应电脑上打开。

**从 Codex 发给 Dot**：在 Codex 聊天中说“请通过 Agent HUD 给 Dot 发送……”。收到 Dot 的消息后，也可以让 Codex 通过 HUD 回复。

运行中的 Codex 聊天会接收补充消息；空闲的聊天会将消息作为新一轮处理。收发消息时保持 HUD 和 Dot 连接开启。

## 6. 日常使用与停止连接

- **再次连接**：开启“启用”即可使用已保存的配置；HUD 重启后也会自动恢复已启用的连接。
- **修改配置**：修改 Tunnel、密钥或代理后，点击“保存并连接”。密钥框留空会保留已保存的密钥。
- **暂时停止**：点击“停止连接”或关闭“启用”，配置会保留。
- **取消订阅**：保持 HUD 连接，在 ChatGPT 的 **Scheduled / 计划任务** 中找到 `Dot-HUD 通信 · Mac` 或 `Dot-HUD 通信 · Windows`，手动删除该任务。若任务名称不同，使用 Dot 设置时报告的名称。删除后 HUD 会显示“等待 Dot 订阅”。

“停止连接”暂停本机通信；取消订阅需要在 Scheduled 中删除任务。以后需要恢复订阅时，再将 HUD 中的提示词发给 Dot。
