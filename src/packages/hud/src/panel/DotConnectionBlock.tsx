import type { Snapshot } from "@agent-hud/protocol";
import { useFormat } from "@agent-hud/ui/format-context";
import { dotConnectionLabel } from "../dot-status";
import { useGround } from "../ground";
import { BlockHeading } from "./BlockHeading";
import { palette, type Logo } from "./theme";

/** Dot is a communication client; the expanded panel has no quota fallback. */
export function DotConnectionBlock({
  snapshot,
  light,
  Logo,
}: {
  snapshot: Snapshot;
  light: boolean;
  Logo: Logo;
}) {
  const { language } = useFormat();
  const colors = palette(useGround(light));
  return (
    <section
      className="hud-dot-connection"
      style={{ display: "grid", gap: "var(--hud-block-gap, 8px)" }}
    >
      <BlockHeading
        vendor="dot"
        Logo={Logo}
        light={light}
        color={colors.text}
        picker={null}
        compact={false}
      />
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 8,
          color: colors.secondary,
        }}
      >
        <span>{language === "zh" ? "连接状态" : "Connection"}</span>
        <strong role="status" style={{ color: colors.text }}>
          {dotConnectionLabel(snapshot.connection.dot, language)}
        </strong>
      </div>
    </section>
  );
}
