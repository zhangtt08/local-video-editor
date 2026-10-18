/** 1.159 工程级基色与 1.161 折叠曲线：名单、话术与「预览要不要折」那句判断，只写在这一处。
 *
 * 可选的那几档是引擎算出来的（`gamut.WORKING_PRIMARIES` 与 `gamut.TRANSFER_CURVES`，随
 * `capabilities.working_primaries` 与 `capabilities.fold_transfers` 下发），这里不另写一份名单，
 * 也不另写一个默认值：抄一份就会与引擎拒收的那一份不一致。折叠本身也不在这儿算——九个系数与
 * 那两张每通道表都由引擎塞进预览那份清单，界面只说它会发生。
 */

/** 监视器那一端是什么：浏览器画布就是 sRGB（同 Rec.709 原色），这一句不跟引擎商量。 */
export const DISPLAY_PRIMARIES = "rec709";

const LABELS: Record<string, string> = {
  rec709: "Rec.709（电视与浏览器的默认）",
  "p3-d65": "P3-D65（数字影院与广色屏的 P3 原色，D65 白）",
  rec2020: "Rec.2020（UHD 宽色域）",
  rec601: "SMPTE-C（Rec.601 标带）",
};

/** 下拉菜单列的就是引擎这份名单；认不得的名字照原样念，不悄悄丢掉。 */
export function workingChoices(published: string[] | undefined): { value: string; label: string }[] {
  return (published ?? []).map((value) => ({
    value,
    label: LABELS[value] ?? `（引擎新认得的 ${value}，这里还没有中文名）`,
  }));
}

/** 工程那一档与监视器那一档不同，预览才会多出一级折叠。默认档一个字节都不动。 */
export function foldsForDisplay(working: string | undefined): boolean {
  return (working ?? DISPLAY_PRIMARIES) !== DISPLAY_PRIMARIES;
}

/** 面板上那一行：只说这一格现在会怎样，以及走不通时此刻走得通的那条路。
 *  「这九个数由谁算、导出折到哪一档由谁决定」是来历，挂在同一格的悬停里（`workingProvenance`）。 */
export function workingWords(
  working: string | undefined,
  published: string[] | undefined,
): string {
  const chosen = working ?? DISPLAY_PRIMARIES;
  const name = LABELS[chosen] ?? chosen;
  if (published === undefined) {
    return (
      "这台引擎没下发可选基色那张表，工程按 Rec.709 解释、不折；出路是把引擎升到会回这张表的那一份。"
    );
  }
  if (!published.includes(chosen)) {
    return (
      `名单里没有 ${chosen} 这一档，现在改不进去；出路是换一台认得它的引擎。`
    );
  }
  if (!foldsForDisplay(chosen)) {
    return (
      "工程按 Rec.709 解释调色后的那幅图：预览与导出都不多折一级。"
    );
  }
  return `工程按 ${name} 解释调色后的那幅图；预览比导出多一趟折回，两端的数同一份。`;
}

/** 同一格的悬停：那一行不说的那些数的来历。
 *
 * 1.210 的分工：面板那一行说「会发生什么」，来历（九个数由谁算、与导出那张立方体是不是同一条形状、
 * 导出折到哪一档由谁决定、表叫什么名字）挂在这一格的 `title` 上。这个界面本来就承诺「把鼠标停在控件上
 * 都有解释」，所以来历有地方说，也不必摊成人眼前那四行灰字。两边各由门禁钉着各自的断言。 */
export function workingProvenance(working: string | undefined, published: string[] | undefined): string {
  const chosen = working ?? DISPLAY_PRIMARIES;
  if (published === undefined) {
    return (
      "这一档的名单本该由 capabilities.working_primaries 下发；这台引擎没下发，"
      + "所以下拉菜单是空的、这一格是灰的，工程按它唯一认得的 Rec.709 走。"
    );
  }
  if (!published.includes(chosen)) {
    return (
      `${chosen} 不在 capabilities.working_primaries 那张表里，写进命令引擎会拒收；`
      + "这一行念的还是工程里现存的那一档，界面不替引擎改一个。"
    );
  }
  if (!foldsForDisplay(chosen)) {
    return (
      "这一档与监视器同色，不额外折，所以这里没有那九个数。"
      + "素材那一段从哪儿读、往哪儿写，由每一段自己的色彩管理那一节回答，这一格不揽。"
    );
  }
  return (
    "那九个数由引擎算（gamut.primaries_matrix）随预览清单交下来，界面一份都不抄；"
    + "折的是「抬进线性光—乘—落回」那三趟，与导出那张立方体同一条形状，所以两端是同一份数；"
    + "导出折到哪一档由交付声明的那个色彩标记决定。"
    + "素材那一段从哪儿读、往哪儿写，由每一段自己的色彩管理那一节回答，这一格不揽。"
  );
}

/** 折叠曲线那一档：id 给人挑，label 是引擎那句「这一档是谁」。 */
export type FoldRow = { id: string; label: string };

/** 名单第一行就是引擎的默认档（`tests/foldcurve_check.py` 钉着这一句），所以界面不自己抄名字。 */
export function foldChoices(published: FoldRow[] | undefined): { value: string; label: string }[] {
  return (published ?? []).map((row) => ({ value: row.id, label: row.label }));
}

export function foldDefault(published: FoldRow[] | undefined): string {
  return published?.[0]?.id ?? "";
}

/** 这一格下面说的话：只说这一档现在管哪一步；走不通时点名此刻走得通的那条路。 */
export function foldWords(chosen: string | undefined, published: FoldRow[] | undefined): string {
  if (published === undefined || published.length === 0) {
    return (
      "这台引擎没下发折叠曲线那张表，它按自己唯一认得的那一条折；出路是把引擎升到会回这张表的那一份。"
    );
  }
  const names = published.map((row) => row.id);
  if (!names.includes(chosen ?? foldDefault(published))) {
    return (
      `名单里没有 ${chosen} 这一档；出路是在这里选回 ${names.join("、")} 中的一档。`
    );
  }
  if ((chosen ?? foldDefault(published)) === foldDefault(published)) {
    return (
      "折那九个数之前先按 BT.709 分段曲线抬进线性光，折完按同一条落回。"
    );
  }
  return (
      "折那九个数之前，按你选的这一档把存储值抬进线性光再落回信号。"
    );
}

/** 同一格的悬停：那一行不说的来历——曲线叫什么、与导出那趟是不是同一条、数在哪儿量过。 */
export function foldProvenance(chosen: string | undefined, published: FoldRow[] | undefined): string {
  const names = (published ?? []).map((row) => row.id);
  if (names.length === 0) {
    return (
      "这一档的名单本该由 capabilities.fold_transfers 下发；这台引擎没下发，"
      + "所以下拉菜单是空的、这一格是灰的，曲线由引擎那唯一一条说了算。"
    );
  }
  if (!names.includes(chosen ?? names[0])) {
    return (
      `${chosen} 不在 capabilities.fold_transfers 那张表里，写进命令引擎会拒收；`
      + "下拉菜单列的就是那张表，界面不替它添一档。"
    );
  }
  if ((chosen ?? names[0]) === names[0]) {
    return (
      "链子里另有一条纯幂 2.4 的曲线，与这一档那条分段曲线不是一回事，别按名字挑。"
      + "这一档与 1.161 之前的做法逐字节相同。"
    );
  }
  return (
    "这一格问的是按哪条曲线编出来的：预览折的那三趟与导出那张立方体同一条形状，"
    + "两条曲线各自折过哪几档、量过哪两个数，见 tests/foldcurve_check。"
  );
}
