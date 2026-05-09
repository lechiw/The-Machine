"""
The Machine 主入口 — 组装所有模块，启动流水线

流水线：
  Camera.stream() → Detector.analyze() → RuleEngine + Scorer → Notifier.send()
"""
import asyncio
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from .api import MachineAPI
from .config import ConfigManager, WhitelistManager
from .detector.detector import Detector, ObjectDetector, FaceRecognizer, MotionDetector
from .analyzer.analyzer import (
    BaselineManager,
    RuleEngine,
    Scorer,
    CoolingManager,
    StayTracker,
    _rule_unknown_person,
    _rule_off_hours_motion,
    _rule_prolonged_stay,
)
from .models import NumberEvent
from .notifier.notifier import Notifier, QuietMode, EventStore, QQFormatter, _generate_event_id
from .sensor.camera import Camera
from .sensor.manager import CameraManager


class TheMachine:
    """The Machine 主系统 — 组装所有组件并编排流水线"""

    def __init__(self, config_path: str = "config.json"):
        # ── 配置 ──
        self._config = self._load_config(config_path)
        self._whitelist = WhitelistManager(self._config)

        # ── 传感器 ──
        self._camera_manager = CameraManager()
        self._init_cameras()

        # ── 检测器（含 OpenCV 模型） ──
        object_detector = ObjectDetector(
            confidence=self._config.get("detection.confidence", 0.5),
            target_classes=self._config.get("detection.target_classes", [0]),
        )
        face_recognizer = FaceRecognizer()
        motion_detector = MotionDetector()
        self._detector = Detector(object_detector, face_recognizer, motion_detector)

        # ── 分析器 ──
        self._baseline_manager = BaselineManager()
        self._rule_engine = RuleEngine()
        self._init_rules()
        self._scorer = Scorer(
            threshold=self._config.get("anomaly.score_threshold", 0.7)
        )
        self._cooling = CoolingManager(
            cooldown_sec=self._config.get("anomaly.cooldown_sec", 300)
        )
        self._stay_tracker = StayTracker(max_stay_sec=300)

        # ── 通知器 ──
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

        # API
        api_port = int(self._config.get("api.port", 18790))
        self._api = MachineAPI(self, port=api_port)

        # 运行状态
        self._running = False
        self._start_time: Optional[datetime] = None
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

    # ── 帧处理流水线 ──

    async def _camera_pipeline(self, camera: Camera) -> None:
        """单个摄像头的帧处理流水线"""
        try:
            async for frame in camera.stream():
                if not self._running:
                    break
                event = self.process_frame(frame)
                if event:
                    self._notifier.send(event)
                    print(f"  🚨 {event.event_type} @ {camera.name}", flush=True)
        except Exception as e:
            print(f"  ⚠️ 摄像头 {camera.name} 流水线异常: {e}", flush=True)

    async def _run_pipeline(self) -> None:
        """运行所有摄像头的帧处理流水线"""
        tasks = []
        for camera in self._camera_manager._cameras.values():
            tasks.append(asyncio.create_task(self._camera_pipeline(camera)))
        if tasks:
            await asyncio.gather(*tasks)

    # ── 核心流水线（单帧处理） ──

    def process_frame(self, frame) -> Optional[NumberEvent]:
        """
        处理单帧全链路：
        Frame → Detector.analyze() → RuleEngine → Scorer → Notifier
        返回 NumberEvent（触发告警时）或 None
        """
        # 1. 检测
        detection = self._detector.analyze(frame)

        # 2. 帧间跟踪
        stay_info = self._stay_tracker.update(frame.camera_id, detection.has_people)

        # 3. 构建规则上下文
        camera = self._get_camera(frame.camera_id)
        rule_context = {
            "faces": [
                {"known": f.known, "name": f.name}
                for f in detection.faces
            ],
            "is_active_hours": camera.is_active_hours() if camera else True,
            "has_objects": len(detection.objects) > 0,
            "stay_duration_sec": stay_info["current_duration_sec"],
            "max_stay_sec": stay_info["max_stay_sec"],
        }

        # 4. 规则评估
        rule_results = self._rule_engine.evaluate_all(rule_context)

        # 5. 评分
        score = self._scorer.score(detection, rule_results)

        # 6. 检查冷却 → 生成告警
        if score.is_alert and score.triggered_rules:
            primary_rule = score.triggered_rules[0]
            if not self._cooling.can_alert(frame.camera_id, primary_rule):
                return None

            self._cooling.mark_alerted(frame.camera_id, primary_rule)
            self._total_alerts += 1

            event = NumberEvent(
                id=_generate_event_id(),
                camera_id=frame.camera_id,
                timestamp=frame.timestamp,
                event_type=primary_rule,
                score=score.value,
                reason=score.reason,
            )
            # 推送到 API 待推送队列
            self._api.push_alert(event)
            return event

        return None

    def _get_camera(self, camera_id: str) -> Optional[Camera]:
        return self._camera_manager.get_camera(camera_id)

    # ── 生命周期 ──

    def start(self) -> None:
        """启动系统"""
        self._running = True
        self._start_time = datetime.now()
        print(f"🤖 The Machine 启动 | {self._camera_manager.count} 摄像头")

    async def start_async(self) -> None:
        """异步启动，含 API 服务器 + 帧流水线"""
        self.start()
        await self._api.start()
        # 启动帧处理流水线（不阻塞）
        self._pipeline_task = asyncio.create_task(self._run_pipeline())

    async def stop_async(self) -> None:
        """异步关闭"""
        if hasattr(self, '_pipeline_task'):
            self._pipeline_task.cancel()
        await self._api.stop()
        self.stop()

    def stop(self) -> None:
        """优雅关闭"""
        self._running = False
        self._camera_manager.stop_all()
        self._detector.shutdown()
        print("🤖 The Machine 已关闭")

    # ── Admin 命令 ──

    def handle_admin_command(self, command: str) -> str:
        """处理来自 QQ 的 Admin 命令"""
        cmd = command.strip()

        if cmd == "状态" or cmd == "status":
            s = self.status()
            return (
                f"📊 运行中 | {s['cameras_connected']}/{s['cameras']} 摄像头在线\n"
                f"处理帧: {s['total_frames']} | 告警: {s['total_alerts']}\n"
                f"推送: {s['notifications_sent']} | 压制: {s['notifications_suppressed']}\n"
                f"运行: {s['uptime_hours']:.1f}h"
            )

        if cmd.startswith("静音") or cmd.startswith("安静模式"):
            self._notifier._quiet_mode.set_quiet(True)
            return "🔇 已切换至安静模式，告警暂时不推送"

        if cmd.startswith("恢复") or cmd.startswith("取消静音"):
            self._notifier._quiet_mode.set_quiet(False)
            return "🔊 已恢复通知模式"

        if cmd.startswith("添加白名单"):
            # "添加白名单：张三"
            parts = cmd.replace("添加白名单", "").replace("：", ":").split(":")
            name = parts[-1].strip() if len(parts) > 1 else None
            if name:
                self._whitelist.add(name, f"{name}_face")
                return f"✅ {name} 已加入白名单（下次检测到人脸时会自动识别）"
            return "⚠️ 格式：添加白名单：名字"

        if cmd.startswith("删除白名单"):
            parts = cmd.replace("删除白名单", "").replace("：", ":").split(":")
            name = parts[-1].strip() if len(parts) > 1 else None
            if name:
                ok = self._whitelist.remove(name)
                return f"✅ {name} 已从白名单移除" if ok else f"⚠️ 白名单中未找到 {name}"
            return "⚠️ 格式：删除白名单：名字"

        if cmd == "白名单":
            wl = self._whitelist.list()
            if not wl:
                return "📋 白名单为空"
            names = "、".join(p["name"] for p in wl)
            return f"📋 白名单 ({len(wl)} 人): {names}"

        return f"❓ 未知命令: {cmd}\n支持: 状态 / 静音 / 恢复 / 白名单 / 添加白名单：名字 / 删除白名单：名字"

    # ── 状态 ──

    def status(self) -> dict:
        """系统状态摘要"""
        uptime = (datetime.now() - self._start_time).total_seconds() if self._start_time else 0
        return {
            "running": self._running,
            "uptime_seconds": round(uptime),
            "uptime_hours": round(uptime / 3600, 1),
            "cameras": self._camera_manager.count,
            "cameras_connected": sum(
                1 for c in self._camera_manager._cameras.values()
                if c.stats["connected"]
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
