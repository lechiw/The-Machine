"""摄像头管理器 — 管理多个 Camera 实例"""
from typing import Optional

from .camera import Camera


class CameraManager:
    """管理多个摄像头，提供统一的启停接口"""

    def __init__(self):
        self._cameras: dict[str, Camera] = {}
        self._running = False

    def add_camera(self, camera: Camera) -> bool:
        """注册摄像头，ID 重复时返回 False"""
        if camera.id in self._cameras:
            return False
        self._cameras[camera.id] = camera
        return True

    def remove_camera(self, camera_id: str) -> bool:
        """移除摄像头"""
        if camera_id not in self._cameras:
            return False
        self._cameras[camera_id].disconnect()
        del self._cameras[camera_id]
        return True

    def get_camera(self, camera_id: str) -> Optional[Camera]:
        return self._cameras.get(camera_id)

    def start_all(self) -> None:
        """启动所有摄像头"""
        self._running = True

    def stop_all(self) -> None:
        """停止所有摄像头"""
        self._running = False
        for cam in self._cameras.values():
            cam.disconnect()

    def get_status(self) -> list[dict]:
        """获取所有摄像头状态"""
        return [cam.stats for cam in self._cameras.values()]

    @property
    def count(self) -> int:
        return len(self._cameras)

    def __repr__(self) -> str:
        return f"<CameraManager cameras={self.count}>"
