import type { Snapshot } from "@agent-hud/protocol";

/** A communication client shows connection, never an invented quota. */
export function dotConnectionLabel(
  status: Snapshot["connection"]["dot"],
  language: "en" | "zh",
): string {
  const labels =
    language === "zh"
      ? ["已关闭", "正在启动", "连接隧道", "等待订阅", "已连接 Luo"]
      : [
          "Off",
          "Starting",
          "Connecting",
          "Awaiting subscription",
          "Connected to Luo",
        ];
  return labels[
    !status?.enabled
      ? 0
      : !status.running
        ? 1
        : !status.ready
          ? 2
          : !status.subscribed
            ? 3
            : 4
  ];
}
