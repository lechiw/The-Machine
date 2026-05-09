# 🎬 The Machine

> *"You're being watched."*

受《疑犯追踪》(Person of Interest) 启发的本地监控告警系统原型。从摄像头感知环境，检测异常行为，推送告警。

## 🏗 开发状态

当前阶段：**Spec Driven** ✅ — 规约已定义，等待实现

## 📋 Spec 清单

| 模块 | 规约文件 | 测试数 |
|------|---------|-------|
| 📹 感知层 | `specs/01_sensor_spec.py` | 4 |
| 👁 检测层 | `specs/02_detector_spec.py` | 9 |
| 🧠 分析层 | `specs/03_analyzer_spec.py` | 14 |
| 📢 通知层 | `specs/04_notifier_spec.py` | 10 |
| ⚙️ 配置管理 | `specs/05_config_spec.py` | 12 |
| 🎬 端到端场景 | `specs/06_scenarios_spec.py` | 9 |

## 🧱 架构

```
摄像头 RTSP → FFmpeg 拉流 → YOLOv8 检测 → 异常评分 → QQ 告警
```

全部本地处理，不上云。

## 🔗

[GitHub](https://github.com/lechiw/The-Machine)
