# -*- coding: utf-8 -*-
"""E15: right-column 3-tab layout (参数配置 / 日志输出 / 运行信息).

Regression for the 1080p report: the right column used to stack the
parameter area above a small bottom tab widget (日志输出 / 运行信息), so
on a 1080p screen (window ~940px tall) the log got only ~150-250px of
the column. E15 makes the whole right column one 3-tab widget, so every
tab owns the column's full height (~800px+).

Pinned here:
- the tab structure (3 tabs, order, content of each page) and the
  default tab (参数配置);
- 2026-11 round 5: the run-state dot/text, runtime and the llama-server
  version live in the *status bar* right side (they used to trail the
  control bar; E15 briefly tried this and it was reverted because the
  status bar painted a wrong white box — the chrome is transparent since
  E13, and test_status_bar_right_items_stay_on_the_card_face pins the
  corner band stays transparent);
- the ``right_tab`` ui pref: saved on state save, restored at startup,
  and the legacy pre-E15 ``bottom_tab`` value maps to +1 (0=日志输出→1,
  1=运行信息→2);
- Ctrl+F (``_show_log_search``) switches to the 日志输出 tab;
- the log tab owns the column's full height at a typical 1080p window
  size;
- 2026-11: the control row (compact buttons + the live-metrics strip,
  merged into ONE row by round 5) is a row of the right column *below* the
  tab widget, so it stays visible on all three tabs (it used to live inside
  参数配置 and vanished on the log/info tabs);
- 2026-11 rounds 5b/5c: the four control buttons keep the *shape* of the
  generic button (no radius/padding/font-size overrides — same family as the
  ↩ 撤销 row) and the icons, but wear the accent colours (gradient fill +
  white bold text): flat white chips made the start/stop actions invisible
  (user: “不要做成白底的，彩色底，白字体，因为这个需要很醒目”). Pinned by
  ``test_control_buttons_wear_the_accent_style``, incl. the two Qt QSS
  specificity traps (``#id`` beats ``:disabled``, and ``#id:hover`` ties with
  ``#id:disabled`` so the disabled rule must come last);
- E11 width self-lock defence, E15 variant: the outer tab widget's
  minimum width stays pinned to the fixed-content minimum when the
  quick grid re-wraps (if the grid's current column count leaked into
  the minimum, the window would self-lock wide and the re-wrap that
  raises the minimum height would never happen).
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import core.config as CC


@pytest.fixture
def temp_settings(tmp_path, monkeypatch):
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(CC, "SETTINGS_FILE", settings_file)
    presets_dir = tmp_path / "presets"
    presets_dir.mkdir()
    monkeypatch.setattr(CC, "PRESETS_DIR", presets_dir)
    yield settings_file


def _qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _window(temp_settings, prefs=None):
    from core.defaults import _FALLBACK_DEFAULTS
    from ui.main_window import MainWindow
    if prefs is not None:
        CC.save_ui_prefs(prefs)
    return MainWindow(work_dir=None, defaults=dict(_FALLBACK_DEFAULTS))


def _settle(app, win, w, h):
    import time
    win.resize(w, h)
    for _ in range(12):
        app.processEvents()
        time.sleep(0.005)


def test_right_column_is_three_tabs(temp_settings):
    app = _qapp()
    w = _window(temp_settings)
    try:
        assert w.tab_widget.count() == 3
        # 参数配置 is the default tab; then the two former bottom tabs
        assert w.tab_widget.currentIndex() == 0
        assert w.tab_widget.tabText(0) == "⚙️ 参数配置"
        assert w.tab_widget.tabText(1) == "📄 日志输出"
        assert w.tab_widget.tabText(2) == "📊 运行信息"
        # the pre-E15 stacked blocks live in the 参数配置 page — the
        # parameter area and the command preview are separated by a
        # draggable vertical QSplitter (E15 follow-up, requested change 2026-10)
        assert w.mode_combo.parent() is w.params_tab
        assert w.cmd_split.parent() is w.params_tab
        assert w.cmd_split.widget(0) is w.panel_scroll
        assert w.cmd_split.widget(1) is w.cmd_box
        # the preview + its caption live in the splitter's bottom box; the
        # extra-height stretch stays on the preview side (panel side = 0)
        assert w.cmd_label.parent() is w.cmd_box
        assert w.cmd_preview.parent() is w.cmd_box
        # 2026-11: the control bar left the 参数配置 page — it is a row of
        # its own below the tab widget (so start/stop/copy work on every tab)
        assert w.btn_start.parent() is w.control_bar
        assert w.btn_stop.parent() is w.control_bar
        assert w.control_bar.parent() is w._right_panel
        assert w.control_bar.parent() is not w.params_tab
        # the log page carries the log editor + search bar + toolbar
        assert w.log_output.parent() is w.log_tab
        assert w.log_search_bar.parent() is w.log_tab
        assert w.btn_export_log.parent() is w.log_tab
        # 运行信息 is added directly as a page (parented to the tab
        # widget's internal stack)
        from PyQt6.QtWidgets import QStackedWidget
        assert isinstance(w.info_display.parent(), QStackedWidget)
        assert w.info_display.parent().parent() is w.tab_widget
    finally:
        w.close()


def test_run_state_and_version_live_in_the_status_bar(temp_settings):
    """2026-11 改版：状态点 / 状态文字 / 运行时长 / llama-server 版本 / ⚠️ 全部
    搬到状态栏右侧（“版本信息与运行时间移到最下面的状态栏底部右侧”）—— 控制栏与
    指标行合成一行后要腾出那一行的宽度，而且它们是"读"的信息。后来又把 GPU
    设备行也搬过来，插在版本左边。

    钉住：父级 = status bar、常驻项排在消息右侧且**GPU 信息 → 版本**在前（后来
    定下版本组，后来要求：“把这个信息也放到状态栏上，放在版本号左边”）、
    控制栏里不再有我。"""
    from PyQt6.QtCore import QPoint
    app = _qapp()
    w = _window(temp_settings)
    try:
        sb = w.statusBar()
        for widget in (w.run_dot, w.status_indicator, w.run_time_label,
                       w.version_label, w.drift_button):
            assert widget.parent() is sb, widget.objectName()
        # 控制栏（= 合一行）里只剩四个按钮 + 指标带
        row = w.control_bar.layout()
        widgets = [row.itemAt(i).widget() for i in range(row.count())]
        widgets = [x for x in widgets if x is not None]
        assert widgets == [w.btn_start, w.btn_stop, w.btn_copy_cmd,
                           w.btn_webui, w.live_metrics]
        w.show()
        _settle(app, w, 1360, 860)
        # 从左到右（后来的要求：“版本号移到首位…” + 后来：“把这个信息也放到
        # 状态栏上，放在版本号左边”）：临时消息 → GPU 信息 → 版本 → ⚠️ → 状态点
        # → 状态 → 时长
        msg = sb.findChild(type(w.status_indicator), "statusMsg")
        assert msg is not None
        x_of = lambda c: c.mapTo(w, QPoint(0, 0)).x()
        # GPU 信息只有探针完成后才显示（隐藏项不占宽度）
        w._on_devices_ready([])
        app.processEvents()
        assert w.gpu_info_label.parent() is sb
        assert w.gpu_info_label.isVisibleTo(sb)
        assert x_of(msg) < x_of(w.gpu_info_label)
        assert x_of(w.gpu_info_label) < x_of(w.version_label)
        assert x_of(w.version_label) < x_of(w.run_dot)
        assert x_of(w.run_dot) < x_of(w.status_indicator)
        assert x_of(w.status_indicator) < x_of(w.run_time_label)
        # ⚠️ 紧跟它评论的那个版本号（只在有 drift 时出现）
        w.drift_button.setVisible(True)
        app.processEvents()
        assert x_of(w.version_label) < x_of(w.drift_button) < x_of(w.run_dot)
        w.drift_button.setVisible(False)
        # 模式行里不再留副本（同一个信息两处各说一套 = 迟早对不上）：父级就是
        # 状态栏，而且「参数配置」页里只有一个 #secondaryInfo（模信信息行）。
        assert w.gpu_info_label.parent() is sb
        from PyQt6.QtWidgets import QWidget
        assert w.params_tab.findChildren(QWidget, "secondaryInfo") == []
    finally:
        w.close()


def test_tab_bar_and_control_buttons_share_one_height(temp_settings):
    """右栏三个 tab 的高度 = 合一行四个按钮的高度（2026-11 改版）。

    要求：“3 个 tab 高度比按钮都高一些，看着不太协调，改为一致” —— 按钮是
    setFixedHeight(28)，tab 原先 `padding: 8px 16px` 量到 ~34px，同一列里两种
    控件高度自然显得不协调。

    关键是**不能只调 padding**：tab 高度原先由文字行高撑开，同一条 padding 在
    捆绑字体下 28、在别的字体环境下 31（全量跑里 QApplication 的字体是**第一个**
    建它的模块设的，各模块不一定相同 → 这个测试本地单跑过、全量跑挂过，就是
    这 3px）。现在 QSS 用 `height: 17px` 固定内容盒（+ 2×4 padding + 2×1 边框
    + 选中态多出的那 1px = 28），行高不再参与撑高；两种字体环境都实测过 == 28。
    断言仍写“相等 + 28”：28 是合一行四个按钮的定高，也是这次要的观感。
    """
    _qapp()
    w = _window(temp_settings)
    try:
        w.show()
        _settle(_qapp(), w, 1360, 860)
        bar = w.tab_widget.tabBar()
        heights = {bar.tabRect(i).height() for i in range(bar.count())}
        assert len(heights) == 1, heights          # 三个 tab 自身也要一致
        tab_h = heights.pop()
        buttons = {b.height() for b in (w.btn_start, w.btn_stop,
                                        w.btn_copy_cmd, w.btn_webui)}
        assert buttons == {28}, buttons
        assert tab_h == 28, tab_h
    finally:
        w.close()


def test_only_the_value_is_boxed(temp_settings):
    """只给数值加框（后来的要求："这个框太小了，看起来不自然，且不用给label加框，只给
    要显示数值的地方加框；上下文那个数值直接写在进度条里面，也不用加框"）。

    后来把整格（标签 + 数字）框成芯片 → 被嫌小、不自然。现在：
    * `#metricCell` 透明无边框（标签就是普通文字）；
    * `#metricValueBox` 是读数窗：`field_bg` 底 + 1px `border` 边框 + 圆角；
    * 条带自身透明无边框；计量条不加框，但轨道必须是 `border` 色（它直接坐在
      win_bg 上，hover_bg 与 win_bg 几乎同色 → 轨道看不见，绿块像凭空飘着）。
    色值一律主题 token，明/暗两套都钉。"""
    _qapp()
    w = _window(temp_settings)
    try:
        for theme in ("light", "dark"):
            pal = w._THEME_PALETTES[theme]
            css = w._get_stylesheet(theme)

            def rule_of(selector):
                start = css.index(selector)
                return css[start:css.index("}", start)]

            strip = rule_of("QWidget#liveMetricsBar {")
            cell = rule_of("QWidget#liveMetricsBar QWidget#metricCell {")
            box = rule_of("QWidget#liveMetricsBar QWidget#metricValueBox {")
            meter = rule_of("QProgressBar#metricMiniBar {")
            for name, rule in (("条带", strip), ("格", cell)):
                assert "background: transparent" in rule, (theme, name, rule)
                assert "border: none" in rule, (theme, name, rule)
            # 读数窗：底色 + 1px 边框 + 圆角，全是主题 token
            assert "border: 1px solid" in box, (theme, box)
            assert pal["border"] in box, (theme, pal["border"], box)
            assert pal["field_bg"] in box, (theme, pal["field_bg"], box)
            assert "border-radius" in box, box
            # 竖向 padding 必须为 0（后来的定案）：高度由代码 `setFixedHeight(_FIELD_H)`
            # 钉，Qt 把样式表 padding 当 contentsMargins → 竖向写了数字就会把 20px
            # 扣到装不下 13px 高的数字，字溢出到边框上。
            decl = box[box.index("padding:"):]
            decl = decl[:decl.index(";")].split(":", 1)[1].split()
            # "0px 8px" / "0px" 两种写法都管：竖向值就是第一个（或唯一那个）
            assert decl[0].split("px")[0] == "0", (theme, decl)
            # 计量条：不加框，轨道用 border（不是 hover_bg —— 与 win_bg 同色）
            assert "border: none" in meter, (theme, meter)
            assert pal["border"] in meter, (theme, pal["border"], meter)
            assert pal["hover_bg"] not in meter, (theme, meter)
    finally:
        w.close()


def test_status_dot_tracks_run_and_endpoint_state(temp_settings):
    """运行状态的**唯一**指示：状态栏那个画出来的 8px 点 + 状态文字（后来从指标
    行搬来）。四态染色：灰=未启动 / 琥珀=启动中（或运行中但两端都不应答）/
    绿=运行中 / 红=异常退出；点与文字同色，tooltip 给完整解释。"""
    _qapp()
    w = _window(temp_settings)
    try:
        assert "#9aa3af" in w.run_dot.styleSheet()      # 未启动：灰
        assert w.status_indicator.text() == "未启动"
        w._current_state = "running"
        w._update_run_indicator()
        assert "#16a34a" in w.run_dot.styleSheet()      # 运行 + 有应答：绿
        assert "#16a34a" in w.status_indicator.styleSheet()
        assert w.status_indicator.text() == "运行中"
        # 运行中但 /slots 与 /metrics 都不应答 → 琥珀 + 专门的 tooltip
        w.live_metrics.set_slots_state("off")
        w.live_metrics.set_metrics_state("unsupported")
        w._update_run_indicator()
        assert "#d97706" in w.run_dot.styleSheet()
        assert "/slots" in w.run_dot.toolTip()
        w._current_state = "error"
        w._update_run_indicator()
        assert "#dc2626" in w.run_dot.styleSheet()      # 错误：红
        assert w.status_indicator.text() == "错误"
        # 指标行不再有第二个点（避免两处各说一套运行状态）
        from PyQt6.QtWidgets import QWidget
        assert w.live_metrics.findChildren(QWidget, "metricDot") == []
    finally:
        w.close()


def test_status_bar_right_items_stay_on_the_card_face(temp_settings):
    """状态栏右侧那几项不能画进透明圆角带 —— E15 那次"状态栏画成一块错的白框"
    事故就是这个形状（有东西在透明角带上画了不透明方块），当时因此把标签撤回控制
    栏。E13 之后 QStatusBar / #statusMsg / 这几项都是 background: transparent，
    这里用像素 + 几何两条断言把它钉死：右下角仍在透明带里，常驻项的右边缘都在
    卡片面内（`_RIGHT_MARGIN` 的作用）。"""
    from PyQt6.QtCore import QPoint
    # 卡片内缩（= 常态下透明阴影带的宽度）定义在 main_window 侧
    from ui.main_window import CARD_CONTENT_INSET
    app = _qapp()
    w = _window(temp_settings)
    try:
        w.show()
        _settle(app, w, 1360, 860)
        img = w.grab().toImage()
        assert img.pixelColor(w.width() - 2, w.height() - 2).alpha() == 0
        limit = w.width() - CARD_CONTENT_INSET - 1
        for widget in (w.status_indicator, w.run_time_label, w.version_label):
            edge = widget.mapTo(w, QPoint(widget.width(), 0)).x()
            assert edge <= limit, (widget.objectName(), edge, limit)
    finally:
        w.close()


def test_control_bar_and_metrics_live_outside_tabs(temp_settings):
    """2026-11 改版：启动按钮与实时指标带**合成一行**（“按钮与 metric 两行合并
    一行，按钮在左，metrics 在右侧，中间 stretch 隔开”），这一行是右栏在标签页
    **下方**的最后一个条目 → 切到任何 tab 都看得到、点得到。

    钉住：右栏只剩「标签页 → 合一行」两段；行内顺序 = 四个按钮 → stretch → 指标
    带；按钮压缩到 28px（指标带的 34px 就是整行高度，比原来两行省 52px）；指标带
    贴行右端（Maximum 策略 → 富余宽度归 stretch，不落在按钮与条带之间）。"""
    from PyQt6.QtCore import QPoint
    app = _qapp()
    w = _window(temp_settings)
    try:
        items = [w._right_panel.layout().itemAt(i)
                 for i in range(w._right_panel.layout().count())]
        widgets = [it.widget() for it in items if it.widget() is not None]
        # 右栏自上而下：标签页 → 合一行（按钮 + 指标带）
        assert widgets[-1] is w.control_bar
        assert w.live_metrics.parent() is w.control_bar
        assert widgets.index(w.tab_widget) < widgets.index(w.control_bar)
        w.show()
        _settle(app, w, 1360, 860)
        for index in range(w.tab_widget.count()):
            w.tab_widget.setCurrentIndex(index)
            _settle(app, w, 1360, 860)
            for widget in (w.btn_start, w.btn_copy_cmd, w.control_bar,
                           w.live_metrics):
                assert not widget.isHidden(), (index, widget)
            # 整行在标签面板下方，行高 = 指标带的 34px
            assert (w.control_bar.mapTo(w._right_panel, QPoint(0, 0)).y()
                    > w.tab_widget.geometry().bottom())
            assert w.control_bar.height() == 34
            assert w.live_metrics.height() == 34
            assert w.btn_start.height() == 28
            assert w.control_bar.width() == w.tab_widget.width()
            # 按钮在左、指标带在右，中间那条 stretch 吃掉富余宽度
            row_l = w.control_bar.mapTo(w._right_panel, QPoint(0, 0)).x()
            left = w.btn_start.mapTo(w._right_panel, QPoint(0, 0)).x() - row_l
            bar_right = (w.live_metrics.mapTo(w._right_panel,
                                              QPoint(w.live_metrics.width(), 0)).x()
                         - row_l)
            assert left <= 1, left                       # 按钮贴行左端
            assert w.control_bar.width() - bar_right <= 1, bar_right
            # 指标带只占内容宽（富余没落进它身上）
            assert (w.live_metrics.width()
                    <= w.live_metrics.sizeHint().width())
    finally:
        w.close()


def test_control_buttons_wear_the_accent_style(temp_settings):
    """2026-11 改版最终定案（要求：“这几个按钮不要做成白底的，彩色底，白字体，
    因为这个需要很醒目，跟一般的按钮不一样，现在这种效果让人忽略了重点”）：
    形状继承通用 QPushButton（**不写** border-radius / padding / font-size →
    与 ↩ 撤销 那排同族），配色走强调色（彩色渐变底 + 白字 + 粗体），图标保留
    （▶ ■ 是普通几何字符 → 跟着白字走；📋 🌐 与参数页 ⬇️ 💾 🗑️ 同一套 emoji）。

    钉住 Qt QSS 的两个特异性坑（(id, 属性/伪类, 类型)）：
    ① QPushButton#x(1,0,1) 压过 QPushButton:disabled(0,1,1) → 四个都必须显式写
      禁用态，否则“按钮已经禁用还是鲜绿/鲜红”；
    ② #x:hover(1,1,1) 与 #x:disabled(1,1,1) 同分 → 谁写在后面谁赢，所以
      :disabled 必须排在 hover/pressed 之后（样式表里逐个按钮检查顺序）。"""
    import re
    from ui.main_window import MainWindow
    _qapp()
    names = ("startBtn", "stopBtn", "copyBtn", "webuiBtn")
    for theme in ("light", "dark"):
        qss = MainWindow._get_stylesheet(theme)
        assert "@@" not in qss, theme       # 禁用态 token 两套主题都要解析得开
        pal = MainWindow._THEME_PALETTES[theme]
        for obj in names:
            rules = re.findall(
                r"QPushButton#%s((?::\w+)?)\s*\{([^{}]*)\}" % obj, qss)
            states = [st or "base" for st, _body in rules]
            bodies = dict(zip(states, [b for _st, b in rules]))
            assert states == ["base", ":hover", ":pressed", ":disabled"], (theme, obj, states)
            base = bodies["base"]
            # 形状继承通用规则；配色是强调色
            for prop in ("border-radius", "padding", "font-size"):
                assert prop not in base, (theme, obj, prop)
            assert "background: qlineargradient" in base, (theme, obj)
            assert "color: #ffffff" in base and "font-weight: bold" in base
            assert "border: none" in base, (theme, obj)   # 通用 1px 灰描边会框住色块
            # 禁用态是"褪色的那颗色"（逐主题 token），不是通用灰底
            stem = obj[:-3]
            assert ("background: %s" % pal["%s_dis_bg" % stem]
                    in bodies[":disabled"]), (theme, obj)
            assert ("color: %s" % pal["%s_dis_fg" % stem]
                    in bodies[":disabled"]), (theme, obj)
        # 强调按钮的禁用底色 / 文字色必须两主题都有定义
        for obj in ("start", "stop", "copy", "webui"):
            assert pal["%s_dis_bg" % obj] in qss and pal["%s_dis_fg" % obj] in qss
    # 图标 + 两字文案（上一版用户“要带图标”仍然生效），全称仍在 tooltip
    w = _window(temp_settings)
    try:
        assert w.btn_start.text() == "▶ 启动"
        assert w.btn_stop.text() == "■ 停止"
        assert w.btn_copy_cmd.text() == "📋 复制"
        assert w.btn_webui.text() == "🌐 WebUI"
        assert w.btn_start.toolTip() == "启动服务"
        assert w.btn_webui.toolTip() == "打开WebUI"
    finally:
        w.close()

def test_right_tab_persisted_and_restored(temp_settings):
    app = _qapp()
    w = _window(temp_settings)
    try:
        w.tab_widget.setCurrentIndex(2)
        w._save_ui_state()
        prefs = CC.load_ui_prefs()
        assert prefs["right_tab"] == 2
        assert "bottom_tab" not in prefs
    finally:
        w.close()

    w2 = _window(temp_settings, prefs={"right_tab": 1})
    try:
        assert w2.tab_widget.currentIndex() == 1
    finally:
        w2.close()

    # legacy pre-E15 bottom_tab maps to +1 (0=日志输出→1, 1=运行信息→2)
    w3 = _window(temp_settings, prefs={"bottom_tab": 1})
    try:
        assert w3.tab_widget.currentIndex() == 2
    finally:
        w3.close()


def test_cmd_split_persisted_and_restored(temp_settings):
    """The draggable parameter/preview split (E15 follow-up) persists as
    ui.cmd_split and is restored on the next launch (showEvent retry).
    Also pins the stretch behaviour: extra column height flows to the
    preview side (the panel keeps its natural height)."""
    app = _qapp()
    w = _window(temp_settings)
    try:
        w.show()
        for _ in range(15):
            app.processEvents()
        # extra height (250px over the minimum) must land on the preview
        # side — the panel side stays at its natural height
        w.resize(w.minimumWidth(), w.minimumHeight() + 250)
        for _ in range(12):
            app.processEvents()
        default = list(w.cmd_split.sizes())
        assert default[1] > 200  # the preview absorbed the extra
        # user drag: panel side +100 / preview side -100 (both sides stay
        # above their own minimums — dragging the preview side below its
        # floor, or the panel below its E11 natural minimum, clamps)
        w.cmd_split.setSizes([default[0] + 100, default[1] - 100])
        for _ in range(8):
            app.processEvents()
        w._save_ui_state()
        prefs = CC.load_ui_prefs()
        assert len(prefs["cmd_split"]) == 2
        assert prefs["cmd_split"][1] < default[1]  # the shrunken preview side
        saved = list(prefs["cmd_split"])
        saved_geo = [0, 0, w.width(), w.height()]
    finally:
        w.close()

    # relaunch at the SAME window size (saved geometry) so the saved split
    # total fits the splitter's total exactly (a smaller window would
    # correctly clamp each side to its own minimum, like the main splitter)
    w2 = _window(temp_settings, prefs={"cmd_split": saved,
                                       "geometry": saved_geo})
    try:
        w2.show()
        for _ in range(30):
            app.processEvents()
        assert getattr(w2, "_pending_cmd_split", None) is None  # retry consumed it
        sizes = w2.cmd_split.sizes()
        assert abs(sizes[1] - saved[1]) <= 20  # the preview side restored
    finally:
        w2.close()


def test_show_log_search_switches_to_log_tab(temp_settings):
    app = _qapp()
    w = _window(temp_settings)
    try:
        w.tab_widget.setCurrentIndex(0)
        w._show_log_search()
        assert w.tab_widget.currentIndex() == 1
        assert not w.log_search_bar.isHidden()
    finally:
        w.close()


def test_log_tab_gets_full_column_height(temp_settings):
    """The whole point of E15: at a typical 1080p window size the 日志
    output tab owns the column's full height (pre-E15 it was the
    ~150-250px leftover below the stacked parameter area)."""
    app = _qapp()
    w = _window(temp_settings)
    try:
        w.show()
        _settle(app, w, 1360, 860)
        w.tab_widget.setCurrentIndex(1)
        _settle(app, w, 1360, 860)
        # the log editor fills the tab page (page margins are 0)
        assert w.log_output.height() >= 600, (
            f"log editor only {w.log_output.height()}px tall at 1360x860")
    finally:
        w.close()


def test_tab_min_width_excludes_quick_grid_columns(temp_settings):
    """E11 width self-lock defence, E15 variant: when the quick-toggles
    grid re-wraps (1 row → 2 rows) the window minimum HEIGHT must follow
    (E11 option A) while the outer tab widget's minimum WIDTH must stay
    pinned to the fixed-content minimum — if the grid's current column
    count leaked into it, the window would self-lock wide and the
    re-wrap would never happen."""
    app = _qapp()
    w = _window(temp_settings)
    try:
        w.show()
        bp = w.basic_panel
        seven = ("mmproj_offload", "flash_attn", "spec_type", "draft_max",
                 "cache_type_k", "cache_type_v", "fit")
        _settle(app, w, 1360, w.minimumHeight())
        bp.set_quick_params(list(seven))
        _settle(app, w, 1360, w.minimumHeight())
        rows_wide = bp._quick_rows_used
        min_w_wide = w.tab_widget.minimumWidth()
        min_h_wide = w.minimumHeight()
        # narrow the window: the grid may re-wrap and the window minimum
        # height follows it (E11 option A)
        _settle(app, w, w.minimumWidth(), w.height())
        assert bp._quick_rows_used >= max(2, rows_wide)
        assert w.minimumHeight() >= min_h_wide
        # the tab minimum width must NOT have followed the column count
        assert w.tab_widget.minimumWidth() == min_w_wide, (
            f"width self-lock: tab min width {min_w_wide} -> "
            f"{w.tab_widget.minimumWidth()} after the quick grid re-wrap")
    finally:
        w.close()
