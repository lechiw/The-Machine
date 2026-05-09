"""测试：分析模块 — 规则引擎 / 评分 / 冷却 / 帧间跟踪"""
import time
from datetime import datetime

from the_machine.models import DetectionResult, Frame, AnomalyScore
from the_machine.analyzer.analyzer import (
    RuleEngine, Scorer, CoolingManager, StayTracker,
    _rule_unknown_person, _rule_off_hours_motion, _rule_prolonged_stay,
)


class TestRuleEngine:
    """规则引擎 — 注册 + 评估"""

    def test_register_and_list(self):
        engine = RuleEngine()
        engine.register("test", lambda ctx: {"triggered": False, "reason": ""})
        assert "test" in engine.list_rules()

    def test_unknown_person_triggered(self):
        engine = RuleEngine()
        engine.register("unknown_person", _rule_unknown_person)
        r = engine.evaluate("unknown_person", {"faces": [{"known": False}]})
        assert r["triggered"] is True

    def test_unknown_person_not_triggered(self):
        engine = RuleEngine()
        engine.register("unknown_person", _rule_unknown_person)
        r = engine.evaluate("unknown_person", {"faces": [{"known": True}]})
        assert r["triggered"] is False

    def test_unknown_person_empty_faces(self):
        engine = RuleEngine()
        engine.register("unknown_person", _rule_unknown_person)
        r = engine.evaluate("unknown_person", {"faces": []})
        assert r["triggered"] is False

    def test_off_hours_triggered(self):
        engine = RuleEngine()
        engine.register("off_hours_motion", _rule_off_hours_motion)
        r = engine.evaluate("off_hours_motion", {
            "is_active_hours": False, "has_objects": True,
        })
        assert r["triggered"] is True

    def test_off_hours_not_triggered_active(self):
        engine = RuleEngine()
        engine.register("off_hours_motion", _rule_off_hours_motion)
        r = engine.evaluate("off_hours_motion", {
            "is_active_hours": True, "has_objects": True,
        })
        assert r["triggered"] is False

    def test_off_hours_not_triggered_no_objects(self):
        engine = RuleEngine()
        engine.register("off_hours_motion", _rule_off_hours_motion)
        r = engine.evaluate("off_hours_motion", {
            "is_active_hours": False, "has_objects": False,
        })
        assert r["triggered"] is False

    def test_prolonged_stay_triggered(self):
        engine = RuleEngine()
        engine.register("prolonged_stay", _rule_prolonged_stay)
        r = engine.evaluate("prolonged_stay", {
            "stay_duration_sec": 600, "max_stay_sec": 300,
        })
        assert r["triggered"] is True

    def test_prolonged_stay_not_triggered(self):
        engine = RuleEngine()
        engine.register("prolonged_stay", _rule_prolonged_stay)
        r = engine.evaluate("prolonged_stay", {
            "stay_duration_sec": 60, "max_stay_sec": 300,
        })
        assert r["triggered"] is False

    def test_evaluate_nonexistent_rule(self):
        engine = RuleEngine()
        r = engine.evaluate("nonexistent", {})
        assert r["triggered"] is False
        assert "不存在" in r["reason"]

    def test_evaluate_all(self):
        engine = RuleEngine()
        engine.register("r1", lambda ctx: {"triggered": True, "reason": "a"})
        engine.register("r2", lambda ctx: {"triggered": False, "reason": "b"})
        results = engine.evaluate_all({})
        assert len(results) == 2
        assert results[0]["name"] == "r1"
        assert results[0]["triggered"] is True


class TestScorer:
    """评分器"""

    def test_no_triggers_zero_score(self):
        scorer = Scorer(threshold=0.7)
        results = [{"triggered": False}, {"triggered": False}]
        score = scorer.score(None, results)  # type: ignore
        assert score.value == 0.0
        assert score.is_alert is False

    def test_all_triggers_max_score(self):
        scorer = Scorer(threshold=0.0)
        results = [
            {"name": "r1", "triggered": True, "reason": "x"},
            {"name": "r2", "triggered": True, "reason": "y"},
        ]
        score = scorer.score(None, results)  # type: ignore
        assert score.value == 1.0

    def test_partial_trigger_score(self):
        scorer = Scorer(threshold=0.7)
        results = [
            {"name": "r1", "triggered": True, "reason": "检测到未知人员"},
            {"name": "r2", "triggered": False, "reason": ""},
        ]
        score = scorer.score(None, results)  # type: ignore
        assert 0 < score.value < 1
        assert "未知人员" in score.reason
        assert score.triggered_rules == ["r1"]

    def test_score_in_range(self):
        scorer = Scorer()
        for data in [[], [{"triggered": False}], [{"triggered": True, "reason": "x"}]]:
            score = scorer.score(None, data)  # type: ignore
            assert 0 <= score.value <= 1


class TestCoolingManager:
    """冷却机制"""

    def test_initial_allowed(self):
        cool = CoolingManager(cooldown_sec=60)
        assert cool.can_alert("cam1", "rule1") is True

    def test_cooldown_suppresses(self):
        cool = CoolingManager(cooldown_sec=300)
        cool.mark_alerted("cam1", "rule1")
        assert cool.can_alert("cam1", "rule1") is False

    def test_different_rule_not_affected(self):
        cool = CoolingManager(cooldown_sec=300)
        cool.mark_alerted("cam1", "rule1")
        assert cool.can_alert("cam1", "rule2") is True  # 不同规则不受影响

    def test_different_camera_not_affected(self):
        cool = CoolingManager(cooldown_sec=300)
        cool.mark_alerted("cam1", "rule1")
        assert cool.can_alert("cam2", "rule1") is True  # 不同摄像头不受影响

    def test_reset_allows_again(self):
        cool = CoolingManager(cooldown_sec=300)
        cool.mark_alerted("cam1", "rule1")
        cool.reset("cam1", "rule1")
        assert cool.can_alert("cam1", "rule1") is True


class TestStayTracker:
    """帧间追踪 — prolonged_stay 支持"""

    def test_initial_no_person(self):
        tracker = StayTracker(max_stay_sec=300)
        info = tracker.update("cam1", has_person=False)
        assert info["continuous"] is False
        assert info["current_duration_sec"] == 0.0

    def test_person_arrives(self):
        tracker = StayTracker(max_stay_sec=300)
        info = tracker.update("cam1", has_person=True)
        assert info["continuous"] is True
        assert info["current_duration_sec"] >= 0.0

    def test_person_leaves(self):
        tracker = StayTracker(max_stay_sec=300)
        tracker.update("cam1", has_person=True)  # arrives
        time.sleep(0.01)
        info = tracker.update("cam1", has_person=False)  # leaves
        assert info["continuous"] is False

    def test_continuous_increases(self):
        tracker = StayTracker(max_stay_sec=300)
        tracker.update("cam1", has_person=True)
        time.sleep(0.05)
        info = tracker.update("cam1", has_person=True)
        assert info["current_duration_sec"] >= 0.03  # 时间应该增加了

    def test_reset_camera(self):
        tracker = StayTracker(max_stay_sec=300)
        tracker.update("cam1", has_person=True)
        tracker.reset_camera("cam1")
        # 重置后像新的一样
        info = tracker.update("cam1", has_person=True)
        assert info["continuous"] is True
        assert info["current_duration_sec"] < 0.5  # 刚刚重置

    def test_multiple_cameras_independent(self):
        tracker = StayTracker(max_stay_sec=300)
        tracker.update("cam1", has_person=True)
        info2 = tracker.update("cam2", has_person=False)
        assert info2["continuous"] is False  # cam2 无人
