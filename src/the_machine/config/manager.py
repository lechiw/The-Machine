"""
配置管理器 — 加载、校验、热重载、白名单管理

用法：
    config = ConfigManager.load("config.json")
    config.get("detection.confidence")      # 0.5
    config.hot_reload()                     # 文件变更时调用
"""
import json
import os
import threading
from pathlib import Path
from typing import Any, Optional

from jsonschema import validate, ValidationError

from ..exceptions import ConfigError, ConfigValidationError
from .schema import CONFIG_SCHEMA, DEFAULT_CONFIG


class ConfigManager:
    """配置管理器 — 单例风格，管理配置全生命周期"""

    def __init__(self, path: Optional[str] = None):
        self._path: Optional[Path] = Path(path) if path else None
        self._config: dict = {}
        self._lock = threading.Lock()
        self._watchdog: Optional[Any] = None

    # ── 加载 ──

    @classmethod
    def load(cls, path: str) -> "ConfigManager":
        """从 JSON 文件加载配置并校验"""
        config_path = Path(path)
        if not config_path.exists():
            return cls._fallback(f"配置文件不存在: {path}")

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except json.JSONDecodeError as e:
            raise ConfigError(f"配置文件 JSON 解析失败: {e}")

        errors = cls._validate_raw(raw)
        if errors:
            raise ConfigValidationError(f"配置校验失败: {'; '.join(errors)}")

        merged = cls._merge_defaults(raw)
        manager = cls(path)
        manager._config = merged
        return manager

    @classmethod
    def _fallback(cls, reason: str) -> "ConfigManager":
        """配置文件缺失时 fallback 到默认配置"""
        manager = cls()
        manager._config = DEFAULT_CONFIG.copy()
        return manager

    # ── 校验 ──

    @staticmethod
    def _validate_raw(raw: dict) -> list[str]:
        """校验原始配置，返回错误列表，空列表表示通过"""
        errors = []
        try:
            validate(instance=raw, schema=CONFIG_SCHEMA)
        except ValidationError as e:
            path = " → ".join(str(p) for p in e.absolute_path) if e.absolute_path else "root"
            errors.append(f"[{path}] {e.message}")
        return errors

    @staticmethod
    def _merge_defaults(raw: dict) -> dict:
        """将默认值与用户配置合并，确保所有字段存在"""
        merged = DEFAULT_CONFIG.copy()
        merged.update(raw)

        # 递归合并嵌套 dict
        for key in DEFAULT_CONFIG:
            if key in raw and isinstance(DEFAULT_CONFIG[key], dict):
                merged[key] = {**DEFAULT_CONFIG[key], **raw[key]}

        return merged

    # ── 取值 ──

    def get(self, key_path: str, default: Any = None) -> Any:
        """按点分路径取值，如 get('detection.confidence')"""
        keys = key_path.split(".")
        value = self._config
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
                if value is None:
                    return default
            else:
                return default
        return value

    @property
    def config(self) -> dict:
        """获取完整配置副本（防止外部修改）"""
        return self._config.copy()

    # ── 热重载 ──

    def hot_reload(self) -> bool:
        """重新加载配置文件并校验，返回是否成功"""
        if self._path is None or not self._path.exists():
            return False

        try:
            with open(self._path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError):
            return False

        errors = self._validate_raw(raw)
        if errors:
            return False

        with self._lock:
            merged = self._merge_defaults(raw)
            self._config = merged
        return True

    def enable_watchdog(self) -> None:
        """启用配置文件变更监听（需 watchdog 库）"""
        if self._path is None:
            return
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            class ConfigChangeHandler(FileSystemEventHandler):
                def __init__(self, manager: "ConfigManager"):
                    self.manager = manager

                def on_modified(self, event):
                    if event.src_path == str(self.manager._path):
                        if self.manager.hot_reload():
                            pass  # 重新加载成功
                        else:
                            pass  # 重新加载失败，保持旧配置

            event_handler = ConfigChangeHandler(self)
            self._watchdog = Observer()
            self._watchdog.schedule(event_handler, str(self._path.parent), recursive=False)
            self._watchdog.start()
        except ImportError:
            pass  # watchdog 未安装，静默跳过

    def disable_watchdog(self) -> None:
        """停止配置文件监听"""
        if self._watchdog:
            self._watchdog.stop()
            self._watchdog = None

    # ── 运行时修改（热重载不修改文件，运行时修改直接写文件） ──

    def update(self, key_path: str, value: Any) -> None:
        """运行时更新配置（内存 + 文件）"""
        keys = key_path.split(".")
        with self._lock:
            target = self._config
            for key in keys[:-1]:
                target = target.setdefault(key, {})
            target[keys[-1]] = value

            if self._path:
                with open(self._path, "w", encoding="utf-8") as f:
                    json.dump(self._config, f, ensure_ascii=False, indent=2)

    def __repr__(self) -> str:
        return f"<ConfigManager cameras={len(self._config.get('cameras', []))}>"
