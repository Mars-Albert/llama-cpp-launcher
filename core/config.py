import json
import logging
import re
import shutil
from pathlib import Path
from datetime import datetime

from core.defaults import get_default_params, _FALLBACK_DEFAULTS
from core.i18n import t

logger = logging.getLogger(__name__)


def _sanitize_preset_name(name: str) -> str:
    """Remove path separators and traversal sequences to prevent path traversal."""
    return re.sub(r'[/\\:\x00]', '_', name).strip('. ')


CONFIG_DIR = Path.home() / ".llama-cpp-launcher"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
PRESETS_DIR = CONFIG_DIR / "presets"
PRESETS_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_FILE = CONFIG_DIR / "settings.json"

DEFAULT_PRESET = dict(_FALLBACK_DEFAULTS)


def _load_settings() -> dict:
    if not SETTINGS_FILE.exists():
        return {}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_settings(settings: dict):
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


def _refresh_defaults(help_text=None):
    global DEFAULT_PRESET
    DEFAULT_PRESET = get_default_params(help_text=help_text)


class ConfigManager:
    def __init__(self, defaults=None):
        self._defaults = defaults or dict(DEFAULT_PRESET)
        self.current = dict(self._defaults)

    @property
    def defaults(self):
        return self._defaults

    def set(self, key, value):
        self.current[key] = value

    def get(self, key, default=None):
        return self.current.get(key, default)

    def reset(self):
        self.current = dict(self._defaults)

    def save_preset(self, name):
        name = _sanitize_preset_name(name)
        path = PRESETS_DIR / f"{name}.json"
        data = {
            "name": name,
            "created": datetime.now().isoformat(),
            "params": dict(self.current),
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
        self.current = data.get("params", dict(self._defaults))
        return True

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
        presets = []
        for f in PRESETS_DIR.glob("*.json"):
            presets.append({
                "name": f.stem,
                "created": datetime.fromtimestamp(f.stat().st_mtime).isoformat() if f.exists() else "",
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
        try:
            with open(src_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or "params" not in data:
                logger.warning(t("导入预设失败: 文件格式无效 {src_path}", src_path=src_path))
                return False
            dest_name = _sanitize_preset_name(Path(src_path).stem)
            dest = PRESETS_DIR / f"{dest_name}.json"
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except (OSError, IOError, json.JSONDecodeError) as e:
            logger.warning(t("导入预设失败: {e}", e=e))
            return False
