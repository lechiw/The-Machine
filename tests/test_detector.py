"""测试：检测模块 — ObjectDetector / FaceRecognizer / MotionDetector / Detector"""
from datetime import datetime

from the_machine.models import Frame, DetectionResult
from the_machine.detector.detector import ObjectDetector, FaceRecognizer, MotionDetector, Detector


def _make_frame(data: bytes = b"fake_jpeg") -> Frame:
    return Frame("test", datetime.now(), data, 320, 240, 30.0)


class TestObjectDetector:
    def test_detect_returns_list(self):
        od = ObjectDetector(confidence=0.5)
        results = od.detect(_make_frame())
        assert isinstance(results, list)

    def test_class_id_mapping(self):
        assert ObjectDetector.class_id_to_label(0) == "person"
        assert ObjectDetector.class_id_to_label(999) == "class_999"


class TestFaceRecognizer:
    def test_no_face_returns_none(self):
        fr = FaceRecognizer()
        assert fr.recognize(_make_frame()) is None

    def test_register_and_clear(self):
        fr = FaceRecognizer()
        assert fr.known_count == 0
        fr.register_face("test", [0.0] * 64)
        assert fr.known_count == 1
        fr.clear()
        assert fr.known_count == 0


class TestMotionDetector:
    def test_first_frame_zero(self):
        md = MotionDetector()
        assert md.detect(_make_frame()) == 0.0

    def test_identical_frames_zero(self):
        md = MotionDetector()
        f = _make_frame()
        md.detect(f)
        assert md.detect(f) == 0.0

    def test_reset(self):
        md = MotionDetector()
        md.detect(_make_frame())
        md.reset()
        assert md.detect(_make_frame()) == 0.0


class TestDetector:
    def test_analyze_returns_detection_result(self):
        det = Detector()
        frame = _make_frame()
        result = det.analyze(frame)
        assert isinstance(result, DetectionResult)
        assert result.frame is frame
        assert isinstance(result.objects, list)
        assert isinstance(result.faces, list)
        assert result.motion_score >= 0

    def test_stats(self):
        det = Detector()
        det.analyze(_make_frame())
        det.analyze(_make_frame())
        assert det.stats["frames_analyzed"] == 2
