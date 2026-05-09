"""检测模块 — 目标检测 + 人脸识别"""
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Any

# Lazy import
np = None


def _lazy_imports():
    global np
    if np is None:
        import numpy as _np
        np = _np

from ..models import Frame, DetectionResult, DetectedObject, FaceResult


class ObjectDetector:
    """目标检测器 — ONNX Runtime 推理"""

    # COCO 数据集中我们关注的前几个类别
    COCO_LABELS = {
        0: "person",
        1: "bicycle",
        2: "car",
        3: "motorcycle",
        5: "bus",
        7: "truck",
        16: "dog",
        17: "horse",
    }

    def __init__(self, model_path: str = "default", confidence: float = 0.5):
        self.confidence = confidence
        self._model_path = model_path
        self._session = None

        if model_path != "default" and model_path != "default":
            self._load_model(model_path)

    def _load_model(self, path: str) -> None:
        """加载 ONNX 模型"""
        try:
            import onnxruntime as ort
            self._session = ort.InferenceSession(path)
        except ImportError:
            pass  # onnxruntime 未安装，降级为 dummy detector

    def detect(self, frame: Frame) -> list[DetectedObject]:
        """对帧进行目标检测，返回检测结果列表"""
        if self._session is not None:
            return self._inference(frame)
        # ONNX 未加载时返回空
        return []

    def _inference(self, frame: Frame) -> list[DetectedObject]:
        """ONNX 推理（待集成具体模型时实现）"""
        results = []
        # Placeholder: 模型集成后在此实现
        return results

    @classmethod
    def class_id_to_label(cls, class_id: int) -> str:
        """将类别 ID 映射为标签名"""
        return cls.COCO_LABELS.get(class_id, f"class_{class_id}")


class FaceRecognizer:
    """人脸识别器 — 特征比对白名单"""

    def __init__(self, similarity_threshold: float = 0.6):
        self.similarity_threshold = similarity_threshold
        self._whitelist_embeddings: dict[str, Any] = {}

    def register_face(self, name: str, embedding: Any) -> None:
        """注册已知人脸特征"""
        self._whitelist_embeddings[name] = embedding

    def recognize(self, frame: Frame) -> Optional[FaceResult]:
        """识别帧中的人脸（无检测模型时返回 None）"""
        return None  # 待模型集成

    def clear(self) -> None:
        """清空所有注册的人脸"""
        self._whitelist_embeddings.clear()


class Detector:
    """检测器编排 — 组合目标检测 + 人脸识别"""

    def __init__(
        self,
        object_detector: Optional[ObjectDetector] = None,
        face_recognizer: Optional[FaceRecognizer] = None,
        max_workers: int = 2,
    ):
        self._object_detector = object_detector or ObjectDetector()
        self._face_recognizer = face_recognizer or FaceRecognizer()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._frame_count = 0

    def analyze(self, frame: Frame) -> DetectionResult:
        """对单帧执行完整检测分析"""
        self._frame_count += 1

        objects = self._object_detector.detect(frame)
        face_result = self._face_recognizer.recognize(frame)

        faces = [face_result] if face_result else []

        return DetectionResult(
            frame=frame,
            objects=objects,
            faces=faces,
        )

    @property
    def stats(self) -> dict:
        return {
            "frames_analyzed": self._frame_count,
        }

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)
