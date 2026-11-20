import { quotaPercentLabel, type QuotaDisplay } from "@agent-hud/ui/format";
import type { HUDVendor } from "./model.ts";

/** A window's short name, as Core names it (the Swift `shortName`). */
export function quotaShortName(quota: {
  name: string;
  shortLabel?: string;
}): string {
  return quota.shortLabel || quota.name;
}

/** The share a Simple mark's ring and number show: its chosen live window — the shortest when the screen asks for it, else the tightest — else the one its last reading holds, drawn grey since its level is then "stale". */
export function markUsed(vendor: HUDVendor): number | null {
  return vendor.used ?? vendor.heldUsed;
}

/** The number a Simple HUD writes beside a mark: its chosen window (`markUsed`), else its balance, else its last 24 hours (vendors.rs `meter_label`). */
export function meterLabel(vendor: HUDVendor, display?: QuotaDisplay): string {
  const used = markUsed(vendor);
  return used == null
    ? (vendor.balance ?? vendor.usage ?? "--")
    : quotaPercentLabel(used, display);
}
