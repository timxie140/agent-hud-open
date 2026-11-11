# Dot连接指南

本指南适用于包含 Dot 功能的 Agent HUD 完整构建（macOS / Windows）。Dot 是你的 ChatGPT 个人智能体；它可以叫 Luo，也可以有其他名字。界面统一使用 Dot，不要求用户给自己的 Dot 改名。

首次配置的顺序：**Platform 创建隧道与受限密钥 → HUD 保存并连接 → ChatGPT 添加插件 → 在已有 Dot 中订阅 → 核对机器和消息送达**。

## 1. 配置入口与需要准备的内容

| 项目 | 入口 / 来源 | 用途 |
| --- | --- | --- |
| Tunnel 管理 | [OpenAI Platform → Organization → Tunnels](https://platform.openai.com/settings/organization/tunnels) | 创建隧道，关联组织和 ChatGPT workspace，取得 Tunnel ID |
| Runtime API key | [OpenAI Platform → Organization → API keys](https://platform.openai.com/settings/organization/api-keys) | 创建 **Restricted** 密钥，**只启用 Tunnels → Read、Use** |
| 组织角色 | [Organization → People → Roles](https://platform.openai.com/settings/organization/people/roles) | 管理员为操作账号授予对应隧道权限 |
| ChatGPT 插件 | ChatGPT 的 **Plugins → ＋ → Add custom MCP server** | 创建指向本机隧道的 Dot-HUD 插件 |
| 本机 HUD | **设置 → 智能体 → Dot** | 保存 Tunnel ID、Runtime API key 和可选代理 |
| 本机 HUD 工具 | **设置 → 智能体插件**中的目标客户端 | 启用 HUD 工具及智能体消息权限，让已有 Codex 聊天收发消息 |

Platform 页面需登录，并选中正确的组织；菜单名称和可用功能可能随账号、工作区权限变化。ChatGPT workspace 与 Platform organization 是两套范围，不能只凭邮箱相同就认为已关联。

### 最小权限：运行密钥只给 Read + Use

1. 打开上表中的 **Runtime API key** 入口，选择创建密钥。
2. 权限选择 **Restricted**，其他能力保持 **None / 无权限**。
3. 仅在 **Tunnels** 下开启 **Read** 和 **Use**；不要给 **Manage**，也不要选择 **All**。
4. 复制生成的密钥，直接在本机 HUD 的密码输入框中填写一次。不要粘贴到聊天、终端命令、文档或截图。
5. 密钥所属账号仍需具有目标组织内的 Tunnels Read + Use；仅勾选密钥权限不能提升账号本身的权限。

| 操作 | 操作账号所需权限 | HUD 是否需要 |
| --- | --- | --- |
| 创建、编辑、删除 Tunnel | Tunnels Read + Manage | 只在 Platform 设置阶段使用；HUD 不管理隧道 |
| 运行已配置的 Tunnel、选择插件隧道 | Tunnels Read + Use | 是 |
| 创建组织角色或分配权限 | 组织所有者 / RBAC 管理员的相应权限 | 普通 HUD 运行不需要 |
| Admin API key | 用于管理 API 的额外管理凭据 | **不需要，不要填进 HUD** |

权限是组织层面的。若出现 “Tunnels access required”，先确认组织和角色，由管理员处理；不要通过扩大运行密钥权限解决。若当前页面没有 Restricted 或 Tunnels Read / Use 选项，先核对账号与页面，不要改用 All 或 Admin key。

依据：[OpenAI Secure MCP Tunnel 的权限与设置说明](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels#permissions-and-access)。

## 2. 创建或复用 Tunnel

1. 在 [Tunnels 管理页](https://platform.openai.com/settings/organization/tunnels) 检查现有隧道。已有合适且未被另一台机器同时使用的隧道，可以复用。
2. 新建时给它易识别的名称，如 `Agent HUD Mac` 或 `Agent HUD Windows`。
3. 核对隧道关联的 **Platform organization**，并加入准备使用插件的 **ChatGPT workspace**。
4. 复制 **Tunnel ID**，稍后 HUD 和 ChatGPT 插件都使用这个相同 ID。Tunnel ID 是路由标识，不是 API key。

当前版本是一台 HUD 对应一个本地运行端。两台机器同时使用时，分别创建 Tunnel 和插件入口，例如：

| 机器 | Tunnel | ChatGPT 插件名 | 固定事件任务名 |
| --- | --- | --- | --- |
| Mac | Mac 自己的 Tunnel ID | `Dot-HUD-Mac` | `Dot-HUD 通信 · Mac` |
| Windows | Windows 自己的 Tunnel ID | `Dot-HUD-Win` | `Dot-HUD 通信 · Windows` |

不要让 Mac 和 Windows 同时使用同一 Tunnel 的 `main` 通道；当前没有自动汇总两台机器会话的网关。一个 MCP 服务两台机器仍是待开发方案。

Runtime API key 与 Tunnel ID 是不同概念：若账号与密钥对两个目标都有权限，可以复用运行密钥；两台机器的 Tunnel ID 仍应分开。分别使用受限密钥便于独立撤销和轮换，不必给任何一个增加权限。

## 3. 在 HUD 首次保存并连接

1. 安装包含 Dot 的完整构建，正常启动 HUD。完整构建已包含 Dot sidecar、tunnel-client 和运行时，不需另装一个临时 listener。
2. 打开 **设置 → 智能体 → Dot**，打开“启用”。首次尚无配置时，这一步只选择启用状态。
3. 填入 **Tunnel ID** 和 **Restricted Runtime API key**。
4. 如网络需要代理，在“本机 HTTP 代理”填你当前代理软件实际提供的回环 HTTP 地址，例如 `http://127.0.0.1:7890`。它指的是这台电脑上的代理端口，不是 Relay 公网地址；不需要代理时留空。
5. 点击 **保存并连接**，等待“连接隧道”进入“等待 Dot 订阅”。系统或 Keychain 授权应通过正常界面处理。
6. 在 HUD 的目标客户端工具设置中核对 HUD 工具和智能体消息权限已允许。若工具尚未加载，使用客户端支持的工具刷新方式。

macOS 将配置凭据保存在当前用户的 Keychain，Windows 使用当前用户 DPAPI；安全存储不可用时拒绝连接，不回退为明文。密码框保存后留空是正常行为，留空再次保存会保留已有密钥。

配置成功后，以后只开“启用”即可自动连接；HUD 重启也会恢复已启用连接。修改 Tunnel、密钥或代理时才需要再次“保存并连接”。开关只使用已保存配置，不提交尚未保存的表单修改。

如果旧临时 listener 已占用本地端口，先识别并正常停止旧 Dot listener 与旧 tunnel-client；HUD 不会自动杀死或接管未知进程。

## 4. 在 ChatGPT 添加并启用插件

保持 HUD 正在运行且隧道已就绪，再进行以下操作：

1. 打开 **Plugins → ＋ → Add custom MCP server**。
2. 名称使用 `Dot-HUD-Mac` 或 `Dot-HUD-Win`，便于区分目标机器。
3. **Connection** 选择 **Tunnel**，选择或粘贴与本机 HUD 完全相同的 Tunnel ID。
4. 当前 HUD 实现由本机 tunnel-client 注入受保护的上游认证；插件端选择 **No authentication**，不配置 OAuth，也不填写 HUD 内部角色密钥。这不表示本机 listener 没有认证。
5. 完成平台提示的检查并创建插件；如需安装，安装到当前账号 / 工作区。
6. 在你准备接收消息的**已有 Dot** 中启用该插件，核对下面五项工具和事件均可见。

| 项目 | 用途 |
| --- | --- |
| 事件 `hud.message.created` | 接收普通消息和最终送达回执 |
| `hud_ack_message` | Dot 实际收到普通消息后确认接收 |
| `hud_reply` | 对原消息回复一次 |
| `hud_get_delivery_status` | 只读查询原消息 / 回复的投递状态 |
| `hud_list_sessions` | 只读列出该机器上的现有 Codex 聊天 |
| `hud_send_message` | 选择列表中的机器和聊天，主动发送消息 |

隧道运行端未启动时，创建插件和发现工具可能失败。出现限流时等待后再试，同时检查 HUD 是否已连接；不要连续新建重复入口。

依据：[添加自定义 MCP 插件](https://developers.openai.com/api/docs/guides/custom-mcp-server)。

## 5. 可复制给 Dot 的首次订阅提示词

HUD 的“首次连接 Dot”提供 **复制提示词** 按钮，自动按本机平台填写入口和固定任务名。也可以复制下面的 Mac 示例；Windows 将 `Dot-HUD-Mac` 改为 `Dot-HUD-Win`，将任务名改为 `Dot-HUD 通信 · Windows`。如果插件使用了自定义名称，先替换为实际入口名。

```text
请在这个已有 Dot 会话中使用已安装的 Dot-HUD-Mac 插件。先核对入口，只读调用 hud_list_sessions 确认机器；如果入口名称不同，请让我指出正确入口，不要选另一台机器。

订阅 hud.message.created，arguments 为 {"mailbox":"dot"}。若已有该入口的事件任务，请核对并复用，不要重复订阅。首次创建任务时固定命名为“Dot-HUD 通信 · Mac”；已有任务若支持改名，也使用此名称。若平台不支持命名，请报告实际任务名。支持时显式请求 ttlMs: null。

data.kind=message 时，实际收到事件后用 data.message_id 调用 hud_ack_message；需要回复时用同一 ID 调用一次 hud_reply。data.kind=delivery_receipt 时只记录，不 ACK、不回复。queued/steered 仅表示受理，不代表实际送达；可只读查询 hud_get_delivery_status，等待 recipientConfirmed=true。pending、refused 或 uncertain 时不要自动重发。

设置期间不要发送测试消息。完成后报告已核对的机器、订阅结果和实际任务名。以后需要取消订阅时，提醒我到 Scheduled 手动删除此任务；本机 HUD 的“停止连接”不会删除平台任务。
```

新订阅统一使用 `mailbox: "dot"`。旧任务的 `mailbox: "luo"` 仍作为兼容别名接受，与 `dot` 指向同一个收件人，不会生成第二个邮箱；已有任务无需为改名重新订阅。`dot:luo` 是仍保留兼容的本机消息路由 ID，不是个人名字。

订阅由平台生成并验证 callback 绑定到真实接收会话，不需要用户复制回调地址或签名秘密。省略 `ttlMs` 时，HUD 默认授予一小时并接受平台刷新；只有平台显式请求且 HUD 授予 `ttlMs: null`，才是无固定到期。工作区策略仍可撤销任务或权限。

## 6. 怎么判断连接、订阅和实际送达

| HUD 状态 | 含义 / 下一步 |
| --- | --- |
| 已关闭 | 本机 Dot 未启用 |
| 正在启动 | 本机运行端启动中 |
| 连接隧道 | 尚未达到隧道 ready，核对网络、Tunnel ID 和权限 |
| 等待 Dot 订阅 | 隧道 ready，但没有有效且已验证的事件订阅；去已有 Dot 执行订阅提示词 |
| 已连接 | 隧道 ready 且事件订阅有效；不代表某条消息已经实际收件 |

侧边栏 Dot 的展开信息显示“连接状态”，与智能体设置使用相同状态规则。Dot 不提供额度数据，不显示虚构的“额度 --”或收件计数。

当前订阅协议没有约定 Dot 的个人名称字段，HUD 也没有可用的普通用户名称查询接口，因此收件人显示通用 **Dot**。企业合规记录中的名称字段需要额外管理员权限，不属于此最小权限配置，也不用于获取显示名。

需要测试时，先确认目标，再只发送一条带唯一标记的消息。原生 `queued` / `steered` / `started` 是受理结果；`recipientConfirmed=true` 才是 HUD 验证了真实收件输入后的最终确认。新消息没有手动确认尾注，HUD 自动提交回执；Dot 收到 `delivery_receipt` 后只记录，避免回执循环。

## 7. Dot 如何主动选择聊天

1. 向 Dot 提供目标机器及已有聊天链接，例如 `codex://threads/<UUID>`。
2. Dot 从对应机器的入口调用 `hud_list_sessions`，核对 `host.label`、`host.platform`、`host.id`。
3. 仅从返回列表精确匹配聊天 UUID，使用该 `host.id` 和聊天 ID 调用 `hud_send_message`。每条发送意图使用一个稳定的新 `request_id`。
4. 运行中的、可验证 Codex Desktop 聊天使用原生 steer，空闲时进入原生队列。拒绝或不确定时不会换队列重投，也不会新建替代聊天。

同一聊天 UUID 可能在两台机器都出现，必须同时核对机器。目标不在列表时，先在目标机器正常打开聊天，等待 HUD 识别后重新只读查询，不要猜 ID。详细参数见 [Dot 技术说明](dot-setup.md#5-从-dot-主动选择现有-codex-聊天)。

## 8. 停止连接、取消订阅与重启

| 操作 | 结果 |
| --- | --- |
| HUD 点击“停止连接”或关闭“启用” | 停止本机 listener / tunnel 和新消息通路，保存配置；**不删除平台任务** |
| 重新打开“启用” | 用已保存配置自动连接；原订阅是否有效仍由平台决定 |
| 正常退出 / 重启 HUD | 结束 / 恢复自有运行端；保留配置和订阅数据 |
| 在 Scheduled 删除事件任务 | 平台取消该任务并发出退订；HUD 收到退订后显示等待 Dot 订阅 |

**取消订阅需手动操作**：保持 HUD 连接，到 ChatGPT 的 **Scheduled（计划任务）**，找到 `Dot-HUD 通信 · Mac` 或 `Dot-HUD 通信 · Windows`，打开菜单并删除对应的事件任务。旧任务可能叫其他名字，以 Dot 报告的实际任务名、触发入口和事件为准，避免删错。

任务删除后核对 HUD 回到“等待 Dot 订阅”。如果操作时 HUD 离线，不能仅凭本地旧状态判断已完成退订；重连后再核对。此前已验证在连接状态删除任务会收到 `events/unsubscribe` 并清除订阅。

Pause 按钮存在，但它是否立即触发退订未完成同等验收；若目标是明确退订，使用删除任务。清空事件列表会被平台要求“至少一个事件”拒绝，不是退订办法。不要删除 Dot 聊天；以后恢复时，在原 Dot 再次订阅即可。

依据：[MCP Events 订阅与退订](https://developers.openai.com/plugins/build/mcp-events#manage-subscriptions)、[Dot 任务控制](https://learn.chatgpt.com/docs/dots/controls#stop-work)。

## 9. 升级后的工具刷新与常见问题

| 情况 | 检查与处理 |
| --- | --- |
| 看不到 `hud_list_sessions` / `hud_send_message` | 确认安装包含这些工具的完整构建；在对应插件详情 **Refresh / Rescan**，核对五项工具 |
| 插件详情有新工具，但原 Dot 仍只有旧工具 | 用户已实测在原 Dot 执行其 `reboot dot` 操作后能加载新工具；这是 Dot 运行实例刷新，**不是系统 `reboot` 命令**。随后只读调用 `hud_list_sessions` 核对 |
| 刷新后等待订阅 | 检查原事件任务、插件权限与订阅是否有效，不自动重复建任务 |
| Tunnel 不在插件列表 | 核对 workspace 关联和操作账号 Tunnels Read + Use；仅关联 Platform organization 不够 |
| 权限报错 | 核对正确组织、账号角色及 Restricted 密钥 Read + Use，不添加 Manage / All |
| App setup was rate limited | 等待后重试；保持 HUD 和代理运行，核对隧道 ready |
| 停止后侧边栏 Dot 消失 | 预期行为；重新启用后自动连接并恢复显示 |
| 已受理但没有最终回执 | 只读查询原 ID，不凭普通聊天 ACK 冒充最终回执，不自动换 ID 重发 |
| 密钥框为空 | 已保存后不会回显；显示“已保存；留空保持现有密钥”即可 |

插件目录刷新、Dot 加载工具、事件订阅、实际消息收件是四件不同的事，需要分别核对。无需为了升级创建替代 Dot 会话或重复 MCP 入口。

本指南描述当前已实现的一台 HUD 对应一个入口的方案；Dev / Relay 聚合部署尚未包含在此配置流程中。构建、安全存储、运行数据和回执机制详见 [Dot 技术说明](dot-setup.md)。

## 10. 分清 Dot 插件与本机 HUD：不要反方向调用

| 谁在操作 | 使用的入口 | 正确工具 |
| --- | --- | --- |
| Dot 选择一个 Codex 聊天并发消息 | ChatGPT 的 `Dot-HUD-Mac` / `Dot-HUD-Win` 插件 | `hud_list_sessions` → `hud_send_message` |
| Dot 回复自己收到的 Codex 消息事件 | 同一个 Dot 插件 | `hud_ack_message`、`hud_reply` |
| Codex 回复自己收到的 Dot 主动消息 | **本机原生 `agent-hud` MCP** | `send_message({"reply_to":"实际收到的消息 ID","text":"回复内容"})` |
| Codex / DSH 查伙伴、派单和读取回信 | **本机原生 `agent-hud` MCP** | `list_sessions`、`send_message`、`get_message` |

Dot 插件的 `hud_list_sessions` 当前只列 Codex，不列 DSH。原生 `list_sessions` 才是查找 DSH 伙伴的通信清单；其中 reachable / idle 是 HUD 的即时报告，不能代替伙伴真实作业清单，也不能保证没有后台任务。

Dot 插件的 `hud_reply` 只接收 `origin=codex` 的原消息。Codex 不能拿 `origin=dot` 的主动消息 ID 调用它来回复 Dot。出现方向错误时，保留原消息，不改 ID、不换账号、不重发；应先找回本机原生工具。

### 已有 Codex 聊天缺少原生消息工具

1. 在 **HUD → 设置 → 智能体插件** 检查目标 Codex 的 HUD 工具和智能体消息权限；由用户允许必要权限，不靠 Dot 插件绕过。
2. 保持 HUD 运行，在 Codex 所在客户端打开 **Settings → MCP servers**，选择已有的 **agent-hud**，使用该连接的 **Refresh tools / Restart / Reconnect**（以当前客户端提供的控件为准）。官方桌面 MCP 设置流程提供保存后 **Restart**；不要创建同名的第二个服务器。
3. 回到**原聊天**，核对模型实际可以调用 `list_sessions`、`send_message`、`get_message`（原生目录还可能提供 `start_session`，本流程不需要调用它）。不要仅凭另开一条临时 MCP 连接看到了工具，就声称原聊天已经更新。
4. 若该客户端没有连接级刷新入口，或刷新后仍缺失，停止相关派单并报告目录缺失，由用户安排客户端重载。保留原聊天；不能通过创建替代聊天或改用 Dot 的 `hud_reply` 来掩盖缺失。

原生 HUD MCP 已在运行时轮询工具组变化并通过 SDK 的 `notifications/tools/list_changed` 通知客户端；自动化测试覆盖工具增加、替换、移除及通知。服务器通知存在，不代表每个客户端、每条已有聊天都一定实时采用新目录；本机测试和远端测试必须分别核对。

官方参考：[Codex MCP 桌面配置与 Restart](https://learn.chatgpt.com/docs/extend/mcp#configure-in-the-chatgpt-desktop-app)。
