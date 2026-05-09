"""
Spec: 检测模块 — YOLO 目标检测 + 人脸识别规约

验收标准：
- Detector 能从 Frame 中检测出指定类别目标
- Detector 输出包含类别、置信度、Bounding Box
- FaceRecognizer 能区分已知/未知人脸
- 性能：CPU 单帧单模型处理 < 2s
"""

import pytest
import numpy as np


class TestObjectDetectorSpec:
    """目标检测器规约"""

    DETECTION_CLASSES = {0: 'person', 2: 'car', 16: 'dog', 24: 'backpack'}

    def test_detector_returns_detections(self, mock_detector, mock_frame_with_person):
        """检测器必须返回 DetectedObject 列表"""
        results = mock_detector.detect(mock_frame_with_person)
        assert isinstance(results, list), "检测结果必须是 list"
        assert len(results) > 0, "画面中有目标时应返回至少一个检测结果"

    def test_detection_has_required_fields(self, mock_detector, mock_frame_with_person):
        """每个检测结果必须包含类别、置信度、Bounding Box"""
        obj = mock_detector.detect(mock_frame_with_person)[0]
        assert hasattr(obj, 'class_id'), "缺少 class_id"
        assert hasattr(obj, 'label'), "缺少 label"
        assert hasattr(obj, 'confidence'), "缺少 confidence"
        assert hasattr(obj, 'bbox'), "缺少 bbox"
        assert len(obj.bbox) == 4, "bbox 必须是 [x1, y1, x2, y2] 四元组"
        assert 0 <= obj.confidence <= 1, "confidence 必须在 [0, 1] 范围内"

    def test_detection_class_mapping(self, mock_detector):
        """class_id 应正确映射到标签名"""
        for class_id, expected_label in self.DETECTION_CLASSES.items():
            label = mock_detector.class_id_to_label(class_id)
            assert label == expected_label, \
                f"class_id {class_id} 应映射为 '{expected_label}'，实际为 '{label}'"

    def test_detector_empty_frame(self, mock_detector, mock_empty_frame):
        """无目标的画面应返回空列表"""
        results = mock_detector.detect(mock_empty_frame)
        assert results == [], "无目标画面应返回空列表"

    def test_detector_performance(self, mock_detector, mock_frame_with_person):
        """CPU 模式下单帧检测耗时 < 2s"""
        import time
        start = time.time()
        mock_detector.detect(mock_frame_with_person)
        elapsed = time.time() - start
        assert elapsed < 2.0, f"单帧检测耗时 {elapsed:.2f}s 超过 2s 限制"


class TestFaceRecognizerSpec:
    """人脸识别器规约"""

    def test_recognize_known_face(self, mock_recognizer, mock_known_face_frame):
        """已知人脸应返回对应身份"""
        result = mock_recognizer.recognize(mock_known_face_frame)
        assert result['known'] is True
        assert result['name'] is not None, "已知人脸应返回姓名"

    def test_recognize_unknown_face(self, mock_recognizer, mock_unknown_face_frame):
        """未注册人脸应标记为 unknown"""
        result = mock_recognizer.recognize(mock_unknown_face_frame)
        assert result['known'] is False
        assert result['name'] == 'unknown', "未知人脸应标记为 'unknown'"

    def test_face_confidence_threshold(self, mock_recognizer):
        """置信度低于阈值时应视为 unknown"""
        low_conf = mock_recognizer.recognize_with_simulated_confidence(0.3)
        assert low_conf['known'] is False, "低置信度应标记为 unknown"
        high_conf = mock_recognizer.recognize_with_simulated_confidence(0.8)
        assert high_conf['known'] is True, "高置信度应标记为 known"

    def test_no_face_in_frame(self, mock_recognizer, mock_no_face_frame):
        """无脸画面不应报错"""
        result = mock_recognizer.recognize(mock_no_face_frame)
        assert result is None or result.get('faces', 0) == 0
