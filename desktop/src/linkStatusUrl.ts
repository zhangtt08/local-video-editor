/**
 * 链接状态那条轮询的 URL。它只读回执里的 `revision` 与 `links`，而这两个键在带 `clips` 的子集
 * 请求里仍按整份工程给（引擎是唯一说法），所以点名选中的那几段既省掉整份清单，也不改变判断。
 *
 * 这里不收 `appInfo`：保持纯函数，壳层检查才能量到同一条式子。
 */
export const linkStatusUrl = (
  base: string,
  projectId: string,
  revision: number,
  sequenceId: string | null,
  clipIds: readonly string[]
) => {
  const wanted = [...new Set(clipIds)];
  const params = [`revision=${revision}`, ...wanted.map((id) => `clips=${encodeURIComponent(id)}`)];
  if (sequenceId) params.push(`sequence_id=${encodeURIComponent(sequenceId)}`);
  return `${base}/v1/projects/${encodeURIComponent(projectId)}/preview-manifest?${params.join("&")}`;
};
