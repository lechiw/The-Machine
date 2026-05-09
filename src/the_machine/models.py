"""
数据模型 — 整个流水线中流通的核心数据结构
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ── 感知层 ──

@dataclass
class Frame:
    """摄像头帧 — 流水线的原始输入"""
    camera_id: str
    timestamp: datetime
    jpeg_bytes: bytes
    width: int = 0
    height: int = 0
    fps: float = 0.0

    @property
    def size_kb(self) -> float:
        return len(self.jpeg_bytes) / 1024


# ── 检测层 ──

@dataclass
class DetectedObject:
    """检测到的目标"""
    class_id: int
    label: str
    confidence: float
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 (归一化 0~1)


@dataclass
class FaceResult:
    """人脸识别结果"""
    known: bool
    name: str = "unknown"
    confidence: float = 0.0
    bbox: Optional[tuple[float, float, float, float]] = None


@dataclass
class DetectionResult:
    """单帧的完整检测结果"""
    frame: Frame
    objects: list[DetectedObject] = field(default_factory=list)
    faces: list[FaceResult] = field(default_factory=list)
    motion_score: float = 0.0

    @property
    def has_people(self) -> bool:
        return any(obj.label == "person" for obj in self.objects)

    @property
    def unknown_faces(self) -> list[FaceResult]:
        return [f for f in self.faces if not f.known]

    @property
    def known_faces(self) -> list[FaceResult]:
        return [f for f in self.faces if f.known]


# ── 分析层 ──

@dataclass
class AnomalyScore:
    """异常评分结果"""
    value: float
    threshold: float
    reason: str = ""
    triggered_rules: list[str] = field(default_factory=list)

    @property
    def is_alert(self) -> bool:
        return self.value >= self.threshold


@dataclass
class Baseline:
    """时间段基线"""
    time_slot: str
    avg_objects: float = 0.0
    std_objects: float = 0.0
    samples: int = 0


# ── 通知层 ──

@dataclass
class NumberEvent:
    """告警事件 — 类比 The Machine 输出的 'Number'"""
    id: str
    camera_id: str
    timestamp: datetime
    event_type: str  # unknown_person | off_hours_motion | prolonged_stay
    score: float
    reason: str
    evidence_path: Optional[str] = None
    acknowledged: bool = False
