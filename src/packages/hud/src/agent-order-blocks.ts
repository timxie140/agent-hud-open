import type { Snapshot } from "@agent-hud/protocol";
import { agentArtworkKey } from "./agent-artwork.ts";

type OrderBlock = { id: string; source: string; balance: boolean };

/** Settings must offer every visible provider, including clients without quota. */
export function agentOrderBlocks(
  snapshot: Pick<Snapshot, "quotas" | "billing" | "providers">,
): OrderBlock[] {
  const blocks = [
    ...new Map<string, OrderBlock>([
      ...snapshot.quotas.map(
        (row) =>
          [
            row.vendor,
            { id: row.vendor, source: row.vendor, balance: false },
          ] as const,
      ),
      ...snapshot.billing.map(
        (account) =>
          [
            `api:${account.vendor}`,
            {
              id: `api:${account.vendor}`,
              source: account.vendor,
              balance: true,
            },
          ] as const,
      ),
    ]).values(),
  ];
  const represented = new Set(
    blocks.map((block) => agentArtworkKey(block.source)),
  );
  for (const provider of snapshot.providers) {
    const key = agentArtworkKey(provider.id);
    if (!provider.detected || !provider.enabled || represented.has(key))
      continue;
    represented.add(key);
    blocks.push({ id: provider.id, source: provider.id, balance: false });
  }
  return blocks;
}
