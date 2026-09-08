import json
import logging
import re
import shutil
from pathlib import Path
from datetime import datetime

from core.defaults import _FALLBACK_DEFAULTS
from core.i18n import t

logger = logging.getLogger(__name__)


def _sanitize_preset_name(name: str) -> str:
    """Remove path separators and traversal sequences to prevent path traversal."""
    result = re.sub(r'[/\\:\x00]', '_', name).strip('. ')
    return result if result else "unnamed"


CONFIG_DIR = Path.home() / ".llama-cpp-launcher"
PRESETS_DIR = CONFIG_DIR / "presets"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
# E3: full (un-truncated) log of the most recent server run
LOGS_DIR = CONFIG_DIR / "logs"
LAST_RUN_LOG = LOGS_DIR / "last_run.log"

_dirs_initialized = False

def _ensure_dirs():
    global _dirs_initialized
    if not _dirs_initialized:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        PRESETS_DIR.mkdir(parents=True, exist_ok=True)
        _dirs_initialized = True

DEFAULT_PRESET = dict(_FALLBACK_DEFAULTS)


def _load_settings() -> dict:
    if not SETTINGS_FILE.exists():
        return {}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, IOError, json.JSONDecodeError) as e:
        logger.warning(t("加载设置失败: {e}", e=e))
        return {}


def _save_settings(settings: dict):
    _ensure_dirs()
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
    except (OSError, IOError) as e:
        logger.warning(t("保存设置失败: {e}", e=e))


def save_scan_path(path: str):
    settings = _load_settings()
    settings["scan_path"] = path
    _save_settings(settings)


def load_scan_path() -> str | None:
    return _load_settings().get("scan_path")


def save_language(lang: str):
    settings = _load_settings()
    settings["language"] = lang
    _save_settings(settings)


def load_language() -> str:
    return _load_settings().get("language", "zh")


def save_ui_prefs(prefs: dict):
    """E2: persist window geometry/mode/tabs/splitter ratio (small JSON-safe dict)."""
    settings = _load_settings()
    settings["ui"] = prefs
    _save_settings(settings)


def load_ui_prefs() -> dict:
    prefs = _load_settings().get("ui")
    return prefs if isinstance(prefs, dict) else {}


# E5: light/dark theme, persisted in settings.json

def load_theme() -> str:
    return "dark" if _load_settings().get("theme") == "dark" else "light"


def save_theme(theme: str):
    settings = _load_settings()
    settings["theme"] = "dark" if theme == "dark" else "light"
    _save_settings(settings)


# E1: configurable llama-server path.
# Resolution order: explicit path in settings.json (if the file still exists)
# > shutil.which("llama-server") (i.e. PATH, the previous behavior) > bare
# "llama-server" (last resort, so errors surface the same way as before).
_server_path_cache = None


def load_server_path() -> str:
    return _load_settings().get("server_path", "") or ""


# Last-used preset: the launcher restores on startup the preset the user
# last clicked 加载 for. The name lives in settings.json ("" = never loaded,
# i.e. startup keeps the defaults — nothing to restore).

def load_last_preset() -> str:
    name = _load_settings().get("last_preset", "")
    return name if isinstance(name, str) else ""


def save_last_preset(name: str):
    settings = _load_settings()
    settings["last_preset"] = name
    _save_settings(settings)


def save_server_path(path: str):
    global _server_path_cache
    settings = _load_settings()
    settings["server_path"] = path
    _save_settings(settings)
    _server_path_cache = None  # invalidate so every caller sees the new path


def get_server_path() -> str:
    """Resolve the llama-server executable path (E1), cached.

    Called on the command-preview tick (300ms) and from the startup worker,
    so the result is cached and only invalidated by save_server_path().
    """
    global _server_path_cache
    if _server_path_cache is not None:
        return _server_path_cache
    explicit = load_server_path()
    if explicit:
        if Path(explicit).is_file():
            _server_path_cache = explicit
            return explicit
        logger.warning("Configured llama-server path no longer exists: %s — falling back to PATH", explicit)
    found = shutil.which("llama-server")
    _server_path_cache = found if found else "llama-server"
    return _server_path_cache


def refresh_defaults(defaults):
    global DEFAULT_PRESET
    DEFAULT_PRESET = defaults


class ConfigManager:
    """Preset JSON IO (plan C3).

    Deliberately stateless about parameter values: MainWindow.params is the
    single source of truth. Presets are passed in / returned as plain dicts;
    the only state kept here is the defaults baseline (used to store just the
    diff on save and to merge against on load).
    """

    def __init__(self, defaults=None):
        self._defaults = defaults or dict(DEFAULT_PRESET)

    @property
    def defaults(self):
        return self._defaults

    def set_defaults(self, defaults):
        """Replace the defaults baseline (live-parsed defaults arriving after startup, plan A10)."""
        self._defaults = dict(defaults)

    def save_preset(self, name, params):
        """Save a params dict as a preset (only the diff vs. defaults is stored)."""
        _ensure_dirs()
        name = _sanitize_preset_name(name)
        path = PRESETS_DIR / f"{name}.json"
        # E6: overwriting a preset keeps its original creation time
        created = datetime.now().isoformat()
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    old = json.load(f)
                if isinstance(old.get("created"), str) and old["created"]:
                    created = old["created"]
            except (OSError, IOError, json.JSONDecodeError):
                pass
        data = {
            "name": name,
            "version": 1,  # A9: schema version for future preset migrations
            "created": created,
            "params": {k: v for k, v in params.items()
                       if v != self._defaults.get(k)},
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except (OSError, IOError) as e:
            logger.warning(t("保存预设失败: {e}", e=e))
            return False
        return True

    def load_preset(self, name):
        name = _sanitize_preset_name(name)
        path = PRESETS_DIR / f"{name}.json"
        if not path.exists():
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, IOError, json.JSONDecodeError) as e:
            logger.warning(t("加载预设失败: {e}", e=e))
            return False
        params = data.get("params", {})
        if not isinstance(params, dict):
            logger.warning(t("加载预设失败: params 字段不是字典"))
            return False
        params = dict(params)
        # Migrate param keys renamed/removed across llama-server versions
        if "checkpoint_every_n_tokens" in params and "checkpoint_min_step" not in params:
            params["checkpoint_min_step"] = params.pop("checkpoint_every_n_tokens")
        params.pop("ctx_size_draft", None)
        # C3: return the merged params instead of mutating self.current —
        # MainWindow.params is the single source of truth
        merged = dict(self._defaults)
        merged.update(params)
        return merged

    def preset_stored_keys(self, name):
        """Keys the preset explicitly stores (post-migration), or None.

        None when the preset is missing/unreadable. Used at startup so a
        restored preset's explicit values survive the live --help defaults
        merge: keys the user deliberately set are protected, keys the preset
        leaves to the defaults are free to adopt the live default.
        """
        name = _sanitize_preset_name(name)
        path = PRESETS_DIR / f"{name}.json"
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, IOError, json.JSONDecodeError):
            return None
        params = data.get("params", {})
        if not isinstance(params, dict):
            return set()
        keys = set(params.keys())
        # Mirror load_preset()'s cross-version migration so the protected
        # set matches the keys that actually end up in the merged params.
        if "checkpoint_every_n_tokens" in keys and "checkpoint_min_step" not in keys:
            keys.discard("checkpoint_every_n_tokens")
            keys.add("checkpoint_min_step")
        keys.discard("ctx_size_draft")
        return keys

    def delete_preset(self, name):
        name = _sanitize_preset_name(name)
        path = PRESETS_DIR / f"{name}.json"
        if path.exists():
            try:
                path.unlink()
                return True
            except OSError:
                return False
        return False

    def list_presets(self):
        _ensure_dirs()
        presets = []
        for f in PRESETS_DIR.glob("*.json"):
            try:
                # E6: the JSON's own created field is the source of truth;
                # mtime is only a fallback for hand-edited/legacy files
                created = datetime.fromtimestamp(f.stat().st_mtime).isoformat()
                try:
                    with open(f, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                    if isinstance(data.get("created"), str) and data["created"]:
                        created = data["created"]
                except (OSError, IOError, json.JSONDecodeError):
                    pass
            except (FileNotFoundError, OSError):
                continue
            presets.append({
                "name": f.stem,
                "created": created,
                "path": str(f),
            })
        return sorted(presets, key=lambda x: x["name"])

    def export_preset(self, name, dest_path):
        name = _sanitize_preset_name(name)
        src = PRESETS_DIR / f"{name}.json"
        if src.exists():
            try:
                shutil.copy2(src, dest_path)
                return True
            except (OSError, IOError):
                return False
        return False

    def import_preset(self, src_path):
        _ensure_dirs()
        try:
            with open(src_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or "params" not in data:
                logger.warning(t("导入预设失败: 文件格式无效 {src_path}", src_path=src_path))
                return False
            if not isinstance(data["params"], dict):
                logger.warning(t("导入预设失败: params 字段不是字典"))
                return False
            dest_name = _sanitize_preset_name(Path(src_path).stem)
            dest = PRESETS_DIR / f"{dest_name}.json"
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except (OSError, IOError, json.JSONDecodeError) as e:
            logger.warning(t("导入预设失败: {e}", e=e))
            return False
