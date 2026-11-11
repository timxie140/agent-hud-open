import { useState } from "react";
import { CircleDot, RefreshCw } from "lucide-react";
import { Button } from "@agent-hud/ui/components/button";
import { ToggleRow } from "../SettingsControls";
import { Notice, Page, Row, Section, type Text } from "../SettingsPrimitives";

export interface DotStatus {
  enabled: boolean;
  tunnelId?: string;
  hasRuntimeApiKey: boolean;
  proxy?: string;
  running: boolean;
  ready: boolean;
  subscribed: boolean;
  notice?: string | null;
  confirmedReplies?: number;
  lastConfirmedAt?: string | null;
}

export function DotDetail({
  status,
  save,
  refresh,
  t,
}: {
  status: DotStatus;
  save: (arguments_: Record<string, unknown>) => Promise<void>;
  refresh: () => Promise<void>;
  t: Text;
}) {
  const [enabled, setEnabled] = useState(status.enabled);
  const [tunnelId, setTunnelId] = useState(status.tunnelId ?? "");
  const [runtimeApiKey, setRuntimeApiKey] = useState("");
  const [proxy, setProxy] = useState(status.proxy ?? "");
  const [pending, setPending] = useState<"save" | "start" | "stop" | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const configured = Boolean(status.tunnelId && status.hasRuntimeApiKey);
  const connect = async () => {
    setPending("save");
    setError(null);
    try {
      await save({
        enabled,
        tunnelId: tunnelId.trim(),
        runtimeApiKey,
        proxy: proxy.trim(),
      });
      setRuntimeApiKey("");
    } catch (cause) {
      setError(String(cause));
    } finally {
      setPending(null);
    }
  };
  const setConnection = async (next: boolean) => {
    setPending(next ? "start" : "stop");
    setError(null);
    try {
      // Toggle only the saved connection; never apply unsaved form fields.
      await save({ enabled: next });
      setEnabled(next);
    } catch (cause) {
      setError(String(cause));
    } finally {
      setPending(null);
    }
  };
  const connection = !status.enabled
    ? t("Off", "已关闭")
    : !status.running
      ? t("Starting", "正在启动")
      : !status.ready
        ? t("Connecting tunnel", "正在连接隧道")
        : !status.subscribed
          ? t("Waiting for Luo's subscription", "等待 Luo 订阅")
          : t("Connected to Luo", "已连接 Luo");
  return (
    <Page>
      <div className="dot-heading">
        <CircleDot aria-hidden="true" size={26} />
        <h2>Dot</h2>
        <Button
          variant="ghost"
          size="icon"
          aria-label={t("Refresh Dot status", "刷新 Dot 状态")}
          disabled={pending !== null}
          onClick={() => {
            void refresh().catch(() =>
              setError(t("Status unavailable", "无法读取状态")),
            );
          }}
        >
          <RefreshCw size={18} />
        </Button>
      </div>
      {error && <Notice>{error}</Notice>}
      <Section>
        <ToggleRow
          title={t("Enabled", "启用")}
          checked={enabled}
          change={(next) => {
            if (configured) {
              void setConnection(next);
            } else {
              setEnabled(next);
            }
          }}
          disabled={pending !== null}
          subtitle={
            configured
              ? t(
                  "Connect automatically using your saved settings. Turning off stops the connection.",
                  "开启后使用已保存配置自动连接，关闭即停止连接。",
                )
              : t(
                  "Enter your connection details and save once. Future toggles connect automatically.",
                  "首次填写连接信息并保存，后续开启即可自动连接。",
                )
          }
        />
        <Row title={t("Connection", "连接状态")}>
          <span role="status">{connection}</span>
        </Row>
        <Row title={t("Recipient", "收件人")}>
          <span>Luo · dot:luo</span>
        </Row>
        <Row
          title={t("Recipient-confirmed replies", "已获收件人确认的回信")}
          subtitle={
            status.lastConfirmedAt ??
            t("No actual delivery confirmation yet", "尚无实际送达确认")
          }
        >
          <span>{status.confirmedReplies ?? 0}</span>
        </Row>
      </Section>
      <Section
        title={t("Private tunnel", "私有隧道")}
        footer={t(
          "The runtime API key is kept in this user's secure system storage and never returned to this form.",
          "runtime API key 保存在当前用户的系统安全存储中，不会回显。",
        )}
      >
        <label className="dot-field">
          Tunnel ID
          <input
            aria-label="Tunnel ID"
            value={tunnelId}
            placeholder="tunnel_…"
            spellCheck={false}
            autoComplete="off"
            disabled={pending !== null}
            onChange={(event) => setTunnelId(event.target.value)}
          />
        </label>
        <label className="dot-field">
          Runtime API key
          <input
            aria-label="Runtime API key"
            type="password"
            autoComplete="new-password"
            value={runtimeApiKey}
            placeholder={
              status.hasRuntimeApiKey
                ? t("Saved; leave blank to keep", "已保存；留空保持现有密钥")
                : t("Enter locally", "仅在本机输入")
            }
            disabled={pending !== null}
            onChange={(event) => setRuntimeApiKey(event.target.value)}
          />
        </label>
        <label className="dot-field">
          {t("Local HTTP proxy (optional)", "本机 HTTP 代理（可选）")}
          <input
            aria-label={t("Local HTTP proxy", "本机 HTTP 代理")}
            value={proxy}
            placeholder="http://127.0.0.1:7890"
            autoComplete="off"
            disabled={pending !== null}
            onChange={(event) => setProxy(event.target.value)}
          />
        </label>
        <div className="dot-actions">
          <Button
            disabled={
              pending !== null ||
              (enabled &&
                (!tunnelId.trim() ||
                  (!runtimeApiKey && !status.hasRuntimeApiKey)))
            }
            onClick={() => {
              void connect();
            }}
          >
            {pending === "save"
              ? t("Saving…", "正在保存…")
              : pending === "start"
                ? t("Connecting…", "正在连接…")
                : t("Save and connect", "保存并连接")}
          </Button>
          {status.enabled && (
            <Button
              variant="outline"
              disabled={pending !== null}
              onClick={() => {
                void setConnection(false);
              }}
            >
              {pending === "stop"
                ? t("Stopping…", "正在停止…")
                : t("Stop connection", "停止连接")}
            </Button>
          )}
        </div>
      </Section>
      {status.notice && <Notice>{status.notice}</Notice>}
      <Section
        title={t("Connect your Dot once", "首次连接 Dot")}
        footer={t(
          "See README → Dot setup for the exact subscription instructions and delivery receipt rules.",
          "详见 README 的 Dot 接入教程：订阅参数、真实送达回执及故障排查。",
        )}
      >
        <Row
          title={t("1. Add the Dot-HUD plugin", "1. 添加 Dot-HUD 插件")}
          subtitle={t(
            "In ChatGPT, add a custom MCP server using this tunnel and enable it for the existing Luo.",
            "在 ChatGPT 添加使用此隧道的自定义 MCP 插件，并在既有 Luo 中启用。",
          )}
        />
        <Row
          title={t(
            "2. Subscribe to hud.message.created",
            "2. 订阅 hud.message.created",
          )}
          subtitle={'arguments: {"mailbox":"luo"}'}
        />
        <Row
          title={t("3. Keep receipts separate", "3. 区分送达回执")}
          subtitle={t(
            "Reply once to a message; record delivery_receipt without replying or acknowledging it.",
            "普通消息可回复一次；delivery_receipt 只记录，不回复、不再确认，避免循环。",
          )}
        />
      </Section>
    </Page>
  );
}
