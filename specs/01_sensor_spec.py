"""
Spec: 感知模块 — Camera 拉流规约

验收标准（这些测试必须全部通过）：
- Camera 能从 RTSP URL 拉取帧
- Camera 按指定间隔输出帧
- Camera 在断流时能自动重连
- Camera 上报帧附带 camera_id 和精确时间戳
"""

import pytest
import time
from pathlib import Path


class TestCameraSpec:
    """Camera 模块行为规约"""

    def test_camera_creates_frame_stream(self, mock_camera):
        """Camera 必须能从 RTSP URL 拉取帧并产出 Frame 对象"""
        frames = []
        for i, frame in enumerate(mock_camera.stream()):
            frames.append(frame)
            if i >= 5:
                break
        assert len(frames) >= 5, "至少产出 5 帧"
        for f in frames:
            assert hasattr(f, 'camera_id'), "帧必须携带 camera_id"
            assert hasattr(f, 'timestamp'), "帧必须携带时间戳"
            assert hasattr(f, 'jpeg_bytes'), "帧必须携带图片数据"
            assert isinstance(f.jpeg_bytes, bytes), "图片数据必须是 bytes"
            assert len(f.jpeg_bytes) > 0, "图片数据不能为空"

    def test_camera_frame_interval(self, mock_camera):
        """Camera 输出帧间隔必须接近配置值（允许 20% 误差）"""
        config_interval = 2.0  # seconds
        mock_camera.interval = config_interval
        start = time.time()
        frames = []
        for i, frame in enumerate(mock_camera.stream(max_frames=3)):
            frames.append(frame)
        elapsed = time.time() - start
        actual_interval = elapsed / (len(frames) - 1) if len(frames) > 1 else 0
        assert abs(actual_interval - config_interval) / config_interval <= 0.2, \
            f"帧间隔 {actual_interval:.2f}s 偏离配置 {config_interval}s 超过 20%"

    def test_camera_auto_reconnect(self, mock_camera_with_flaky_connection):
        """当 RTSP 断流时，Camera 应自动重连，不抛出异常"""
        frames = []
        errors = []
        for frame in mock_camera_with_flaky_connection.stream(max_frames=10):
            if frame is None:
                continue  # 重连中跳过
            frames.append(frame)
        assert len(frames) >= 3, "断流恢复后应继续产出帧"
        assert not errors, "不应抛出未处理的异常"

    def test_camera_mandatory_fields(self, mock_camera):
        """每帧必须包含完整的元数据"""
        frame = next(mock_camera.stream())
        metadata = {
            'camera_id': frame.camera_id,
            'timestamp': frame.timestamp,
            'width': frame.width,
            'height': frame.height,
            'fps': frame.fps,
        }
        for key, value in metadata.items():
            assert value is not None, f"元数据字段 '{key}' 不应为 None"
