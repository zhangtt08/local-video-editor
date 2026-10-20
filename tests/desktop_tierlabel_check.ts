// 1.220：下拉那一行只许写名字，整句挂同一颗控件的悬停；量具必须看得见这件事。
//
// 这一档存在的缺陷是量出来的：发布包 1480×900 那一屏上，「Rec.709（电视与浏览器的默认）」要 201 px、
// 「BT.709 分段曲线（容器那一格本来的意思）」要 292 px，而那一格只有 215 px——字被竖切在括号中间。
// 断的是三件事：短名只有一处算法、界面画的就是那一处、量具数得出现场。
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

declare const REPO_ROOT: string;

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync) ?? resolve(REPO_ROOT, parts[0]);
  assert.ok(existsSync(found!), `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};

const space = read("desktop/src/workingSpace.ts", "../../desktop/src/workingSpace.ts");
const inspector = read("desktop/src/views/Inspector.tsx", "../../desktop/src/views/Inspector.tsx");
const css = read("desktop/src/styles.css", "../../desktop/src/styles.css");
const probe = read("scripts/ui_shape_probe.js", "../../scripts/ui_shape_probe.js");
const gate = read("tests/ui_shape_check.py", "../../tests/ui_shape_check.py");

// ① 短名只有一处：括号前那一段就是名字，两只下拉都问它
assert.match(space, /export function shortLabel\(label: string\): string \{\s*return label\.split\("（"\)\[0\];\s*\}/,
  "短名那一处要么没有，要么不再按全角括号切");
const uses = (space.match(/short: shortLabel\(/g) ?? []).length;
assert.equal(uses, 2, `两只下拉的短名要出自同一处（现在量到 ${uses} 处）`);

// ② 界面画的是短名，整句挂 option 与 select 的悬停上——两处都要在，缺一个就没人说整句。
// 数的是**整对**出现的次数：只在一处写对、另一处忘了，这一档就要红。
const optionRows = inspector.match(/<option key=\{choice\.value\} value=\{choice\.value\} title=\{choice\.label\}>\{choice\.short\}<\/option>/g) ?? [];
assert.equal(optionRows.length, 2, `两只下拉都要「画短名 + option 挂整句」（现在量到 ${optionRows.length} 处）`);
const selectTitles = inspector.match(/title=\{(?:working|fold)Choices\(app\.caps[^\n]*\?\.label \?\? ""\}/g) ?? [];
assert.equal(selectTitles.length, 2, `那一颗 select 自己也要挂整句的悬停，切了才有人说得清它是什么（现在 ${selectTitles.length} 处）`);
assert.equal((inspector.match(/\{choice\.label\}<\/option>/g) ?? []).length, 0,
  "还有一排在下拉里直接画整句——那一行会被竖切");

// ③ 那一格学着自己让位：竖切换成省略号，标签不许折成两行
assert.match(css, /\.ps-working select\s*\{[^}]*text-overflow: ellipsis/, "那一格放不下时要给省略号，不许把字竖切");
assert.match(css, /\.ps-working select\s*\{[^}]*white-space: nowrap/, "select 里的字不许折行");
assert.match(css, /\.proxy-ctl\s*\{[^}]*white-space: nowrap/, "「代理」那一枚标签不许折成两行（发布包里量到的代/理）");

// ④ 量具数得出现场：按选中的那一行实际要多宽，且切了又没有悬停就算缺陷
assert.match(probe, /tagName\.toLowerCase\(\) === "select"/, "扫描不再看下拉，被切那一类就看不见");
assert.match(probe, /needs > el\.clientWidth/, "判被切要比的是那一格自己的宽度");
assert.match(probe, /has_title: Boolean\(el\.title\)/, "被切的那一行有没有整句的悬停，要一起交回门禁");
assert.match(probe, /truncated_select_count/, "数出来的那几行要有名字，门禁才数得清");
assert.match(gate, /下拉那一行被切又没有悬停可看整句/, "门禁不再把「切了且没人说」当缺陷");
assert.match(gate, /truncated_selects/, "门禁读的是量具那一份名单，不是自己再数一遍");

// ⑤ 展开那几段也算一屏：合着的 details 里那一行根本没画出来，量不到就等于没管
assert.match(read("scripts/ui_shape_sweep.cjs", "../../scripts/ui_shape_sweep.cjs"), /open-details/, "扫描没有「把每一段真展开再量」这一档");
assert.match(read("tests/ui_shape_check.py", "../../tests/ui_shape_check.py"), /"--open-details", "1"/, "门禁没把展开那一屏要进来");
// 中心点判在不在屏幕上：矩形会撒谎，滚动线以下那一枚只是要往下滚一段
assert.match(probe, /cy <= box\.top \+ 2 \|\| cy >= box\.bottom - 2/, "判可见还在用整块矩形，滚动线以下那一枚会被记成点不到");

console.log("PASS: 下拉只画短名、整句挂在同一颗控件的悬停、那一格用省略号、「代理」不折行、扫描按选中的那一行量被切、展开那几段也进门禁、可见性按中心点判");
