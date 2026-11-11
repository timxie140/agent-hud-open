import type { Snapshot } from "@agent-hud/protocol";

/** A communication client shows connection, never an invented quota. */
export function dotConnectionLabel(
  status:
    | Pick<
        NonNullable<Snapshot["connection"]["dot"]>,
        "enabled" | "running" | "ready" | "subscribed"
      >
    | undefined,
  language: "en" | "zh",
): string {
  const labels =
    language === "zh"
      ? ["已关闭", "正在启动", "连接隧道", "等待 Dot 订阅", "已连接"]
      : [
          "Off",
          "Starting",
          "Connecting",
          "Awaiting Dot subscription",
          "Connected",
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
