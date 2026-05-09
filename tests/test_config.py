"""测试：配置管理与校验 — 对应 spec.md 中的 A5 验收标准"""
import json
import tempfile
from pathlib import Path

import pytest

from the_machine.config import ConfigManager, DEFAULT_CONFIG, CONFIG_SCHEMA
from the_machine.config.whitelist import WhitelistManager


class TestConfigValidation:
    """A5: 配置校验"""

    VALID_CONFIG = {
        "cameras": [
            {
                "id": "front_door",
                "name": "门口",
                "rtsp": "rtsp://192.168.1.100:554/stream1",
            }
        ],
        "detection": {"confidence": 0.5},
        "anomaly": {},
    }

    def test_valid_config_returns_no_errors(self):
        """有效配置应通过校验"""
        errors = ConfigManager._validate_raw(self.VALID_CONFIG)
        assert errors == []

    def test_missing_cameras_returns_errors(self):
        """缺少 cameras 应返回错误"""
        errors = ConfigManager._validate_raw({"detection": {"confidence": 0.5}, "anomaly": {}})
        assert len(errors) > 0

    def test_camera_missing_id_returns_errors(self):
        """cameras 条目缺少 id 应返回错误"""
        errors = ConfigManager._validate_raw({
            "cameras": [{"name": "门口", "rtsp": "rtsp://..."}],
            "detection": {"confidence": 0.5},
            "anomaly": {},
        })
        assert len(errors) > 0

    def test_camera_missing_rtsp_returns_errors(self):
        """cameras 条目缺少 rtsp 应返回错误"""
        errors = ConfigManager._validate_raw({
            "cameras": [{"id": "cam1", "name": "门口"}],
            "detection": {"confidence": 0.5},
            "anomaly": {},
        })
        assert len(errors) > 0

    def test_confidence_out_of_range(self):
        """confidence 超出 [0,1] 应返回错误"""
        errors = ConfigManager._validate_raw({
            "cameras": [{"id": "cam1", "name": "x", "rtsp": "rtsp://..."}],
            "detection": {"confidence": 1.5},
            "anomaly": {},
        })
        assert len(errors) > 0

    def test_invalid_rule_name(self):
        """rules 中不存在的规则名应返回错误"""
        errors = ConfigManager._validate_raw({
            "cameras": [{"id": "cam1", "name": "x", "rtsp": "rtsp://..."}],
            "detection": {"confidence": 0.5},
            "anomaly": {"rules": ["unknown_person", "magic_rule"]},
        })
        assert len(errors) > 0

    def test_unknown_field_rejected(self):
        """不应允许额外未知字段"""
        errors = ConfigManager._validate_raw({
            "cameras": [{"id": "cam1", "name": "x", "rtsp": "rtsp://..."}],
            "detection": {"confidence": 0.5},
            "anomaly": {},
            "unknown_field": "should_not_exist",
        })
        assert len(errors) > 0


class TestConfigLoad:
    """A5: 配置加载"""

    def test_load_from_file(self):
        """配置应从 JSON 文件加载"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "cameras": [{"id": "cam1", "name": "测试", "rtsp": "rtsp://localhost/test"}],
                "detection": {"confidence": 0.5},
                "anomaly": {},
            }, f)
            path = f.name

        try:
            config = ConfigManager.load(path)
            assert config is not None
            assert len(config.get("cameras")) == 1
        finally:
            Path(path).unlink(missing_ok=True)

    def test_missing_file_fallback(self):
        """配置文件缺失应 fallback 到默认配置"""
        config = ConfigManager.load("/nonexistent/path.json")
        assert config.get("detection.confidence") == DEFAULT_CONFIG["detection"]["confidence"]

    def test_get_dot_path(self):
        """点分路径取值应正确"""
        config = ConfigManager.load("/nonexistent/path.json")
        assert config.get("detection.confidence") == 0.5
        assert config.get("detection.interval_sec") == 2.0

    def test_get_with_default(self):
        """不存在的路径应返回 default"""
        config = ConfigManager.load("/nonexistent/path.json")
        assert config.get("nonexistent.key", "fallback") == "fallback"


class TestConfigHotReload:
    """A5: 配置变更热重载"""

    def test_hot_reload_updates_config(self):
        """热重载后配置应更新"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "cameras": [{"id": "cam1", "name": "旧", "rtsp": "rtsp://old"}],
                "detection": {"confidence": 0.5},
                "anomaly": {},
            }, f)
            path = f.name

        try:
            config = ConfigManager.load(path)
            assert config.get("cameras")[0]["name"] == "旧"

            # 修改文件
            with open(path, "w", encoding="utf-8") as f:
                json.dump({
                    "cameras": [{"id": "cam1", "name": "新", "rtsp": "rtsp://new"}],
                    "detection": {"confidence": 0.5},
                    "anomaly": {},
                }, f)

            assert config.hot_reload() is True
            assert config.get("cameras")[0]["name"] == "新"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_hot_reload_invalid_config_keeps_old(self):
        """无效配置热重载应保留旧配置"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "cameras": [{"id": "cam1", "name": "保留", "rtsp": "rtsp://keep"}],
                "detection": {"confidence": 0.5},
                "anomaly": {},
            }, f)
            path = f.name

        try:
            config = ConfigManager.load(path)
            assert config.get("cameras")[0]["name"] == "保留"

            # 写入无效配置
            with open(path, "w", encoding="utf-8") as f:
                f.write("invalid json{")

            assert config.hot_reload() is False
            assert config.get("cameras")[0]["name"] == "保留"  # 未变
        finally:
            Path(path).unlink(missing_ok=True)

    def test_runtime_update_writes_file(self):
        """运行时修改应同时更新内存和文件"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "cameras": [{"id": "cam1", "name": "原始", "rtsp": "rtsp://x"}],
                "detection": {"confidence": 0.5},
                "anomaly": {},
            }, f)
            path = f.name

        try:
            config = ConfigManager.load(path)
            config.update("detection.confidence", 0.8)

            assert config.get("detection.confidence") == 0.8

            # 文件也应更新
            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            assert saved["detection"]["confidence"] == 0.8
        finally:
            Path(path).unlink(missing_ok=True)


class TestWhitelistManager:
    """A5: 白名单管理"""

    def test_add_person(self):
        """白名单应支持新增人员"""
        config = ConfigManager.load("/nonexistent/path.json")
        wm = WhitelistManager(config)
        wm.add("张三", "zhangsan_face")
        names = [p["name"] for p in wm.list()]
        assert "张三" in names

    def test_remove_person(self):
        """白名单应支持移除人员"""
        config = ConfigManager.load("/nonexistent/path.json")
        wm = WhitelistManager(config)
        wm.add("待删除", "temp")
        wm.remove("待删除")
        names = [p["name"] for p in wm.list()]
        assert "待删除" not in names

    def test_remove_nonexistent(self):
        """移除不存在的人员应返回 False"""
        config = ConfigManager.load("/nonexistent/path.json")
        wm = WhitelistManager(config)
        assert wm.remove("不存在的人") is False

    def test_is_known(self):
        """已知 face_label 应返回对应名称"""
        config = ConfigManager.load("/nonexistent/path.json")
        wm = WhitelistManager(config)
        wm.add("老大", "laoda_face")
        assert wm.is_known("laoda_face") == "老大"
        assert wm.is_known("unknown_face") is None
