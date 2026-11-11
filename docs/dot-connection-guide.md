# Dot connection guide

[简体中文](Dot连接指南.md)

Connect your Dot in ChatGPT to Agent HUD to exchange messages with Codex chats on this computer. Available on macOS and Windows.

## 1. Prepare a tunnel and API key

1. Open [OpenAI Platform → Tunnels](https://platform.openai.com/settings/organization/tunnels), select your organization and create a tunnel.
2. Associate it with the ChatGPT workspace where you use Dot, then copy the **Tunnel ID**.
3. Open [OpenAI Platform → API keys](https://platform.openai.com/settings/organization/api-keys) and create a **Restricted** key.
4. Enable only **Tunnels → Read and Use**. Leave all other permissions at **None**. You will enter this key in HUD.

Your account needs tunnel access in that organization. See the [official OpenAI tunnel documentation](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels#permissions-and-access) for access requirements.

If you use both Mac and Windows, create a separate tunnel and plugin for each computer:

| Computer | Example tunnel name | ChatGPT plugin name |
| --- | --- | --- |
| Mac | Agent HUD Mac | `Dot-HUD-Mac` |
| Windows | Agent HUD Windows | `Dot-HUD-Win` |

## 2. Connect in HUD

1. Install and open Agent HUD with Dot support.
2. Open **Settings → Agents → Dot** and turn **Enabled** on.
3. Enter the **Tunnel ID** and **Runtime API key** from the previous step.
4. If you use a local HTTP proxy, enter its address, such as `http://127.0.0.1:7890`. Otherwise, leave it blank.
5. Click **Save and connect** and wait for **Awaiting Dot subscription**. Complete any first-use system authorization prompts.
6. In **Settings → Agent plugins**, enable HUD tools for Codex and **Let agents message each other**.

## 3. Add the ChatGPT plugin

Keep HUD running with Dot enabled during setup.

1. Open **Plugins** in ChatGPT, select **＋ / Add** at the top right, then **Add custom MCP server**.
2. Name the plugin **Dot-HUD-Mac** on Mac or **Dot-HUD-Win** on Windows.
3. Select **Tunnel** as the connection type. In the tunnel list, choose the same tunnel configured in HUD.
4. Set Authentication to **No authentication**.
5. Select **Add / Create as a plugin**, install it, and enable it in the Dot chat you want to use.

The [official OpenAI instructions](https://developers.openai.com/api/docs/guides/custom-mcp-server) also describe adding a plugin.

## 4. Let Dot receive HUD messages

In HUD's **Connect your Dot once** section, select **Copy prompt** and send the prompt to your Dot. HUD fills in the plugin and task names for Mac or Windows automatically.

Allow Dot to use the plugin when prompted. Once Dot subscribes, HUD shows **Connected** and setup is complete.

You can also use this Mac example. For Windows, replace the plugin name with `Dot-HUD-Win` and the task name with `Dot-HUD Communication · Windows`:

```text
Use Dot-HUD-Mac to connect to this Mac and subscribe to hud.message.created with mailbox dot.
Name the subscription task “Dot-HUD Communication · Mac”; keep using the task if one already exists for this plugin.
Acknowledge ordinary messages after receiving them and reply when needed. Only record delivery receipts.
Tell me the subscription result and task name when finished.
```

## 5. Send and receive messages

**From Dot to Codex:** tell Dot the computer and chat link, for example:

```text
Use Dot-HUD-Mac to send a message to this Codex chat: [paste the chat link]
Message: Please tell me the current task's progress.
```

You can also ask Dot to list the Codex chats on that computer, then choose one to message. Open the target chat on that computer first.

**From Codex to Dot:** ask in a Codex chat, “Use Agent HUD to send Dot …”. You can also ask Codex to reply through HUD after receiving a Dot message.

A running Codex chat receives the message as additional input; an idle chat handles it as a new turn. Keep HUD and the Dot connection on while exchanging messages.

## 6. Everyday use and disconnecting

- **Reconnect:** turn **Enabled** on to use the saved settings. HUD also restores an enabled connection when it restarts.
- **Change settings:** after changing the tunnel, key or proxy, select **Save and connect**. Leaving the key field blank keeps the saved key.
- **Pause the connection:** select **Stop connection** or turn **Enabled** off. Your settings are kept.
- **Unsubscribe:** keep HUD connected, open **Scheduled** in ChatGPT, find `Dot-HUD Communication · Mac` or `Dot-HUD Communication · Windows`, and manually delete that task. If it has another name, use the name Dot reported during setup. HUD then shows **Awaiting Dot subscription**.

**Stop connection** pauses local communication; unsubscribing requires deleting the task in Scheduled. To subscribe again later, send Dot the prompt from HUD.
