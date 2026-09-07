"""D4: i18n coverage tests.

- core/i18n.py must stay Qt-free (C4) so it can be tested headless;
- every t("literal") call in main.py / ui/ / core/ must have an _EN entry,
  so a forgotten translation fails the build instead of silently showing
  Chinese in English mode;
- t() must survive literal braces in copy (MCP JSON examples, plan C4).
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _pyqt_imports(path: pathlib.Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("PyQt"):
                    yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").startswith("PyQt"):
                yield node.module


def test_i18n_is_qt_free():
    # C4: _LanguageEmitter (the only QObject) was removed — the emitter had
    # zero subscribers; live switching goes through retranslate_ui().
    assert list(_pyqt_imports(ROOT / "core" / "i18n.py")) == []


def test_all_t_literals_translated():
    import core.i18n as I

    missing = []
    files = [ROOT / "main.py"]
    files += sorted((ROOT / "ui").glob("*.py"))
    files += sorted((ROOT / "core").glob("*.py"))
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            if node.func.id != "t" or not node.args:
                continue
            first = node.args[0]
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                continue  # dynamic key — not statically checkable
            if first.value not in I._EN:
                missing.append(f"{path.name}:{node.lineno}: {first.value[:60]!r}")
    assert not missing, "t() literals missing from _EN:\n" + "\n".join(missing)


def test_en_entries_are_nonempty():
    import core.i18n as I

    empty = [k for k, v in I._EN.items() if not str(v).strip()]
    assert not empty, f"empty EN translations: {empty}"


def test_t_format_failure_falls_back_to_source():
    import core.i18n as I

    original = I.get_language()
    try:
        I.set_language("zh")
        # literal braces + no kwargs: untouched
        assert I.t('{"a": 1}') == '{"a": 1}'
        # format attempt fails -> fall back to the unformatted source, no crash
        assert I.t('{"a": 1}', x=1) == '{"a": 1}'
        I.set_language("en")
        assert I.t('{"a": 1}', x=1) == '{"a": 1}'
        # normal formatting still works in both directions
        I.set_language("zh")
        assert I.t("已扫描: {n_models} 个模型, {n_mmprojs} 个 mmproj", n_models=1, n_mmprojs=2) == \
            "已扫描: 1 个模型, 2 个 mmproj"
    finally:
        I.set_language(original)
