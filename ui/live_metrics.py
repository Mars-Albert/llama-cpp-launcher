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
   即不用启动后再显示出来，一直都显示" → 提示语删除，未运行时七格仍是定宽灰
   破折号，"为什么还没有数值"进 tooltip（未启动 / 未勾选 --metrics / unix
   socket 无 HTTP 端点 三种情形各有专门说明）。行高 34px 常驻，E11 最小高度
   算术不变，而且条带只有一种排版 → 窗口最小宽度不随服务启停变化。
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

左组（实时，/slots @1s）：Prefill · Decode · 上下文（内联计量条：正常 →
70% 琥珀 → 90% 红）。右组（服务启动以来的累计，/metrics @5s，需勾选
--metrics）：输入 · 缓存 · 输出 · 命中。格标签刻意缩短（总输入→输入…），
全称在 tooltip；组标题删除后"累计"这层意思也靠 tooltip + 分隔线传达。
右组的"还没有数据"是 **0**（计数从 0 起算，第八轮），左组的"还没有数据"
是破折号（当前速率/占用确实是未知）。

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
    set_theme_colors(text, muted, info)；endpoints_alive() 供状态栏的运行状态点
    使用。数值经 update() 灌入，其余状态变化只重绘文案与 tooltip。未运行 / 无
    HTTP → 同一批格子改为定宽灰破折号 + 说明性 tooltip（不再有"提示态"）。

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
    _SPEED_TIPS = {
        "prefill": "Prefill 速度：最近窗口 /slots 计数器每秒差值，每秒刷新",
        "decode": "Decode 速度：最近窗口 /slots 计数器每秒差值，每秒刷新",
    }
    _CTX_TIP = ("上下文占用（近似）：(输入 token + 生成 token) / n_ctx，"
                "取最忙 slot")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("liveMetricsBar")
        self.setFixedHeight(34)
        # Maximum：只长到内容宽，再多一寸也不要 → 合一行里那条 stretch 才能
        # 拿到富余宽度（把本行推到右端）。宽度不够时仍可缩到最小（标签省略）。
        self.setSizePolicy(QSizePolicy.Policy.Maximum,
                           QSizePolicy.Policy.Fixed)
        self._last = {}
        self._running = False
        self._no_http = False
        self._metrics_checked = False
        self._metrics_state = "unknown"
        self._slots_state = "unknown"
        # 默认浅色主题值；MainWindow 构造后与 _apply_theme 都会同步
        self._text = "#1a1a2e"
        self._muted = "#666"
        self._info = "#6b7280"
        self._tiles = {}

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(0)

        # 七格常驻（第七轮）：未运行也在这里，只是定宽灰破折号。行内无弹性项：
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

    def set_theme_colors(self, text, muted, info=None):
        """主题同步：数值 HTML 的 span 颜色 + ElidingLabel 的 palette 色。

        MainWindow 构造后与每次 _apply_theme 调用（QSS 管不进 rich text，
        ElidingLabel 自绘也只认 palette）。
        """
        if text:
            self._text = text
        if muted:
            self._muted = muted
        if info:
            self._info = info
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

    def _apply_caption_colors(self):
        """组标题 muted、格标签与单行提示 info（随主题同步）。"""
        for key in self._ALL_KEYS:
            cap = self._tiles[key][0].property("cap")
            if cap is not None:
                self._caption_style(cap, self._info, False)

    def set_running(self, running):
        self._running = running
        if not running:
            self._last = {}
            self._no_http = False
            self._slots_state = "unknown"
            self._metrics_state = "unknown"
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

    def update(self, stats):
        if self._running and not self._no_http:
            self._last = stats
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

    def _render_placeholder(self, tip):
        """未运行 / 无 HTTP 端点时的常驻排版（第七轮起条带只有一种排版）。

        两组分别对待：
        * 实时组（当前速度 / 上下文占用）**确实未知** → 定宽灰破折号；
        * 累计组是"服务启动以来"的计数，一次任务都没跑过就是 **0** —— 0 是个值，
          不是"没有值"（第八轮，用户："session 里的值开始不应该没有值，开始就
          是 0"；旧版整排破折号看着像坏了）。
        "为什么还是 0 / —"（未启动 / 未勾选 --metrics / unix socket 无 HTTP 端点）
        在 tooltip 里；“怎么勾上”用**准确导航路径**（_metrics_nav：「高级模式」→
        「服务」→「Prometheus指标 (--metrics)」，名字从 schema 取，不手写）。
        """
        for key in self._SPEED_KEYS + ("ctx",):
            self._set_cell(key, None, tip)
        self._set_bar(None, 0)
        for key in self._METRIC_KEYS:
            self._set_cell(key, _ZERO_TEXT[key], tip)

    def _render(self):
        """常驻七格：没有数值时画定宽灰破折号，原因写进 tooltip。"""
        if self._no_http:
            self._render_placeholder(
                t("server 以 unix socket 启动 · 无 HTTP 端点，指标不可用"))
            return
        if not self._running:
            tip = t("服务未启动 · 启动后在这里显示实时速度与累计指标")
            if not self._metrics_checked:
                tip += t(" · 累计指标：请在{nav}勾选并重启服务",
                         nav=_metrics_nav())
            self._render_placeholder(tip)
            return
        self._render_left(self._last)
        self._render_right(self._last)

    def _render_left(self, d):
        off = self._slots_state == "off"
        off_tip = t("该 server 已关闭 /slots 端点（检查启动参数），实时速度不可用")
        for key in self._SPEED_KEYS:
            if off:
                self._set_cell(key, None, off_tip)
                continue
            value = d.get(key + "_tps")
            tip = t(self._SPEED_TIPS[key])
            self._set_cell(key, None if value is None else _fmt_speed(value),
                           tip)

        if off:
            self._set_cell("ctx", None, off_tip)
            self._set_bar(None, 0)
            return
        frac = d.get("ctx_frac")
        if frac is None:
            self._set_cell("ctx", None, t(self._CTX_TIP))
            self._set_bar(None, 0)
            return
        pct = frac * 100
        used, total = d.get("ctx_used"), d.get("ctx_total")
        if used is not None and total:
            tip = t("上下文占用（近似）：{used} / {total} tokens ({pct}%)",
                    used=f"{used:,}", total=f"{total:,}", pct=f"{pct:.1f}")
        else:
            tip = t(self._CTX_TIP)
        self._set_cell("ctx", f"{pct:.1f}", tip)
        self._set_bar(frac, pct)

    def _render_right(self, d):
        if self._metrics_state in ("unsupported", "error"):
            if self._metrics_state == "error":
                tip = t("读取 /metrics 端点失败，请检查服务状态")
            elif not self._metrics_checked:
                tip = t("请在{nav}勾选并重启服务后显示", nav=_metrics_nav())
            else:
                tip = (t("参数已勾选，但本服务实例未提供 /metrics 端点；"
                         "重启服务后生效（或当前 server 不支持）"))
            for key in self._METRIC_KEYS:
                self._set_cell(key, None, tip)
            return

        # 累计组：/metrics 还没回数据时按 0 计（第八轮："开始就是 0"）—— 这些是
        # 服务启动以来的累计计数，"还没有"与"是 0"是同一件事，画成破折号反而像
        # 坏了。真正未知的是实时组。/metrics 明确不可用（unsupported / error）
        # 时仍走上面的破折号分支：那是"读不到"，不是"值为 0"。
        total = d.get("prompt_total") or 0
        cached = d.get("prompt_cached_total") or 0
        predicted = d.get("predicted_total") or 0

        self._set_cell("total_in", _fmt_tokens(total + cached),
                       t("服务启动以来输入的 token 数（未缓存 {nc} + 缓存 {c}）",
                         nc=f"{int(total):,}", c=f"{int(cached):,}"))
        self._set_cell("cached_in", _fmt_tokens(cached),
                       t("服务启动以来命中 KV 缓存的输入 token 数：{c}",
                         c=f"{int(cached):,}"))
        self._set_cell("total_out", _fmt_tokens(predicted),
                       t("服务启动以来生成的 token 数：{n}",
                         n=f"{int(predicted):,}"))
        denom = total + cached
        task_rate = d.get("task_cache_hit")
        if denom <= 0:
            # 0/0 的命中率是未定义，但"0%"与"还没开始"在视觉上等价，且比破折号
            # 更符合"开始就是 0"；tooltip 说清楚分母还是 0。
            tip = t("会话累计命中率（/metrics）· 尚无输入 token")
        elif task_rate is not None:
            tip = t("本任务 {a}%（/slots）· 会话累计 {b}%（/metrics）",
                    a=f"{task_rate * 100:.0f}",
                    b=f"{cached / denom * 100:.1f}")
        else:
            tip = t("会话累计命中率（/metrics）：{b}%",
                    b=f"{cached / denom * 100:.1f}")
        self._set_cell("hit_rate",
                       "0.0" if denom <= 0 else f"{cached / denom * 100:.1f}",
                       tip)
