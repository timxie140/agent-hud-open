import { useState } from "react";
import { Button } from "@agent-hud/ui/components/button";
import { Notice, Row, Section, type Text } from "../SettingsPrimitives";

export function DotSetup({ t, platform }: { t: Text; platform?: string }) {
  const machine =
    platform === "macos" ? "Mac" : platform === "windows" ? "Windows" : "";
  const entry =
    machine === "Mac"
      ? "Dot-HUD-Mac"
      : machine === "Windows"
        ? "Dot-HUD-Win"
        : "Dot-HUD";
  const task = `Dot-HUD 通信${machine ? ` · ${machine}` : ""}`;
  const prompt = t(
    `Use the installed ${entry} plugin in this existing Dot conversation. First verify the entry and call hud_list_sessions read-only to check the host. If the entry has a different name, ask me to identify it; do not choose another machine.

Prefer subscribing to hud.message.created with arguments {"mailbox":"dot"}. If the current tool does not accept dot, report its supported parameters and ask me; do not guess, switch arguments or create another subscription. Reuse the existing task for this entry; do not create duplicate subscriptions. Name a new task "${task}"; if an existing task can be renamed, use that name. If naming is unsupported, report the actual task name.

For data.kind=message, call hud_ack_message with data.message_id only after receiving the event. Reply once with hud_reply using the same ID when a reply is needed. For data.kind=delivery_receipt, only record it; never ACK or reply to it. queued/steered means accepted, not confirmed delivery. Use hud_get_delivery_status read-only and wait for recipientConfirmed=true; never resend pending, refused or uncertain messages automatically.

Do not send a test message during setup. Report the verified machine, subscription result and actual task name. If I later want to unsubscribe, remind me to delete this task manually in Scheduled. Stopping the local HUD connection does not delete the task.`,
    `请在这个已有 Dot 会话中使用已安装的 ${entry} 插件。先核对入口，只读调用 hud_list_sessions 确认机器；如果入口名称不同，请让我指出正确入口，不要选另一台机器。

优先订阅 hud.message.created，arguments 为 {"mailbox":"dot"}。若当前工具不接受 dot，请报告实际支持的参数并询问我；不要自行猜测、切换参数或新建订阅。若已有该入口的事件任务，请核对并复用，不要重复订阅。首次创建任务时固定命名为“${task}”；已有任务若支持改名，也使用此名称。若平台不支持命名，请报告实际任务名。

data.kind=message 时，实际收到事件后用 data.message_id 调用 hud_ack_message；需要回复时用同一 ID 调用一次 hud_reply。data.kind=delivery_receipt 时只记录，不 ACK、不回复。queued/steered 仅表示受理，不代表实际送达；可只读查询 hud_get_delivery_status，等待 recipientConfirmed=true。pending、refused 或 uncertain 时不要自动重发。

设置期间不要发送测试消息。完成后报告已核对的机器、订阅结果和实际任务名。以后需要取消订阅时，提醒我到 Scheduled 手动删除此任务；本机 HUD 的“停止连接”不会删除平台任务。`,
  );
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  const copy = async () => {
    setCopied(false);
    setFailed(false);
    try {
      await navigator.clipboard.writeText(prompt);
      setCopied(true);
    } catch {
      setFailed(true);
    }
  };
  return (
    <Section
      title={t("Connect your Dot once", "首次连接 Dot")}
      action={
        <Button
          variant="outline"
          onClick={() => {
            void copy();
          }}
        >
          {copied ? t("Copied", "已复制") : t("Copy prompt", "复制提示词")}
        </Button>
      }
      footer={t(
        "See README → Dot connection guide for Platform links, restricted key permissions and troubleshooting.",
        "完整步骤、Platform 入口、密钥最小权限和故障排查见 README → Dot连接指南。",
      )}
    >
      <Row
        title={t("1. Enable this plugin for your Dot", "1. 在 Dot 中启用插件")}
        subtitle={t(
          `Add a custom MCP plugin named ${entry}, select Tunnel and use the same Tunnel ID as above. Keep this HUD connected while setting it up.`,
          `添加名为 ${entry} 的自定义 MCP 插件，连接方式选择 Tunnel，并使用上方相同的 Tunnel ID。设置期间保持本机 HUD 已连接隧道。`,
        )}
      />
      <label className="dot-field">
        {t(
          "2. Send this prompt to your existing Dot",
          "2. 将此提示词发给已有 Dot",
        )}
        <textarea
          aria-label={t("Dot subscription prompt", "Dot 订阅提示词")}
          readOnly
          rows={10}
          value={prompt}
        />
      </label>
      {failed && (
        <Notice>
          {t(
            "Copy failed. Select and copy the prompt above.",
            "复制失败，请选中上方提示词手动复制。",
          )}
        </Notice>
      )}
      <Row
        title={t(
          "Unsubscribe manually in Scheduled",
          "取消订阅需到 Scheduled 手动删除任务",
        )}
        subtitle={t(
          `Find "${task}" in Scheduled and delete that event task. If the platform uses a different name, use the name reported by Dot. Stop connection only stops this computer.`,
          `在 Scheduled（计划任务）中找到“${task}”并删除对应事件任务；若平台未采用此名称，以 Dot 报告的实际任务名为准。“停止连接”只停止本机通信。`,
        )}
      />
    </Section>
  );
}
