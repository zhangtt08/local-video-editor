/**
 * 1.209 的壳层检查：面板上那一行只说「这一格现在怎么了」，长段说明必须在帮助里。
 *
 * 为什么单独一档：圆润化做了六档，管的都是字号、圆角与颜色；**话的长度**没人管，于是检查器那一列
 * 长出了一段三四行、比正文小一号、还用着最暗一档字色的灰字（最长的一段 450 多个汉字）——用户说的
 * 「拒绝用小字堆信息」，本体就是这里。把长度钉进门禁才有意义：今天收成一行的那一格，明天有人
 * 顺手再补两句就又回去了，而所有旧断言都不会红。
 * 判据是量出来的，不是拍的：本轮把两个视图里每一条可见说明的静态汉字数都数了一遍，
 * 40 字是收完之后最长那一条的数（含动态插值之外的所有字）。
 */
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

declare const REPO_ROOT: string;

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync) ?? resolve(REPO_ROOT, parts[0]);
  assert.ok(existsSync(found!), `找不到源文件：${parts[0]}`);
  return readFileSync(found!, "utf8");
};

const views = ["desktop/src/views/Inspector.tsx", "desktop/src/views/GradeFields.tsx"];
const LIMIT = 40;
const cjk = (text: string) => (text.match(/[\u3400-\u9fff]/g) ?? []).length;

const long: string[] = [];
let counted = 0;
for (const rel of views) {
  const source = read(rel, `../../${rel}`);
  for (const hit of source.matchAll(/<p className="hint">([\s\S]*?)<\/p>/g)) {
    // 花括号里的是表达式（数值、条件），不是给人读的那行字；只数写死的汉字。
    const visible = hit[1].replace(/\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}/g, "").replace(/<[^>]+>/g, "");
    const size = cjk(visible);
    counted += 1;
    if (size > LIMIT) {
      const line = source.slice(0, hit.index).split(/\r?\n/).length;
      long.push(`${rel.split("/").pop()}:${line} 那一条有 ${size} 个字`);
    }
  }
}
assert.ok(counted >= 24, `只读到 ${counted} 条面板说明，量具没摆开（这一档就没法证明长度被管住了）`);
assert.deepEqual(long, [], `有 ${long.length} 条面板说明超过 ${LIMIT} 个字：${long.join("；")}`);

// 收下来的字必须还在——搬去帮助，不是删掉。名字对不上就红，谁搬空了谁负责。
const MOVED_NAMES = ["检查器·那几行为什么只写一句", "调色·节点", "合成·第二路画面", "时间线·划动与滑移", "检查器·音画链接与组合", "合成·叠一层原图", "检查器·文字样式", "调色·执行顺序与并联"];
const help = read("desktop/src/views/Help.tsx", "../../desktop/src/views/Help.tsx");
for (const name of MOVED_NAMES) {
  assert.ok(help.includes(`{ name: "${name}"`), `帮助「区域说明」里没有「${name}」这一条——长段是被删了，不是被搬走的`);
}
const moved = ["colorchannelmixer", "feComponentTransfer", "LAYER_POSITION", "LAYER_KEY_RANGE", "J/L cut", "mask_rotation_schedule_segments"];
for (const needle of moved) {
  assert.ok(help.includes(needle), `「${needle}」这条判断原来写在面板上，现在帮助里也找不到它了`);
}

// 明说的差别不许跟着长段一起被搬走：这三句必须还在面板上看得见。
const grade = read("desktop/src/views/GradeFields.tsx", "../../desktop/src/views/GradeFields.tsx");
const inspector = read("desktop/src/views/Inspector.tsx", "../../desktop/src/views/Inspector.tsx");
assert.ok(grade.includes("预览不生效、导出生效"), "跨通道那张表的「预览不生效、导出生效」被搬走了——那是 1.143/1.193 明说的差别，必须留在面板上");
assert.ok(grade.includes("共用同一张窗表"), "层针「位置、大小与淡共用同一张窗表」这句被搬走了——它是那一层能不能打点的正面回答");
assert.ok(inspector.includes("切口不算一条边"), "淡那句「切口不算一条边」被搬走了——那是分割之后为什么不会凭空淡一下的答案");

// 那一行走的是正文那一档，不是最暗那一档：小字 + 灰到看不清才是「堆信息」。
const css = read("desktop/src/styles.css", "../../desktop/src/styles.css");
const hintRule = /\n\.hint \{([^}]*)\}/.exec(css);
assert.ok(hintRule, "读不到 .hint 那一条规则");
assert.match(hintRule![1], /font-size: var\(--fs-body\)/, "面板说明还停在比正文小一号的那一档");
assert.match(hintRule![1], /color: var\(--ink-2\)/, "面板说明还在用最暗那一档字色");

console.log(
  `desktop_prose_check: 面板上 ${counted} 条说明最长 ${LIMIT} 字以内（收下来的长段都在帮助那 ${MOVED_NAMES.length} 条里），` +
    `.hint 走 --fs-body / --ink-2，三句「明说的差别」仍留在面板上`
);
