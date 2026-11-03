<div align="center">

<img src="assets/icon.png" alt="Llama CPP Launcher 图标" width="88" />

# 🦙 Llama CPP Launcher / Llama 启动器

**功能完整的 `llama-server` (llama.cpp) GUI 启动器 — 自带你的 llama.cpp 二进制。**

**235** 个 `llama-server` CLI 参数一屏全出 · 动态默认值检测 · 预设管理 · 实时日志解析 · 实时指标带 · 内置 GGUF 检查器

[![Version](https://img.shields.io/github/v/release/Mars-Albert/llama-cpp-launcher?label=version)](https://github.com/Mars-Albert/llama-cpp-launcher/releases/latest)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776ab)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.11-41cd52)](https://pypi.org/project/PyQt6/)
[![License: MIT](https://img.shields.io/badge/License-MIT-2ea44f)](LICENSE)
[![Platform](https://img.shields.io/badge/平台-Windows%20exe%20%7C%20任意系统%20(源码)-8a2be2)]()

**[⬇️ 下载最新版本](https://github.com/Mars-Albert/llama-cpp-launcher/releases/latest)** · **[📖 English README](README.md)** · [⭐ Star 本项目](https://github.com/Mars-Albert/llama-cpp-launcher)

</div>

---

<details>
<summary><b>📑 目录</b></summary>

- [为什么选择 Llama CPP Launcher？](#why)
- [软件截图](#screenshot)
- [快速开始](#quick-start)
- [功能详解](#features)
  - [双模式设计](#two-modes)
  - [高级模式 — 9 个标签页](#advanced-tabs)
  - [模型浏览器](#model-browser)
  - [实时日志解析](#log-parsing)
  - [实时指标带](#metrics-row)
  - [日志面板](#log-panel)
  - [预设管理](#presets)
  - [逐参数帮助](#param-help)
  - [GGUF 检查器](#gguf-inspector)
  - [服务生命周期](#server-lifecycle)
  - [布局与状态栏](#layout)
  - [窗口与界面](#window-ui)
  - [国际化与主题](#i18n-themes)
- [与其他工具对比](#comparison)
- [开发](#development)
- [许可证](#license)

</details>

---

<a id="why"></a>

## 💡 为什么选择 Llama CPP Launcher？

大多数 GUI 工具（Ollama、LM Studio 等）**内置固定版本的 llama.cpp**，且命令行对用户不可见。Llama CPP Launcher 走的是另一条路：它驱动的是*你自己*安装的 `llama-server`，一切行为可见可控。

| | Llama CPP Launcher | 内置后端的工具 |
|---|---|---|
| 升级 llama.cpp | ✅ 换个二进制文件，完事 | ❌ 等应用更新 |
| 自定义编译（CUDA / ROCm / Vulkan / Metal / SYCL） | ✅ 任意构建都能用 | ❌ 只能用内置版本 |
| 体验最新提交 | ✅ 今天编译，今天跑 | ❌ 等几周甚至几个月 |
| 回退版本 | ✅ 换回旧二进制文件 | ❌ 祈祷官方提供 |
| 应用实际执行的命令 | ✅ 始终可见，一键复制 | ❌ 黑盒 |

而且它会自动保持同步：

- **🔍 动态默认值检测** — 启动时运行 `llama-server --help`，解析*你的*二进制版本的真实默认值。不存在过时的硬编码，版本漂移还会通过 ⚠️ 指示器提示。
- **🗂️ 聊天模板自动发现** — 你的二进制内置的模板会自动出现在 UI 中。
- **🖥️ GPU 检测** — 通过 `--list-devices` 探测，在**状态栏**（版本号左侧）显示如 `检测到 2× GPU：RTX 5090 (32GB) + RTX 2080 (8GB)`（只展示，不自动填写，永远由你决定）。

**🪶 轻量且私密** — 约 16,000 行 Python，唯一运行时依赖是 PyQt6。无内置后端、无账号、无遥测、不联网上报，100% 本地运行。

<a id="screenshot"></a>

## 📸 软件截图

*高级模式（浅色主题，左）· 基础模式模型运行中（深色主题，右）— 运行时信息从服务端日志实时解析。*

<table>
  <tr>
    <td width="50%"><img src="cn_light.png" width="560" alt="高级模式（浅色主题）" /></td>
    <td width="50%"><img src="cn.png" width="560" alt="基础模式运行中（深色主题）" /></td>
  </tr>
</table>

> 🎭 截图是**渲染出来的，不是拍出来的**：`python tools/render_screenshots.py` 用真实 UI + 合成数据出图（显卡、模型、版本号、日志与各项数字都是编的），所以界面改版后重出图不会把任何人的机器发出去。要更新截图请用它，别改用真机截图。
> 图片为 2000×1175（即 1600×941 窗口在 125% 缩放下的原生像素），含卡片投影与透明圆角。

<a id="quick-start"></a>

## 🚀 快速开始

### 方式一：Windows exe（推荐）

1. 从 [Releases](https://github.com/Mars-Albert/llama-cpp-launcher/releases/latest) 下载 `LlamaCppLauncher.exe`，双击运行 — 无需安装 Python。
2. 安装 `llama-server`（如从 [ggml-org/llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases) 下载）。
3. 在应用中：**文件 → 设置 llama-server 路径…**，指向该二进制文件（或把它加入 `PATH` — 启动器会自动找到）。
4. 选模型，点 **启动**，打开 WebUI。搞定。

> ⚠️ Windows SmartScreen 可能警告未签名的可执行文件 — 点击 **更多信息 → 仍要运行** 即可。

### 方式二：从源码运行（任意系统）

```bash
git clone https://github.com/Mars-Albert/llama-cpp-launcher.git
cd llama-cpp-launcher

python -m venv venv
venv\Scripts\activate   # Windows   ·  source venv/bin/activate  # Linux/macOS
pip install -r requirements.txt

python main.py          # Windows 下也可双击 run.bat
```

<a id="features"></a>

## ✨ 功能详解

<a id="two-modes"></a>

### 🎭 双模式设计

| 基础模式 | 高级模式 |
|---|---|
| 模型 & mmproj 选择器（背后是模型浏览器） | **235 个参数**，9 个标签页 |
| 温度 / Top-P / Min-P / 重复惩罚滑块 + Top-K 数值框 | LoRA 适配器与缩放、控制向量、图像 Token 限制 |
| 上下文快捷按钮：Default → 4K → 262K | 模型来源：本地文件、**HF 仓库**、**URL**、**Docker 仓库** |
| GPU 层数 auto / all / 手动，host/port/并行数 | 投机解码（draft-mtp、ngram、lookup cache） |
| ⚡ 快捷开关（**可自定义**，设置 → 自定义快捷开关…）：FlashAttn、推理、分割模式、投机类型、草稿 Token 上限… | 完整服务端配置：SSL、CORS、slots、embedding/rerank、MCP |
| *几秒钟让模型跑起来* | *精细调节每一个细节* |

<a id="advanced-tabs"></a>

### 🎛️ 高级模式 — 9 个标签页

| 标签页 | 内容 |
|---|---|
| 🧠 模型 | 模型文件、别名、标签、HF/URL/Docker 来源、LoRA、控制向量、mmproj（视觉） |
| 📏 上下文 | 上下文大小、prompt 与 KV 缓存、RoPE / YaRN 缩放 |
| 🎲 采样 | 温度、top-k/p、min-p、惩罚项、语法与重复控制 |
| 🎮 GPU-性能 | 卸载、显存、CPU 线程、亲和性、优先级 |
| ⚡ 投机解码 | 草稿模型（draft-mtp）、ngram、lookup cache、草稿 Token 数 |
| 🌐 服务 | host/port、slots、并行、端点、SSL、CORS、embedding/rerank、router、Prometheus 指标 |
| 🤖 Agent/工具 | 工具调用、MCP 服务、agent 设置 |
| 💬 聊天-推理 | 聊天模板、推理模式、thinking budget |
| 🔧 高级 | 文本 I/O、日志、`extra_args` 万能出口 |

<a id="model-browser"></a>

### 📂 模型浏览器

- 🔎 后台线程扫描模型目录 — 界面永不卡顿
- 🏷️ 自动把 `.gguf` 文件分类为 **模型** / **多模态 (mmproj)**，并显示大小
- 📏 即时模型信息：大小、估算参数量、量化类型
- 🧾 **GGUF 快速元数据行**：当前选中模型的架构 + 最大上下文，只解析文件*头部*（几 MB，有缓存，后台线程执行）；当上下文设置超过模型上限时该行变**琥珀色**提示（启动后会被截断）
- 🔗 按名称自动匹配 mmproj 到对应模型
- 📁 扫描目录跨会话记忆；F5 重新扫描

<a id="log-parsing"></a>

### 📊 实时日志解析

`llama-server` 的每一行输出都会在被打印的同时解析（74 条规则，兼容新旧两种日志格式，含 v9174+ `srv` 前缀格式），提炼进 **运行时信息** 面板 — 8 大类、40+ 数据点：

| 类别 | 你看到的信息 |
|---|---|
| 🖥️ 硬件 | GPU 名称 / 计算能力 / 每卡总显存与空闲显存、CPU |
| 📦 模型 | 文件、模型名、量化类型、GGUF 版本 |
| 🏗️ 架构 | 参数量、层数、embed/FFN 维度、词表、张量精度分布 |
| ⚙️ 运行参数 | 训练 vs 运行上下文、batch/ubatch、slots、RoPE 频率、thinking 模式 |
| 💾 显存 | 卸载层数、模型/KV 缓存/计算缓冲、预计显存占用 |
| ⚡ 性能 | Flash attention、KV 统一、图节点数与分割数 |
| 🔧 系统 | 线程、OpenMP、repack |
| 👁️ 视觉 | 编码器状态、mmproj、图像分辨率、最小图像 Token |

面板**实时刷新** — 卸载层数在加载过程中逐步出现，缓冲大小在初始化时填充，服务端开始监听的那一刻状态立即切换为 **就绪**。

<a id="metrics-row"></a>

### 📟 实时指标带

标签页下方的那一行在**任何标签页**都常驻，显示模型跑起来时你真正会盯的数字：

| 组 | 读数 | 来源 |
|---|---|---|
| ⚡ 实时（每秒） | **Prefill** t/s · **Decode** t/s · **上下文**计量条 + % | `GET /slots` |
| 📈 累计（每 5 秒） | **输入** tokens · **缓存** · **输出** tokens · 缓存**命中**率 | `GET /metrics` |

- 上下文是一条细计量条，百分比**写在条里**：绿 → 70% 琥珀 → 90% 红
- 速度差值在本地计算，并在每次任务边界重新起算基线 —— 新发起一个请求不会算出负速度
- 累计指标需要开启服务端 metrics 端点：**高级模式 → 服务 → 「Prometheus指标 (--metrics)」**，然后重启服务。第一次采样之前读作 `0`；确实未知的值读作 `—`，每一格的 tooltip 会说明当前是哪一种
- 未运行时七个读数不折叠：点「启动」不会让窗口重新排版

<a id="log-panel"></a>

### 📄 日志面板

- 🔍 **Ctrl+F 搜索**，带匹配计数与循环查找
- **级别过滤** — 调试 / 信息 / 警告 / 错误（默认跟随"错误"级别）
- 📤 导出可见区域或**完整运行日志**（每次运行都会完整镜像到 `~/.llama-cpp-launcher/logs/last_run.log`）
- 🪟 **每级独立历史窗口** — 调试 / 信息 / 警告 / 错误各保留自己 5,000 行的窗口，隐藏级别的日志爆发（如 debug 提示词转储）不会把你正在过滤的级别挤掉
- 🔊 默认带上 `--log-verbosity 4 (trace)`：新版 llama.cpp 把自己那些 INFO 行改走 TRACE，若沿用二进制默认级别，运行信息面板会是空的
- 自动滚动开关、清空按钮、按级别着色

<a id="presets"></a>

### 💾 预设管理

- 保存 / 加载 / 删除命名预设 — 只存储与默认值的差异
- 以 JSON 文件导入 / 导出，方便分享；列表中显示创建时间
- 保存时可选择**包含或排除本机路径**（model/mmproj）
- 上次加载的预设会在**下次启动时自动恢复**
- 跨 llama.cpp 版本被重命名/删除的参数键会在加载时自动迁移

<a id="param-help"></a>

### ❓ 逐参数帮助

每个参数行都有 **?** 按钮，点开后弹出浮动帮助卡片：CLI 参数名、你二进制版本的*实时默认值*（来自 `--help`）、取值范围，以及通俗的解释。再也不用记 `--no-kv-offload` 是干什么的了。

<a id="gguf-inspector"></a>

### 🔬 GGUF 检查器

内置二进制检查器（不加载权重，纯标准库解析）：

- **7 个标签页**：概览 · 统计 · 元数据 · 张量 · 分词器 · 文件名 · 诊断
- 📊 可视化分析：量化分布、层/模块结构、参数集中度
- 🩺 **启动器感知诊断**：上下文超出模型上限、mmproj 名称不匹配、draft-mtp 缺少 sidecar、聊天模板 / RoPE / MoE / 分片信息
- 📤 导出 JSON / CSV / Markdown · 后台线程解析 + 内存缓存

<a id="server-lifecycle"></a>

### 🚀 服务生命周期

- ▶️ 一键启动/停止，彩色状态指示 + 运行计时器（MM:SS）
- ⚠️ 启动前端口冲突检测
- 🌐 一键在浏览器中打开 llama-server WebUI
- 优雅停止（非阻塞，超时强杀兜底）；关闭应用时自动停止服务
- ↩️ **撤销** — 800ms 防抖快照，最多回退 20 步
- 📝 **命令预览** — 精确的 `llama-server` 命令，每次修改即时更新，一键复制（含空格路径已正确加引号）

<a id="layout"></a>

### 🧭 布局与状态栏

- 🗂 **右栏 = 3 个标签页** — 参数配置 · 日志输出 · 运行信息，每个标签页都拿到整列高度（1080p 窗口下日志区约 800px，而不是 200px 的一条缝）；参数区 / 命令预览之间**可拖动分割**
- 🎛 **一行控制按钮，在标签页外面** — ▶ 启动 · ■ 停止 · 📋 复制 · 🌐 WebUI 与实时指标带：开着哪个标签页都能用
- 📌 **状态栏** — 检测到的 GPU · `llama-server` 版本 · ⚠ 参数漂移提示（点击看完整列表）· 运行状态点（灰=未启动 / 琥珀=启动中或两端无应答 / 绿=运行中 / 红=异常）· 状态文字 · 运行时长

<a id="window-ui"></a>

### 🪟 窗口与界面

- 🖼️ **无边框圆角卡片窗口** — 应用自绘卡片与柔和投影：一体式标题行（图标 · 标题 · 菜单 · Win11 风格最小化/最大化/关闭），拖动移动、双击最大化，贴住可见卡片边缘即可边缘缩放；最大化时卡片铺满全屏并使用系统自身的圆角。
- 🎴 **主题化对话框与消息框** — 所有对话框、确认框、错误提示都属于同一无边框卡片家族（深色/浅色自适应），风格统一不突兀。
- 📐 **默认尺寸舒适** — 首次启动以 1600×940（按屏幕可用区钳制）打开，左侧模型栏 400px；窗口大小、位置、模式、当前标签页与分割栏布局在下次启动时自动恢复。
- 🧘 **小窗体不塌方** — 参数区永不出垂直滚动条，控件不会被压缩或重叠：快捷开关自动换行成更多行并增大窗口最小尺寸；极窄窗口下宽行横向滚动。

<a id="i18n-themes"></a>

### 🌐 国际化与主题

- 🈶/🈷 **中 ↔ 英实时切换** — 无需重启，偏好持久保存
- 🌙 **深色 / 浅色主题** — **设置**菜单一键切换（文件 · 设置 · 帮助），自动记忆；日志面板与检查器均随主题适配
- 菜单布局：**文件**（扫描路径、llama-server 路径、刷新、退出）· **设置**（自定义快捷开关、语言、主题）· **帮助**（关于）

<a id="comparison"></a>

## 🆚 与其他工具对比

| 功能 | Llama CPP Launcher | Ollama | LM Studio |
|---|:---:|:---:|:---:|
| 自带 llama.cpp 二进制 | ✅ | ❌ | ❌ |
| 当天使用最新 llama.cpp | ✅ | ❌ | ❌ |
| 任意自定义后端（CUDA/ROCm/Vulkan/Metal/SYCL） | ✅ | ❌ | ❌ |
| 完整 CLI 参数访问（235 个） | ✅ | ❌ | 部分 |
| 实际命令可见且可复制 | ✅ | ❌ | ❌ |
| 版本感知的预设迁移 | ✅ | ❌ | ❌ |
| 内置 GGUF 检查器 | ✅ | ❌ | ❌ |
| 无遥测，100% 本地 | ✅ | ❌ | ✅ |
| 单一轻量依赖（PyQt6） | ✅ | — | ❌ |

<a id="development"></a>

## 🛠️ 开发

- Python 3.11+，PyQt6（版本锁定），pytest 测试
- 约 16,000 行应用代码（另有约 8,000 行测试，531 个测试用例）；核心 schema（`core/params_schema.py`）是 UI、CLI 命令生成、get/set 值、i18n 覆盖率的唯一事实来源 — 新增一个参数只需一条记录
- `gguf/`、`ui/log_parser.py`、`ui/command_builder.py` 均不依赖 Qt，可无界面单元测试

<details>
<summary><b>项目结构</b></summary>

```
llama-cpp-launcher/
├── main.py                  # 入口（异步启动、日志配置）
├── run.bat                  # Windows 启动脚本（激活 venv）
├── build_config.py          # 应用名 / 版本（CI 按 tag 改写）
├── llama_cpp_launcher.spec  # PyInstaller 构建配置（内嵌图标）
├── requirements.txt
├── core/
│   ├── params_schema.py     # ★ 235 参数 schema（Qt-free，唯一事实来源）
│   ├── params_help.py       # 逐参数帮助文本（235 条）
│   ├── defaults.py          # `--help` 解析、回退默认值、GPU 探测
│   ├── config.py            # 预设与设置 IO（~/.llama-cpp-launcher）
│   ├── runner.py            # QProcess 封装（启动/停止/就绪检测）
│   ├── i18n.py              # 中/英翻译（中文为源语言）
│   └── constants.py
├── gguf/                    # 纯标准库 GGUF 二进制读取器
│   ├── parser.py  models.py  ggml_types.py  filename.py  diagnostics.py
├── ui/
│   ├── main_window.py       # 窗口编排、主题、日志面板
│   ├── frameless.py         # 无边框圆角卡片窗口、标题栏、边缘缩放
│   ├── message_box.py       # 主题化无边框消息框与对话框基类
│   ├── basic_panel.py       # 基础模式（含可自定义快捷开关）
│   ├── advanced_panel.py    # 高级模式（schema 驱动，9 标签页）
│   ├── quick_params.py      # 快捷开关候选池 + 控件工厂
│   ├── quick_params_dialog.py  # 自定义快捷开关对话框
│   ├── server_path_dialog.py   # llama-server 路径对话框
│   ├── param_help.py        # "?" 按钮 + 浮动帮助卡片
│   ├── model_browser.py     # GGUF 扫描器（后台线程）
│   ├── gguf_inspector.py    # 7 标签页检查器对话框
│   ├── log_parser.py        # 日志行模式 → 运行时信息（Qt-free）
│   ├── live_stats.py        # /slots + /metrics 轮询、速度差值（Qt-free）
│   ├── live_metrics.py      # 实时指标带（七个读数 + 上下文计量条）
│   ├── command_builder.py   # 参数 → `llama-server` argv（Qt-free）
│   └── runtime_info.py      # 运行时信息 HTML（Qt-free）
├── tests/                   # 31 个测试模块（无界面，内存假数据）
└── assets/icon.ico|png
```

</details>

**发布**：推送 `v*` tag 触发 CI（windows-latest）— 跑测试 → PyInstaller 打包 → 自动发布 exe 到 GitHub Release。

<a id="license"></a>

## 📄 许可证

[MIT](LICENSE) — 想怎么用就怎么用。
