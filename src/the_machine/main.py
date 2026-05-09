"""
The Machine 主入口 — 组装所有模块，启动流水线
"""
import asyncio
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Optional

from .config import ConfigManager, WhitelistManager
from .detector.detector import Detector, ObjectDetector, FaceRecognizer
from .analyzer.analyzer import (
    BaselineManager,
    RuleEngine,
    Scorer,
    CoolingManager,
    _rule_unknown_person,
    _rule_off_hours_motion,
    _rule_prolonged_stay,
)
from .models import Frame, DetectionResult, AnomalyScore, NumberEvent
from .notifier.notifier import Notifier, QuietMode, EventStore, QQFormatter, _generate_event_id
from .sensor.camera import Camera
from .sensor.manager import CameraManager


class TheMachine:
    """The Machine 主系统 — 组装所有组件并编排流水线"""

    def __init__(self, config_path: str = "config.json"):
        # 配置
        self._config = self._load_config(config_path)
        self._whitelist = WhitelistManager(self._config)

        # 传感器
        self._camera_manager = CameraManager()
        self._init_cameras()

        # 检测器
        object_detector = ObjectDetector(
            model_path=self._config.get("detection.model", "default"),
            confidence=self._config.get("detection.confidence", 0.5),
        )
        face_recognizer = FaceRecognizer()
        self._detector = Detector(object_detector, face_recognizer)

        # 分析器
        self._baseline_manager = BaselineManager()
        self._rule_engine = RuleEngine()
        self._init_rules()
        self._scorer = Scorer(
            threshold=self._config.get("anomaly.score_threshold", 0.7)
        )
        self._cooling = CoolingManager(
            cooldown_sec=self._config.get("anomaly.cooldown_sec", 300)
        )

        # 通知器
        quiet_mode = QuietMode(
            dnd_start=self._config.get("notifier.dnd_start", "23:00"),
            dnd_end=self._config.get("notifier.dnd_end", "07:00"),
        )
        event_store = EventStore(
            db_path=self._config.get("storage.db_path", "data/events.db"),
        )
        self._notifier = Notifier(
            formatter=QQFormatter(),
            quiet_mode=quiet_mode,
            event_store=event_store,
        )

        # 运行状态
        self._running = False
        self._start_time: Optional[datetime] = None
        self._total_frames = 0
        self._total_alerts = 0

    # ── 初始化 ──

    @staticmethod
    def _load_config(path: str) -> ConfigManager:
        return ConfigManager.load(path)

    def _init_cameras(self) -> None:
        for cam_config in self._config.get("cameras", []):
            camera = Camera(
                camera_id=cam_config["id"],
                name=cam_config.get("name", cam_config["id"]),
                rtsp_url=cam_config["rtsp"],
                interval_sec=cam_config.get("interval_sec", 2.0),
                active_hours=cam_config.get("active_hours"),
            )
            self._camera_manager.add_camera(camera)

    def _init_rules(self) -> None:
        self._rule_engine.register("unknown_person", _rule_unknown_person)
        self._rule_engine.register("off_hours_motion", _rule_off_hours_motion)
        self._rule_engine.register("prolonged_stay", _rule_prolonged_stay)

    # ── 流水线 ──

    def _process_frame(self, frame: Frame) -> Optional[NumberEvent]:
        """处理单帧全链路：检测 → 分析 → 评分 → 告警"""
        # 1. 检测
        detection = self._detector.analyze(frame)

        # 2. 构建规则上下文
        rule_context = {
            "faces": [
                {"known": f.known, "name": f.name}
                for f in detection.faces
            ],
            "is_active_hours": self._get_camera(frame.camera_id).is_active_hours()
            if self._get_camera(frame.camera_id) else True,
            "has_objects": len(detection.objects) > 0,
            "stay_duration_sec": 0,  # TODO: 跨帧跟踪
        }

        # 3. 规则评估
        rule_results = self._rule_engine.evaluate_all(rule_context)

        # 4. 评分
        score = self._scorer.score(detection, rule_results)

        # 5. 检查冷却
        triggered_rules = score.triggered_rules
        if triggered_rules:
            # 只取第一个触发的规则用于冷却判定
            primary_rule = triggered_rules[0]
            camera = self._get_camera(frame.camera_id)
            if not self._cooling.can_alert(frame.camera_id, primary_rule):
                return None

            # 6. 生成告警
            self._cooling.mark_alerted(frame.camera_id, primary_rule)
            self._total_alerts += 1

            return NumberEvent(
                id=_generate_event_id(),
                camera_id=frame.camera_id,
                timestamp=frame.timestamp,
                event_type=primary_rule,
                score=score.value,
                reason=score.reason,
                evidence_path=None,  # 可保存截图
            )

        return None

    def _get_camera(self, camera_id: str) -> Optional[Camera]:
        return self._camera_manager.get_camera(camera_id)

    # ── 生命周期 ──

    def start(self) -> None:
        """启动系统"""
        self._running = True
        self._start_time = datetime.now()
        print(f"🤖 The Machine 启动 | {len(self._camera_manager._cameras)} 摄像头")

    def stop(self) -> None:
        """优雅关闭"""
        self._running = False
        self._camera_manager.stop_all()
        self._detector.shutdown()
        print("🤖 The Machine 已关闭")

    def status(self) -> dict:
        """系统状态"""
        uptime = (datetime.now() - self._start_time).total_seconds() if self._start_time else 0
        return {
            "running": self._running,
            "uptime_seconds": round(uptime),
            "cameras": self._camera_manager.count,
            "cameras_connected": sum(
                1 for c in self._camera_manager._cameras.values()
                if c._cap and c._cap.isOpened()
            ),
            "total_frames": self._detector.stats["frames_analyzed"],
            "total_alerts": self._total_alerts,
            "notifications_sent": self._notifier.stats["sent"],
            "notifications_suppressed": self._notifier.stats["suppressed"],
        }

    def is_alive(self) -> bool:
        return self._running

    def __repr__(self) -> str:
        s = self.status()
        return (
            f"<TheMachine running={s['running']} "
            f"cameras={s['cameras']} "
            f"alerts={s['total_alerts']}>"
        )
