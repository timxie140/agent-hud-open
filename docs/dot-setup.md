# Dot / Luo 接入与实际送达回执

Dot 是 HUD 中独立的通信客户端，不能当作 Codex 会话或用一个猜测的聊天 ID 代替。
本版本支持 macOS、Windows；不需要 Codex Bridge。回程沿用 HUD 既有 Codex
投递通道，不新建或接管替代聊天，也不自行恢复另一个会话。

## 1. 在 HUD 配置一次

1. 安装包含 Dot sidecar 和独立 tunnel-client 的完整构建。
2. 打开 **设置 → 智能体 → Dot**，打开“启用”。
3. 填写现有或新建的 **Tunnel ID** 和有对应隧道 Read + Use 权限的 **Runtime API key**。
   隧道还须关联 Luo 所在的 ChatGPT workspace；仅关联 Platform organization 不够。
4. 如本机通过代理联网，在“本机 HTTP 代理”填写现有的回环代理，例如
   `http://127.0.0.1:7890`。Windows 会预填已配置且无凭据的回环代理；可清空直连。
5. 点击“保存并连接”。密钥只在本机填写，不发到聊天、命令行或 GitHub。
   Windows 用当前用户 DPAPI，macOS 用登录 Keychain；无法访问安全存储时失败关闭，
   不回退成明文文件。留空密钥输入框会保留原密钥，不会清除或回显。

保存并启用后，“保存并连接”右侧显示“停止连接”。点击会保存禁用状态，
停止本 HUD 自有的 listener 与 tunnel，不会保存表单中尚未提交的 Tunnel、密钥或代理修改。
已保存配置和既有订阅保留；停止期间不再通过本机 Dot 投递新消息，但无法撤回已经受理的消息。
连接信息只需首次填写并保存。此后开启“启用”即可使用已保存配置自动连接，关闭开关立即停止；
开关不会提交尚未保存的表单修改。修改连接信息时仍使用“保存并连接”。
停止本机连接不等于删除 ChatGPT 的订阅任务。

状态依次为启动、连接隧道、等待 Luo 订阅、已连接 Luo。启用不等于订阅成功。
全局“智能体消息”权限仍须由用户允许，Dot 不会自动打开或绕过该权限。

以后启动 HUD 会自动启动启用的 Dot 连接，客户端注册及订阅数据持久保存，
无需在每个 Codex 线程手动注册。正常关闭 HUD 时结束它自己启动的 sidecar 和
tunnel；不会结束其他应用或修改系统代理、服务、计划任务。macOS 首次访问
Keychain 可能要求用户授权；拒绝后须由用户处理，程序不会绕过。

### 从此前临时脚本迁移

先在原终端结束**旧 Dot MCP 和旧独立 tunnel 两个临时进程**，再启用新版本。
程序发现 `8787` 已占用会拒绝接管，不自动杀进程。不要让两个客户端同时使用
同一 tunnel 的 main 通道。删除旧 Bridge 程序不应删除 Dot 已沿用的平台隧道。
不从旧进程提取密钥；在 HUD 中重新安全输入一次。新版本首次连接需重新订阅，
之后自动恢复持久状态并接受平台刷新，不要求反复手工注册。

## 2. 在现有 Luo 中连接插件

1. 在 ChatGPT Plugins 添加自定义 MCP server，名称可为 **Dot-HUD**。
2. Connection 选择 **Tunnel**，使用 HUD 中相同的 tunnel ID。
   当前实现通过私有隧道注入上游认证，无需另填 sidecar 的局部访问密钥。
3. 在**现有 Luo** 中启用该插件，核实有：
   - 事件 `hud.message.created`
   - 工具 `hud_ack_message`、`hud_reply`、`hud_get_delivery_status`
4. 升级后在插件页重新扫描工具和事件，不要沿用只包含旧 payload schema 的缓存。

新增工具后，在现有 **Dot-HUD-Mac / Dot-HUD-Win** 插件详情中执行 **Refresh**，
确认目录列出 `hud_list_sessions` 和 `hud_send_message`。若目录已经更新、原 Luo
仍只能看到旧工具，本机实测由用户在**原 Dot** 执行 `reboot dot` 后，新工具会在原会话出现。
随后让 Luo 从正确机器入口只读调用 `hud_list_sessions`，核对 host 和目标 UUID。
平台目录刷新与原 Dot 运行实例加载工具是两步；不要仅凭 HUD 重启或订阅恢复判断工具已更新。
此步骤不要求新建替代聊天或重复订阅。

不要猜 Dot ID，不新建替代聊天来冒充 Luo。`dot:luo` 是注册的逻辑邮箱 ID。

## 3. 给 Luo 的订阅说明

将以下说明发送到现有 Luo（只需要首次设置，或实际订阅失效需要恢复时）：

> 请订阅 Dot-HUD 的 `hud.message.created`，arguments 为 `{"mailbox":"luo"}`。
> 若工作区和订阅工具支持，请显式请求 `ttlMs: null`，保留无固定到期的订阅。
> data.kind 为 `message` 时，先调用 `hud_ack_message`，id 使用
> data.message_id；需要回复时调用一次 `hud_reply`，id 仍用原消息 ID。
> `hud_reply` 的 accepted/queued 仅表示投递受理，不代表 Codex 实际收到。
> data.kind 为 `delivery_receipt` 时，仅记录送达通知；可以用
> `hud_get_delivery_status` 查询该原消息 ID，确认 recipientConfirmed=true。
> 不对 delivery_receipt 调用确认或回复，不形成 ACK 循环。
> 不确定时保留原 ID 和状态，不自动重发。

订阅由平台提供的签名 callback 绑定到真实接收聊天。HUD 验证 challenge、
HTTPS、公网地址和签名；代理方式仍将 callback 固定到已验证公网 IP，TLS 校验
原域名，不允许 Fake-IP/私有地址或重定向。回调 URL 和签名秘密不会出现在日志中。
显式 `ttlMs:null` 才授予无固定到期；省略时仍默认一小时并由平台刷新。工作区策略
或平台任务被停止时不能靠本机伪造恢复；HUD 会显示等待订阅，须在原 Luo 中恢复。

### 取消平台订阅

在 ChatGPT 的 **Scheduled（计划任务）** 中找到原 Luo 对应的事件任务，使用该任务的
停用或删除操作；清空事件列表不是退订方式。不要删除 Luo 聊天或新建重复订阅。
平台协议 `events/unsubscribe` 使用原事件名 `hud.message.created`、
原参数 `{"mailbox":"luo"}` 和原 webhook 绑定来定位订阅，由平台提供原 callback，
不需要用户读取或粘贴地址。HUD 已实现匹配退订，收到后下一轮状态刷新显示等待订阅。
只暂停平台任务是否立即产生退订请求须核对实际结果，不能仅凭任务状态声称 HUD 已解绑。

官方参考：[Dot 任务控制](https://learn.chatgpt.com/docs/dots/controls#stop-work)、
[MCP Events 退订协议](https://developers.openai.com/plugins/build/mcp-events#stop-a-subscription)。

## 4. Codex 像给 DSH 一样发送

使用 HUD 已有工具：

```json
list_sessions({})
send_message({"to":"dot:luo","text":"一次性通信验证 YOUR-UNIQUE-MARKER"})
get_message({"id":"发送返回的消息ID"})
```

必须从列表核对 `client=dot`、`id=dot:luo`、标题 Luo 和可达状态。
消息源来自 Codex MCP 执行器的真实线程元数据，不接受模型任意指定另一线程。
没有可识别发送身份、未启用、无有效订阅或权限关闭时拒绝，不能换身份绕过。

### 原生投递反馈与实际收件确认

`hud_reply` 会短暂等待已有 HUD 投递器的结果，返回 `transportState`：
`queued` / `steered` / `started` 保留原生客户端的真实反馈。
仍未处理时返回 `pending_hud`；`refused` / `uncertain` 不会自动重发。
反馈超时不撤销已有投递，也不证明失败，可只读查询 `hud_get_delivery_status`。

HUD 在原 Codex Desktop owner 的规范输入记录中核对目标线程、请求 ID 和完整输入指纹后，
会自动提交最终确认。队列、RPC 受理、乐观 UI 状态和回复查询均不能触发确认。
Codex 可能将客户端请求 ID 换成原生 item ID；此时使用规范输入的完整信封
（原请求和回信 ID）及精确指纹绑定，仍拒绝显式冲突的客户端身份或重复输入。
没有可验证 owner、输入记录尚未进入规范历史或客户端格式不受支持时保持未确认，
原生观察只读，不创建或恢复替代聊天。
自动确认先持久保留尝试，同一回信只尝试一次；崩溃或不确定结果不自动补发通知。

新消息仅包含 Dot 信封和正文，不再附带手动确认提示或可见确认凭据，也不提供手动确认工具。
HUD 验证唯一的真实收件输入后，通过已认证的本机控制通道取得绑定原消息、收件线程与正文的
确认凭据；凭据由现有安全存储中的本机角色密钥派生，数据库只保存其哈希。
重启后可恢复验证，凭据不会进入聊天、公开工具结果或通知；原有已投递旧格式消息仍兼容自动确认。
**读取 get_message 的答案不算实际收到**。确认生成一条 `delivery_receipt` 事件通知 Luo；
重复确认只读回原结果，不再发事件。平台 HTTP 2xx 仅为通知受理，Luo 仍可通过
hud_get_delivery_status 读取持久的确认记录。丢失/不确定的通知不自动重发。
若此时订阅已过期或被停止，合法收件确认仍会保存，通知状态为
`notification_unavailable`；不会向失效订阅发送，也不会自动补发。

| 状态 | 能证明什么 |
| --- | --- |
| webhook_accepted / queued | 事件被接收或消息在队列中 |
| dotAcknowledged=true | Luo 调用了实际接收确认 |
| replyId / replyText | Luo 调用了主动回复工具 |
| nativeReceipt accepted | 原生 HUD 接受了回程投递 |
| recipientConfirmed=true | 真实收件输入已由原生 owner 验证，或收件 Codex 已提交合法最终确认 |

本服务不把原生 accepted、查询结果或模型自行复述当作最终送达确认。
退出或崩溃后已经保留的投递 reservation 不会自动重新发送。

启用 Dot 后，HUD 智能体条可显示独立的 Dot 圆点标识及连接状态，收发复用纸飞机动画。
若个人 HUD 布局限定了智能体列表，需在布局中选入 Dot；不会覆盖已有显示偏好。
Dot 没有用量配额，不显示虚构的 token、余额或额度。

## 5. 从 Dot 主动选择现有 Codex 聊天

在目标机器对应的 MCP 入口调用 `hud_list_sessions()`。返回的 `host` 包含
`label`（Mac / Windows）、`platform` 和当前 HUD 的固定实例 `id`；
`sessions` 只包含本机 HUD 当前列出的现有 Codex 主聊天，提供标题、UUID 和 `codex://threads/<UUID>`。
列表不包含项目路径或凭据，消息权限关闭或列表过期时拒绝选择目标。

用户可把聊天链接发给 Luo，例如 `[工作聊天](codex://threads/<UUID>)`。
Luo 应先从正确机器的入口取列表，核对 `host`，再按 URL 中的 UUID 精确匹配；
未列出的 ID 不能用于创建、恢复或替代一个聊天。主动发送示例：
若目标未列出，先由用户在目标机器正常打开该聊天，待 HUD 识别后重新取列表。

```json
hud_send_message({
  "host_id": "取自该入口返回的 host.id",
  "session_id": "取自列表的 UUID 或 codex://threads/<UUID>",
  "text": "消息内容",
  "request_id": "luo-task-20261111-001"
})
```

每条意图使用一个新的稳定 `request_id`。相同 request_id、目标和正文的重复调用只读取原回执，
包括重启、拒绝和不确定结果之后；不得换 request_id 来自动重发。机器实例 ID 不匹配时拒绝，
所以 Windows 与 Mac 即便有相同聊天 UUID，也不能跨入口投递。

主动消息及 `hud_reply` 均使用自动策略：可验证的 Codex Desktop owner 正在运行时执行原生 steer；
空闲或确认没有 Desktop owner 时进入原生队列。不确定或拒绝的 steer 不会改走队列重发。
队列不会创建替代聊天。其他原生客户端不在此功能范围内。

`hud_send_message` 返回 `id` / `deliveryId` 和 `transportState`。
可用同入口 `hud_get_delivery_status({"id":"返回的 id"})` 只读跟踪；
实际输入被验证后自动生成 `delivery_receipt`，Luo 仅记录，不再 ACK 或回复回执。

## 6. 故障排查与运行数据

- **等待订阅**：核插件启用、事件扫描及 workspace 的事件任务权限，保留平台原始错误。
- **端口占用**：结束用户启动的旧 Dot 临时进程，勿结束不明进程或启动第二个相同隧道。
- **隧道未就绪**：核 tunnel ID、Read + Use 权限、workspace 关联和现有代理。
- **callback_* 错误**：查看有界 `diagnostics.jsonl` 的类别；不允许关闭 TLS、签名或公网校验。
- **native refused/uncertain**：记录原生状态及原消息 ID，不自动换路重投。
- **原生受理但没有最终确认**：尚未取得唯一、可验证的原生收件记录；保持未确认，不能声称成功。
- **实际收到但尚未自动确认**：保留原消息 ID，核对原生 owner 与规范收件记录；不要用普通聊天 ACK 冒充回执，也不要自动重发。
- **macOS 安全提示或 Keychain 拒绝**：如实报告，使用系统支持的授权方式；不移除隔离属性或绕过安全限制。

数据位于当前用户的 `AgentHUDPrivate/dot-client`（Windows 在 LocalAppData，macOS 在
`~/Library/Application Support`）。保存加密配置、受保护订阅秘密、消息与回执状态，
以及最多 1 MiB 的脱敏诊断。消息正文只留在本机数据库，不提交到源码仓库。
诊断日志不含密钥、签名、回调路径或消息正文。卸载程序前先在 Dot 中停止订阅；
不要把另一个产品的清理脚本用于这个目录或仍在使用的平台隧道。

## 构建与验收范围

Windows 和 macOS 必须各在本机系统的 runner 构建，不能将交叉生成文件当作通过。
执行 `python -m pip install -r src/apps/dot/requirements-build.txt` 后按仓库平台构建命令
生成完整安装包；构建会打包 sidecar、独立 tunnel-client、许可证和来源校验记录。
隧道二进制固定为 upstream v0.0.19，下载档案 SHA256 必须匹配才可打包。

CI 产物带源码 revision、runner 架构、校验文件。未配置开发者签名/公证时明确标记
unsigned，CI 构建通过不等于该平台真实 GUI、Keychain 或完整聊天路径已人工验收。

### macOS 本地开发签名

本机已合法配置 Apple Development（或 Mac Developer）身份时，仅为当前构建
进程设置完整身份名称到 `APPLE_SIGNING_IDENTITY`，
再执行 `pnpm run build:macos -- --bundle`。`PYTHON` 可指向 checkout 外的独立
Python 3.12 venv。身份、证书和凭据不得写进共享配置或提交。

该入口先由 Tauri 构建完整 app，并从冻结产物恢复 Tauri 资源复制时丢失的
Python framework 符号链接，再逐一签名其中的 Mach-O、Python framework，
最后签主 app。可执行文件保留自己的 entitlements；Bun MCP 单独增加 JIT 权限。
framework/动态库不使用主 app 的 entitlements 或 provisioning profile。
每个组件都核对架构、签名身份和严格验证，再执行主 app 的递归严格验证。
DMG 使用 `hdiutil` 包装已签名 app，不调用 Finder、不清除扩展属性。
签名记录写在 bundle 外的 `bundle/dmg/local-signature.json`。

此开发签名路径不提交公证，也不自动回退 ad-hoc。免费 Personal Team 的
Apple Development 签名仅供本人开发测试，不代表 Developer ID 分发或 Apple 公证；
Gatekeeper 的系统评估应单独记录，拒绝时使用系统支持的授权流程。
签名后勿再修改 bundle；本地产物使用自己的 SHA256，不与发行包的哈希混用。

资源打包先在同一文件系统的临时目录完成冻结、冒烟和来源校验，再替换生成目录。
这样重复构建不会合并旧 Python framework 的符号链接或残留旧库；失败保留上次产物。

参考：[Tauri 签名配置](https://v2.tauri.app/distribute/sign/macos/)、
[Apple 嵌套签名顺序](https://developer.apple.com/documentation/xcode/using-the-latest-code-signature-format)、
[Bun 可执行文件签名](https://bun.sh/docs/compiler/executables#code-signing-on-macos)。
