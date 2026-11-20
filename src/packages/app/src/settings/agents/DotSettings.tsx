import { useCallback, useEffect, useState } from "react";
import { ChevronLeft } from "lucide-react";
import { LinkButton } from "../SettingsControls";
import { invoke, isTauri } from "@tauri-apps/api/core";
import type { Snapshot } from "@agent-hud/protocol";
import { useText } from "../SettingsPrimitives";
import { DotDetail, type DotStatus } from "./DotDetail";

export function DotSettings({
  snapshot,
  active,
  back,
}: {
  snapshot: Snapshot;
  active?: boolean;
  back: () => void;
}) {
  const t = useText(snapshot);
  const [status, setStatus] = useState<DotStatus | null>(null);
  const read = useCallback(async () => {
    const next = isTauri()
      ? await invoke<DotStatus>("native_dot", { action: "status" })
      : {
          enabled: false,
          running: false,
          ready: false,
          subscribed: false,
          hasRuntimeApiKey: false,
          notice: "Dot's native runtime is unavailable in this preview.",
        };
    setStatus(next);
  }, []);
  useEffect(() => {
    if (active === false) return;
    let disposed = false;
    const refresh = () => {
      void read().catch((error) => {
        if (!disposed)
          setStatus({
            enabled: false,
            running: false,
            ready: false,
            subscribed: false,
            hasRuntimeApiKey: false,
            notice: String(error),
          });
      });
    };
    refresh();
    const timer = setInterval(refresh, 10000);
    return () => {
      disposed = true;
      clearInterval(timer);
    };
  }, [active, read]);
  return (
    <>
      <div className="agents-back">
        <LinkButton onClick={back}>
          <ChevronLeft size={13} />
          {t("Agents", "智能体")}
        </LinkButton>
      </div>
      {status ? (
        <DotDetail
          t={t}
          status={status}
          platform={snapshot.connection.system?.platform}
          refresh={read}
          save={async (arguments_) => {
            const next = await invoke<DotStatus>("native_dot", {
              action: "configure",
              arguments: arguments_,
            });
            setStatus(next);
          }}
        />
      ) : (
        <p role="status">{t("Reading Dot settings…", "正在读取 Dot 设置…")}</p>
      )}
    </>
  );
}
