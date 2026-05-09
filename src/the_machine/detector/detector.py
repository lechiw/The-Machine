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
        # 确保 OpenCV 已加载（供 HOG 检测使用）
        _ensure_cv2()
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
        """对帧进行目标检测 — 同时运行 DNN + HOG 行人检测"""
        results = []
        
        # HOG 行人检测（始终运行）
        results.extend(self._detect_people(frame))
        
        # DNN 推理（如果模型加载成功）
        if self._net is not None:
            results.extend(self._dnn_inference(frame))
        
        # 过滤 + 去重（按置信度保留最优的）
        seen = set()
        filtered = []
        for obj in sorted(results, key=lambda o: o.confidence, reverse=True):
            key = (obj.label, tuple(round(b, 1) for b in obj.bbox))
            if key not in seen:
                seen.add(key)
                if obj.confidence >= self.confidence:
                    filtered.append(obj)
        return filtered

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

    def _detect_people(self, frame: Frame) -> list[DetectedObject]:
        """HOG 行人检测 — 检测画面中的人（无论是否在移动）"""
        results = []
        try:
            _ensure_cv2()
            img_array = _np.frombuffer(frame.jpeg_bytes, dtype=_np.uint8)
            img = _cv2.imdecode(img_array, _cv2.IMREAD_COLOR)
            if img is None:
                return results
            h, w = img.shape[:2]
            hog = _cv2.HOGDescriptor()
            hog.setSVMDetector(_cv2.HOGDescriptor_getDefaultPeopleDetector())
            rects, weights = hog.detectMultiScale(img, winStride=(8, 8), padding=(4, 4), scale=1.05)
            for (x, y, fw, fh), weight in zip(rects, weights):
                results.append(DetectedObject(
                    class_id=0, label="person",
                    confidence=min(float(weight), 1.0),
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
    """人脸识别器 — Haar Cascade 检测 + LBPH 人脸识别 (OpenCV contrib)"""

    FACE_SIZE = (100, 100)  # LBPH 训练用统一尺寸

    FEATURES_PATH = None  # 外部可设置特征文件路径

    def __init__(self, confidence_threshold: float = 0.5):
        self.confidence_threshold = confidence_threshold  # 余弦相似度阈值
        self._cascade: Any = None
        # 手动特征库（从 pickle 加载）
        self._known_features: dict[str, Any] = {}  # name -> feature_vector
        self._load_known_features()

    def _load_known_features(self):
        """从 pickle 文件加载预训练的人脸特征"""
        import pickle
        import os
        path = FaceRecognizer.FEATURES_PATH or os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "data", "known_faces.pkl"
        )
        if os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    features = pickle.load(f)
                    if isinstance(features, dict):
                        self._known_features = features
            except Exception:
                pass

    def _get_cascade(self):
        if self._cascade is None:
            _ensure_cv2()
            self._cascade = _cv2.CascadeClassifier(_cascade_path())
        return self._cascade

    def _detect_one_face(self, gray: Any) -> Optional[tuple[int, int, int, int]]:
        """检测帧中最 prominent 的人脸"""
        faces = self._get_cascade().detectMultiScale(gray, 1.1, 4, minSize=(50, 50))
        if faces is None or len(faces) == 0:
            return None
        # 取最大的脸
        largest = max(faces, key=lambda f: f[2] * f[3])
        return tuple(largest)

    def _extract_face(self, gray: Any, rect: tuple) -> Optional[Any]:
        """提取并归一化人脸区域"""
        x, y, w, h = rect
        if w < 20 or h < 20:
            return None
        face = gray[y:y + h, x:x + w]
        if face.size == 0:
            return None
        return _cv2.resize(face, self.FACE_SIZE)

    def _extract_feature(self, gray_face: Any) -> Any:
        """从归一化的人脸图像提取特征向量（64x64 归一化缩略图）"""
        try:
            resized = _cv2.resize(gray_face, (64, 64)).flatten().astype(_np.float32)
            return (resized - resized.mean()) / (resized.std() + 1e-8)
        except Exception:
            return None

    @staticmethod
    def _cosine_similarity(a: Any, b: Any) -> float:
        """余弦相似度"""
        dot = _np.dot(a, b)
        norm = _np.linalg.norm(a) * _np.linalg.norm(b)
        return float(dot / (norm + 1e-8))

    def register_from_frame(self, name: str, frame: Frame) -> bool:
        """从帧中检测人脸并注册"""
        _ensure_cv2()
        img_array = _np.frombuffer(frame.jpeg_bytes, dtype=_np.uint8)
        gray = _cv2.imdecode(img_array, _cv2.IMREAD_GRAYSCALE)
        if gray is None:
            return False
        rect = self._detect_one_face(gray)
        if rect is None:
            return False
        face = self._extract_face(gray, rect)
        if face is None:
            return False
        feature = self._extract_feature(face)
        if feature is None:
            return False
        self._known_features[name] = feature
        self._save_features()
        return True

    def register_from_image(self, name: str, image_path: str) -> bool:
        """从图片文件注册人脸"""
        _ensure_cv2()
        gray = _cv2.imread(image_path, _cv2.IMREAD_GRAYSCALE)
        if gray is None:
            return False
        rect = self._detect_one_face(gray)
        if rect is None:
            return False
        face = self._extract_face(gray, rect)
        if face is None:
            return False
        feature = self._extract_feature(face)
        if feature is None:
            return False
        self._known_features[name] = feature
        self._save_features()
        return True

    def _save_features(self):
        """保存特征到文件"""
        import pickle
        import os
        path = FaceRecognizer.FEATURES_PATH or os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "data", "known_faces.pkl"
        )
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "wb") as f:
                pickle.dump(self._known_features, f)
        except Exception:
            pass
        self._label_map[label] = name

        self._faces.append(face)
        self._labels.append(label)
        self._trained = False
        return True

    def recognize(self, frame: Frame) -> Optional[FaceResult]:
        """识别帧中的人脸 — 与已注册特征比对"""
        _ensure_cv2()
        img_array = _np.frombuffer(frame.jpeg_bytes, dtype=_np.uint8)
        gray = _cv2.imdecode(img_array, _cv2.IMREAD_GRAYSCALE)
        if gray is None:
            return None

        rect = self._detect_one_face(gray)
        if rect is None:
            return None

        face = self._extract_face(gray, rect)
        if face is None:
            return None

        feature = self._extract_feature(face)
        if feature is None:
            return FaceResult(known=False, name="unknown", confidence=0.0)

        if not self._known_features:
            return FaceResult(known=False, name="unknown", confidence=0.0)

        # 与所有已注册特征比对
        best_name = "unknown"
        best_sim = 0.0
        for name, known_feat in self._known_features.items():
            sim = self._cosine_similarity(feature, known_feat)
            if sim > best_sim:
                best_sim = sim
                best_name = name

        is_known = best_sim >= self.confidence_threshold
        return FaceResult(
            known=is_known,
            name=best_name if is_known else "unknown",
            confidence=best_sim,
        )

    def clear(self) -> None:
        """清空所有已注册人脸"""
        self._known_features.clear()

    @property
    def known_count(self) -> int:
        return len(self._known_features)


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
            gray = _cv2.GaussianBlur(gray, (15, 15), 0)
            if self._prev_gray is None:
                self._prev_gray = gray
                return 0.0
            diff = _cv2.absdiff(self._prev_gray, gray)
            _, thresh = _cv2.threshold(diff, 10, 255, _cv2.THRESH_BINARY)
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
