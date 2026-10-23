/**
 * 3D 立方表在浏览器里的那一路：一块 WebGL2 画布，整条调色链按顺序走一遍。
 *
 * 为什么是画布而不是再加一个滤镜原语：`feComponentTransfer` 每通道一张表、`feColorMatrix`
 * 一次 3×3，都是「只看自己这一格」的函数；`lut3d` 的取值要看三路通道拼出来的那个格子，
 * SVG 滤镜里没有这种原语（1.103 起这一级就只在导出里生效）。WebGL2 有 3D 纹理，而且导出侧
 * `lut3d=file=…:interp=tetrahedral` 用的就是四面体插值——这一档照着同一张表、同一档插值写，
 * 两端读的是同一批格点。
 *
 * 这条链里还有曝光／对比／饱和（`clip.color` 那三个数）：它们由引擎在清单里交成
 * `color_basics`，画布之外一格都不许再乘（CSS 那边已经按 `webgl` 把滤镜串清空）。
 */

import type { ChromaRow, GradeTables } from "./engine";

const VERTEX = `#version 300 es
in vec2 aPos;
out vec2 vUv;
void main() {
  vUv = vec2(aPos.x * 0.5 + 0.5, 0.5 - aPos.y * 0.5);
  gl_Position = vec4(aPos, 0.0, 1.0);
}`;

/** CSS 的 brightness / contrast / saturate：与浏览器滤镜同一组系数（滤镜在 sRGB 上算）。 */
const COMMON = `
vec3 basics(vec3 c, vec3 k) {
  c = c * k.x;
  c = (c - 0.5) * k.y + 0.5;
  float l = dot(clamp(c, 0.0, 1.0), vec3(0.2126, 0.7152, 0.0722));
  return clamp(mix(vec3(l), c, k.z), 0.0, 1.0);
}
`;

/**
 * 四面体插值。六个四面体按三个小数部分的次序选，与 FFmpeg `lut3d` 的 `tetrahedral` 同一种分解
 * （顺序不同但等价——测试里会拿真导出逐点对，不是照着这句话信）。
 */
const TETRA = `
vec3 tetra(sampler3D cube, float size, vec3 c) {
  float span = size - 1.0;
  vec3 p = clamp(c, 0.0, 1.0) * span;
  vec3 base = floor(p);
  base = min(base, vec3(span - 1.0));
  vec3 f = p - base;
  ivec3 i = ivec3(base);
  vec3 c000 = texelFetch(cube, i, 0).rgb;
  vec3 c111 = texelFetch(cube, i + ivec3(1), 0).rgb;
  if (f.x >= f.y) {
    if (f.y >= f.z) {
      vec3 c100 = texelFetch(cube, i + ivec3(1, 0, 0), 0).rgb;
      vec3 c110 = texelFetch(cube, i + ivec3(1, 1, 0), 0).rgb;
      return c000 + f.x * (c100 - c000) + f.y * (c110 - c100) + f.z * (c111 - c110);
    }
    if (f.x >= f.z) {
      vec3 c100 = texelFetch(cube, i + ivec3(1, 0, 0), 0).rgb;
      vec3 c101 = texelFetch(cube, i + ivec3(1, 0, 1), 0).rgb;
      return c000 + f.x * (c100 - c000) + f.z * (c101 - c100) + f.y * (c111 - c101);
    }
    vec3 c001 = texelFetch(cube, i + ivec3(0, 0, 1), 0).rgb;
    vec3 c101 = texelFetch(cube, i + ivec3(1, 0, 1), 0).rgb;
    return c000 + f.z * (c001 - c000) + f.x * (c101 - c001) + f.y * (c111 - c101);
  }
  if (f.z >= f.y) {
    vec3 c001 = texelFetch(cube, i + ivec3(0, 0, 1), 0).rgb;
    vec3 c011 = texelFetch(cube, i + ivec3(0, 1, 1), 0).rgb;
    return c000 + f.z * (c001 - c000) + f.y * (c011 - c001) + f.x * (c111 - c011);
  }
  if (f.z >= f.x) {
    vec3 c010 = texelFetch(cube, i + ivec3(0, 1, 0), 0).rgb;
    vec3 c011 = texelFetch(cube, i + ivec3(0, 1, 1), 0).rgb;
    return c000 + f.y * (c010 - c000) + f.z * (c011 - c010) + f.x * (c111 - c011);
  }
  vec3 c010 = texelFetch(cube, i + ivec3(0, 1, 0), 0).rgb;
  vec3 c110 = texelFetch(cube, i + ivec3(1, 1, 0), 0).rgb;
  return c000 + f.y * (c010 - c000) + f.x * (c110 - c010) + f.z * (c111 - c110);
}
`;

type Stage = GradeTables["stages"][number];

function decodeCube(stage: Stage): Uint8Array | null {
  if (stage.type !== "lut3d" || !("cells_u8" in stage) || !stage.cells_u8) return null;
  const binary = atob(stage.cells_u8);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

/** 这一条链要不要走画布：只要有一个带格点的立方阶段就是。 */
export function gradeNeedsCanvas(grade?: GradeTables | null): boolean {
  if (!grade) return false;
  return grade.stages.some((stage) => gradeStageCube(stage) !== null);
}

/** 1.276：挂了色度键的那一段也走画布——CSS 的滤镜串里没有「按离键色多远决定透明度」这一支，
 *  而画布有。判断只在这一处，界面不许再问一遍「这一段有没有键」。 */
export function chromaNeedsCanvas(chroma?: ChromaRow | null): boolean {
  return chroma !== null && chroma !== undefined;
}

function gradeStageCube(stage: Stage): Uint8Array | null {
  return decodeCube(stage);
}

function shaderFor(stages: Stage[], chroma: boolean): string {
  const calls = stages
    .map((stage, index) => {
      if (stage.type === "lut") return `  c = table${index}(c);`;
      if (stage.type === "matrix") {
        // 引擎那九个数是**行主序**（r' = m0·r + m1·g + m2·b），GLSL 的 mat3 构造是列主序。
        const column = [stage.m[0], stage.m[3], stage.m[6], stage.m[1], stage.m[4], stage.m[7], stage.m[2], stage.m[5], stage.m[8]];
        return `  c = clamp(mat3(${column.join(", ")}) * c, 0.0, 1.0);`;
      }
      if (stage.type === "lut3d") return `  c = tetra(uCube${index}, ${stage.size}.0, c);`;
      return "";
    })
    .filter(Boolean)
    .join("\n");
  const helpers = stages
    .map((stage, index) => {
      if (stage.type !== "lut") return "";
      const rows = ["r", "g", "b"]
        .map((channel) => `  out.${channel} = texture(uLut${index}, vec2(clamp(c.${channel}, 0.0, 1.0), 0.5)).${channel};`)
        .join("\n");
      return `vec3 table${index}(vec3 c) {\n  vec3 out;\n${rows}\n  return out;\n}\n`;
    })
    .filter(Boolean)
    .join("\n");
  const uniforms = stages
    .map((stage, index) => {
      if (stage.type === "lut") return `uniform sampler2D uLut${index};`;
      if (stage.type === "lut3d") return `uniform sampler3D uCube${index};`;
      return "";
    })
    .filter(Boolean)
    .join("\n");
  // 1.276：色度键。判的是**原始那一帧**的颜色（`src.rgb * 255`，与导出那趟 `geq` 挂在调色
  // 之前同一条顺序），数全部由引擎折好下发（`low`/`high`/`width`），这里不减不乘。
  const keyUniforms = chroma
    ? "uniform vec3 uKey;\nuniform float uLow;\nuniform float uHigh;\nuniform float uWidth;\nuniform float uSoft;\nuniform float uInvert;\nuniform float uMatte;"
    : "";
  const keyStep = chroma
    ? `  float d = distance(src.rgb * 255.0, uKey);
  a = uSoft > 0.5 ? clamp((d - uLow) / uWidth, 0.0, 1.0) : step(uHigh, d);
  if (uInvert > 0.5) a = 1.0 - a;
  // 「看遮罩」只是这一档预览：AE 与达芬奇都拿它判断键抠得干不干净，导出里没有这一说。
  if (uMatte > 0.5) { fragColor = vec4(a, a, a, 1.0); return; }`
    : "";
  return `#version 300 es
precision highp float;
precision highp sampler2D;
precision highp sampler3D;
in vec2 vUv;
out vec4 fragColor;
uniform sampler2D uSrc;
uniform vec3 uBasics;
${uniforms}
${keyUniforms}
${COMMON}
${TETRA}
${helpers}
void main() {
  vec4 src = texture(uSrc, vUv);
  float a = 1.0;
${keyStep}
  vec3 c = basics(src.rgb, uBasics);
${calls}
  c = clamp(c, 0.0, 1.0);
  // 预乘交出去：那一块洞要让下面那一层露出来，浏览器按 c*a 与页面相合。
  fragColor = vec4(c * a, a);
}`;
}

type Built = {
  id: string;
  program: WebGLProgram;
  uniforms: Map<string, WebGLUniformLocation | null>;
  textures: WebGLTexture[];
  source: WebGLTexture;
};

type State = {
  gl: WebGL2RenderingContext;
  built: Built | null;
  buffer: WebGLBuffer;
};

const STATES = new WeakMap<HTMLCanvasElement, State>();

function compile(gl: WebGL2RenderingContext, kind: number, body: string): WebGLShader | null {
  const shader = gl.createShader(kind);
  if (!shader) return null;
  gl.shaderSource(shader, body);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    console.error("grade shader:", gl.getShaderInfoLog(shader));
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

function build(state: State, grade: GradeTables | null | undefined, chroma: ChromaRow | null): Built | null {
  const gl = state.gl;
  const stages = grade?.stages ?? [];
  const vertex = compile(gl, gl.VERTEX_SHADER, VERTEX);
  const fragment = compile(gl, gl.FRAGMENT_SHADER, shaderFor(stages, chroma !== null));
  if (!vertex || !fragment) return null;
  const program = gl.createProgram();
  if (!program) return null;
  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.bindAttribLocation(program, 0, "aPos");
  gl.linkProgram(program);
  gl.deleteShader(vertex);
  gl.deleteShader(fragment);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    console.error("grade program:", gl.getProgramInfoLog(program));
    gl.deleteProgram(program);
    return null;
  }
  gl.useProgram(program);
  const uniforms = new Map<string, WebGLUniformLocation | null>();
  const textures: WebGLTexture[] = [];
  stages.forEach((stage, index) => {
    if (stage.type === "lut") {
      const table = gl.createTexture();
      if (!table) return;
      gl.activeTexture(gl.TEXTURE0 + 1 + index);
      gl.bindTexture(gl.TEXTURE_2D, table);
      // 一张 256×1 的 RGBA：R 通道放红表、G 放绿表、B 放蓝表，三路共用一次上传。
      const data = new Uint8Array(256 * 4);
      for (let level = 0; level < 256; level += 1) {
        data[level * 4] = Math.round(stage.r[level] * 255);
        data[level * 4 + 1] = Math.round(stage.g[level] * 255);
        data[level * 4 + 2] = Math.round(stage.b[level] * 255);
        data[level * 4 + 3] = 255;
      }
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, 256, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, data);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      uniforms.set(`uLut${index}`, gl.getUniformLocation(program, `uLut${index}`));
      textures[index] = table;
      return;
    }
    if (stage.type === "lut3d") {
      const cells = decodeCube(stage);
      if (!cells) return;
      const cube = gl.createTexture();
      if (!cube) return;
      gl.activeTexture(gl.TEXTURE0 + 1 + index);
      gl.bindTexture(gl.TEXTURE_3D, cube);
      gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
      // 引擎交的是 RGB 三字节一格；这张纹理开 RGBA8（3D 纹理上各家实现最保守的一档），
      // 第四格补 255。红最快的顺序原样不动——它本来就是 3D 纹理 x 轴最快的顺序。
      const texels = stage.size ** 3;
      const rgba = new Uint8Array(texels * 4);
      for (let texel = 0; texel < texels; texel += 1) {
        rgba[texel * 4] = cells[texel * 3];
        rgba[texel * 4 + 1] = cells[texel * 3 + 1];
        rgba[texel * 4 + 2] = cells[texel * 3 + 2];
        rgba[texel * 4 + 3] = 255;
      }
      gl.texImage3D(gl.TEXTURE_3D, 0, gl.RGBA8, stage.size, stage.size, stage.size, 0, gl.RGBA, gl.UNSIGNED_BYTE, rgba);
      gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_R, gl.CLAMP_TO_EDGE);
      uniforms.set(`uCube${index}`, gl.getUniformLocation(program, `uCube${index}`));
      textures[index] = cube;
    }
  });
  uniforms.set("uSrc", gl.getUniformLocation(program, "uSrc"));
  uniforms.set("uBasics", gl.getUniformLocation(program, "uBasics"));
  gl.uniform1i(uniforms.get("uSrc") ?? null, 0);
  stages.forEach((stage, index) => {
    if (stage.type === "lut") gl.uniform1i(uniforms.get(`uLut${index}`) ?? null, 1 + index);
    else if (stage.type === "lut3d") gl.uniform1i(uniforms.get(`uCube${index}`) ?? null, 1 + index);
  });
  for (const name of ["uKey", "uLow", "uHigh", "uWidth", "uSoft", "uInvert", "uMatte"]) {
    uniforms.set(name, gl.getUniformLocation(program, name));
  }
  const source = gl.createTexture();
  if (source) {
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, source);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  }
  return { id: canvasKey(grade, chroma), program, uniforms, textures, source };
}

/** 程序缓存的那一把钥匙：同一条链换了键、或同一个键换了链，都得重编一次着色器。 */
function canvasKey(grade: GradeTables | null | undefined, chroma: ChromaRow | null): string {
  return `${grade?.id ?? "none"}${chroma ? "|key" : ""}`;
}

/**
 * 把这一帧画进画布。`source` 是当前那一路 `<video>`／`<img>`（已经解码好的那一帧）。
 * 返回 false 表示这个浏览器给不出 WebGL2——调用方据此显示「预览画不出」而不是留一块黑。
 */
export function paintGrade(
  target: HTMLCanvasElement,
  source: TexImageSource,
  grade: GradeTables | null | undefined,
  basics: number[],
  chroma: ChromaRow | null = null,
  matte = false,
): boolean {
  let state = STATES.get(target);
  if (!state) {
    // `preserveDrawingBuffer`：截图与读回（验收要逐点比预览与成片的像素）都发生在画完之后的
    // 另一个任务里，不保留这一帧就只能读到一块黑。预览这一块每秒最多六十次，这点代价买得值。
    // 1.276：`alpha: true` 不是可选项——色度键抠出来的那一块洞要让**下面那一层**露出来，
    // 缓冲没有 alpha 通道时画布永远是一块不透明的矩形（量过：洞画在着色器里，屏幕上仍是绿）。
    const gl = target.getContext("webgl2", {
      alpha: true, premultipliedAlpha: true, antialias: false, preserveDrawingBuffer: true,
    });
    if (!gl) return false;
    const buffer = gl.createBuffer();
    if (!buffer) return false;
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    state = { gl, built: null, buffer };
    STATES.set(target, state);
  }
  const gl = state.gl;
  const wanted = canvasKey(grade, chroma);
  if (!state.built || state.built.id !== wanted) {
    if (state.built) gl.deleteProgram(state.built.program);
    state.built = build(state, grade, chroma);
  }
  const built = state.built;
  if (!built || !built.source) return false;
  gl.viewport(0, 0, target.width, target.height);
  gl.useProgram(built.program);
  gl.activeTexture(gl.TEXTURE0);
  gl.bindTexture(gl.TEXTURE_2D, built.source);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, gl.RGBA, gl.UNSIGNED_BYTE, source);
  const [brightness, contrast, saturation] = basics;
  gl.uniform3f(built.uniforms.get("uBasics") ?? null, brightness ?? 1, contrast ?? 1, saturation ?? 1);
  if (chroma && built.uniforms.get("uKey")) {
    // 三个整数与那一段距离都是引擎算好的；这里只做一次 `uniform`，不换算、不夹、不四舍五入。
    const [red, green, blue] = chroma.color;
    gl.uniform3f(built.uniforms.get("uKey") ?? null, red, green, blue);
    gl.uniform1f(built.uniforms.get("uLow") ?? null, chroma.low);
    gl.uniform1f(built.uniforms.get("uHigh") ?? null, chroma.high);
    gl.uniform1f(built.uniforms.get("uWidth") ?? null, chroma.width);
    gl.uniform1f(built.uniforms.get("uSoft") ?? null, chroma.soft ? 1 : 0);
    gl.uniform1f(built.uniforms.get("uInvert") ?? null, chroma.inverted ? 1 : 0);
    gl.uniform1f(built.uniforms.get("uMatte") ?? null, matte ? 1 : 0);
  }
  gl.drawArrays(gl.TRIANGLES, 0, 3);
  return true;
}
