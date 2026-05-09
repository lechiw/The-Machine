"""检测模块 — 目标检测 + 人脸识别（OpenCV 实现，惰性加载）

所有 OpenCV/numpy 依赖在首次使用时惰性导入，
确保模块可以在没有安装这些库的环境中被导入。
"""
import os
import pickle
import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

from ..models import Frame, DetectionResult, DetectedObject, FaceResult

# ── 惰性导入 ──

_cv2: Any = None
_np: Any = None


def _ensure_cv2():
    global _cv2, _np
    if _cv2 is None:
        import cv2 as __cv2
        import numpy as __np
        _cv2 = __cv2
        _np = __np


def _cascade_path() -> str:
    _ensure_cv2()
    return _cv2.data.haarcascades + "haarcascade_frontalface_default.xml"


# ── ObjectDetector ──

class ObjectDetector:
    """目标检测器 — OpenCV DNN + MobileNet SSD"""

    COCO_LABELS = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle",
                   5: "bus", 7: "truck", 16: "dog"}

    _MOBILENET_LABELS = [
        "background", "aeroplane", "bicycle", "bird", "boat",
        "bottle", "bus", "car", "cat", "chair",
        "cow", "diningtable", "dog", "horse", "motorbike",
        "person", "pottedplant", "sheep", "sofa", "train", "tvmonitor",
    ]

    def __init__(self, confidence: float = 0.5, target_classes: Optional[list[int]] = None):
        self.confidence = confidence
        self.target_classes = target_classes or [0]
        self._net = None
        self._model_loaded = False
        self._load_default_model()

    def _load_default_model(self) -> None:
        try:
            model_dir = Path(__file__).parent / "models"
            model_dir.mkdir(exist_ok=True)
            prototxt = str(model_dir / "MobileNetSSD_deploy.prototxt")
            model_file = str(model_dir / "MobileNetSSD_deploy.caffemodel")
            if Path(prototxt).exists() and Path(model_file).exists():
                _ensure_cv2()
                self._net = _cv2.dnn.readNetFromCaffe(prototxt, model_file)
                self._model_loaded = True
        except Exception:
            self._net = None

    def detect(self, frame: Frame) -> list[DetectedObject]:
        """对帧进行目标检测"""
        results = []
        if self._net is not None:
            results = self._dnn_inference(frame)
        else:
            results = self._haar_fallback(frame)
        return [obj for obj in results if obj.confidence >= self.confidence]

    def _dnn_inference(self, frame: Frame) -> list[DetectedObject]:
        """MobileNet SSD 推理"""
        results = []
        try:
            _ensure_cv2()
            img_array = _np.frombuffer(frame.jpeg_bytes, dtype=_np.uint8)
            img = _cv2.imdecode(img_array, _cv2.IMREAD_COLOR)
            if img is None:
                return results
            h, w = img.shape[:2]
            blob = _cv2.dnn.blobFromImage(img, 0.007843, (300, 300), 127.5)
            self._net.setInput(blob)
            detections = self._net.forward()
            for i in range(detections.shape[2]):
                conf = detections[0, 0, i, 2]
                if conf < self.confidence:
                    continue
                class_id = int(detections[0, 0, i, 1])
                if class_id >= len(self._MOBILENET_LABELS):
                    continue
                label = self._MOBILENET_LABELS[class_id]
                if class_id not in self.target_classes and label not in ["person", "car", "dog"]:
                    continue
                box = detections[0, 0, i, 3:7] * _np.array([w, h, w, h])
                x1, y1, x2, y2 = box.astype(int)
                results.append(DetectedObject(
                    class_id=class_id, label=label, confidence=float(conf),
                    bbox=(x1 / w, y1 / h, x2 / w, y2 / h),
                ))
        except Exception:
            pass
        return results

    def _haar_fallback(self, frame: Frame) -> list[DetectedObject]:
        """无 DNN 时的回退：Haar Cascade 人脸检测"""
        results = []
        try:
            _ensure_cv2()
            img_array = _np.frombuffer(frame.jpeg_bytes, dtype=_np.uint8)
            img = _cv2.imdecode(img_array, _cv2.IMREAD_GRAYSCALE)
            if img is None:
                return results
            face_cascade = _cv2.CascadeClassifier(_cascade_path())
            faces = face_cascade.detectMultiScale(img, 1.1, 4)
            h, w = img.shape[:2]
            for (x, y, fw, fh) in faces:
                results.append(DetectedObject(
                    class_id=0, label="person", confidence=0.6,
                    bbox=(x / w, y / h, (x + fw) / w, (y + fh) / h),
                ))
        except Exception:
            pass
        return results

    @classmethod
    def class_id_to_label(cls, class_id: int) -> str:
        return cls.COCO_LABELS.get(class_id, f"class_{class_id}")


# ── FaceRecognizer ──

class FaceRecognizer:
    """人脸识别器 — Haar Cascade 检测 + 白名单比对"""

    def __init__(self, similarity_threshold: float = 0.6):
        self.similarity_threshold = similarity_threshold
        self._whitelist_features: dict[str, Any] = {}
        self._cascade: Any = None

    def _get_cascade(self):
        if self._cascade is None:
            _ensure_cv2()
            self._cascade = _cv2.CascadeClassifier(_cascade_path())
        return self._cascade

    def register_face(self, name: str, feature: Any) -> None:
        self._whitelist_features[name] = feature

    def register_from_frame(self, name: str, frame: Frame) -> bool:
        faces = self._detect_faces(frame)
        if not faces:
            return False
        largest = max(faces, key=lambda f: (f[2] * f[3]))
        feature = self._extract_feature(frame, largest)
        if feature is not None:
            self.register_face(name, feature)
            return True
        return False

    def recognize(self, frame: Frame) -> Optional[FaceResult]:
        faces = self._detect_faces(frame)
        if not faces:
            return None

        results = []
        for face_rect in faces:
            feature = self._extract_feature(frame, face_rect)
            if feature is None:
                continue
            best_match = ("unknown", 0.0)
            for name, known_feat in self._whitelist_features.items():
                sim = self._cosine_similarity(feature, known_feat)
                if sim > best_match[1]:
                    best_match = (name, sim)
            is_known = best_match[1] >= self.similarity_threshold
            results.append(FaceResult(
                known=is_known,
                name=best_match[0] if is_known else "unknown",
                confidence=best_match[1],
            ))

        if not results:
            return None
        return max(results, key=lambda r: r.confidence)

    def _detect_faces(self, frame: Frame) -> list[tuple[int, int, int, int]]:
        try:
            _ensure_cv2()
            img_array = _np.frombuffer(frame.jpeg_bytes, dtype=_np.uint8)
            gray = _cv2.imdecode(img_array, _cv2.IMREAD_GRAYSCALE)
            if gray is None:
                return []
            return self._get_cascade().detectMultiScale(gray, 1.1, 4)
        except Exception:
            return []

    def _extract_feature(self, frame: Frame, face_rect: tuple) -> Optional[Any]:
        try:
            x, y, w, h = face_rect
            _ensure_cv2()
            img_array = _np.frombuffer(frame.jpeg_bytes, dtype=_np.uint8)
            img = _cv2.imdecode(img_array, _cv2.IMREAD_GRAYSCALE)
            if img is None:
                return None
            face_img = img[y:y + h, x:x + w]
            if face_img.size == 0:
                return None
            face_resized = _cv2.resize(face_img, (64, 64)).flatten().astype(_np.float32)
            face_resized = (face_resized - face_resized.mean()) / (face_resized.std() + 1e-8)
            return face_resized
        except Exception:
            return None

    @staticmethod
    def _cosine_similarity(a, b):
        _ensure_cv2()
        dot = _np.dot(a, b)
        norm = _np.linalg.norm(a) * _np.linalg.norm(b)
        return float(dot / (norm + 1e-8))

    def clear(self) -> None:
        self._whitelist_features.clear()

    @property
    def known_count(self) -> int:
        return len(self._whitelist_features)


# ── MotionDetector ──

class MotionDetector:
    """运动检测器 — 帧间差分"""

    def __init__(self, threshold: float = 0.05):
        self.threshold = threshold
        self._prev_gray: Any = None

    def detect(self, frame: Frame) -> float:
        try:
            _ensure_cv2()
            img_array = _np.frombuffer(frame.jpeg_bytes, dtype=_np.uint8)
            gray = _cv2.imdecode(img_array, _cv2.IMREAD_GRAYSCALE)
            if gray is None:
                return 0.0
            gray = _cv2.GaussianBlur(gray, (21, 21), 0)
            if self._prev_gray is None:
                self._prev_gray = gray
                return 0.0
            diff = _cv2.absdiff(self._prev_gray, gray)
            _, thresh = _cv2.threshold(diff, 25, 255, _cv2.THRESH_BINARY)
            score = float(_cv2.countNonZero(thresh)) / float(gray.size)
            self._prev_gray = gray
            return score
        except Exception:
            return 0.0

    def reset(self) -> None:
        self._prev_gray = None


# ── Detector 编排 ──

class Detector:
    """检测器编排 — 组合目标检测 + 人脸识别 + 运动检测"""

    def __init__(
        self,
        object_detector: Optional[ObjectDetector] = None,
        face_recognizer: Optional[FaceRecognizer] = None,
        motion_detector: Optional[MotionDetector] = None,
    ):
        self._object_detector = object_detector or ObjectDetector()
        self._face_recognizer = face_recognizer or FaceRecognizer()
        self._motion_detector = motion_detector or MotionDetector()
        self._executor = ThreadPoolExecutor(max_workers=2)
        self._frame_count = 0

    def analyze(self, frame: Frame) -> DetectionResult:
        """对单帧执行完整检测分析"""
        self._frame_count += 1
        objects_future = self._executor.submit(self._object_detector.detect, frame)
        face_future = self._executor.submit(self._face_recognizer.recognize, frame)
        motion_future = self._executor.submit(self._motion_detector.detect, frame)
        objects = objects_future.result()
        face_result = face_future.result()
        motion_score = motion_future.result()
        faces = [face_result] if face_result else []
        return DetectionResult(frame=frame, objects=objects, faces=faces, motion_score=motion_score)

    @property
    def stats(self) -> dict:
        return {"frames_analyzed": self._frame_count}

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)
