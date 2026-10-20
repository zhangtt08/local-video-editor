// 1.230：轨道比时间线高的时候，人要看得见、够得着。
//
// 这一条是演示那条工程量出来的：卡片加高到 68px 之后，四条轨在默认时间线高度里放不下，
// 第 4 条（配乐）落在折线以下——滚动条在，可是「选中了却看不见它」「加了一条却没出现」
// 这两件事都只能靠人自己去猜。现在三处各有一句话：
//   ① 选中一段 → 把它所在的那一行滚进视野（横向一个像素都不动）；
//   ② 加一条轨 → 滚到最后一行；
//   ③ 还有轨在折线以下 → 一块「下面还有 N 条轨」的胶囊，点它滚到底。
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

declare const REPO_ROOT: string;

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync) ?? resolve(REPO_ROOT, parts[0]);
  assert.ok(existsSync(found!), `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};

const timeline = read("desktop/src/views/Timeline.tsx", "../../desktop/src/views/Timeline.tsx");
const css = read("desktop/src/styles.css", "../../desktop/src/styles.css");

// ① 选中那一段 → 它所在的那一行
const reveal = /  useEffect\(\(\) => \{\n    const scroll = scrollRef\.current;\n    const clip = project && app\.selectedClips\.length[\s\S]*?\n  \}, \[app\.selectedClips, project\?\.id\]\);/.exec(timeline);
assert.ok(reveal, "选中片段之后没有人把那一行带进视野");
assert.match(reveal[0], /project!\.tracks\.findIndex\(\(track\) => track\.id === clip\.track_id\)/,
  "没有按片段自己那条轨去找行");
assert.match(reveal[0], /\.tl-row:not\(\.ruler-row\)/, "行要按轨道行取，标尺那一行不算");
assert.match(reveal[0], /scrollIntoView\(\{ block: "nearest", inline: "nearest" \}\)/, "没滚到最近的那一处");
assert.match(reveal[0], /const left = scroll\.scrollLeft;/, "滚动前没记下横向位置");
assert.match(reveal[0], /scroll\.scrollLeft = left;/, "横向被 scrollIntoView 改了——播放头那一格会被甩出屏幕");

// ② 加一条轨 → 最后一行
const added = /  const trackCount = useRef\(project\?\.tracks\.length \?\? 0\);[\s\S]*?\n  \}, \[project\?\.tracks\.length\]\);/.exec(timeline);
assert.ok(added, "加轨之后没有人滚到新那一行");
assert.match(added![0], /count > trackCount\.current/, "加轨的判断不在（比较轨数的那一刻）");
assert.match(added![0], /rows\[rows\.length - 1\]\?\.scrollIntoView/, "滚的不是最后一行");
assert.match(added![0], /scroll\.scrollLeft = left;/, "加轨这一路也会把横向位置带走");

// ③ 还有几条轨：数的是没整行露出来的轨道行，点一下滚到底
assert.match(timeline, /const \[below, setBelow\] = useState\(0\);/, "没有「还有几条轨」这个数");
const measure = /const measure = \(\) => \{\n      setView[\s\S]*?setBelow\(lower\);/.exec(timeline);
assert.ok(measure, "那条测量不见了");
assert.match(measure![0], /\.tl-row:not\(\.ruler-row\)/, "数的是轨道行");
assert.match(measure![0], /const rect = row\.getBoundingClientRect\(\);/, "每一行只量一次矩形");
assert.match(measure![0], /if \(rect\.bottom > box\.bottom \+ 1\) lower \+= 1;/, "判的是「整行露出来没有」");
assert.match(timeline, /下面还有 \{below\} 条轨/, "画面上没有那枚牌子");
// 反方向也要有：滚到底以后，上面那几条轨同样会消失。
assert.match(timeline, /const \[above, setAbove\] = useState\(0\);/, "没有「上面还有几条轨」这个数");
assert.match(measure![0], /if \(rect\.top < box\.top - 1\) upper \+= 1;/, "没有数折线以上的轨道行");
assert.match(timeline, /上面还有 \{above\} 条轨/, "画面上没有「上面还有」那枚牌子");
assert.match(timeline, /scrollTo\(\{ top: 0 \}\)/, "上面那枚牌子点了不回顶");
assert.match(timeline, /scrollTo\(\{ top: scrollRef\.current\.scrollHeight \}\)/, "那颗牌子点了不滚到底");
assert.match(css, /\.tl-more-tracks \{[^}]*border-radius: var\(--r-pill\)/, "那枚牌子不是刻度里的胶囊");

console.log("PASS: 选中就露出那一行（横向不动）、加轨滚到最后一行、折线以下还有几条轨有名字且点得动");
