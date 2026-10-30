# 🎬 AgentCut

<p align="center">
  <b>专为普通人和 AI 设计的本地视频剪辑神器</b><br>
  剪映般流畅的可视化多轨桌面端 · 原生支持 MCP 协议与 AI 自动化调用 · 纯本地无损渲染
</p>

<p align="center">
  <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License" />
  <img src="https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6?logo=windows&logoColor=white" alt="Platform" />
  <img src="https://img.shields.io/badge/Core-Python%20%2B%20FFmpeg-3776AB?logo=python&logoColor=white" alt="Python FFmpeg" />
  <img src="https://img.shields.io/badge/UI-Modern%20Timeline%20GUI-61DAFB?logo=react&logoColor=white" alt="UI" />
  <img src="https://img.shields.io/badge/AI%20Agent-MCP%20Ready-orange.svg" alt="MCP" />
  <img src="https://img.shields.io/badge/100%25-本地离线隐私-brightgreen" alt="Offline" />
</p>

<p align="center">
  <a href="https://github.com/zhangtt08/local-video-editor/releases/latest"><b>🚀 [点击立即下载 Windows 绿色免安装版]</b></a>
</p>

---

## ⚡ 3 秒了解 AgentCut

你是否想过：
- **既能像用剪映一样**，在漂亮的可视化时间线上拖拽素材、裁切视频、加关键帧、实时播放预览；
- **又能让 AI Agent（Claude Code / Cursor / 自定义智能体）**，通过一行指令在后台全自动调 API 完成精准剪辑、音画合成与字幕对齐？

**AgentCut 打破了两者界限！**  
普通人在界面上的每一次点击，与 AI Agent 在后台调用的每一条指令，**操作的是完全相同的时间线与工程文件**。没有两套规则，没有黑盒，所见即所得。

---

## 🎯 为什么选择 AgentCut？

| 痛点场景 | 传统软件（剪映 / PR） | 纯代码库（MoviePy / FFmpeg CLI） | AgentCut ✨ |
| :--- | :--- | :--- | :--- |
| **AI 自动化接入** | ❌ 封闭私有协议，AI 无法控制 | ⚠️ 虽可写脚本，但没有时间线可视化 | ✅ **原生开放 HTTP & MCP 协议** |
| **可视化交互** | ✅ 界面友好，但只能靠纯人工肝 | ❌ 零界面，调关键帧全靠盲猜 | ✅ **现代化多轨界面 + 实时预览** |
| **数据与隐私** | ⚠️ 部分需登录/素材上传云端 | ✅ 本地运行 | ✅ **100% 本地无损，绝不上传** |
| **批量短视频生产** | ❌ 极度消耗人力与时间 | ⚠️ 代码门槛高，音画极易不同步 | ✅ **人机协同：AI 粗剪，人工微调** |

---

## ✨ 核心特性

- 🎞️ **多轨时间线与所见即所得**：支持视频轨、音频轨、特效轨自由叠加，支持缩放、吸附、拖拽裁切与实时平滑播放。
- 📐 **专业关键帧动画系统**：位置、缩放、旋转、不透明度、音量全参数关键帧支持，具备平滑缓动曲线。
- 🛡️ **原子事务与安全快照**：工程历史版本只增不退，支持一键撤销、重做与快照回滚，绝不损坏原工程。
- 🔊 **广播级响度对齐（EBU R128）**：一键智能闪避（Ducking）、背景音乐人声避让，告别人声音量忽大忽小。
- ⚡ **本地极速渲染引擎**：基于深度优化的 Python + FFmpeg 双核驱动，支持硬件级极速导出。
- 🤖 **原生 AI MCP 协议**：开放 40+ 个原子级剪辑工具，Cursor、Claude Code 或自主智能体一键接入。

---

## 📥 快速下载与使用

### 方式一：下载桌面安装包（推荐，开箱即用）
1. 前往 **[Releases 页面](https://github.com/zhangtt08/local-video-editor/releases/latest)** 下载最新的 `AgentCut.exe` 便携版；
2. 双击直接运行（内置运行引擎与 FFmpeg，免装 Python、免配环境变量）；
3. 拖入视频素材即可开启丝滑剪辑！

### 方式二：开发者源码运行
需要 Python 3.11+ 与 Node.js 18+：
```bash
# 1. 克隆仓库
git clone https://github.com/zhangtt08/local-video-editor.git
cd local-video-editor

# 2. 安装 Python 核心依赖
pip install -e .

# 3. 安装前端桌面依赖并启动
cd desktop
npm install
npm run dev
```

---

## 🤖 让 AI 帮你剪视频（MCP 协议接入）

AgentCut 内置面向 AI 智能体的 MCP（Model Context Protocol）标准服务：

```bash
# 启动面向 Agent 的本地服务（默认端口 8792）
python -m agentcut.server
```

在 **Claude Code**、**Cursor** 或 **Antigravity** 中接入后，你可以直接对 AI 下达日常指令：
- *"把视频前 5 秒裁掉，并在第 10 秒加入画面放大特效"*
- *"提取当前视频的人声音量，并在背景音轨加入淡入淡出"*
- *"批量把 assets 文件夹里的 10 条素材按解说脚本自动合成成片"*

---

## 📄 架构与历史开发凭证
- 详细 API 接口文档：[`docs/api.md`](docs/api.md)
- 系统架构与决策日志：[`docs/architecture.md`](docs/architecture.md)
- 历史工程与端到端交付检验台账：[`docs/VERIFICATION_LEDGER.md`](docs/VERIFICATION_LEDGER.md)

---

## ⭐ 支持与致谢

如果 AgentCut 让你感受到了人机协同剪辑的便捷与乐趣，请给本项目点一个 **Star ⭐**！你的支持是保持持续开源迭代的最大动力！

## 📄 开源许可证
本项目基于 [MIT License](LICENSE) 协议开源，完全免费。
