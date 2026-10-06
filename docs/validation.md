# 架构复核与验证记录

## 1.8.0 发布验证（2026-10-05）

修复最新 1.7 审计中的分离声音、链接滚动锁轨/源时钟、工程包原子恢复与去重、旧文字回执、依赖锁、真实合成示波器问题。Ruff 检查与 29 文件格式检查、HTTP/MCP/重启综合自检和 13 项专项 Python 检查、2 项桌面逻辑检查、TypeScript 与 Vite/esbuild 构建通过。隔离目录 npm ci 398 包，与锁文件版本一致，生成文件与最终 ASAR 的 3 个 renderer / 2 个 shell 文件逐字节一致；142 个引擎资源与 staging 一致。

最终包内引擎冷启动 651 ms；真实导出 10 秒 H.264 960×540 + AAC 48 kHz，声画各 10 秒，mean_volume=-24.1 dB；包内工程包往返/重试及上层蓝色合成 PNG 验证通过。最终 renderer 在内嵌浏览器验证工程包选择→导入→自动打开完整 r0 工程，音画播放、示波器与 1040×660 / 1280×720 面板边界。未验证 Windows 安装向导、原生窗口/文件对话框和扬声器回环录音；包未签名。

详见本次交付记录 `C:/Users/Administrator/Documents/Codex/2026-10-04/du/outputs/AgentCut-1.8-交付记录.md`。下面保留早期架构底座验证记录，不代表当前新增功能的完整范围。

日期：2026-10-03。结论：可作为后续模块开发的架构底座交付；完整专业剪辑产品尚未完成。

## 实际运行结果

环境：Windows 11、Python 3.12.4。锁定验证版本：FastAPI 0.142.2、Pydantic 2.13.5、MCP 1.30.0、HTTPX 0.28.1、Uvicorn 0.54.0、Ruff 0.16.10。

```text
uv run ruff check src tests examples
All checks passed!

uv run ruff format --check src tests examples
9 files already formatted

uv run python tests/self_check.py
PASS: clocks, images/audio, HTTP, atomic edits, retries, concurrency, history, MCP stdio, example, API restart
```

自检启动真实 API 进程，由官方 MCP ClientSession 通过 stdio 启动 MCP 子进程并调用工具。
验收包含认证/Host 检查、严格 JSON 校验、源范围、时间对齐、批失败回滚、dry-run、重复请求、同版本竞争、并发同 id 去重、历史恢复、MCP 错误与 structuredContent、示例工作流，以及 API 真正重启后重放旧请求。

## ARCH-PRIMARY

以下 partial 指当前故意保留的轻量依赖，并非未修复的数据正确性缺陷。

```text
BASELINE | contracts + timeline | expected: 版本化契约与可测试剪辑规则 | observed: Pydantic 契约、纯 reducer、最终时间线检查，无 I/O | fit: partial | patterns: [P-DTO, P-HO] | violations: [] | suggestion: 保持共享 schema，不复制模型
BASELINE | projects | expected: 原子状态与请求去重的唯一门面 | observed: SQLite 事务中保存项目、历史和回执，应用与持久化合并 | fit: partial | patterns: [P-UC, P-GW] | violations: [] | suggestion: 出现第二种存储时再提取 port
BASELINE | HTTP | expected: 认证、校验、委派 | observed: 薄 controller 调用 ProjectStore，不另写剪辑规则 | fit: align | patterns: [P-CTRL, P-ADP] | violations: [] | suggestion: 新能力复用同一提交路径
BASELINE | MCP | expected: 官方协议适配并共用 HTTP 权威状态 | observed: 8 工具、输出 schema、结构化结果、准确更新提示 | fit: align | patterns: [P-ADP] | violations: [] | suggestion: 保留真实 stdio 验收
BASELINE | main | expected: 配置和组装入口 | observed: 回环地址启动、环境配置、选择传输 | fit: align | patterns: [P-CR] | violations: [] | suggestion: 媒体规则放入自己的模块

CODEBASELINE | contracts/timeline | responsibility: 合法确定性剪辑 | observed: 类型、范围、时钟与重叠检查，输入深拷贝 | fit: clean | practices: [CC-DATA, CC-FLOW, CC-ERROR] | violations: [] | next: 新命令补对应最小检查
CODEBASELINE | projects | responsibility: 可恢复原子提交 | observed: 回执先于 revision 校验、同事务落盘与失败回滚 | fit: clean | practices: [CC-FLOW, CC-ERROR] | violations: [] | next: 真媒体阶段补崩溃注入
CODEBASELINE | HTTP/MCP/main | responsibility: 一致传输与启动 | observed: 共享契约、真实协议验收、无重复业务逻辑 | fit: clean | practices: [CC-BOUNDARY, CC-ERROR] | violations: [] | next: 桌面入口沿用 HTTP

ALGBASELINE | validate_timeline | problem: 精确范围与同轨不重叠 | data: 最多 20000 片段、128 轨道 | choice: map 查引用、分轨排序、相邻比较 | complexity: O(A + T + C log C); O(T + C) 辅助空间 | preconditions: 合法模型与可整除时钟 | exactness: exact | fit: sound | practices: [ALG-PROBLEM, ALG-PRECOND] | violations: [] | next: 测量大工程后再索引化
DATABASELINE | mutate | authority: SQLite 项目快照 | consistency: 序列化写入和乐观 revision | transaction: 项目/历史/回执一起提交 | replication/partition: 单机库 | delivery/order: 持久回执重放、revision 单调 | recovery: 新 revision 恢复内容、重启回执验证 | fit: conditional | practices: [DATA-SOT, DATA-TXN] | violations: [] | next: 后续补备份工具和故障注入
APIBASELINE | v1 | authority: contracts.py | consumers: [HTTP, MCP, 未来桌面] | compatibility: 明确版本与严格请求 | errors: 领域 code 和冲突状态 | evolution: schema/回执迁移约定 | fit: aligned | next: 新功能同时更新能力与验收
SECBASELINE | local entrypoints | trust: 回环 HTTP 与受控 stdio | identity: 同一随机 Bearer Token | data: 不读取不可信素材 reference | fit: conditional | next: 媒体导入补文件边界，远程访问另行设计
DOCBASELINE | docs | audience: 接续开发的 Agent 与维护者 | observed: 数据模型、调用链、ADR、范围和任务书与代码一致 | fit: aligned | next: 模块实现后同步文档与能力
ENGBASELINE | module handoff | owner: 契约协调者与模块 Agent | consumers/dependencies: [素材→渲染, 桌面→HTTP, 效果→RenderPlan] | coordination: 共享文件统一合并 | cognitive-load: 可单独领取任务与验收 | delivery/operations: 统一自检入口 | fit: aligned | next: 按依赖顺序推进
```

## ARCH-ADVERSARY

独立复核 Agent 没有修改代码，检查并实际执行了时钟、图片分割、reducer 输入不变性、缺失源错误，以及 MCP schema、结果与注解。

- 初始时钟对 96 kHz 不可整除：已统一为 70,560,000，并增加采样时钟验证。
- 图片分割后的源入点：已保持两半为 0，并通过真实接口验收。
- 不存在素材时分割：已返回 MISSING_REFERENCE 和 command_index，事务回滚。
- MCP 输出未生成 structuredContent：已使用 Project/MutationResult 与带类型的 dict，8 工具均有输出 schema。
- edit/restore 的 destructiveHint：已设为 true；create 保持 false，并由真实协议检查。
- “完全无框架领域核心”表述：拒绝该说法，文档明确 Pydantic 依赖及 SQLite 门面的部分边界。
- “现在就必须增加 repository 接口和双份模型”：不采纳，目前无第二种存储实现。
- 源时间戳是否应对齐序列：已明确源时钟与序列不同，具体解码/重采样规则由后续媒体模块负责。

复核修正后无未解决的实质缺陷；没有把待开发的渲染和界面当作现有能力。

## ARCH-SYNTH

```text
VALIDATION | agents: [ARCH-PRIMARY, ARCH-ADVERSARY, ARCH-SYNTH] | agreement: high | unresolved: 0 | ready: yes
```

ready 仅针对本次架构底座。尚未验证真实素材导入、渲染质量/性能、GPU 路径、桌面打包、其他操作系统、备份恢复或运行中崩溃注入。

## 对接时使用的官方资料

- MCP v1 接口与显式版本锁定：[官方 Python SDK 文档](https://py.sdk.modelcontextprotocol.io/v1/)。
- 工具 schema、结果与行为提示：[MCP 工具规范](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)。
- API 生命周期初始化：[FastAPI Lifespan](https://fastapi.tiangolo.com/advanced/events/)。
- 后续数据库备份方式：[Python sqlite3 backup API](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup)。
