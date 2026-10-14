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

/** 那一行下面说的话：声明的是什么、不替谁做决定、折的那一趟谁算。 */
export function workingWords(
  working: string | undefined,
  published: string[] | undefined,
): string {
  const chosen = working ?? DISPLAY_PRIMARIES;
  const name = LABELS[chosen] ?? chosen;
  if (published === undefined) {
    return (
      "这台引擎没有下发可选基色的那张表（capabilities.working_primaries），工程就按它唯一认得的 Rec.709 " +
      "解释：预览与导出都不多折一级，这与 1.159 之前的做法逐字节相同。出路是把引擎升到会回这张表的那一份。"
    );
  }
  if (!published.includes(chosen)) {
    return (
      `引擎下发的名单（capabilities.working_primaries）里没有 ${chosen}，所以这一档现在改不进去——` +
      "写的时候引擎会拒收并把版本号留在原处，下拉菜单只列名单里的那些。出路是换一台认得这一档的引擎，" +
      "或在这里选回名单里的一档。"
    );
  }
  if (!foldsForDisplay(chosen)) {
    return (
      "工程按 Rec.709 解释调色后的那幅图：预览与导出都不多折一级，这与 1.159 之前的唯一一种做法逐字节相同。" +
      "素材自己从哪档来仍由那一段的色彩管理判断（那里管的是曲线，不是原色）。"
    );
  }
  return (
    `工程按 ${name} 解释调色后的那幅图。监视器是 sRGB，所以预览在链子最后多一趟 ${chosen}→Rec.709 的折叠：` +
    "先按那条曲线抬进线性光、乘九个系数、再落回信号，与导出那张立方体同一条形状。九个系数由引擎算" +
    "（gamut.primaries_matrix）随清单一起交下来，界面一份都不抄；导出折到哪一档由交付声明的那个色彩标记" +
    "决定，同一张表。它不替你判断素材从哪档来——那是每一段自己的色彩管理。"
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

/** 这一格下面说的话：三种情形各自说清自己的范围与出路，不许把「同名两条曲线」这件事藏起来。 */
export function foldWords(chosen: string | undefined, published: FoldRow[] | undefined): string {
  if (published === undefined || published.length === 0) {
    return (
      "这台引擎没有下发折叠曲线那张表（capabilities.fold_transfers），所以它按自己唯一认得的那一条折：" +
      "预览那两级表与导出那张立方体都与 1.161 之前逐字节相同。出路是把引擎升到会回这张表的那一份。"
    );
  }
  const names = published.map((row) => row.id);
  if (!names.includes(chosen ?? foldDefault(published))) {
    return (
      `引擎下发的名单（capabilities.fold_transfers）里没有 ${chosen}，所以这一档现在改不进去——` +
      "写的时候引擎会拒收并把版本号留在原处，下拉菜单只列名单里的那些。出路是在这里选回 " +
      names.join("、") + " 中的一档。"
    );
  }
  if ((chosen ?? foldDefault(published)) === foldDefault(published)) {
    return (
      "折那九个数之前，先把存储值按容器那一格本来的意思抬进线性光（BT.709 的分段曲线），" +
      "折完再按同一条落回来；导出那张立方体也是这一条。这与 1.161 之前的做法逐字节相同。" +
      "要留意调色链里那个「rec709」曲线节点用的是纯幂 2.4——同一个名字两条曲线，所以下面那一格" +
      "把「按哪一条折」交给你声明，引擎不替这一幅像素猜它是谁编的。"
    );
  }
  return (
    "折那九个数之前，按你选的这一档把存储值抬进线性光，折完再按同一条落回信号；" +
    "预览那两级表与导出那张立方体用的是同一档（由引擎算，界面一份都不抄）。这一档该选谁，" +
    "问的是「画面上那些存储值实际是哪条曲线编出来的」：本机编码器把容器那一格写下去时，" +
    "实际用的就是纯幂 2.4；按标准那一格的本意读它才是分段曲线。配对与配错差多少，本轮由 " +
    "tests/foldcurve_check.py 在同一批格子上两个方向都量过，那两个数写在 README 那一行。"
  );
}
