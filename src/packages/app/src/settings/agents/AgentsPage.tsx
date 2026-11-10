/* Settings → Agents: the list of agents on the left, the chosen one's
 * settings on the right. */
import { useEffect, useRef, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { DotDetail, type DotStatus } from "./DotDetail";
import type {
  NativeMethod,
  PanelLayout,
  Snapshot,
  SourcePreferences,
} from "@agent-hud/protocol";
import { useText } from "../SettingsPrimitives";
import { AgentList } from "./AgentList";
import { AgentDetail } from "./AgentDetail";
import "./agents.css";

export interface AgentsPageProps {
  snapshot: Snapshot;
  /** Whether the window is on screen; Codex's model list reads only then. */
  active?: boolean;
  action: (
    method: NativeMethod,
    params?: Record<string, unknown>,
  ) => Promise<unknown>;
  layout: PanelLayout;
  onLayout: (layout: PanelLayout) => Promise<unknown>;
  preferences: Record<string, SourcePreferences>;
  onPreferences: (source: string, patch: SourcePreferences) => Promise<unknown>;
}

export default function AgentsPage({
  snapshot,
  active,
  action,
  layout,
  onLayout,
  preferences,
  onPreferences,
}: AgentsPageProps) {
  const t = useText(snapshot);
  const [selectedID, setSelected] = useState<string>();
  const page = useRef<HTMLDivElement>(null);
  const [dot, setDot] = useState<DotStatus | null>(null);
  const readDot = async () => {
    const status = isTauri()
      ? await invoke<DotStatus>("native_dot", { action: "status" })
      : {
          enabled: false,
          running: false,
          ready: false,
          subscribed: false,
          hasRuntimeApiKey: false,
          notice: t(
            "Dot's native runtime is unavailable in this preview.",
            "当前预览无法使用 Dot 本机运行端。",
          ),
        };
    setDot(status);
  };
  useEffect(() => {
    if (active === false) return;
    let disposed = false;
    const refresh = () => {
      if (!disposed) void readDot().catch(() => {});
    };
    refresh();
    const timer = setInterval(refresh, 10000);
    return () => {
      disposed = true;
      clearInterval(timer);
    };
  }, [active]);
  // Found agents first; otherwise the order the runtime lists them in, so
  // the list never jumps when the panel order changes.
  const providers = [...snapshot.providers].sort(
    (a, b) => Number(b.detected) - Number(a.detected),
  );
  providers.push({
    id: "dot",
    name: "Dot",
    detected: true,
    enabled: dot?.enabled ?? false,
    notice: null,
    sessions: dot?.subscribed ? 1 : 0,
  });
  const source =
    providers.find((provider) => provider.id === selectedID) ?? providers[0];
  const select = (id: string) => {
    setSelected(id);
    // Show the new agent from its top, wherever the last one was scrolled.
    page.current?.closest(".settings-scroll")?.scrollTo({ top: 0 });
  };

  return (
    <div className="agents-page" ref={page}>
      <AgentList
        t={t}
        providers={providers}
        selected={source?.id}
        select={select}
      />
      <div className="agents-detail">
        {source?.id === "dot" ? (
          dot ? (
            <DotDetail
              t={t}
              status={dot}
              refresh={readDot}
              save={async (arguments_) => {
                const next = await invoke<DotStatus>("native_dot", {
                  action: "configure",
                  arguments: arguments_,
                });
                setDot(next);
              }}
            />
          ) : (
            <p role="status">
              {t("Reading Dot settings…", "正在读取 Dot 设置…")}
            </p>
          )
        ) : (
          source && (
            // Keyed by agent, so a draft or an error never carries over.
            <AgentDetail
              key={source.id}
              t={t}
              snapshot={snapshot}
              source={source}
              active={active}
              action={action}
              layout={layout}
              onLayout={onLayout}
              preferences={preferences}
              onPreferences={onPreferences}
            />
          )
        )}
      </div>
    </div>
  );
}
