"""
感知模块 — 摄像头 RTSP 拉流管理

FFmpeg 子进程拉取 RTSP 流，逐帧解码为 JPEG bytes，
通过 async generator 产出 Frame 对象。
"""
import asyncio
import subprocess
from datetime import datetime, time
from pathlib import Path
from typing import AsyncGenerator, Optional

# Lazy imports — cv2/numpy only needed when Camera.connect() is called
cv2 = None
np = None


def _lazy_imports():
    global cv2, np
    if cv2 is None:
        import cv2 as _cv2
        import numpy as _np
        cv2 = _cv2
        np = _np

from ..exceptions import CameraConnectionError, CameraStreamError
from ..models import Frame


class Camera:
    """单个摄像头管理 — 连接、拉流、断流重连"""

    SUPPORTED_PROTOCOLS = {"rtsp", "rtmp", "http", "https"}

    def __init__(
        self,
        camera_id: str,
        name: str,
        rtsp_url: str,
        interval_sec: float = 2.0,
        active_hours: Optional[dict] = None,
        max_reconnect_attempts: int = 3,
        frame_queue_size: int = 30,
    ):
        self.id = camera_id
        self.name = name
        self.rtsp_url = rtsp_url
        self.interval_sec = interval_sec
        self.active_hours = active_hours or {"start": "00:00", "end": "23:59"}
        self.max_reconnect_attempts = max_reconnect_attempts
        self.frame_queue_size = frame_queue_size

        self._cap: Optional[cv2.VideoCapture] = None
        self._running = False
        self._reconnect_count = 0
        self._frame_count = 0
        self._fps_estimate = 0.0

        self._validate_rtsp()

    def _validate_rtsp(self) -> None:
        """校验 RTSP URL 格式"""
        protocol = self.rtsp_url.split(":")[0]
        if protocol not in self.SUPPORTED_PROTOCOLS:
            raise CameraConnectionError(
                f"不支持的协议 '{protocol}'，支持: {', '.join(self.SUPPORTED_PROTOCOLS)}"
            )

    # ── 连接管理 ──

    def connect(self) -> None:
        """打开摄像头连接"""
        _lazy_imports()
        self._cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        if not self._cap.isOpened():
            raise CameraConnectionError(f"无法连接到摄像头 {self.name} ({self.rtsp_url})")

        # 读取第一帧确认连接正常
        ret, _ = self._cap.read()
        if not ret:
            self._cap.release()
            raise CameraConnectionError(f"摄像头 {self.name} 连接成功但无法读取帧")

        self._reconnect_count = 0
        self._fps_estimate = self._cap.get(cv2.CAP_PROP_FPS) or 30.0

    def disconnect(self) -> None:
        """关闭摄像头连接"""
        self._running = False
        if self._cap and self._cap.isOpened():
            self._cap.release()
            self._cap = None

    async def reconnect(self) -> bool:
        """尝试重连，返回是否成功"""
        self.disconnect()
        await asyncio.sleep(5)  # 等待 5 秒再重连

        try:
            self.connect()
            self._reconnect_count = 0
            return True
        except CameraConnectionError:
            self._reconnect_count += 1
            return False

    # ── 流式产出帧 ──

    async def stream(self) -> AsyncGenerator[Frame, None]:
        """异步生成器，逐帧产出 Frame"""
        self._running = True
        self.connect()

        try:
            while self._running:
                if self._cap is None or not self._cap.isOpened():
                    if self._reconnect_count >= self.max_reconnect_attempts:
                        raise CameraStreamError(
                            f"摄像头 {self.name} 重连 {self.max_reconnect_attempts} 次均失败"
                        )
                    ok = await self.reconnect()
                    if not ok:
                        continue

                ret, raw_frame = self._cap.read()
                if not ret:
                    raise CameraStreamError(f"摄像头 {self.name} 读帧失败")

                self._frame_count += 1

                # 编码为 JPEG bytes
                _, jpeg_buffer = cv2.imencode(".jpg", raw_frame, [
                    cv2.IMWRITE_JPEG_QUALITY, 85,
                ])
                jpeg_bytes = jpeg_buffer.tobytes()

                height, width = raw_frame.shape[:2]

                yield Frame(
                    camera_id=self.id,
                    timestamp=datetime.now(),
                    jpeg_bytes=jpeg_bytes,
                    width=width,
                    height=height,
                    fps=self._fps_estimate,
                )

                # 按间隔等待
                await asyncio.sleep(self.interval_sec)

        except CameraStreamError:
            raise
        finally:
            self.disconnect()

    # ── 辅助 ──

    def is_active_hours(self, current: Optional[time] = None) -> bool:
        """检查当前是否在活动时段内"""
        now = current or datetime.now().time()

        def _parse(t_str: str) -> time:
            parts = t_str.split(":")
            return time(int(parts[0]), int(parts[1]))

        start = _parse(self.active_hours["start"])
        end = _parse(self.active_hours["end"])

        if start <= end:
            return start <= now <= end
        else:
            # 跨天：如 23:00 - 07:00
            return now >= start or now <= end

    @property
    def stats(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "frames_captured": self._frame_count,
            "connected": self._cap is not None and self._cap.isOpened(),
            "reconnect_count": self._reconnect_count,
        }

    def __repr__(self) -> str:
        return f"<Camera {self.id}: {self.name}>"
