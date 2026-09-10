# 优化与修复计划

> 生成日期：2026-07（基于全量代码审查，约 10,000 行）
> 用法：逐项处理，完成后把 `- [ ]` 改为 `- [x]`。每项都包含：位置、问题、影响、修法。
> 行号基于当前工作区版本，代码变动后以函数名/代码片段定位为准。

## 进度总览

| 类别 | 总数 | 完成 |
|---|---|---|
| A. 正确性 Bug | 10 | 10 |
| B. 性能优化 | 8 | 8 |
| C. 架构与可维护性 | 9 | 7 |
| D. 测试与 CI | 5 | 5 |
| E. 功能/UX | 8 | 8 |

**⚡ 快速修复清单（半天可完成，建议先做）：A1、A2、A4、A5、C6、D3** — ✅ 全部完成（2026-07）

---

## A. 正确性 Bug（优先）

### A1. `_validate_params` 在主线程阻塞运行 `llama-server --help` 🔴 ✅
- **位置**：`ui/main_window.py:2349` `_validate_params()`；调用链 `_on_version_result`（def :2327，:2337 调用 `_validate_params`）→ `get_default_params()`（无参，`core/defaults.py:648`，help_text=None 分支）→ `_run_server_command`（:598）→ `subprocess.run(["llama-server","--help"], timeout=10)`（:600）
- **问题**：版本检查线程完成后，回调跑在**主线程**，里面同步执行子进程（最长 10 秒）。冷启动/杀软扫描时 UI 冻结数秒。
- **叠加问题**：`main.py:22` 启动时已拉过一次 `--help`，`_VersionCheckWorker` 又跑 `--version`，这里是**第三次**子进程，其中 help 是重复的。
- **修法**：
  1. `MainWindow` 保存启动时的 `help_text`（或解析后的 defaults），`_validate_params` 复用，不再起子进程；
  2. 或把 `_validate_params` 整体挪进 `_VersionCheckWorker.run()`（同一线程里先 `--version` 再 `--help`，一次子进程调用拿全）。
- **验证**：把 `llama-server` 换成一个 sleep 5s 的假脚本，观察窗口不卡。

### A2. 复制/预览命令不转义含空格的路径 🔴 ✅
- **位置**：`ui/main_window.py:1506`（预览 `setPlainText`）、`:1564`（`_copy_command` 内 join）、`:1544`（`_start_server` 日志打印命令）
- **问题**：`"llama-server " + " ".join(args)`，模型路径含空格（`C:\Users\xxx\My Models\foo.gguf` 极常见）时，用户复制出去执行会断参失败。
- **修法**：写一个 `_quote_arg(a)`（含空格/制表符时用双引号包裹，内部 `"` 转义），预览、复制、日志三处统一用。注意：`ServerRunner.start` 走 `QProcess.setArguments(args)` 逐参数传，**不需要**也不应该加引号（Qt 自己处理）——只改展示/复制层。
- **验证**：模型路径带空格，复制命令粘到 PowerShell 可直接执行。

### A3. 负向 flag 只发单边（默认 false 时用户打开开关无效）🟠 ✅（补 `models_autoload`：计划清单外但同一 bug；单元测试见 D2）
- **位置**：`ui/main_window.py` 所有 `_build_*_args`，模式：
  ```python
  if not self._is_default("mmap", v):
      if not v.get("mmap", True):
          args.append("--no-mmap")
  ```
- **涉及参数**（`core/defaults.py` `_NEG_FLAG_MAP`；构建器实测行号）：`kv_offload(890), repack(1086), mmap(1077), op_offload(1126), cache_prompt(878), kv_unified(893), slots(1285), jinja(1372), prefill_assistant(1390), cont_batching(1276), escape(903), warmup(1117), mmproj_auto(814), mmproj_offload(817), cache_idle_slots(910), webui(1262), cors_credentials(1324), spec_draft_backend_sampling(1165)`
- **注意**：`no_host`（:1083）虽叫 `--no-host`，但构建器是"值为 true 才发"的正向逻辑，**不受**此 bug 影响；`webui_mcp_proxy`/`context_shift` 的构建器同样是正向发射，不受影响
- **问题**：只有"默认开→用户关"才发 `--no-X`；若某版本默认是 false、用户想开，则**什么 flag 都不发**，用户意图被静默丢弃。当前 fallback 默认恰好全是 true 所以没爆，但与"动态解析默认值"的核心设计矛盾，版本一翻转就出错。
- **修法**：统一 helper：
  ```python
  def _neg_flag(v, key, neg, pos):
      if self._is_default(key, v): return
      if not v.get(key, True): args.extend(neg)
      elif self.defaults.get(key) is False: args.extend(pos)  # 默认关且用户开
  ```
  对每个负向参数补齐正向 flag（`_FLAG_MAP`/`_VALUE_FLAG_MAP` 里有现成 flag 名）。
- **验证**：构造 `defaults={"mmap": False}`，UI 勾选 mmap，断言命令行含 `--mmap`（或对应正向形式）。

### A4. 撤销系统出现"幽灵步" 🟠 ✅
- **位置**：`ui/main_window.py:745` `_undo()` + `:1496` `_update_cmd_preview` 的防抖快照逻辑
- **问题**：`_undo` 弹出历史后 `self._last_saved` 未同步；300ms 定时器发现 `params != _last_saved`，`_flush_snapshot` 会再追加一条**重复快照** → 每次撤销后撤销按钮重新点亮，能多按一次无效撤销。
- **修法**：`_undo` 末尾加 `self._last_saved = dict(self.params)`。
- **机制确认**：`_flush_snapshot`（:1510-1518）在 :1517 执行 `btn_undo.setEnabled(len(params_history) > 1)`，重复快照确实会让按钮重新点亮。
- **验证**：改参数→等 1s（快照落盘）→撤销→按钮应立即禁用，且 1s 后不再点亮。

### A5. 预设导入/导出失败也提示成功 🟠 ✅
- **位置**：`ui/main_window.py:2030` `_import_preset`、`:2037` `_export_preset`
- **问题**：无视 `config.import_preset()/export_preset()` 的 False 返回值，无条件弹"预设已导入/已导出"。
- **修法**：检查返回值，失败用 `QMessageBox.warning` 提示；`import_preset` 覆盖已有同名预设时先询问（与 `_save_preset` 的覆盖确认逻辑一致）。

### A6. mmproj 自动选择过于激进 🟡 ✅
- **位置**：`ui/model_browser.py:158` `auto_select_mmproj`
- **问题**：选任何模型（含纯文本模型）只要目录里有 mmproj 就 fallback 自动填入第一个 → 纯文本模型被悄悄加上 `--mmproj`。
- **修法**：只在名字匹配时自动选；无匹配时不自动填，最多在状态栏提示"发现 N 个 mmproj 可手动选择"。

### A7. 端口占用检测永远查 127.0.0.1 🟡 ✅
- **位置**：`ui/main_window.py:2046` `_is_port_in_use(port, host='127.0.0.1')`；调用处 `_start_server` 只传了 port
- **问题**：用户填局域网 IP 或 0.0.0.0 时检测结果失真（0.0.0.0 监听会接受 loopback 连接所以大致可用；绑定特定网卡时不可用）。
- **修法**：调用时传实际 host；host 为 0.0.0.0 时检查 127.0.0.1；host 为其他 IP 时检查该 IP。

### A8. 小 bug 集合 🟡 ✅（get_chat_templates 子进程项随 A10 已消：调用方全部显式传 help_text）
- **`--sse-ping-interval` tooltip 说 "-1 = 禁用"**（`ui/advanced_panel.py:975-978`）但 spinbox 范围 0~99999，填不了 -1。→ 改范围或改 tooltip（确认 llama-server 是否支持 -1）。
- **`webui_mcp_proxy`、`context_shift` 同时存在于 `_FLAG_MAP` 和 `_NEG_FLAG_MAP`**（`core/defaults.py`：`_FLAG_MAP` :429/:440，`_NEG_FLAG_MAP` :477-478）：同一行 help 文本会被两套逻辑解析。→ 从其中一个 map 移除（看实际 `--help` 输出该参数展示的是哪个 flag）。两者 fallback 默认均为 False（:113/:146）。
- **`prio` 解析支持 "low"（`core/defaults.py:239` `_PRIO_MAP` 有 -1:low）但 UI combo 只有 normal/medium/high/realtime**（`advanced_panel.py:618` `adv_prio`、:20 `DRAFT_PRIO_ITEMS`）。→ 补 "low" 或从解析映射去掉。
- **llama-server 缺失时 `get_chat_templates` 会再起一次子进程**（`core/defaults.py:659-664`，help_text=None 分支）：`main.py:31` 传入的 help_text 为 None 时。→ main.py 里 help_text 为 None 时直接传空串短路。
- **相对模型路径**：`ServerRunner` 的 work_dir 是 exe 目录（frozen 模式），但 `_start_server` 里 `Path(model_path).exists()` 用进程 CWD 判断，两者可能不一致。→ 检查时也基于 work_dir 解析。
- **`_start_server` 中 `port` 变量赋值两次**（取 v 前后各一次），清理。

### A9. 明文密钥/机器路径进预设 ⚠️（安全/体验）✅
- **位置**：`core/config.py` `save_preset`（保存 `current` 与 defaults 的差异，含 `api_key`、`hf_token`、`model`、`mmproj` 绝对路径）
- **问题**：预设是明文 JSON；换机器加载会带失效绝对路径 + 明文密钥。
- **修法**（可选其一或组合）：
  1. 保存预设时对 `api_key/hf_token` 打码提示（至少状态栏警告）；
  2. 加载预设后校验 model/mmproj 路径存在性，不存在则清空该字段并提示；
  3. 预设加 `"version": 1` 字段为将来迁移留口。

### A10. 启动流程：窗口出现前同步跑 `--help`（最长 10s 黑屏）🟠 ✅
- **位置**：`main.py:22` `fetch_help_text()` 在 `QApplication` 之前
- **修法**：先创建 QApplication + 主窗口（用 `_FALLBACK_DEFAULTS` 或上次缓存的 defaults），`--help`/`--version` 放后台线程，拿到后 `refresh_defaults` + 通知窗口更新版本标签与参数校验。
- **注意**：`refresh_defaults` 会改 `DEFAULT_PRESET`，但 `MainWindow` 已持有自己的 `self.defaults` 副本，异步化时要保证窗口拿到最终 defaults 后同步给两个 panel（可复用现有 `_apply_params_to_current` 路径，注意别污染 undo 历史——在首个快照落盘前应用是安全的）。

---

## B. 性能优化

### B1. 命令预览 300ms 轮询（`main_window.py:362`）✅（方案 1 + 窗口隐藏时暂停定时器；方案 2 的 panel 信号版留待 C1）
- `preview_timer`（`main_window.py:362` 启动，:723 模式切换后重启）每 300ms 调 `_update_cmd_preview` → `_save_current_to_params` → 高级模式 `get_values()`（229 行、逐控件读取）；窗口失焦/最小化也在跑；命令没变也 `setPlainText` 重绘。
- **修法**：
  1. 最低成本：`_update_cmd_preview` 里 `new_text != self.cmd_preview.toPlainText()` 才 set；
  2. 彻底：监听所有控件 change 信号（两个 panel 各加一个 `values_changed = pyqtSignal()`，在 valueChanged/textChanged 等连接点转发），主窗口收到后 80ms 防抖刷新，删掉轮询定时器。

### B2. 日志逐行 `appendHtml`（`main_window.py:1672` `_append_log`）✅
- verbose/`--perf` 高吞吐日志下每行一次 Qt 布局操作。
- **修法**：`_append_log` 里把行累积到 buffer，`QTimer` 100ms 批量 `insertHtml("".join(...))`；自动滚动判断移到批量刷新时。保留 `_log_tail` 半行拼接逻辑不变（批量 flush 时同样要处理尾部）。

### B3. `ServerRunner._check_ready` 每块 join+lower（`core/runner.py:98`）✅
- 每个 stdout 块都对最多 8KB 缓冲 `"".join(parts).lower()`。
- **修法**：就绪前只需检测短语 "starting the main loop" / "server is listening" / "listening on http"，保留**末尾 200 字符**滚动窗口即可（短语最长 24 字符，跨块也能命中）。

### B4. `--help` 解析 O(行×flag) 重复 split（`core/defaults.py:542`、`:589` `_flag_in_line`）✅（实测 56.7ms → 1.3ms，差分测试与旧版输出一致）
- 每个 flag 调用 `_flag_in_line` 都对整行 `replace().split()`，约 300 行 × 300 flag ≈ 9 万次重复切分。
- **修法**：
  1. 模块级预构建反向索引：`{flag: (param_key, parser, kind)}`（kind ∈ value/flag/neg）；
  2. 每行只 split 一次得 `tokens = set(...)`，`hits = tokens & index.keys()` 处理。
- 预期启动解析从百 ms 级降到 10ms 级（纯 Python 常数级收益）。

### B5. `_classify_tensor` 每张量重排序（`gguf/parser.py:113`）✅
- 10 万张量 × 每次 `sorted()` 20 项。→ `_KNOWN_MODULES` 提升为模块级常量（顺序按长度降序）。

### B6. GGUF 解析缓存内存（`ui/gguf_inspector.py:55-75`）✅（方案 1：上限 10→3；`clear_parse_cache` 已在 C6 删除）
- `_parse_cache` 最多 10 个 `GGUFInfo`，每个含完整 metadata：15 万 token 列表（约 10-20MB Python 对象）+ 数 MB 的 `tokenizer.huggingface.json` 字符串 → 常驻可达数百 MB~GB。
- **修法**（按工作量排序）：
  1. `PARSE_CACHE_MAX` 从 10 降到 3（`core/constants.py:20`）；
  2. 缓存"展示快照"（渲染好的 HTML 串 + 表格数据）而非原始 `GGUFInfo`；
  3. 按累计字节数做 LRU（估算 = metadata 字符串长度 + 张量数 × 100B）。
- 顺带：`clear_parse_cache()`（:71）定义了无人调用——要么接到菜单（帮助→清理缓存），要么删掉。

### B7. `MetadataTableModel._format_value` 对大数组立即 `json.dumps`（`ui/gguf_inspector.py:100`，`json.dumps` 在 :122）✅
- 15 万元素数组 → 数 MB 字符串存进每行 tuple，只为右键"复制全部/复制值"。
- **修法**：`full_str` 改懒计算（`functools.cached_property` 或首次访问时算）；`get_all_json` 保持可用。

### B8. 启动子进程合并 ✅
- 启动共 3 次 llama-server 调用：`--help`（main.py，同步）+ `--version`（worker）+ `--help`（A1 的 validate）。
- **修法**：与 A1/A10 一起：worker 内先 `--version` 再 `--help`（两次调用、同一线程、窗口已显示），validate 复用 help 文本。

---

## C. 架构与可维护性

### C1. 160 参数四处手工同步（最大长期成本）✅（2026-07 完成）
- 原问题：`advanced_panel.get_values`/`set_values`/`_set_values_impl`、`main_window._build_*_args` 8 个方法（约 710 行）、`i18n._EN`、`_FALLBACK_DEFAULTS` 四处各写一遍参数逻辑，已出现漂移（A8 的 sse tooltip、prio 缺 low）。
- **实现**：`core/params_schema.py` — 226 个 `Param` frozen dataclass（单源），携带 key/tab/row/label/widget 定义（14 种控件）/默认值/CLI flag 别名/15 种 emit 模式。四个消费方全部由 schema 驱动：
  1. **① 高级面板 UI**：`AdvancedPanel._create_tab/_build_param_row` 按 `tab_params(tab)` 逐行构造，7 个 tab × ~900 行手写 UI 代码 → ~180 行分发器；E8 GPU 信息行与草稿模型分节标题以“锚点参数”方式保留（gpu tab 行 5/38 为预留非参数行）；
  2. **② 命令构造**：`ui/command_builder.py` 的 `build()` 按 PARAMS 顺序（= emit 顺序）走 `_emit(p, v)` 分发 15 种模式；旧的 8 个 `build_*_args` 删除；
  3. **③ get/set_values**：`_read_param/_write_param` 按控件类型读写，含 ngl 复合控件（combo 为真源 + 辅助 spin）；
  4. **④ i18n 缺失检查**：`schema_i18n_strings()` 导出全部 schema 字符串，`tests/test_params_schema.py::test_schema_i18n_coverage` 强制含 CJK 的字符串必须有 `_EN` 条目（已实际抓到并修复 3 个旧缺口："禁用 (0)"、dry-sequence-breaker placeholder、spec-draft-override-tensor label）。
- **附带**：`core/defaults.py` 的 `_FALLBACK_DEFAULTS` 与三张 `--help` 解析映射（`_VALUE_FLAG_MAP`/`_FLAG_MAP`/`_NEG_FLAG_MAP`）也由 schema 派生（`fallback_defaults()`/`help_flag_maps()`，parser 以字符串名传递避免循环导入）；`_FLAG_INDEX`（B4）逐键一致。
- **验证**：新旧 UI 全量状态差分（225 控件 × 范围/步长/项目/占位符/tooltip/初始值/行序/tab 标题）0 差异，中英文 retranslate 同样 0 差异；CommandBuilder 对 1000 组随机值的 emit 差分 0 差异；get/set_values 对 20 组值字典 + 坏值字典差分 0 差异；245 测试全绿。
- **后续（2026-09）tab 语义重分组**：原 7 tab（模型/上下文/采样/GPU/服务/聊天/高级）是早期按大类粗分，其中 GPU tab 达 77 行且混了 43 行投机解码参数。对照 llama.cpp 源码语义（`llama-server --help` 的 common/sampling/speculative/server-specific 分区、`common_params_sampling`/`common_params_speculative` 结构体、server README 的 Multimodal/Tools/MCP 章节）重分为 9 个 tab：模型（+来源+LoRA/控制向量+多模态）、上下文（+KV cache+RoPE/YaRN）、采样、GPU/性能（+CPU 线程/亲和/优先级）、**投机解码（新）**、服务（+embedding/rerank 模式+router）、**Agent/工具（新）**、聊天/推理、高级（只剩文本 IO+日志+extra_args）。参数键、emit、默认值全部不变，仅 `tab`/`row` 字段与 UI 顺序变化；持久化 tab 位置改用稳定键 `adv_tab_key`（`adv_tab` 索引仍兼容旧值）。

### C2. `main_window.py` 2774 行拆分 ✅
- 拆出：
  - `ui/log_parser.py`：`_compile_log_patterns` + `_parse_log_line` 逻辑（纯函数，可单测）；
  - `ui/command_builder.py`：`_build_*_args` + `_is_default` + `_quote_arg`（纯函数，可单测）——A2/A3 的修复顺手放这里；
  - `ui/runtime_info.py`：`_update_info_display` 的 HTML 渲染（info dict → HTML 字符串，可单测）。
- MainWindow 只保留编排/信号连接。

### C3. 双份状态源：`MainWindow.params` vs `ConfigManager.current` ✅
- 预设加载走 config→params→widgets；保存走 widgets→params→config→json。
- **修法**：`ConfigManager` 只负责 JSON IO；`MainWindow.params` 为唯一状态源。`load_preset` 返回 dict 而非改 `self.current`。

### C4. i18n 加固 ✅（emitter 零订阅者，直接删除而非懒加载；顺带落地 D4 覆盖率测试）
- **翻译覆盖无检查**：`t("...")` 漏翻译时静默显示中文。→ 加测试（D4）。
- **`t()` 的 `.format()` 与字面花括号冲突**：文案含 `{}`（如 MCP JSON 示例）会 `KeyError` 崩溃。→ `t()` 内用 `string.Formatter` 的 try/except 或先 `result.replace("{{","{")`…更稳妥：format 失败时回退原文并 logger.error。
- **硬编码英文标签**（`ui/basic_panel.py`）：`"mmproj:"`、`"Top-P:"`、`"Top-K:"`、`"Min-P:"`、`"FlashAttn:"`、`QCheckBox("WebUI")`、`QCheckBox("Verbose")`、按钮 `"..."` 未走 `t()`，中文模式中英混杂。→ 补 `_EN` 条目并包 `t()`。
- **`core/i18n.py` 依赖 PyQt6**（`_LanguageEmitter`）→ 核心模块无法无 Qt 测试。→ emitter 懒加载/可选注入（没有 QApplication 时 no-op），或把信号挪到 UI 层。

### C5. `_validate_params` 的 67-key 硬编码 skip 列表（`main_window.py:2355` 起，实测 67 个 key）✅（移入 core/defaults.py `USER_INPUT_PARAMS`，缩减为 63：tools/sampler_seq/cors_origins/cors_headers 参与漂移检查）
- 每加一个参数都要记得维护。
- **修法**：改成"对比启动时解析的 defaults 与 `_FALLBACK_DEFAULTS`"（漂移提示才是目的），skip 列表缩减为真正的"用户输入型"参数（model、路径类、key 类）；或干脆把 skip 列表移入 `core/defaults.py` 与参数 schema 同源（配合 C1）。

### C6. 死代码清理（半天内可清完） ✅
- `core/constants.py:16` `WEBUI_OPEN_DELAY_MS`：导入后从未使用；
- `ui/gguf_inspector.py:71` `clear_parse_cache()`：无调用；
- `ui/model_browser.py:12` `scan_progress` 信号：声明未 emit；
- `ui/basic_panel.py` / `ui/advanced_panel.py` 的 `reset()`：无调用（主窗口 reset 用自己的逻辑）;
- `core/i18n.py:23` `on_language_changed`：无订阅者；
- `ui/main_window.py:17` `QSize` 导入未用；`_colorize_log_line` 内 `import html as _html` 与顶部 `html_mod` 重复；
- `ui/model_browser.py` `scan_progress` 相关。
- **验证**：`python -m compileall` + 现有测试 + 手工跑一次 app。

### C7. logging 无 handler（exe 里日志全丢） ✅
- 全部模块 `logger.warning(...)`，但无任何 handler 配置；spec `console=False` → 用户永远看不到，排障无据。
- **修法**：`main.py` 启动时 `logging.basicConfig(filename=CONFIG_DIR/"launcher.log", level=logging.INFO, rotation)`（`logging.handlers.RotatingFileHandler`，1MB×3）。

### C8. `QSplitter` 左侧 `setFixedWidth(280)` → 分割条拖不动（`main_window.py` `_create_left_panel`） ✅（状态持久化归 E2）
- 要么去掉 setFixedWidth 允许拖动（并持久化 splitter 状态，见 E2），要么换成普通布局。

### C9. LoRA 扫描结果未展示 ⏸（2026-07 先实现后回退：按用户决定移除左栏 LoRA 分组——LoRA 使用率低，高级面板内手动添加的入口保留）
- `ModelBrowser` 把含 "lora" 的文件收集进 `self.loras` 但 UI 无任何入口（状态栏也不显示）。
- **修法**：左栏加 "LoRA" 分组列表（复用 mmproj 分组），点击后填充高级面板 LoRA 列表 / 基础模式提示去高级模式。

---

## D. 测试与 CI

### D1. `core/defaults.py` `--help` 解析器零测试 🔴 ✅
- `_parse_help_to_defaults` 是纯函数，最高性价比的测试目标。
- **修法**：`tests/test_defaults.py`，准备 2-3 段真实样本 help 文本（新旧格式各一，存 `tests/data/`）：
  - 数值/布尔/字符串默认值提取；
  - 多 flag 别名（`-c`/`--ctx-size`）；
  - 占位符归一化（"none"/"unused" → ""）;
  - prio 映射；`_KNOWN_STRING_DEFAULTS` 命中；
  - llama-server 缺失时 fallback。

### D2. 命令构造零测试 🔴 ✅
- 依赖 C2 拆分（`command_builder.py` 纯函数化后）：
  - 默认值不发射 flag；
  - 负向 flag 双向（配合 A3）；
  - `n_gpu_layers="all"→999`、"auto"→发射；
  - extra_args 的 shlex 解析与异常回退；
  - 含空格路径的 `_quote_arg`（配合 A2）。

### D3. CI 不跑测试 🟠 ✅
- `.github/workflows/release.yml` 直接构建。→ 在 "Install dependencies" 后加：
  ```yaml
  - name: Run tests
    run: python -m pytest tests/ -q
  ```
  （gguf 测试纯 stdlib 可跑；defaults 测试需要 PyQt6 已装，requirements 里有。）

### D4. i18n 覆盖率测试 ✅
- `tests/test_i18n.py`：AST 扫描 `ui/ core/ main.py` 所有 `t("字面量")` 调用，断言字面量 ∈ `_EN`（中文原文 key）。新字符串忘加翻译立刻挂测试。
- 需先解决 C4 的 PyQt 依赖（或测试里 mock PyQt6）。

### D5. 依赖钉版本 ✅（PyQt6==6.11.0、pyinstaller==6.22.2）
- `requirements.txt`：`PyQt6>=6.6`；CI 加 `pyinstaller==x.y.z`（锁定，防打包行为漂移）。

---

## E. 功能 / UX 建议

### E1. 可配置的 llama-server 路径（价值最高） ✅（`get_server_path()` 解析器：settings > which > 裸名；文件菜单对话框带预填/浏览/--version 验证，保存后重跑 A10 刷新流）
- 现状：`core/runner.py:43` `cmd = "llama-server"`（`start()` 内）与 `core/defaults.py`（`_run_server_command`/`fetch_help_text` 默认参数）、`main_window.py:307`（`_VersionCheckWorker`）都写死依赖 PATH。
- **修法**：settings.json 加 `server_path`；启动时：显式路径 > PATH 探测（`shutil.which("llama-server")`）> 报错；UI 在文件菜单加"设置 llama-server 路径…"（对话框输入 + 浏览按钮，保存后校验 `--version` 可执行）。`ServerRunner.start` 与 `fetch_help_text/_run_server_command/_VersionCheckWorker` 全部改用该路径（可加全局 `get_server_path()` 入口）。

### E2. 窗口状态持久化 ✅（`core.config.save_ui_prefs/load_ui_prefs` 存 settings.json `ui` 键：geometry(base64)、mode、adv_tab、bottom_tab、splitter[2]；`closeEvent` 保存、`__init__` 经 `_restore_ui_state()` 逐项校验恢复；splitter 宽度经 `_apply_pending_splitter()` 在 showEvent 后重试应用——Qt 在首次布局前会丢弃 setSizes，且右栏布局最小宽 ~1041px 会在窄窗口把左栏压回 180 最小值，故应用后需校验实际值、未生效则保留 pending 重试；`tests/test_ui_prefs.py` 5 测试）

### E3. 日志面板增强 ✅（Ctrl+F 搜索栏（wrap-around 搜索 + 匹配计数 + Shift+Enter 反向，`_log_search_find`）+ D/I/W/E 级别过滤（F 跟随 E；过滤/恢复都从 `_log_records` 重建视图，banner 级别 None 恒显示）+ 每次运行全量镜像到 `~/.llama-cpp-launcher/logs/last_run.log`（行缓冲，崩溃不丢尾部，写失败静默降级）；导出时若全量文件比显示区多则弹三选：仅显示区/完整日志(N 行)/取消；`tests/test_log_panel.py` 8 测试）

### E4. GGUF Inspector 打开任意文件 ✅（顶栏"📂 打开..."按钮 → QFileDialog（filter 保持英文字面量）→ `_add_file_option()` 按 resolve 路径去重后追加 `_file_options` + 下拉项，复用既有 cache/parse 流；`tests/test_gguf_inspector_ui.py` 4 测试）

### E5. 深色主题 ✅（`_get_stylesheet(theme)` 模板 + light/dark 双调色板（@@token@@ 替换，light 输出与原 QSS 逐字一致）；settings.json `theme` 键持久化（`load_theme/save_theme`）；帮助菜单可勾选"🌙 深色主题"，切换同时应用 window 级 + app 级 QSS（GGUF Inspector/对话框跟随，同串跳过重抛光）；`tests/test_theme.py` 4 测试；`tests/conftest.py` 新增 autouse 清理——PyQt6 中 close() 只隐藏不销毁，残留隐藏顶层窗口会让 app 级 setStyleSheet 二次方变慢，每个测试后 gc.collect() 释放）；**后续修复（2026-07）**：底部 日志输出/运行信息 tab 原本有一段硬编码浅色内联 QSS，会覆盖 app 级主题（深色下 tab 栏发白）——新增 `_bottom_tabs_qss(theme)`（浅色串与原内联 sheet 逐字一致，深色用 Catppuccin 同系 #11111b/#1e1e2e/#7aa2f7），初始化与 `_apply_theme()` 均按主题应用，`tests/test_theme.py` 加回归测试 + 离屏像素验证）

### E6. 预设增强 ✅（保存对话框升级为 QDialog：名称 + "包含模型路径 (model/mmproj)" 复选框，不勾选时 `values.pop(model/mmproj)`；`list_presets` 改读 JSON 内 `created` 字段（mtime 仅作回退），覆盖保存保留原创建时间；预设下拉项带创建时间 tooltip + 选中时状态栏提示"预设 X · 创建于 …"；加载缺路径提示/清空已由 A9 实现；`tests/test_presets_e6.py` 6 测试）

### E7. 版本标签增强 ✅（`_on_version_result` 存 `_server_version_line`，「关于」对话框展示检测到的版本；参数漂移升级为控制栏可点击 ⚠️ 按钮 `drift_button`：无漂移隐藏，有漂移点击弹 QMessageBox（setDetailedText 展开）显示完整列表（不再截断 5 项）；tooltip 保留；`tests/test_version_label_e7.py` 4 测试）

### E8. GPU 感知 ✅（2026-07，新增，与用户确认）
- **B（运行真相）**：`ui/log_parser.py` 修正 offload 模式 check 串（新构建前缀 `load_all_data:` 无 `load_tensors`，改为只检查稳定措辞 `offloaded`/`layers`）；新增 `using device CUDA\d+ (...)` 模式作为设备名回退；`ui/runtime_info.py` 硬件区首行新增"🖥️ GPU（本次运行）"汇总（设备 + 显存 + 卸载层数）。
- **A（启动探测）**：`_StartupInfoWorker` 在 `--help` 后追加 `--list-devices`（仅当 help 文本含该 flag，老版本静默跳过）；`core/defaults.py` 新增 `parse_device_list()` 解析 `CUDA0: NVIDIA GeForce RTX 5090 (32579 MiB, 30819 MiB free)` 行；新信号 `devices_ready(list)` → MainWindow 分发到基础/高级面板新增的 `gpu_info_label`（基础面板 ngl 行下方、高级面板 tensor-split 行下方）：`检测到 2× GPU: RTX 5090 (32GB) + RTX 2080 (8GB)`，tooltip 全量 MiB 明细；无 GPU 显示"仅 CPU（未检测到 GPU 设备）"。**不自动填 ngl**（auto 已是正确默认，探测无法得知模型尺寸）。
- 实测：双卡机器（RTX 5090 + RTX 2080）离屏冒烟通过——真实 `--list-devices` 输出解析正确、两面板渲染正确、日志行生成 GPU 汇总行。
- 背景：多卡/异构双卡（如 RTX 5090 + RTX 2080）用户面对 ngl/split-mode/tensor-split 参数时缺少硬件上下文；单卡用户也有"我的卡到底用上了吗"的排障需求。
- **A. 启动探测**：`_StartupInfoWorker` 在 `--help` 后追加 `--list-devices`（仅当 help 文本含该 flag，老版本静默跳过）。输出格式实测（b10825）：`CUDA0: NVIDIA GeForce RTX 5090 (32579 MiB, 30819 MiB free)`，逐行好解析。展示在基础面板 GPU 层数旁（如 `2× GPU：RTX 5090 32GB / RTX 2080 8GB`，tooltip 全量），高级面板 split-mode 行同样受益。**不自动填 ngl**（不知道模型尺寸，auto 已是合理默认）。
- **B. 运行真相（优先做）**：服务器启动日志本身会报告实际使用设备与实际 offload 层数（如 `offloaded 33/38 layers to GPU`）；在 `ui/log_parser.py` 加 2-3 个模式（兼容新旧措辞），运行信息面板加一行 `GPU: …` 。零额外子进程，回答"这次实际跑了什么"。
- 验证：双卡机器离屏冒烟（探测行渲染 + 启动服务器后运行信息出现 offload 行）；无 GPU 环境（仅 CPU）下两行分别显示"仅 CPU"/不显示，不报错。

### E11. 小窗体控件压缩/重叠 ✅（2026-09，用户反馈：窗体尺寸比较小时控件被压缩并重叠）
- **根因**：窗口 `setMinimumSize(1100, 700)` 低于内容实际布局最小（开发机实测 1201×861）——最小窗口下布局无法满足最小尺寸，行被压到 4px 高、控件互相叠画。宽度上快捷开关 grid 最小 ~1005px（QLabel 单行标签的 minimumSizeHint=整行文字宽）、模型组 ngl+上下文+7 个预设按钮单行 ~934px，共同把窗口最小宽顶到 1201+。
- **设计（用户决定：参数区不要垂直滚动条）**：行保持完整高度，窗口直接不允许缩到放不下的高度——面板设硬最小高而非让面板自己滚动。
- **修复**：
  - `BasicPanel` 硬最小高 = 面板自然高（`resync_min_height()` = `layout().minimumSize().height()`）。自然高依赖解析后的字体，所以 `MainWindow._sync_panel_min()` 在 showEvent（直接 + 0ms timer 补第一次布局）和快捷开关自定义后再重新 pin 一次——构造期读到的是字体未定的近似值（400 vs 实际 486，不重 pin 会把底部裁掉）。
  - `stacked` 仍包在无边框 `QScrollArea`（`panel_scroll`，widgetResizable）里，但垂直滚动条 `AlwaysOff`：`_sync_panel_min()` 显式给 scroll area 设最小高=面板最小高+2（QScrollArea 不会把内容最小**高**传给自己，widgetResizable 内容会被静默压扁——宽度会尊重最小值、高度不会，实测如此）。
  - `_sync_panel_min()` 末尾按 live `minimumSizeHint()` 抬窗口最小（`max(MIN_WINDOW_*, hint)`，MIN 降为 900×690 地板）——字体/DPI 不同也能保证"窗口最小=内容最小"，永远不会缩进压缩态。
  - scroll area / `stacked` 只保留水平方向滚动：`stacked` 硬最小宽 = 固定组（模型/采样/服务）最宽者（`_update_panel_content_min()`），刻意不含自适应换行的快捷开关 grid（其最小随列数变，是移动靶）。这个宽度地板同时保证窗口内 grid 恒 ≥4 列（2 行），使面板最小高与窗口宽度无关——高度闭环成立的关键。
  - 快捷开关：槽位标签 `setMinimumWidth(1)`（空最小=未设置，Qt 会回退 minimumSizeHint=整行文字宽）；`_quick_cols()` 按"最大可容纳列数"贪心（按 scroll-area viewport 宽，祖先链查找），且**不低于 2 列**——单列会让 grid（和面板最小高）依赖当前窗口宽度，窄于 2 列最小宽时改出水平滚动条而不是折成单列。
  - 模型组 ngl 行与上下文行拆为两行（原单行 ~934px 是宽度主要来源之一）。
  - 服务行 host/port/parallel 固定宽微调（110/70/60 → 100/64/56），行最小 843→833。
- 实测（offscreen 全量 widget 几何扫描，visibility 按滚动区 viewport 裁剪）：最小尺寸/1100×700/默认尺寸 × 基础/高级模式 = 0 重叠、无垂直滚动条、面板恒为完整高度；左栏拖到最宽的最坏组合下 grid 仍 2 行；旧代码同扫描 8 组重叠（行被压至 4px）；窗口最小 1100×700（名义）/1201×861（实际）→ 902×879（开发机字体）。
- **第二轮（用户第二次反馈：窗口横向缩小后快捷开关从 1 行折成 2 行，多出来的行高被"借"自模型设置组，压扁了该组行高）**——用户选定**方案 A：尺寸变化时动态重新同步**（在面板布局 pass 之前检测 grid 折行并提前重 pin 硬最小，当前高度放不下时窗口自动加高，而不是让 Qt 去压"最软"的组）：
  - `BasicPanel._arrange_quick_toggles()`：列数变化才重排（避免拖动期间每帧 takeAt/addWidget），行数变化时发 `quick_wrap_changed(rows)`；grid 收进 `_quick_grid_host` 包装 widget，**显式**最小高 = 行数×槽位高（算术值）。
  - `MainWindow.eventFilter` 监视 `panel_scroll.viewport()` 尺寸变化——viewport 在面板自己的布局 pass **之前**被调整，这是唯一的"提前量"；重排后 `_on_quick_wrap_changed` 直接（不再延迟）调 `_sync_panel_min()`，同一 pass 内更新窗口最小，`setMinimumSize` 大于当前尺寸时 Qt 自动加高窗口。
  - **Qt 最小尺寸缓存的两个坑**（本轮实测发现）：① grid 的 takeAt/addWidget 之后，其 layout 最小值要隔一个事件循环 pass 才更新，期间面板 layout 的 `minimumSize()` 缓存同样是旧值——所以 grid 用显式最小高（host widget，QLayout 本身没有最小值）、`resync_min_height()` 改为逐项累加各组的 `minimumSizeHint()`（按需计算、不读缓存）；② `minimumSizeHint()` 会少报 scroll area 的显式最小值，而日志标签页的弹性区会把缺口全部分给面板——所以窗口最小**高**改为右列子项最小值之和 + 菜单栏/状态栏 + 中央 margins（实测 914 vs hint 879，缺口 35px 正好被日志区吃成压缩）。
  - GPU 信息标签晚到（异步探测，可能在任意模式/时机出现）后也补一次同步，覆盖"高级模式切换回来时模型组已含 GPU 行"的压缩 case。
  - **窗口最小宽不能含 grid 当前列数最小宽**：`minimumSizeHint().width()` 会带上 grid 当前列数（1 行时 ~1015px）的最小宽，把窗口最小宽顶到 1276+ —— "1 行 grid 把窗口撑宽、宽窗口让 grid 保持 1 行"自我锁死，折行永远不发生。改为显式计算：左栏最小宽 + splitter handle（未布局前 `handleWidth()=-1`，floor 到 10）+ 右列子项最大最小宽（scroll area 用其固定内容最小宽 `_panel_fixed_min_width` 替代）。
  - **长单行标签也会顶宽**：GPU 设备行（"检测到 2× GPU: RTX 5090 (32GB) + …"）和版本字符串（`llama-server 10867 (…)`）的 QLabel 最小宽 = 整行文字宽（~1090px），同样把窗口最小宽顶到 1276。`setWordWrap` 更差（折行标签的 minimumSizeHint = 最长单词处的多行高，永久拉高最小高）。改用 `basic_panel.ElidingLabel`：省略号截断、最小宽 0、最小高恒 1 行、tooltip 保留全文（颜色走 palette + 显式字号，不走 QSS——自定义 paintEvent 会忽略 QSS 颜色）。GPU 标签与 version_label 均已换用；实测 GPU 晚到后窗口不再跳宽（1020 稳定），仅按 2 行+GPU 行加高。
- 第二轮实测（7 快捷项场景：1360 宽 → 927 窄 → 最小 → 放大 → 高级/基础来回，连跑 3 次覆盖异步 GPU 探测的不同落地时机）：折行时窗口最小 885→923 自动跟上，5 个状态全部 0 压缩 0 重叠，无垂直滚动条。
- **第三轮（用户第三次反馈：快捷开关行水平拉伸时标签文字容易被盖住，如 "KV C"、"适"——要求保证显示全）**：根因是 `_quick_cols()` 用 grid **最小宽**（标签被压到 1px）选列数——列数按"压扁后"的宽度算，放得下更多列，但每列实际分到的宽度不够完整标签，文字被控件盖住。修复：
  - 列数改按 **自然宽**（`sizeHint`，标签完整显示所需宽度）选列：`_quick_grid_natural_width(cols)`（每列取该列最宽 slot）≤ viewport 宽才用该列数；
  - `_apply_quick_column_widths()`：每列 `setColumnMinimumWidth` = 该列最宽 slot 的自然宽——任何宽度下列都不窄于标签所需，文字永远完整；连列数不变的重排（语言切换改标签长度）也会刷新；
  - 代价：同样宽度下列数变少、行数变多（如 1180 宽 7 项从 5 列 2 行变 4 列 2 行，最小宽下 3 列 3 行），窗口最小高随之自动加高（第二轮机制，不压任何组）；两列自然宽都放不下时出水平滚动条（滚得开、不裁切）。标签自身的 `setMinimumWidth(1)` 保留——列最小宽才是保证，slot 自身不能再把 grid 撑得更宽。
- 第三轮实测（真实字体，7 快捷项）：1180（用户截图宽度）4 列 2 行、最小宽 937 3 列 3 行、1360 4 列 2 行——全部标签完整显示（KV Cache K类型 / KV Cache V类型 / 适配内存不再被截断），无水平/垂直滚动条，各组零压缩。
- 测试：`tests/test_small_window.py` 4 测试（窗口最小≥内容最小、6 个尺寸×模式组合零重叠、3 个尺寸下面板完整高度+无垂直滚动条+grid ≥2 列、**7 项快捷开关宽→窄场景 grid 折行不压缩任何组且窗口最小跟随**）；stash 回退验证旧代码必挂。

---

## 附：审查时确认过、无需改的点（避免重复排查）

- GGUF 解析器防御性完善（EOF 检查、sanity limits、version>3 警告）✅
- 日志跨块半行拼接（`_log_tail`）逻辑正确 ✅
- 模式切换/应用预设时的信号屏蔽（`_mode_switching`/`_applying_values`）考虑周到 ✅
- QThread 生命周期处理（scanner 不 wait 旧线程、inspector worker 模块级保活）正确 ✅
- 预设名路径穿越防护（`_sanitize_preset_name`）✅
- `gguf/` 包纯 stdlib 设计（可无 Qt 测试）✅，41 个测试全部通过 ✅
- `QProcess.setArguments` 逐参数传值本身不需要 shell 引号（A2 只改展示层）✅

## 复核记录（行号验证）

> 本文档所有行号/数量/行为声明已于 2026-07 对照当前工作区代码逐条复核：
> - ✅ 行为声明（A1-A10、B1-B8、C2-C9、D1-D5、E1-E7 的问题本质）全部与代码一致；
> - 修正过 9 处行号/数量偏差（A1 子进程实际在 defaults.py:600、A3 移除 no_host、A8 map 行号 429/440/477-478、C1 各模块实际行数、C5 实为 67 key、E1 实为 runner.py:43、B6/B7 行号等）；
> - A4 幽灵撤销机制已确认：`_flush_snapshot` :1517 会重新点亮撤销按钮；
> - 代码后续变动后行号可能漂移，以函数名/代码片段定位为准。

## 建议实施顺序

1. **第一批（半天，快速见效）**：A1 → A2 → A4 → A5 → C6 → D3（✅ 全部完成，2026-07）
2. **第二批（1-2 天，核心质量）**：A3（含测试）→ C2 拆分 → D1/D2 测试补齐 → A10 启动异步化（✅ 全部完成，2026-07；B8 随 A1+A10 一并完成）
3. **第三批（按需）**：B1-B8 性能、A6-A9、C1-C5（✅ 全部完成，2026-07；D4 随 C4 一并落地）
4. **收尾批**：C7、C8、D5（✅ 完成，2026-07；C9 实现后按用户决定回退）
5. **第四批（体验）**：E1-E8 全部完成（2026-07，E8 = GPU 感知，B 优先）
6. **最后**：C1 参数 schema 大重构（✅ 完成，2026-07）

> **当前状态（2026-07）**：全部 40 项完成（A 10/10、B 8/8、C 8/9、D 5/5、E 8/8）；唯一未完成项 C9（LoRA 左栏分组）按用户决定回退⏸——LoRA 使用率低，高级面板内手动添加入口保留。
