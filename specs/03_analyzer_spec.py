"""
Spec: 分析模块 — 异常行为评分与规则引擎规约

验收标准：
- Analyzer 维护按时间段/区域的检测基线
- 偏离基线超过阈值触发异常评分
- 规则引擎支持多条规则组合判定
- 连续相似告警应合并（冷却机制）
"""

import pytest
from datetime import datetime, timedelta


class TestBaselineSpec:
    """基线管理规约"""

    def test_baseline_builds_from_history(self, mock_analyzer, sample_detection_history):
        """基线应从历史检测数据中构建"""
        baseline = mock_analyzer.build_baseline(sample_detection_history)
        assert 'avg_objects' in baseline, "基线包含平均目标数"
        assert 'std_objects' in baseline, "基线包含标准差"
        assert 'time_slot' in baseline, "基线包含时间段"
        assert baseline['avg_objects'] >= 0, "平均目标数非负"

    def test_baseline_by_time_slot(self, mock_analyzer, sample_detection_history):
        """基线应按时间段区分（如 08:00-08:15 与 02:00-02:15 不同）"""
        morning = mock_analyzer.build_baseline(sample_detection_history, time_slot='08:00-08:15')
        night = mock_analyzer.build_baseline(sample_detection_history, time_slot='02:00-02:15')
        # 如果早上有更多人流，基线应不同
        assert morning['avg_objects'] != night['avg_objects'] or \
               morning['std_objects'] != night['std_objects'], \
            "不同时间段基线应有差异"

    def test_baseline_adapts(self, mock_analyzer):
        """基线应随时间推移自适应更新"""
        old_baseline = {'avg_objects': 2.0, 'std_objects': 0.5, 'samples': 100}
        # 新增 50 个样本（新常态：5 个人）
        new_samples = [{'num_objects': 5} for _ in range(50)]
        updated = mock_analyzer.update_baseline(old_baseline, new_samples)
        assert updated['avg_objects'] > old_baseline['avg_objects'], "基线应反映新趋势"


class TestAnomalyScoringSpec:
    """异常评分规约"""

    def test_normal_activity_low_score(self, mock_analyzer, normal_activity_data):
        """正常活动模式下评分应低于告警阈值"""
        score = mock_analyzer.score(normal_activity_data)
        assert score.value < score.threshold, f"正常活动评分 {score.value} 应 < 阈值 {score.threshold}"

    def test_anomaly_activity_high_score(self, mock_analyzer, anomaly_activity_data):
        """异常活动模式下评分应超过告警阈值"""
        score = mock_analyzer.score(anomaly_activity_data)
        assert score.value >= score.threshold, f"异常活动评分 {score.value} 应 >= 阈值 {score.threshold}"

    def test_score_is_normalized(self, mock_analyzer):
        """评分应在 [0, 1] 范围内"""
        for data in [{'num_objects': 0}, {'num_objects': 100}]:
            score = mock_analyzer.score(data)
            assert 0 <= score.value <= 1, f"评分 {score.value} 超出 [0,1]"

    def test_score_contains_reason(self, mock_analyzer, anomaly_activity_data):
        """评分必须附带推理说明"""
        score = mock_analyzer.score(anomaly_activity_data)
        assert score.reason is not None, "评分必须附带推理原因"
        assert len(score.reason) > 0, "推理原因不能为空字符串"
        assert isinstance(score.reason, str), "推理原因应为字符串"


class TestRuleEngineSpec:
    """规则引擎规约"""

    RULES = ['unknown_person', 'off_hours_motion', 'prolonged_stay', 'suspicious_object']

    def test_all_rules_registered(self, mock_rule_engine):
        """规则引擎应注册所有预设规则"""
        registered = mock_rule_engine.list_rules()
        for rule in self.RULES:
            assert rule in registered, f"规则 '{rule}' 未注册"

    def test_unknown_person_rule(self, mock_rule_engine):
        """unknown_person: 白名单之外的人出现 → 告警"""
        result = mock_rule_engine.evaluate('unknown_person', {
            'known_faces': [],
            'faces_detected': 1,
        })
        assert result['triggered'] is True, "出现未知人脸应触发告警"

    def test_unknown_person_no_alert_when_known(self, mock_rule_engine):
        """白名单人员出现不应触发 unknown_person"""
        result = mock_rule_engine.evaluate('unknown_person', {
            'known_faces': ['老大'],
            'all_faces_known': True,
        })
        assert result['triggered'] is False, "只有已知人脸不应触发告警"

    def test_off_hours_motion_rule(self, mock_rule_engine):
        """off_hours_motion: 非活动时段有移动目标 → 告警"""
        result = mock_rule_engine.evaluate('off_hours_motion', {
            'is_active_hours': False,
            'motion_detected': True,
        })
        assert result['triggered'] is True, "非活动时段有动静应触发告警"

    def test_off_hours_no_alert_during_active_hours(self, mock_rule_engine):
        """活动时段不应触发 off_hours_motion"""
        result = mock_rule_engine.evaluate('off_hours_motion', {
            'is_active_hours': True,
            'motion_detected': True,
        })
        assert result['triggered'] is False, "活动时段不应触发"

    def test_prolonged_stay_rule(self, mock_rule_engine):
        """prolonged_stay: 同一区域滞留超过阈值 → 告警"""
        result = mock_rule_engine.evaluate('prolonged_stay', {
            'stay_duration_sec': 600,
            'max_stay_sec': 300,
        })
        assert result['triggered'] is True, "滞留超过阈值应触发告警"

    def test_prolonged_stay_no_alert_under_threshold(self, mock_rule_engine):
        """短暂停留不应触发"""
        result = mock_rule_engine.evaluate('prolonged_stay', {
            'stay_duration_sec': 60,
            'max_stay_sec': 300,
        })
        assert result['triggered'] is False, "未超阈值不应告警"


class TestCoolingSpec:
    """冷却机制规约"""

    def test_same_event_cooldown(self, mock_analyzer, anomaly_activity_data):
        """同一类型的告警在冷却期内不应重复触发"""
        first = mock_analyzer.score_and_alert(anomaly_activity_data)
        assert first is not None, "首次应触发告警"

        # 立即再次触发（冷却期内）
        second = mock_analyzer.score_and_alert(anomaly_activity_data)
        assert second is None, "冷却期内不应重复触发"

    def test_cooling_expires(self, mock_analyzer, anomaly_activity_data):
        """冷却期过后应允许再次触发"""
        first = mock_analyzer.score_and_alert(anomaly_activity_data)
        assert first is not None

        # 模拟冷却期结束
        mock_analyzer.reset_cooldown('front_door', 'unknown_person')

        third = mock_analyzer.score_and_alert(anomaly_activity_data)
        assert third is not None, "冷却期结束后应允许再次触发"
