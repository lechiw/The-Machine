"""
Spec: 配置模块 — Config Schema 与校验规约

验收标准：
- Config 加载后通过 JSON Schema 校验
- 必填字段缺失时报错
- 字段类型错误时报错
- 白名单支持增删改操作
- 配置热重载（不重启服务）
"""

import pytest
import json
import jsonschema


class TestConfigValidationSpec:
    """配置校验规约"""

    VALID_CONFIG = {
        "cameras": [
            {
                "id": "front_door",
                "name": "门口",
                "rtsp": "rtsp://192.168.1.100:554/stream1",
                "active_hours": {"start": "07:00", "end": "23:00"}
            }
        ],
        "whitelist": [
            {"name": "老大", "face_label": "laoda"}
        ],
        "detection": {
            "model": "yolov8n",
            "confidence": 0.5,
            "interval_sec": 2,
            "target_classes": [0, 2]
        },
        "anomaly": {
            "score_threshold": 0.7,
            "cooldown_sec": 300,
            "rules": ["unknown_person", "off_hours_motion"]
        }
    }

    def test_valid_config_passes(self, config_validator):
        """有效配置应通过校验"""
        errors = config_validator.validate(self.VALID_CONFIG)
        assert errors is None or len(errors) == 0, f"有效配置不应报错: {errors}"

    def test_missing_cameras_field(self, config_validator):
        """缺少 cameras 应报错"""
        invalid = self.VALID_CONFIG.copy()
        del invalid['cameras']
        with pytest.raises(jsonschema.ValidationError):
            config_validator.validate(invalid)

    def test_camera_missing_id(self, config_validator):
        """camera 缺少 id 应报错"""
        invalid = self.VALID_CONFIG.copy()
        invalid['cameras'][0] = {
            "name": "门口",
            "rtsp": "rtsp://192.168.1.100:554/stream1"
        }
        with pytest.raises(jsonschema.ValidationError):
            config_validator.validate(invalid)

    def test_camera_missing_rtsp(self, config_validator):
        """camera 缺少 rtsp 应报错"""
        invalid = self.VALID_CONFIG.copy()
        invalid['cameras'][0] = {
            "id": "front_door",
            "name": "门口"
        }
        with pytest.raises(jsonschema.ValidationError):
            config_validator.validate(invalid)

    def test_invalid_confidence_type(self, config_validator):
        """confidence 应为数字"""
        invalid = self.VALID_CONFIG.copy()
        invalid['detection']['confidence'] = "high"
        with pytest.raises(jsonschema.ValidationError):
            config_validator.validate(invalid)

    def test_confidence_range(self, config_validator):
        """confidence 应在 [0, 1] 范围"""
        for val in [-0.1, 1.5]:
            invalid = self.VALID_CONFIG.copy()
            invalid['detection']['confidence'] = val
            errors = config_validator.validate(invalid)
            assert errors is not None, f"confidence={val} 应校验失败"

    def test_unknown_rule_name(self, config_validator):
        """rules 中不存在的规则名应报错"""
        invalid = self.VALID_CONFIG.copy()
        invalid['anomaly']['rules'] = ["unknown_person", "magic_rule"]
        errors = config_validator.validate(invalid)
        assert errors is not None, "不存在的规则名应校验失败"

    def test_invalid_rtsp_url(self, config_validator):
        """rtsp URL 格式应合法"""
        invalid = self.VALID_CONFIG.copy()
        invalid['cameras'][0]['rtsp'] = "not-a-url"
        errors = config_validator.validate(invalid)
        assert errors is not None, "无效的 RTSP URL 应校验失败"

    def test_empty_config(self, config_validator):
        """空配置应报错"""
        with pytest.raises(jsonschema.ValidationError):
            config_validator.validate({})


class TestConfigManagementSpec:
    """配置管理规约"""

    def test_load_config_from_file(self, config_manager):
        """配置应从 JSON 文件加载"""
        config = config_manager.load("test_config.json")
        assert config is not None
        assert len(config['cameras']) > 0

    def test_whitelist_add_person(self, config_manager):
        """白名单应支持新增人员"""
        config_manager.add_to_whitelist("访客A", "visitor_A")
        whitelist = config_manager.get_whitelist()
        names = [p['name'] for p in whitelist]
        assert "访客A" in names, "新增人员应在白名单中"

    def test_whitelist_remove_person(self, config_manager):
        """白名单应支持移除人员"""
        config_manager.add_to_whitelist("待删除", "temp")
        config_manager.remove_from_whitelist("待删除")
        whitelist = config_manager.get_whitelist()
        names = [p['name'] for p in whitelist]
        assert "待删除" not in names, "移除后不应在白名单中"

    def test_config_hot_reload(self, config_manager):
        """配置热重载应生效，不中断服务"""
        old_confidence = config_manager.get('detection.confidence')
        config_manager.update_config({'detection': {'confidence': 0.8}})
        config_manager.hot_reload()
        new_confidence = config_manager.get('detection.confidence')
        assert new_confidence == 0.8, "热重载后配置应更新"
        # 改回来
        config_manager.update_config({'detection': {'confidence': old_confidence}})
