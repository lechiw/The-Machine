"""分析模块 — 基线管理 + 规则引擎 + 异常评分 + 冷却机制"""
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, Optional

from ..models import AnomalyScore, Baseline, DetectionResult


# ── 基线管理 ──

class BaselineManager:
    """按时间段（15 分钟 slot）维护检测基线"""

    SLOT_MINUTES = 15

    def __init__(self):
        self._baselines: dict[str, Baseline] = {}

    def _slot_key(self, dt: Optional[datetime] = None) -> str:
        now = dt or datetime.now()
        slot = (now.hour * 60 + now.minute) // self.SLOT_MINUTES
        total_minutes = slot * self.SLOT_MINUTES
        h, m = total_minutes // 60, total_minutes % 60
        end_h, end_m = (total_minutes + self.SLOT_MINUTES) // 60, (total_minutes + self.SLOT_MINUTES) % 60
        return f"{h:02d}:{m:02d}-{end_h:02d}:{end_m:02d}"

    def build(self, history: list[dict]) -> Baseline:
        """从历史数据构建基线"""
        slot = self._slot_key()
        if not history:
            return Baseline(time_slot=slot, avg_objects=0.0, std_objects=0.0, samples=0)

        obj_counts = [h.get("num_objects", 0) for h in history]
        avg = sum(obj_counts) / len(obj_counts)
        variance = sum((c - avg) ** 2 for c in obj_counts) / len(obj_counts)

        return Baseline(
            time_slot=slot,
            avg_objects=avg,
            std_objects=variance ** 0.5,
            samples=len(history),
        )

    def update(self, baseline: Baseline, new_samples: list[dict]) -> Baseline:
        """增量更新基线"""
        if not new_samples:
            return baseline

        new_counts = [s.get("num_objects", 0) for s in new_samples]
        n = baseline.samples
        m = len(new_samples)

        old_sum = baseline.avg_objects * n
        new_sum = sum(new_counts)
        new_avg = (old_sum + new_sum) / (n + m)

        return Baseline(
            time_slot=baseline.time_slot,
            avg_objects=new_avg,
            std_objects=baseline.std_objects,  # 简化：不重算标准差
            samples=n + m,
        )

    def get(self, time_slot: str) -> Optional[Baseline]:
        return self._baselines.get(time_slot)


# ── 规则引擎 ──

RuleFn = Callable[[dict], dict]


class RuleEngine:
    """规则引擎 — 注册 + 评估"""

    def __init__(self):
        self._rules: dict[str, RuleFn] = {}

    def register(self, name: str, rule_fn: RuleFn) -> None:
        self._rules[name] = rule_fn

    def evaluate(self, name: str, context: dict) -> dict:
        """评估单条规则，返回 {'triggered': bool, 'reason': str}"""
        if name not in self._rules:
            return {"triggered": False, "reason": f"规则 '{name}' 不存在"}
        return self._rules[name](context)

    def evaluate_all(self, context: dict) -> list[dict]:
        """评估所有已注册规则"""
        return [
            {"name": name, **self.evaluate(name, context)}
            for name in self._rules
        ]

    def list_rules(self) -> list[str]:
        return list(self._rules.keys())


def _rule_unknown_person(ctx: dict) -> dict:
    """规则：出现未知人脸"""
    faces = ctx.get("faces", [])
    unknown = [f for f in faces if not f.get("known", True)]
    if unknown:
        count = len(unknown)
        return {"triggered": True, "reason": f"检测到 {count} 名未知人员"}
    return {"triggered": False, "reason": "所有人员均为已知"}


def _rule_off_hours_motion(ctx: dict) -> dict:
    """规则：非活动时段有移动目标"""
    is_active = ctx.get("is_active_hours", True)
    has_objects = ctx.get("has_objects", False)
    if not is_active and has_objects:
        return {"triggered": True, "reason": "非活动时段检测到移动目标"}
    return {"triggered": False, "reason": ""}


def _rule_prolonged_stay(ctx: dict) -> dict:
    """规则：同一区域人员滞留超过阈值"""
    stay_duration = ctx.get("stay_duration_sec", 0)
    threshold = ctx.get("max_stay_sec", 300)
    if stay_duration >= threshold:
        return {
            "triggered": True,
            "reason": f"人员滞留超过 {threshold} 秒（实际 {stay_duration:.0f} 秒）",
        }
    return {"triggered": False, "reason": ""}


# ── 评分器 ──

class Scorer:
    """异常评分器 — 综合规则结果计算归一化评分"""

    def __init__(self, threshold: float = 0.7):
        self.threshold = threshold

    def score(self, detection: DetectionResult, rule_results: list[dict]) -> AnomalyScore:
        """计算异常评分"""
        triggered = [r for r in rule_results if r.get("triggered")]
        if not triggered:
            return AnomalyScore(value=0.0, threshold=self.threshold, reason="一切正常")

        # 评分：触发规则数 / 总规则数
        total_rules = len(rule_results)
        triggered_count = len(triggered)
        score_value = min(triggered_count / max(total_rules, 1), 1.0)

        reasons = [r["reason"] for r in triggered if r.get("reason")]
        reason = "；".join(reasons)
        triggered_names = [r["name"] for r in triggered]

        return AnomalyScore(
            value=score_value,
            threshold=self.threshold,
            reason=reason or f"触发规则: {', '.join(triggered_names)}",
            triggered_rules=triggered_names,
        )


# ── 冷却机制 ──

class CoolingManager:
    """冷却管理器 — 按 (camera_id, rule_name) 防重复告警"""

    def __init__(self, cooldown_sec: float = 300):
        self._cooldown_sec = cooldown_sec
        self._last_triggered: dict[tuple[str, str], float] = {}

    def can_alert(self, camera_id: str, rule_name: str) -> bool:
        """检查是否允许触发告警"""
        key = (camera_id, rule_name)
        last_time = self._last_triggered.get(key, 0)
        return (time.time() - last_time) >= self._cooldown_sec

    def mark_alerted(self, camera_id: str, rule_name: str) -> None:
        """记录告警触发时间"""
        key = (camera_id, rule_name)
        self._last_triggered[key] = time.time()

    def reset(self, camera_id: str, rule_name: str) -> None:
        """重置冷却（用于测试）"""
        key = (camera_id, rule_name)
        self._last_triggered.pop(key, None)
