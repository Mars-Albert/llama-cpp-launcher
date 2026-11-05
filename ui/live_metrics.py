# -*- coding: utf-8 -*-
"""实时指标行：与启动按钮**同一行**的那条淡底色圆角带（2026-11 重设计）。

本条带**自己不管水平对齐**：它是 MainWindow 合一行（`MainWindow.control_bar`）
里最右的一项，横向策略 Maximum（只长到内容宽）→ 行里那条 stretch 吃掉富余
宽度，所以“按钮靠左、指标靠右”由行布局负责（第五轮：“按钮与 metric 两行合并
一行，按钮在左，metrics 在右侧，中间 stretch 隔开”）。

**只有数值带框**（第十轮，用户：“这个框太小了，看起来不自然，且不用给label加框，
只给要显示数值的地方加框；上下文那个数值直接写在进度条里面，不写在外面，也不用加
框”）：标签是普通文字，数值套 `#metricValueBox` 那层读数窗（field_bg 底 + 1px 边框
+ 圆角 + 宽松内边距）；上下文 = 标签 + 计量条，百分比画在**条里面**（`_CtxMeter`）。
条带自身始终透明无边框。

结构（左→右）：3 格 + 计量条 + 1px 分隔线 + 4 格（第八轮删掉「实时 / 累计」两个
组标题：用户"live 和 session 这两个 label 不需要，光占地方" —— 分组已经由条带的
外边框 + 中间那条分隔线表达，累计语义在每格 tooltip 里）。**布局按内容走**（第二轮：“不要每个指标都均匀排布啊，比如 prefill
这些就一个数字，占那么大位置干嘛，留那么多空白”）：格宽 = 标签 + 定宽数值
（标签与数值之间固定 4px），组内固定间距 _CELL_GAP；行内**没有任何弹性项**
（第五轮：能与富余宽度抢地方的只应该是行级 stretch，条带内再留空隙就又会长出
空白）。每格的 x 只取决于条带宽度、与数字位数无关 → 1Hz 刷新整行不抖动。

相对第一版（用户反馈"太丑陋，不美观，不协调"）修掉的八件事：

1. 符号图标全部删除 —— 旧的 ≫ ▸ ◔ Σ Σ Σ ⊙ 在 Consolas 里没有字形，逐个
   回退到不同字体/字号/基线（◔ 在 Windows 下渲染成一个怪方块，三个 Σ 完全
   重复），是"不协调"的最大来源。分组先改由组标题 + 留白承担，第八轮又删掉
   组标题、改由外边框 + 分隔线 + 留白承担。
2. 内层格 widget 强制透明 —— 它们是普通 QWidget，被全局
   ``QWidget { background: win_bg }`` 各自刷了一块底色，盖在条带自己的
   hover_bg 上 → 深浅不一的"补丁"感。
3. 数值列定宽（_ValueColumn：格里叠一个透明的“最宽取值”strut，列宽 = 最宽
   取值的宽度，与当前文本无关）+ 右对齐，单位降为次要色小字（旧版
   ``812.4t/s`` 挤成一坨）；``t/s`` 前留一格空隙，``%`` 按排版习惯紧跟数字。
4. 上下文计量条：与文字同基线垂直居中的内联细条，**定长 _BAR_W 100px**
   （两轮反馈：“34px 短到看不出比例”→ 曾做成随窗口拉长 60→240；与按钮合一行
   后富余宽度归行级 stretch，因此定为 100px：比例一眼可读，又只把条带最小宽度
   抬高 40px）；轨道从 hover_bg（在 hover_bg 条带上根本看不见，绿块像凭空飘着）
   改为 border 色，填充按 绿→70% 琥珀→90% 红。它是**条带的直属项**而不是 ctx
   格内的 widget —— 放在格里，拉伸会把格子撑出一块死空间；数字排在条**右侧**
   （第十轮：“那个数值直接写在进度条里面，不写在外面，也不用加框” → 条内居中，
   填充侧白字 / 轨道侧正文色各裁一半，见 _CtxMeter）；tooltip 挂在格与条两处。
5. 未运行 / unix socket：第七轮（2026-11）定案为**七格常驻** —— 曾经折叠成
   一句提示（"服务未启动 · 启动后…"），用户指着那行说"这行文字换成指标值，
   即不用启动后再显示出来，一直都显示" → 提示语删除，未运行时七格仍在原位，
   "为什么还没有数值"进 tooltip 的那一行身份（未启动 / unix socket 无 HTTP 端点；
   “未勾选 --metrics”的导航引导只在**运行中且端点不支持**时才说 —— 那才是行动点，
   没启动时用户能做的只有先把服务跑起来）。行高 34px 常驻，E11 最小高度算术不变，而且
   条带只有一种排版 → 窗口最小宽度不随服务启停变化。**哪格是 0、哪格是破折号**：
   速度格未知 → 定宽灰破折号；累计组与**上下文条** → **0**（用户：“上下文
   进度条仅在有活动时显示，停止了就不显示了，应该一直显示，哪怕刚开始时也
   应为 0”）——
   0 是个值、破折号是“读不到”；服务停掉后 KV 随之消失，0% 就是真实情况。只有
   **读不到**（/slots 被关、unix socket）时上下文条才回到破折号（见 _set_ctx_zero）。
6. 组内 1px 竖分隔线删除（旧版 7px 间距让线贴着下一个字，像断笔的 ``|Σ``），
   只留两组之间一条。
7. 格标签用 ElidingLabel（最小宽度 0）：整行最小宽度（捆绑字体实测）
   ~559px，与参数面板固定组的 ~720px 地板同量级 —— 与按钮合行后行最小宽
   = 按钮 ~200 + 条带 ~559 ≈ 760 → 窗口最小宽度 ~947 → ~990（第五轮合并两行
   的代价，已实测告知用户并选定）。窄窗口下标签省略号，数字永不裁（定宽列）。
8. 行内不再有状态点（第五轮：“metric 行那个绿色小圆点删了或者移动到运行时
   间那”）→ 运行状态改由**状态栏那一个点**表达（MainWindow._update_run_indicator，
   画出来的 8px 圆角块，四态染色，位置就在运行时长前面），本条带成为纯数据；
   “运行中但 /slots 与 /metrics 都不应答”仍由本模块判定（endpoints_alive()），
   避免两处各写一套语义。
9. **阶段提示（2026-11 尾轮，用户：“在不同阶段（prefill/decode）时，它的 label
   最好能显示个不同颜色，用于指示提醒用户当前在哪个阶段”）**：`diff_slots` 额外
   发布 `prefilling` / `decoding`（判据 = 该 slot `is_processing` 且 `n_decoded`
   是否为 0；**不用 `processed < n_prompt_tokens`** —— 投机解码会把生成 token 追进
   那段历史，使该式在生成期间也成立 → 阶段永远卡在 prefill，同一个坑见
   `ui/live_stats.py` 的 ctx 注释），条带据此给**正在进行的阶段那一格的格标签**染
   阶段色（prefill 蓝 / decode 绿，其余保持 info 灰；多 slot 混合阶段时两个同时亮，
   空闲与停服回灰）。阶段色两套主题各一份，经 `set_theme_colors(..., prefill,
   decode)` 从 `MainWindow._THEME_PALETTES` 的 `phase_prefill` / `phase_decode` 注入
   （暗色下浅蓝/浅绿在 `win_bg` 上对比不够，换亮一档）；模块里 `_PHASE_PREFILL` /
   `_PHASE_DECODE` 只是浅色默认值。**只上色、不加粗**（粗体会改标签宽度，而整行按
   内容定宽、E11 的最小宽度就是从这条量出来的），且只在阶段**变化**时重染（/slots
   一秒一帧，`setStyleSheet` 会重新 polish ElidingLabel）。不给**数值**上阶段色：
   数值的颜色已经编码了“实时 / 上一段均值 / 未知 / 最后已知值”，再叠一层就没人读
   得懂。阶段本身不进 tooltip：颜色已经把这件事说了，再追一句就是“刻意”。
10. **tooltip 的固定三槽（尾轮，用户：“tooltip 里不要刻意地写，重新整体规划
    下显示的内容”）**：`_tip(key, value, note)` 是七格的唯一入口，**缺的不占行**：
    ① 全名（`_FULL_NAMES`，格标签会被省略号截断，这里不会）；② **精确值**
    （屏上那个可能缩成了 1.5K；速度带单位，破折号不占行）；③ **一行身份**，
    只在“这**不是**主来源的当前值”时出现：上一段的均值 / 最后已知值 / 读不到的
    原因（服务未启动、unix socket 无 HTTP 端点、/slots 端点已关闭、当前没有该类
    活动）。**第三行与次要色同进同出**（同一个分支给出，不会只改一边）。含义 /
    算法 / 数据来源 / 刷新频率 这类长期说明全部删除（选定两行结构），“本任务
    命中率”这类额外数据也一律不再挤进 tooltip（代价：这个值现在无处可查）。
    `tests/test_live_metrics.py::test_bar_tooltips_share_one_shape_name_value_optional_identity`
    钉住形状与旧文案不得复活。

左组（实时，/slots @1s）：Prefill · Decode · 上下文（内联计量条：正常 →
70% 琥珀 → 90% 红）。右组（服务启动以来的累计，/metrics @5s，需勾选
--metrics）：输入 · 缓存 · 输出 · 命中。格标签刻意缩短（总输入→输入…），
全称在 tooltip 第一行；组标题删除后“累计”这层意思只剩两组之间的留白与名称本身
（尾轮 tooltip 重写后不再逐格写“服务启动以来…”，见第 10 条）。
右组的"还没有数据"是 **0**（计数从 0 起算，第八轮），**上下文条也是 0%**
（尾轮：常驻，不再只在有活动时才显示）；只有速度格（当前速率）的"还没有
数据"是破折号。累计值只要非 0 就一直显示：`/metrics` 半路挂了也用次要色保留
最后已知值（转次要色 + tooltip 那一行身份说原因），只有从没读到过数时才回到破折号。

** Prefill / Decode 的空档不再是破折号，而是上一段的均值 **（2026-11 尾轮，用户：
“没有活动时应显示上一段请求处理的平均值，仅前一段连续活动、不是全程平均；首次
没处理可以保持 —”）：本窗口无该类活动时（服务空闲，**或正处在另一个阶段**——
decode 期间的 Prefill 格），改显示上一段连续活动的均值，拿 `slot print_timing` 里
服务端自己算的单任务累计值（→ `ui/log_parser.py` 的 `prompt_tps_last` /
`decode_tps_last` → `MainWindow._parse_log_line` → `set_last_task_speeds`）：它天然就是
“上一段”而非累计，也没有 1s 轮询差分的边界误差。均值有**两层**：阶段运行中的
`prompt processing, … / 2792.41 tokens per second` 与 `n_gen = …, tg = 104.02 t/s`（每约 1s /
3s 一行），然后阶段结束时那对精确的 `prompt eval time` / `eval time` 再覆盖 —— 只靠后者
就是用户报的 bug：“第一次 prefill 完了到 decode 时 prefill 显示 -，第二次才有”，因为
`print_timings()` 只在任务结束分支里调，第一个任务的 decode 阶段拿不到本任务 prefill
的均值。画**次要色**（与破折号同族）+ tooltip 说明，免把静止的历史均值读成当前速度；
一个任务都没跑过（无该日志行）时仍是破折号，停服时清空（`set_running(False)`）。短
prefill（<3s）与短生成（<100 token）服务端不打阶段内那两行 → 那种任务的第一个阶段空档
仍是破折号，**宁可破折号也不拿 1s 轮询差分数估算**（短段会低估几倍）。依赖 slot INFO：
启动器把 `log_verbosity` 钉为 4 且不采纳 --help 解析值 → 默认配置下必然在；用户手动
降到 3 可能没有 → 退化成现有的破折号，**不会编出一个错的数**。

数值颜色（HTML span）由 MainWindow 经 set_theme_colors 从主题色板注入
（QSS 管不进 rich text）；标签/组标题/提示是 ElidingLabel，颜色走 palette
（它们自绘，QSS color 无效）。
"""
from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtWidgets import (QStyle, QStyleOptionProgressBar, QStylePainter,
                             QWidget, QLabel, QHBoxLayout, QGridLayout,
                             QProgressBar, QSizePolicy)
from PyQt6.QtGui import QFont, QPalette, QColor

from core.i18n import get_language, t
from core.params_schema import PARAMS_BY_KEY, TAB_TITLES
from ui.basic_panel import ElidingLabel


def _metrics_nav():
    """累计指标的**准确导航路径**（tooltip 用）：模式 → 标签页 → 参数行。

    三个名字全部从 schema / TAB_TITLES 里取（只去掉行标签尾部那个冒号），**不手写**
    —— 手写的那份会与真实 UI 漂移（原来写的是“在服务页勾选「Prometheus 指标」”，
    而那个标签字面其实叫「Prometheus指标 (--metrics)」、它在「服务」标签页里、
    且只有高级模式看得到；用户：“这个表述不正确，用准确的导航语言来说”）。
    英文模式下同样自动跟着翻译走（Advanced Mode → Server → "Prometheus Metrics
    (--metrics)"），引号也按语言换（中文「」/ 英文 ""）。
    """
    zh = get_language() == "zh"
    parts = (t("高级模式"),
             t(dict(TAB_TITLES)[PARAMS_BY_KEY["metrics"].tab]),
             t(PARAMS_BY_KEY["metrics"].label.rstrip(":")))
    return " \u2192 ".join(f"「{p}」" if zh else f'"{p}"' for p in parts)

# 计量条语义色（与运行状态指示同族：绿=正常、琥珀=警告、红=危险）。状态点的
# 四色已随状态点一起搬到 MainWindow._update_run_indicator。
_BAR_GREEN = "#16a34a"
_BAR_AMBER = "#d97706"
_BAR_RED = "#dc2626"

# 阶段色（**浅色主题默认值**；暗色由 MainWindow 从主题色板注入更亮的同名色）：
# prefill = 应用通用强调蓝，decode = “运行中”那个绿（状态点 / 版本行同一族）。
# 只给**格标签**上色：数值的颜色已经编码了“实时 / 上一段均值 / 未知”，再叠一层
# 阶段色就没人读得懂了。也**不加粗**：这一行按内容定宽，粗体会让标签宽度在阶段
# 切换时跳几个像素（整行布局按内容走，E11 的最小宽度也是从这条量出来的）。
_PHASE_PREFILL = "#2563eb"
_PHASE_DECODE = "#16a34a"

# 数值列的定宽样本（该指标的最宽取值 + 单位）：列宽 = 这个样本的宽度，与当前
# 文本无关 → 1Hz 刷新整行不抖动、数字右对齐到同一列（实现见 _ValueColumn 的
# strut；刻意不用 QFontMetrics 量宽，也不用 &nbsp; 填充 —— 前者可以量到垃圾值，
# 后者依赖“nbsp 与数字同宽”这个字体前提）。
_WIDEST = {
    "prefill": "9999.9 t/s", "decode": "9999.9 t/s",   # ≥1e4 收为整数（≤ 5 位）
    "ctx": "100.0%",
    "total_in": "999.9M", "cached_in": "999.9M",       # K/M/G/T 都是 6 字
    "total_out": "999.9M",
    "hit_rate": "100.0%",
}
# 累计 counter 的量级档（从大到小，与 _fmt_tokens 一起决定输出宽度上限）
_TOKEN_TIERS = (("T", 1_000_000_000_000), ("G", 1_000_000_000),
                ("M", 1_000_000), ("K", 1_000))
# 单位（次要色小字，跟在数值后；不可用时仍渲染，保持列宽不变）
_UNITS = {"prefill": "t/s", "decode": "t/s", "ctx": "%", "hit_rate": "%"}
# 累计组的"一次任务都没跑过"取值（第八轮：开始就是 0，不是破折号）。列宽由
# _WIDEST 的 strut（再加一个数字位的余量）决定，与文本无关 → 0 与 999.9M 占同一
# 宽度，不抖动。
_ZERO_TEXT = {"total_in": "0", "cached_in": "0", "total_out": "0",
              "hit_rate": "0.0"}
# 上下文格的“没有内容”：与累计组同一套规矩（0 是个值，不是“读不到”），
# 而且服务停掉后 KV 随之消失，0% 就是真实情况（见 _set_ctx_zero）
_CTX_ZERO_TEXT = "0.0"
# 数值字体（与 _THEME_TEMPLATE 里 #metricValue 的 QSS 一致：Consolas 11px 粗体）
_VALUE_PX = 11

# 内容驱动的水平留白（2026-11 用户反馈：不要每格等宽平摊 —— 一个数字占一整列、
# 标签与数字之间一大块空白）：格宽 = 内容宽，组内固定间距；行内无弹性项，
# 富余宽度全归 MainWindow 合一行里的那条 stretch。
# 第九轮：每格自己就是一颗**带边框的芯片**（chip），所以格间距可以收得很紧
# （旧 18px 是"没有边框、只能靠留白分组"时代的值）。
# 第十一轮（用户：“这些框看起来比文字矮，视觉不统一，起码跟进度条一样高吧，视觉上
# 整体优化下”）：行内两个"读数控件"（数值框 / 计量条）**共用一个高度 `_FIELD_H`**。
# 上一轮框高由 QSS 竖向 padding + 标签自己的行高撑出来（Consolas 11px ≈ 13px）→
# 量出来比计量条矮一截，一排里高高低低；改成代码里一个数给两处用，永远齐平。
_CELL_GAP = 14        # 相邻两个指标之间
_CAP_GAP = 8          # ctx 里：标签 → 计量条
_VALUE_GAP = 6        # 标签 → 数值框，固定不变
_GROUP_GAP = 22       # 两组之间（实时 ⇄ 累计），比 _CELL_GAP 再宽一档就够读出分组
_FIELD_H = 20         # 读数控件统一高度：数值读数框 = 计量条 = 20px（够装 11px
                      # 粗体字 + 上下各 3px；行高 34px 里还剩上下各 7px）
_BAR_W = 100          # 上下文计量条定长（“34px 太短”→ 100px：比例可读，且只把
                      # 条带最小宽度抬高 40px → 窗口最小宽度 ~947 → ~990）


def _fmt_tokens(value):
    """累计 counter 紧凑格式：≥1e3 → K、≥1e6 → M、≥1e9 → G、≥1e12 → T。

    **输出宽度有上限（最宽 6 字，= _WIDEST 的 strut）**，因为超宽就是“数字显示
    不全”（第十一轮用户：“输入 缓存 输出 这个框子有点短啊，数字多一些就显示不全
    了”）。两件事保证这一点：

    * **进档比舍入早一步**：旧版先选档再除，999_999 → `f"{999.999:.1f}K"` =
      "1000.0K"（7 字）把列宽撑穿 → 数字被裁。现在舍入后 ≥ 1000 就进上一档
      （999_999 → "1.0M"），而 "1000.0K" 本来也不是人想要的写法。
    * **最高档封顶**：到 T 还进不了档（≥ 1e15）就改用整数（"9995T"），不再带
      ".0" 白白多占两位。
    """
    value = max(float(value), 0.0)
    for i, (suffix, div) in enumerate(_TOKEN_TIERS):
        if value >= div:
            if i > 0 and round(value / div, 1) >= 1000.0:
                suffix, div = _TOKEN_TIERS[i - 1]
                return f"{value / div:.1f}{suffix}"
            if round(value / div, 1) >= 1000.0:      # 最高档没有上一档可进
                return f"{value / div:.0f}{suffix}"
            return f"{value / div:.1f}{suffix}"
    return str(int(value))


def _fmt_speed(value):
    """速度：常规一位小数；破万（小模型/全缓存）收为整数，保证 ≤ 6 字。"""
    return f"{value:.0f}" if value >= 10_000 else f"{value:.1f}"


class _ValueColumn(QWidget):
    """定宽数值列：同一格里叠「当前数值」+「最宽取值占位标签（strut，完整
    文本但完整透明）」。

    两者都在同一个 QGridLayout 单元里 → 格宽 = 两者最大宽度 = strut 宽度，
    只取决于字体与最宽取值，**与当前文本无关** → 数字右对齐到固定列、1Hz
    刷新整行不抖动。

    为什么不用 setFixedWidth(QFontMetrics(...).horizontalAdvance(样本))：量出来
    的数可以是垃圾 —— offscreen 平台没有真实字体库（量得 9px），而真实运行时
    用户的字体库也可能被第三方“字体美化”文件搞坏（本仓库已有 Inter / Segoe UI
    被顶替的前科）。strut 由同一个排版引擎量宽，不存在“量到一个值、渲染到
    另一个值”的可能，也不需要监听 FontChange 重度量。

    数值标签填满格子并右对齐；单位在同一标签里（次要色 span），因此数字的
    右边缘固定在“格宽 - 单位宽”处。
    """

    def __init__(self, widest, parent=None):
        super().__init__(parent)
        self.setObjectName("metricValueCol")
        lay = QGridLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        # strut：撑宽度用，文字透明（inline sheet 赢过 QSS 的 color）。
        # 前面多垫一个 "0" = **多留一个数字位**（第十一轮：“数字多一些就显示
        # 不全了”）：strut 是透明的，只有宽度意义，所以拿它要余量是字体量出来的
        # （不是写死 px，见类注释），格式化函数哪天多吐一位也不会被裁。
        strut = QLabel("0" + widest)
        strut.setObjectName("metricStrut")
        strut.setStyleSheet("color: transparent; background: transparent;"
                            " border: none;")
        strut.setFont(_value_font())
        strut.setMinimumWidth(1)
        self._strut = strut
        lay.addWidget(strut, 0, 0)
        self.value = QLabel()
        self.value.setObjectName("metricValue")
        self.value.setFont(_value_font())
        # 右对齐：数字右边缘固定（= 格宽 - 单位宽）
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight
                                | Qt.AlignmentFlag.AlignVCenter)
        # 后参加的子 widget 画在上层（与 strut 完全重叠）
        lay.addWidget(self.value, 0, 0)

    def minimumSizeHint(self):
        """数值列**不许被压扁**：最小宽度 = strut 的宽度（= 该指标最宽取值的宽度）。

        2026-11 第五轮实测：容器（合一行）比布局最小值还窄时 QLayout 会把每一项
        压到自己的最小值以下，数值列原先最小宽是 1 → 被压到 30px，数字看不见，而
        这行的全部意义就是那几个数字。拿 strut 的 sizeHint 当下限：与渲染出自同一
        个排版引擎（不是 QFontMetrics，见类里的注释）→ “量到的”与“画出来的”永远是
        同一个数，字体 / DPI 变了自动跟着变。
        hidden 的 QWidget 报无效 sizeHint(-1)，所以缓存最后一次真实宽度。
        """
        own = super().minimumSizeHint()
        strut_w = self._strut.sizeHint().width()
        if strut_w > 0:
            self._strut_w = strut_w
        return QSize(max(own.width(), getattr(self, "_strut_w", strut_w)),
                     own.height())



def _value_font():
    """数值字体：Consolas 11px 粗体（与 _THEME_TEMPLATE 里 #metricValue /
    #metricStrut 的 QSS 一致，strut 与数值必须同字体才能量准）。"""
    f = QFont("Consolas")
    f.setPixelSize(_VALUE_PX)
    f.setBold(True)
    return f


def _qcolor(value, fallback):
    """颜色字符串 → QColor，**不可解析时退到 fallback**。

    只给 `_CtxMeter.paintEvent` 用：paintEvent 是 C++ 绘制路径调用的虚函数，在里面
    抛异常（`QColor("...")` 对垃圾字符串就是 ValueError）不会变成一条 traceback，
    而是整个进程静默 fastfail（与本仓库已知的 eventFilter 构造期崩溃同一家族）。
    颜色现在全来自主题色板，但“主题 token 改了个名”不该变成打不开的应用。
    """
    color = QColor(value) if value else QColor()
    return color if color.isValid() else QColor(fallback)


class _CtxMeter(QProgressBar):
    """上下文计量条：**百分比写在条里面**（居中），条外不排数字、也不加框。

    第十轮（用户：“上下文那个数值直接写在进度条里面，不写在外面，也不用加框”）。
    两个坑：

    * **不借 ``setFormat()`` 显示文字**：format 里 ``%`` 是替换符（``%p`` / ``%v``
      / ``%m``），而我们要显示的就是带百分号的 "62.0%" —— 这种文本走 Qt 的格式解析
      规则属于"看着能行、换个值就翻车"。这里自己画，条里显示什么只由 ``set_text`` 说。
    * **文字分两侧画**：数字居中，占用 62% 时字正好跨在「绿填充」与「浅轨道」的
      边界上，任何单一颜色总有一侧读不清。于是同一个 rect 画两遍、各裁一半：填充侧
      白字、轨道侧正文色，跨不跨界都清楚。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._label = ""
        self._label_muted = False
        self._text_color = "#1a1a2e"
        self._muted_color = "#666"
        self._fill_color = "#ffffff"

    def text(self):
        """条里现在画的那个文本（Python 侧读取用：tooltip / 测试）。

        ``QProgressBar::text()`` 不是虚函数，Qt 自己的绘制路径不会走到这里（我们
        本来就 ``setTextVisible(False)`` + 自绘），所以这只是个便利访问器，让
        ``_tiles[key][1].text()`` 对七个指标含义一致。
        """
        return self._label

    def set_text(self, text, muted=False):
        self._label = text or ""
        self._label_muted = muted
        self.update()

    def set_colors(self, text, muted):
        self._text_color = text
        self._muted_color = muted
        self.update()

    def paintEvent(self, event):
        painter = QStylePainter(self)
        opt = QStyleOptionProgressBar()
        self.initStyleOption(opt)
        opt.text = ""           # 文字自己画（下面分两侧），别让 style 再画一遍
        # CE_ProgressBar 属于 ControlElement（drawControl），不是 ComplexControl；
        # 枚举名写错 = paintEvent 里抛异常 = 从 C++ 绘制路径逃出去 = 进程
        # 静默 fastfail（no traceback、faulthandler 也看不见），所以这里只写
        # 能静态确认的东西，颜色也不例外（见 _qcolor）。
        painter.drawControl(QStyle.ControlElement.CE_ProgressBar, opt)
        if not self._label:
            return
        painter.setFont(_value_font())
        rect = self.rect()
        if self._label_muted:
            painter.setPen(_qcolor(self._muted_color, "#666666"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._label)
            return
        total = max(self.maximum() - self.minimum(), 1)
        filled = int(round((self.value() - self.minimum()) * rect.width()
                           / float(total)))
        filled = max(0, min(filled, rect.width()))
        track = QRect(rect.left() + filled, rect.top(),
                      rect.width() - filled, rect.height())
        chunk = QRect(rect.left(), rect.top(), filled, rect.height())
        for clip, color, fallback in ((track, self._text_color, "#1a1a2e"),
                                      (chunk, self._fill_color, "#ffffff")):
            painter.save()
            painter.setClipRect(clip)
            painter.setPen(_qcolor(color, fallback))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._label)
            painter.restore()


class LiveMetricsBar(QWidget):
    """单行 34px（带 1px 外边框）：3 格 + 计量条 + 1px 分隔线
    + 4 格，同一条圆角带（格按内容定宽，行内无弹性项，宽度 Maximum = 内容宽）。

    状态入口：set_running / set_no_http（unix socket 启动，无 HTTP 端点）/
    set_metrics_checked / set_metrics_state（"available" | "unsupported" |
    "error"）/ set_slots_state（"available" | "off"）/ update(stats_dict) /
    set_last_task_speeds(...) / set_theme_colors(text, muted, info)；
    endpoints_alive() 供状态栏的运行状态点使用。数值经 update() 灌入，其余状态
    变化只重绘文案与 tooltip。未运行 / 无 HTTP → 同一批格子改为定宽灰破折号 +
    说明性 tooltip（不再有"提示态"）。

    ``_tiles[key] = (cell_widget, value_label, bar_or_None)``：tooltip 挂在
    格上（整格可悬停），数值文本在 value_label（HTML）。
    """
    _SPEED_KEYS = ("prefill", "decode")
    _METRIC_KEYS = ("total_in", "cached_in", "total_out", "hit_rate")
    _ALL_KEYS = _SPEED_KEYS + ("ctx",) + _METRIC_KEYS
    # 格标签 i18n 键（中文原文字面量，test_i18n / 显式覆盖测试钉住）
    _LABELS = {
        "prefill": "Prefill",
        "decode": "Decode",
        "ctx": "上下文",
        "total_in": "输入",
        "cached_in": "缓存",
        "total_out": "输出",
        "hit_rate": "命中",
    }
    # 每格在 tooltip 里的**全称**（格标签会被省略号截断，这里不会）
    _FULL_NAMES = {
        "prefill": "Prefill 速度",
        "decode": "Decode 速度",
        "ctx": "上下文占用",
        "total_in": "输入 token",
        "cached_in": "缓存命中输入 token",
        "total_out": "输出 token",
        "hit_rate": "缓存命中率",
    }
    # tooltip 第二行给的是**精确值**（屏上那个是被缩写过的 1.5K / 0）：零值这一档
    # 在常驻排版里用得到，非零值当场算（见 _render_right）
    _EXACT_ZERO = {"total_in": "0 tokens", "cached_in": "0 tokens",
                   "total_out": "0 tokens", "hit_rate": "0.0%"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("liveMetricsBar")
        self.setFixedHeight(34)
        # Maximum：只长到内容宽，再多一寸也不要 → 合一行里那条 stretch 才能
        # 拿到富余宽度（把本行推到右端）。宽度不够时仍可缩到最小（标签省略）。
        self.setSizePolicy(QSizePolicy.Policy.Maximum,
                           QSizePolicy.Policy.Fixed)
        self._last = {}
        # 上一段连续活动的均值（服务端 print_timing）：{key: (tps, tokens)}。
        # 实时速率为空时拿它顶位（见 _speed_from_last_task），停服时清空。
        self._last_task = {}
        self._running = False
        self._no_http = False
        self._metrics_checked = False
        self._metrics_state = "unknown"
        self._slots_state = "unknown"
        # 默认浅色主题值；MainWindow 构造后与 _apply_theme 都会同步
        self._text = "#1a1a2e"
        self._muted = "#666"
        self._info = "#6b7280"
        # 当前阶段（用户：“不同阶段时 label 最好显示个不同颜色，用于指示当前在哪个
        # 阶段”）：("prefill",) / ("decode",) / 两者（多 slot 混合阶段）/ ()
        self._phases = ()
        self._phase_colors = {"prefill": _PHASE_PREFILL, "decode": _PHASE_DECODE}
        self._tiles = {}

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(0)

        # 七格常驻（第七轮）：未运行也在这里（速度格 = 定宽灰破折号，上下文与
        # 累计组 = 0）。行内无弹性项：
        # 条带宽度 = 内容宽，靠右由外层合一行（MainWindow.control_bar）负责。
        # 「实时 / 累计」两个组标题于第八轮删除（用户："live 和 session 这两个
        # label 不需要，光占地方"）：分组交给「数值读数框 + 两组之间一道比组内宽的
        # 缝」，"是不是服务启动以来的累计"每格 tooltip 里都写着。省下的
        # 宽度直接换成窗口最小宽度变小（合一行是它的宽度约束）。
        for i, key in enumerate(self._SPEED_KEYS):
            if i:
                row.addSpacing(_CELL_GAP)
            row.addWidget(self._make_cell(key), 0,
                          Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(_CELL_GAP)
        # 上下文（第十轮）：标签 + 计量条，**百分比写在条里面** —— 条外不再排数字，
        # 也不给它加框（用户：“那个数值直接写在进度条里面，不写在外面，也不用加框”）
        row.addWidget(self._make_ctx_cell("ctx"), 0,
                      Qt.AlignmentFlag.AlignVCenter)
        # 两组之间不画竖线（旧 #metricGroupSep 已删）：每个数值自己就是一个框，
        # 两组之间一条比 _CELL_GAP 宽的缝就足够读出分组，竖线夹在框之间反而杂
        row.addSpacing(_GROUP_GAP)
        for i, key in enumerate(self._METRIC_KEYS):
            if i:
                row.addSpacing(_CELL_GAP)
            row.addWidget(self._make_cell(key), 0,
                          Qt.AlignmentFlag.AlignVCenter)

        # 布局最小宽度的单调最大值，见 min_content_width()：合一行（按钮 + 这条
        # 带）窄到一定程度时 QLayout 会把每一项都压到自己的最小值以下，数字会被
        # 切掉 —— 所以 MainWindow._sync_panel_min 必须把这条带的地板算进**窗口**
        # 最小宽度。这里不 setMinimumWidth：那会让"窄于地板"在布局与测试里不可表示。
        self._floor_w = 0

        self._apply_caption_colors()
        self._render()

    def min_content_width(self):
        """本条带必须拿到的宽度 = **指标态的布局最小宽度**（单调最大，两种模式同值）。

        2026-11 第五轮。`MainWindow._sync_panel_min` 手算窗口最小宽度（绕开 E11
        快捷开关组的自锁），而合一行不在 tab 页里、那个手算看不见它 —— 行比
        「按钮 sizeHint + 本条带最小宽度」还窄时数字会被切掉，所以由这里报数。

        * 取「见过的最大布局最小宽度」：QSS 的 11px 等宽字体要等 polish 才生效，
          构造期量到的是小值（本环境实测 344 → 就位后 616），单调最大保证它只会
          朝正确的方向收敛，也保证服务启停都不改变这个数。
        * 由布局自己量（同一个排版引擎），不用 QFontMetrics：见 _ValueColumn 的
          strut 注释。
        """
        current = self.layout().minimumSize().width()
        if current > self._floor_w:
            self._floor_w = current
        return self._floor_w

    # ------------------------------------------------------- 构造小工具
    def _make_cell(self, key):
        """一个指标：普通文字标签 + **只有数值带框**，宽度 = 内容宽。

        第十轮（用户：“不用给label加框，只给要显示数值的地方加框”）：`#metricCell`
        是透明容器，`#metricValueBox` 才是那层读数窗（field_bg 底 + 1px 边框 + 圆角
        + 宽松内边距）。标签是 ElidingLabel（最小宽度 0）、数值列定宽（strut）→
        格宽与数字位数无关，1Hz 刷新不抖动；行内无弹性项 → 窗口拉伸也不改排版。
        """
        cell = QWidget()
        cell.setObjectName("metricCell")     # 透明容器：边框只在下面的 #metricValueBox
        lay = QHBoxLayout(cell)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(_VALUE_GAP)
        cap = ElidingLabel(t(self._LABELS[key]))
        cap.setObjectName("metricLabel")
        lay.addWidget(cap)
        box = QWidget()
        box.setObjectName("metricValueBox")
        # 高度由**代码**钉（不在 QSS 里写 min-height + padding 的算术）：这一轮的
        # 要求就是"跟进度条一样高"，那两者必须读同一个常量；靠 padding 撑高则实得
        # 高度 = padding + 标签行高（字体一变就漂），对不上计量条。
        box.setFixedHeight(_FIELD_H)
        # 内边距**不在这里写**：Qt 把样式表算出的 padding 当作 contentsMargins，
        # 两处都写会叠两遍（QSS 里只留横向 padding，竖向写会把 20px 压成放不下
        # 13px 高的数字 → 字溢出到边框上）。
        box_lay = QHBoxLayout(box)
        box_lay.setContentsMargins(0, 0, 0, 0)
        box_lay.setSpacing(0)
        column = _ValueColumn(_WIDEST[key])
        box_lay.addWidget(column, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(box, 0, Qt.AlignmentFlag.AlignVCenter)
        self._tiles[key] = (cell, column.value, None)
        cell.setProperty("cap", cap)
        return cell

    def _make_ctx_cell(self, key):
        """ctx 这个指标：普通文字标签 + 计量条，**百分比写在条里面**，不加框。

        第十轮（用户：“上下文那个数值直接写在进度条里面，不写在外面，也不用加框”）。
        条定长 _BAR_W（不参与拉伸），高 _FIELD_H（与数值读数框同高，第十一轮），
        百分比写在里面；条外没有第二个数字部件，`_tiles["ctx"]` 的「数值」与
        「计量条」是同一个 widget。
        """
        cell = QWidget()
        cell.setObjectName("metricCell")     # 透明无边框（ctx 不加框，用户明确要求）
        lay = QHBoxLayout(cell)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        cap = ElidingLabel(t(self._LABELS[key]))
        cap.setObjectName("metricLabel")
        lay.addWidget(cap)
        lay.addSpacing(_CAP_GAP)
        meter = self._make_meter()
        lay.addWidget(meter, 0, Qt.AlignmentFlag.AlignVCenter)
        # "数值"就是计量条本身：ctx 没有第二个部件，百分比写在条里（_set_cell 走
        # set_text），tooltip 同时挂在格与条上，整块都能悬停。
        self._tiles[key] = (cell, meter, meter)
        cell.setProperty("cap", cap)
        return cell

    def _make_meter(self):
        """上下文计量条：**定长 _BAR_W × 统一高 _FIELD_H**，百分比画在里面。

        定长而不是弹性：与启动按钮合一行后，富余宽度归行级 stretch（用户要
        “中间 stretch 隔开”），条带自己只能贴内容（Maximum 策略）。高度与数值
        读数框共用 `_FIELD_H`（第十一轮：“起码跟进度条一样高吧” —— 一个常量两处
        用，字才不会再显得比条矮、条比字高）；垂直居中、tooltip 与 ctx 格同步
        （见 _set_cell）。"""
        bar = _CtxMeter()
        bar.setObjectName("metricMiniBar")
        bar.setFixedSize(_BAR_W, _FIELD_H)
        bar.setRange(0, 1000)
        bar.setValue(0)
        bar.setTextVisible(False)     # 文字由 _CtxMeter.paintEvent 自己画（分两侧）
        return bar

    def set_theme_colors(self, text, muted, info=None, prefill=None,
                         decode=None):
        """主题同步：数值 HTML 的 span 颜色 + ElidingLabel 的 palette 色。

        MainWindow 构造后与每次 _apply_theme 调用（QSS 管不进 rich text，
        ElidingLabel 自绘也只认 palette）。`prefill` / `decode` 是**阶段色**：
        暗色主题下浅色的蓝/绿在 `win_bg` 上对比不够，所以两套主题各给一份。
        """
        if text:
            self._text = text
        if muted:
            self._muted = muted
        if info:
            self._info = info
        if prefill:
            self._phase_colors["prefill"] = prefill
        if decode:
            self._phase_colors["decode"] = decode
        ctx = self._tiles.get("ctx")
        if ctx is not None:
            # 条里的百分比是自己画的（QSS 管不到 paintEvent 的 pen）
            ctx[1].set_colors(self._text, self._muted)
        self._apply_caption_colors()
        self._render()

    def _caption_style(self, lab, color, bold):
        """格标签 / 组标题 / 提示都是 ElidingLabel：它自绘只认 palette Text
        （QSS color 无效），而 app 级 QWidget 规则会在 show 后重新 polish 掉
        代码里设的 palette/font —— 所以两样都给：inline sheet（赢过
        re-polish，定 11px + 粗体）+ palette（喂 paintEvent）。与
        #secondaryInfo 的 _sync_secondary_info_labels 同款做法。
        """
        lab.setStyleSheet("color: %s; background: transparent; font-size: 11px;"
                          % color
                          + (" font-weight: bold;" if bold else ""))
        pal = lab.palette()
        pal.setColor(QPalette.ColorRole.Text, QColor(color))
        lab.setPalette(pal)

    def _caption_color(self, key):
        """格标签颜色：正在进行的阶段用**阶段色**，其余一律 info（次要灰）。

        “正在跑的那一格自己亮着”比“两格都在、颜色互换”更好读：空闲时两格都是
        灰色，一眼就知道没在活动。
        """
        return self._phase_colors[key] if key in self._phases else self._info

    def _apply_caption_colors(self):
        """格标签：当前阶段染阶段色，其余 info（都随主题同步）。"""
        for key in self._ALL_KEYS:
            cap = self._tiles[key][0].property("cap")
            if cap is not None:
                self._caption_style(cap, self._caption_color(key), False)

    def _note_phases(self, stats):
        """从这一帧 /slots 差分里读出当前阶段，**只在变化时**重染格标签。

        /slots 每秒一帧，而 `setStyleSheet` 会让 ElidingLabel 重新 polish；阶段是
        稳态量（一秒一跳的是数值），没变就什也不做。
        """
        phases = tuple(k for k, on in (("prefill", stats.get("prefilling")),
                                       ("decode", stats.get("decoding")))
                       if on)
        if phases == self._phases:
            return
        self._phases = phases
        self._apply_caption_colors()

    def set_running(self, running):
        self._running = running
        if not running:
            self._last = {}
            # 上一段均值属于**这个**服务实例：停服/异常退出就清掉，否则重启后
            # 会出现“累计计数已归零、速度却还写着上个实例的成绩”的自相矛盾。
            self._last_task = {}
            self._no_http = False
            self._slots_state = "unknown"
            self._metrics_state = "unknown"
            # 阶段也归零（没在服务 = 两格都回灰色），并重新染一次标签
            self._phases = ()
            self._apply_caption_colors()
        self._render()

    def set_no_http(self, on):
        """server 以 unix socket 启动：没有 HTTP 端点，七格灰显 + 专门 tooltip
        （区别于"未启动"的说法）。"""
        self._no_http = bool(on)
        self._render()

    def set_metrics_checked(self, checked):
        self._metrics_checked = bool(checked)
        self._render()

    def set_metrics_state(self, state):
        self._metrics_state = state
        self._render()

    def set_slots_state(self, state):
        self._slots_state = state
        self._render()

    def set_last_task_speeds(self, prefill_tps, prefill_tokens, decode_tps,
                             decode_tokens):
        """灌入**上一段连续活动**的均值（prefill / decode 各一份，None = 从未跑过）。

        数据是 llama.cpp 自己在 `slot print_timing` 前缀下报的单任务累计值（全部走
        `ui/log_parser.py` → `MainWindow._parse_log_line`）：阶段**运行中**就有
        `prompt processing, …` / `n_gen = …, tg = …`（短 prefill <3s、短生成 <100 token 不打），
        阶段**结束时**再来一对精确的 `prompt eval time` / `eval time` 覆盖它。只靠结束那
        一对是不够的：第一个请求的 decode 阶段拿不到本任务 prefill 的均值，会整段显示
        破折号（用户报的 bug：“第一次 prefill 完了到 decode 时 prefill 那里会显示 -，
        第二次就显示”）。所以：① 精确（服务端 ms 级计时），不带 1s 轮询差分的边界误差；
        ② 语义就是“上一段连续活动”，而不是服务启动以来的平均值；③ 一个任务都没跑过
        时两者都是 None → 格子里仍是现有的定宽破折号（绝不估算）。

        **先比较再重绘**：MainWindow 每解析到一条会改 runtime info 的日志都会同步一次，
        而均值只在阶段运行中（约每秒一行 print_timing）与阶段结束时变 —— 与 /slots 的
        1Hz 刷新同量级；模型加载那种日志洪水期（每秒上百行）绝不得次次 `_render()`。
        """
        incoming = {}
        if prefill_tps is not None:
            incoming["prefill"] = (prefill_tps, prefill_tokens)
        if decode_tps is not None:
            incoming["decode"] = (decode_tps, decode_tokens)
        if incoming == self._last_task:
            return
        self._last_task = incoming
        self._render()

    def update(self, stats):
        if self._running and not self._no_http:
            self._last = stats
            self._note_phases(stats)
            self._render()

    def retranslate_ui(self):
        for key in self._ALL_KEYS:
            self._tiles[key][0].property("cap").setText(t(self._LABELS[key]))
        self._render()

    # ------------------------------------------------------------- 绘制
    def _value_html(self, key, text, color=None):
        """数值（主色；字体已是 Consolas 11px 粗体，列定宽右对齐）+ 次要色单位。

        宽度不靠填充维持（见 _WIDEST / _ValueColumn）；不可用时仍是定宽破折号，
        列不跳。
        """
        body = text if text else "&mdash;"
        color = color or (self._text if text else self._muted)
        html = f'<span style="color:{color}">{body}</span>'
        unit = _UNITS.get(key)
        if unit:
            # t/s 前留一格空隙；% 按排版习惯紧跟数字
            gap = "" if unit == "%" else "&nbsp;"
            html += f'<span style="color:{self._muted}">{gap}{unit}</span>'
        return html

    def _tip(self, key, value=None, note=None):
        """一格 tooltip 的全部内容：**名称 / 精确值 /（必要时）一行身份**。

        用户（2026-11 尾轮）：“tooltip 里不要刻意地写，重新整体规划下显示的内容”
        → 选定两行结构。以前是一句基础文案后面按分支拼“· 提醒”，同一个意思在四个
        分支里各写一遍（阶段进行中、空闲仍占 KV、--metrics 引导、上一段均值……）。
        现在只有三个固定槽位，**缺的不占行**：

        1. **名称** —— 全称（格标签会被省略号截断，这里不会）；
        2. **数值** —— 精确值（屏上那个可能已被缩写成 1.5K）；无值（破折号）
           时不占行；
        3. **身份** —— 只在“这**不是**主来源的当前值”时出现：上一段的均值 /
           最后已知值 / 读不到的原因。这一行与格子的**颜色同源**（次要色 ↔ 这一行
           同时出现，两者由同一个分支决定），颜色变了必须有个文字说法。

        其余全删：含义、算法、数据来源、刷新频率这类长期说明（选定两行），以及
        “本阶段正在进行”（格标签已经变色）、“服务空闲，这段上下文仍在 KV 里”
        （那是 ctx 这个指标本来的含义，不是提醒）。
        """
        rows = [t(self._FULL_NAMES[key])]
        if value is not None:
            rows.append(value)
        if note:
            rows.append(note)
        return "\n".join(rows)

    def _set_cell(self, key, text, tip, color=None):
        cell, value, meter = self._tiles[key]
        cell.setToolTip(tip)
        if meter is value:
            # ctx：数值写在条里面（第十轮），"%" 是单位所以跟着进条；无值时是
            # 定宽灰破折号而不是 "0%"（没读到 ≠ 值为 0）
            meter.setToolTip(tip)
            unit = _UNITS.get(key, "")
            meter.set_text((text + unit) if text else ("—" + unit),
                           text is None)
            return
        value.setText(self._value_html(key, text, color))
        value.parentWidget().setToolTip(tip)
        if meter is not None:
            meter.setToolTip(tip)

    def _set_bar(self, frac, pct):
        bar = self._tiles["ctx"][2]
        if frac is None:
            bar.setStyleSheet("")
            bar.setValue(0)
            return
        color = (_BAR_GREEN if pct < 70
                 else _BAR_AMBER if pct < 90 else _BAR_RED)
        bar.setStyleSheet(
            f"QProgressBar::chunk {{ background-color: {color}; }}")
        bar.setValue(int(min(max(frac, 0.0), 1.0) * 1000))

    def endpoints_alive(self):
        """两端（/slots、/metrics）里至少还有一个能应答。

        MainWindow 的运行状态点用它：运行中但两端都不应答时点转琥珀（这条
        语义只有本模块清楚两边的状态，放在这里免得两处各写一套）。unknown 按
        “活”算 —— 还没探到结果，不吓唬人。
        """
        live_ok = self._slots_state != "off"
        sess_ok = self._metrics_state not in ("unsupported", "error")
        return live_ok or sess_ok

    def _set_ctx_zero(self, tip):
        """上下文条的“没内容”就是 **0.0%**，不是破折号。

        用户：“上下文进度条仅在有活动时显示，停止了就不显示了，应该一直显示，
        哪怕刚开始时也应为 0”。这与累计组同一套规矩（第八轮：“session 里的值
        开始不应该没有值，开始就是 0”）：**0 是个值，破折号是“读不到”**。服务停掉后
        KV 缓存随之消失，0% 就是真实情况，不是“暂无数据”。
        只有**读不到**（/slots 被关、unix socket 无 HTTP 端点）才给破折号。
        """
        self._set_cell("ctx", _CTX_ZERO_TEXT, tip)
        self._set_bar(0.0, 0)

    def _render_placeholder(self, note, ctx_known=True):
        """未运行 / 无 HTTP 端点时的常驻排版（第七轮起条带只有一种排版）。

        三档分别对待（都还是"0 是个值、破折号是读不到"那条规矩）：
        * 速度格（当前速率）**确实未知** → 定宽灰破折号；
        * 上下文：`ctx_known` 为真就是 **0.0%**（没启动 = KV 里一个 token 都没有），
          否则是真读不到（unix socket 无 HTTP 端点）→ 破折号；
        * 累计组是"服务启动以来"的计数，一次任务都没跑过就是 **0**（第八轮，
          用户："session 里的值开始不应该没有值，开始就是 0"；旧版整排破折号
          看着像坏了）。

        `note` 是那"一行身份"，七格共用一句（"怎么勾上 --metrics"不再拼到这里：
        启动服务之后才可行动，届时累计格自己会说，见 _render_right）。
        """
        for key in self._SPEED_KEYS:
            self._set_cell(key, None, self._tip(key, None, note))
        if ctx_known:
            self._set_ctx_zero(self._tip("ctx", _CTX_ZERO_TEXT + "%", note))
        else:
            self._set_cell("ctx", None, self._tip("ctx", None, note))
            self._set_bar(None, 0)
        for key in self._METRIC_KEYS:
            self._set_cell(key, _ZERO_TEXT[key],
                           self._tip(key, self._EXACT_ZERO[key], note))

    def _render(self):
        """常驻七格：没有数值时画定宽灰破折号，原因在 tooltip 的那行身份里。"""
        if self._no_http:
            # 连 HTTP 端点都没有 → 实时组与上下文真的读不到
            self._render_placeholder(t("unix socket 无 HTTP 端点"),
                                     ctx_known=False)
            return
        if not self._running:
            self._render_placeholder(t("服务未启动"))
            return
        self._render_left(self._last)
        self._render_right(self._last)

    def _speed_from_last_task(self, key, note=None):
        """本窗口无该类活动时，画上一段的均值（**次要色** + 同一分支的那行身份）。

        "上一段"既可能是**同一个任务的上一阶段**（prefill 已完、正在 decode：数值来自
        服务端阶段内的 `prompt processing, …` 行），也可能是上一个任务 —— 所以文案写
        "上一段"而不写"上一段任务"。

        次要色而不是主色：一个静止不动的历史均值如果与实时速率同色，会被读成
        "当前速度"（与破折号同族，表示"这不是现在的数"）。颜色与那行身份由同一个
        分支给出 —— 两者必须同进同出（旧版是两处各写一遍，改文案时容易漏一处）。
        """
        tps, tokens = self._last_task[key]
        text = _fmt_speed(tps)
        if note is None:
            note = (t("上一段的均值 · {n} tokens", n=f"{int(tokens):,}")
                    if tokens else t("上一段的均值"))
        self._set_cell(key, text,
                       self._tip(key, text + " t/s", note), self._muted)

    def _render_left(self, d):
        off = self._slots_state == "off"
        off_note = t("/slots 端点已关闭")
        for key in self._SPEED_KEYS:
            value = None if off else d.get(key + "_tps")
            if value is not None:
                text = _fmt_speed(value)
                # tooltip 里要带单位：屏上那个 " t/s" 是 HTML 单位后缀，
                # 不在 `_fmt_speed` 的返回里
                self._set_cell(key, text, self._tip(key, text + " t/s"))
                continue
            # 本窗口没有该类活动（服务空闲，或正处在另一个阶段：decode 期间的
            # Prefill 格）—— 先试上一段的均值，一个任务都没跑过才回到定宽破折号。
            # /slots 被关掉时同样走这里：均值来自日志、与端点无关，比整排破折号
            # 有用；但身份那行要换成"端点被关"，不能写"当前没有该类活动"（那会让人
            # 以为服务在空转）。
            last = self._last_task.get(key)
            if last is not None:
                self._speed_from_last_task(key, off_note if off else None)
                continue
            self._set_cell(key, None,
                           self._tip(key, None,
                                     off_note if off
                                     else t("当前没有该类活动")))

        if off:
            self._set_cell("ctx", None, self._tip("ctx", None, off_note))
            self._set_bar(None, 0)
            return
        frac = d.get("ctx_frac")
        used, total = d.get("ctx_used"), d.get("ctx_total")
        if frac is None:
            # /slots 正常应答但还没有读数（模型还在加载、slot 未建好）：那也是
            # “KV 里还没有 token” → 0%，上下文条常驻（见 _set_ctx_zero）
            self._set_ctx_zero(self._tip("ctx", _CTX_ZERO_TEXT + "%",
                                         t("KV 缓存为空")))
            return
        pct = frac * 100
        # tooltip 第二行给完整账（屏上只有百分比）。缺 used/total 时（只能从
        # ctx_frac 拿到比例）也不能把格刷成 0%：比例是真读数
        exact = (f"{int(used):,} / {int(total):,}（{pct:.1f}%）"
                 if used is not None and total else f"{pct:.1f}%")
        # “空闲时这段上下文仍在 KV 里”**不写**：那就是“上下文占用”这个指标
        # 本来的含义（任务结束 slot 不释放缓存，下个请求直接复用），不是提醒
        self._set_cell("ctx", f"{pct:.1f}", self._tip("ctx", exact))
        self._set_bar(frac, pct)

    def _render_right(self, d):
        # 累计组：/metrics 还没回数据时按 0 计（第八轮："开始就是 0"）—— 这些是
        # 服务启动以来的累计计数，"还没有"与"是 0"是同一件事，画成破折号反而像
        # 坏了。真正未知的是实时组。
        total = d.get("prompt_total") or 0
        cached = d.get("prompt_cached_total") or 0
        predicted = d.get("predicted_total") or 0
        note = None
        color = None

        if self._metrics_state in ("unsupported", "error"):
            if self._metrics_state == "error":
                why = t("读取 /metrics 端点失败")
            elif not self._metrics_checked:
                why = t("请在{nav}勾选并重启服务后显示", nav=_metrics_nav())
            else:
                why = t("本服务实例未提供 /metrics 端点，重启服务后生效")
            if not (total or cached or predicted):
                # 读不到、而且手里一个数都没有 → 破折号（/metrics 明确不可用
                # 就是"读不到"，不是"值为 0"）。写 0 是说不过去的：这一场可能
                # 已经跑了几百万 token，只是端点没开 / 打不通
                for key in self._METRIC_KEYS:
                    self._set_cell(key, None, self._tip(key, None, why))
                return
            # 读不到了，但手里**有已知的非 0 值** → 继续把它们显示出来，而不是把
            # 已经不为 0 的数字藏成破折号（用户："只要不为 0，就要保持一直显示"）。
            # 次要色与"最后已知值"那一行由同一个分支给出。停服仍归零：那些 counter
            # 属于**那个**服务进程（与左组"上一段均值"停服清空同一理由）。
            note = t("最后已知值 · {why}", why=why)
            color = self._muted

        def cell(key, shown, exact):
            """一格累计值：屏上是缩写（1.5K），tooltip 第二行给精确值。"""
            self._set_cell(key, shown, self._tip(key, exact, note), color)

        cell("total_in", _fmt_tokens(total + cached),
             f"{int(total + cached):,} tokens")
        cell("cached_in", _fmt_tokens(cached), f"{int(cached):,} tokens")
        cell("total_out", _fmt_tokens(predicted), f"{int(predicted):,} tokens")
        denom = total + cached
        # 0/0 的命中率未定义，但"0%"与"还没开始"在视觉上等价，且比破折号更符合
        # "开始就是 0"（第八轮）；屏上那个数就是答案，不再补一行解释
        cell("hit_rate",
             "0.0" if denom <= 0 else f"{cached / denom * 100:.1f}",
             "0.0%" if denom <= 0 else f"{cached / denom * 100:.1f}%")
