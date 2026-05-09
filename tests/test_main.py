"""测试：摄像头模块 + 主入口"""
from datetime import datetime, time

from the_machine.models import Frame
from the_machine.sensor.camera import Camera
from the_machine.sensor.manager import CameraManager
from the_machine.exceptions import CameraConnectionError
from the_machine.main import TheMachine

# ── Camera ──

class TestCamera:
    def test_invalid_protocol_raises(self):
        try:
            Camera("b", "b", "ftp://invalid")
            assert False, "应报错"
        except CameraConnectionError:
            pass

    def test_valid_camera(self):
        cam = Camera("test", "测试", "rtsp://192.168.1.100:554/stream1",
                     active_hours={"start": "07:00", "end": "23:00"})
        assert cam.id == "test"
        assert cam.name == "测试"

    def test_active_hours(self):
        cam = Camera("test", "测试", "rtsp://x",
                     active_hours={"start": "07:00", "end": "23:00"})
        assert cam.is_active_hours(time(10, 0)) is True
        assert cam.is_active_hours(time(2, 0)) is False

    def test_active_hours_cross_midnight(self):
        cam = Camera("test", "测试", "rtsp://x",
                     active_hours={"start": "23:00", "end": "07:00"})
        assert cam.is_active_hours(time(1, 0)) is True
        assert cam.is_active_hours(time(10, 0)) is False

    def test_stats(self):
        cam = Camera("test", "测试", "rtsp://x")
        s = cam.stats
        assert s["connected"] is False
        assert s["frames_captured"] == 0


class TestCameraManager:
    def test_add_get_remove(self):
        mgr = CameraManager()
        cam = Camera("cam1", "A", "rtsp://x")
        assert mgr.add_camera(cam) is True
        assert mgr.get_camera("cam1") is cam
        assert mgr.count == 1
        assert mgr.add_camera(Camera("cam1", "B", "rtsp://x")) is False  # 重复
        assert mgr.remove_camera("cam1") is True
        assert mgr.count == 0
        assert mgr.remove_camera("none") is False
        assert mgr.get_camera("none") is None

    def test_status(self):
        mgr = CameraManager()
        mgr.add_camera(Camera("a", "A", "rtsp://x"))
        mgr.add_camera(Camera("b", "B", "rtsp://x"))
        assert len(mgr.get_status()) == 2


class TestTheMachine:
    def test_init_start_stop(self):
        m = TheMachine("/nonexistent/config.json")
        assert m.is_alive() is False
        m.start()
        assert m.is_alive() is True
        m.stop()
        assert m.is_alive() is False

    def test_status(self):
        m = TheMachine("/nonexistent/config.json")
        m.start()
        s = m.status()
        assert s["running"] is True
        assert s["cameras"] == 0
        m.stop()

    def test_admin_commands(self):
        m = TheMachine("/nonexistent/config.json")
        m.start()
        assert "运行中" in m.handle_admin_command("状态")
        assert "安静" in m.handle_admin_command("静音")
        assert "恢复" in m.handle_admin_command("恢复")
        assert "张三" in m.handle_admin_command("添加白名单：张三")
        assert "张三" in m.handle_admin_command("白名单")
        assert "移除" in m.handle_admin_command("删除白名单：张三")
        assert "未知命令" in m.handle_admin_command("随便")
        m.stop()
