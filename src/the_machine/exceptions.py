"""
自定义异常层级 — The Machine 错误处理的核心。

所有模块异常都继承自 MachineError，上层按需捕获。
"""


class MachineError(Exception):
    """所有 The Machine 异常的基类"""
    pass


class CameraError(MachineError):
    """摄像头相关错误：连接失败、断流、帧读取失败等"""
    pass


class CameraConnectionError(CameraError):
    """摄像头 RTSP 连接失败"""
    pass


class CameraStreamError(CameraError):
    """摄像头流读取中断"""
    pass


class DetectionError(MachineError):
    """检测模块错误"""
    pass


class AnalysisError(MachineError):
    """分析模块错误"""
    pass


class NotifyError(MachineError):
    """通知模块错误"""
    pass


class ConfigError(MachineError):
    """配置管理错误"""
    pass


class ConfigValidationError(ConfigError):
    """配置校验失败"""
    pass
