import type { LinkStatus } from "./engine";

type Difference = LinkStatus["differences"][string];

// The axes `link_status` reports an offset on. The engine holds the numbers; this file only decides
// how they read in Chinese, so a sentence can never disagree with the same project's own state.
const PHRASES: { key: keyof Difference; short: string; long: string }[] = [
  { key: "position_ticks", short: "开始比基准早", long: "开始比基准晚" },
  { key: "duration_ticks", short: "比基准短", long: "比基准长" },
  { key: "source_ticks", short: "源入点比基准靠前", long: "源入点比基准靠后" },
];

export function linkOffsetParts(diff: Difference, say: (ticks: number) => string): string[] {
  const parts: string[] = [];
  for (const { key, short, long } of PHRASES) {
    const value = diff[key];
    if (value) parts.push(`${value < 0 ? short : long} ${say(Math.abs(value))}`);
  }
  if (diff.speed_percent) parts.push(`速度差 ${diff.speed_percent > 0 ? "+" : ""}${diff.speed_percent}%`);
  return parts;
}

/** One line naming which side of a link ran ahead of the anchor, by how much, on which axis. */
export function linkOffsetSentence(
  link: LinkStatus,
  nameOf: (clipId: string) => string,
  say: (ticks: number) => string,
): string {
  const anchor = nameOf(link.anchor_clip_id);
  const moved = link.clip_ids.filter((id) => id !== link.anchor_clip_id && linkOffsetParts(link.differences[id], say).length);
  const listed = moved.map((id) => `${nameOf(id)}：${linkOffsetParts(link.differences[id], say).join("、")}`);
  return `以${anchor} 为基准${listed.length ? " · " + listed.join("；") : "（成员都落在同一窗口，只有速度不同）"}`;
}
