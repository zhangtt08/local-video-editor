/**
 * 1.227 的壳层检查：全应用不许再有浏览器原生的那一只「选择文件」控件。
 *
 * 弹层里那一行原生 input（`选择文件 / 未选择文件`）是 1.227 把「导入 SRT 字幕」那扇弹层
 * 第一次扫进门禁时量到的：它是整个界面里唯一一处没被刻度管过的控件——字号、圆角、颜色
 * 全是浏览器默认的，夹在按 `--r-*` 排的弹层里。另外两处 import（LUT、工程包）走的是
 * 「hidden input + 应用自己的按钮」，这一档把那条规矩钉住：
 * ① 每一个 `type="file"` 的 input 都必须带 `hidden`；
 * ② 字幕那一扇必须有一颗能点的按钮，且它点的是那一只被藏起来的 input（不是第二份状态）。
 */
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync);
  assert.ok(found, `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};

const sources = ["views/Assets.tsx", "views/GradeFields.tsx", "views/Home.tsx"]
  .map((name) => ({ name, text: read("desktop/src/" + name) }));

for (const file of sources) {
  // 按**整个标签**判，不按行：JSX 的属性常换行写（Home.tsx 的 `type="file"` 与 `hidden`
  // 就在两行上），逐行认会把合规的写法报成违规。
  for (const tag of file.text.match(/<input\b[^>]*>/g) ?? []) {
    if (tag.includes('type="file"')) {
      assert.ok(/\bhidden\b/.test(tag), `${file.name} 里有一只没藏起来的原生 file input：${tag.replace(/\s+/g, " ").slice(0, 90)}`);
    }
  }
}

const assets = sources.find((file) => file.name === "views/Assets.tsx")!.text;
assert.ok(assets.includes('aria-label="选择 SRT 文件"'), "字幕那一只 input 不见了——换法不能把入口换没");
assert.ok(assets.includes("captionFile.current?.click()"),
  "字幕的按钮没去点那一只被藏起来的 input（那就是第二份状态，点了也不会开选择框）");
assert.ok(/className="btn"[^<]*>\s*选择字幕文件\s*</.test(assets),
  "字幕那一行没有应用自己的那颗按钮（`.btn` + 中文动词），弹层里就还是浏览器的默认控件");

console.log("PASS: 三只 file input 全是 hidden + 样式按钮，字幕那一扇的按钮真的去点那一只");
