"""
Spec: 通知模块 — QQ 告警推送规约

验收标准：
- AnomalyEvent 转成 QQ 消息格式
- 告警附带截图证据（本地路径或 base64）
- 告警级别决定消息优先级
- 支持静默模式/免打扰时段
"""

import pytest
from datetime import time


class TestNumberEventSpec:
    """告警事件格式规约"""

    REQUIRED_FIELDS = ['id', 'camera_id', 'timestamp', 'event_type', 'score', 'reason']

    def test_anomaly_event_has_required_fields(self, mock_number_event):
        """告警事件必须包含所有必填字段"""
        for field in self.REQUIRED_FIELDS:
            assert hasattr(mock_number_event, field), f"缺少必填字段 '{field}'"

    def test_event_id_is_unique(self, mock_event_generator):
        """告警 ID 应全局唯一"""
        ids = set()
        for _ in range(1000):
            event = mock_event_generator.generate()
            assert event.id not in ids, f"告警 ID {event.id} 重复"
            ids.add(event.id)

    def test_event_carries_evidence(self, mock_number_event):
        """告警应携带证据（截图路径）"""
        assert hasattr(mock_number_event, 'evidence_path'), "缺少证据路径"
        if mock_number_event.evidence_path:
            assert isinstance(mock_number_event.evidence_path, str), "证据路径应为字符串"


class TestQQMessageFormatSpec:
    """QQ 消息格式规约"""

    def test_message_contains_number_header(self, mock_formatter, mock_number_event):
        """QQ 消息应以 '🚨 Number #{ID}' 开头"""
        msg = mock_formatter.format(mock_number_event)
        assert msg.startswith('🚨'), "消息应以 🚨 开头"
        assert 'Number #' in msg, "消息应包含 Number # 标记"
        assert str(mock_number_event.id) in msg, "消息应包含告警 ID"

    def test_message_contains_key_details(self, mock_formatter, mock_number_event):
        """消息应包含时间、区域、类型、置信度"""
        msg = mock_formatter.format(mock_number_event)
        checks = [
            '区域：', '类型：', '置信度：',
            mock_number_event.camera_id,
            mock_number_event.event_type,
        ]
        for check in checks:
            assert check in msg, f"消息缺少关键信息: '{check}'"

    def test_message_contains_reason(self, mock_formatter, mock_number_event):
        """消息应包含推理摘要"""
        msg = mock_formatter.format(mock_number_event)
        assert '详情：' in msg, "消息缺少推理详情"
        assert mock_number_event.reason in msg, "消息应包含推理摘要文字"

    def test_no_evidence_no_crash(self, mock_formatter):
        """无证据截图时不影响消息生成"""
        event = mock_formatter.create_event_without_evidence()
        msg = mock_formatter.format(event)
        assert len(msg) > 0, "无证据时也应正常生成消息"

    def test_message_length_limit(self, mock_formatter, mock_number_event):
        """QQ 消息应控制在合理长度内（< 2000 字符）"""
        msg = mock_formatter.format(mock_number_event)
        assert len(msg) < 2000, f"消息长度 {len(msg)} 超过 2000 字符限制"


class TestQuietModeSpec:
    """静默模式规约"""

    def test_quiet_mode_suppresses_alerts(self, mock_notifier):
        """静默模式下不应推送告警"""
        mock_notifier.set_quiet_mode(True)
        result = mock_notifier.send(mock_notifier.make_event(), dry_run=True)
        assert result['suppressed'] is True, "静默模式应压制告警"

    def test_normal_mode_sends_alerts(self, mock_notifier):
        """正常模式下应推送告警"""
        mock_notifier.set_quiet_mode(False)
        result = mock_notifier.send(mock_notifier.make_event(), dry_run=True)
        assert result['sent'] is True, "正常模式应发送告警"
        assert result['suppressed'] is False

    def test_do_not_disturb_hours(self, mock_notifier):
        """在免打扰时段内不应推送"""
        mock_notifier.set_do_not_disturb(time(23, 0), time(7, 0))

        # 凌晨 3 点（免打扰）
        mock_notifier.set_current_time(time(3, 0))
        result = mock_notifier.send(mock_notifier.make_event(), dry_run=True)
        assert result['suppressed'] is True, "免打扰时段应压制告警"

        # 下午 3 点（非免打扰）
        mock_notifier.set_current_time(time(15, 0))
        result = mock_notifier.send(mock_notifier.make_event(), dry_run=True)
        assert result['suppressed'] is False, "非免打扰时段应发送"
