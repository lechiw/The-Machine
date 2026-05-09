# Plan — The Machine MVP

> 基于 [spec.md](./spec.md) 的架构方案。  
> 人起草 → AI 细化 → 人审核。

---

## Architecture Decision

采用**管道-过滤器（Pipeline + Filter）架构**，以摄像头帧为单位流经各处理阶段。

```
[Camera] → [Frame Buffer] → [Detector] → [Analyzer] → [Notifier]
    ↑            ↑               ↑             ↑            ↑
  拉流         队列缓冲       目标检测       异常评分      告警推送
```

**决策理由：**
- 管道架构与视频帧的流式本质天然匹配
- 每个阶段可独立开发、测试、替换
- 单帧处理失败不影响其他帧
- 检测耗时较长时队列缓冲防止丢帧

---

## Module Breakdown

### M1: `sensor/` — 摄像头管理

**职责：** 管理摄像头 RTSP 连接，按间隔产出帧

```
CameraManager
  ├── Camera(id, rtsp_url, interval, active_hours)
  │     ├── connect()        → 启动 FFmpeg 子进程拉流
  │     ├── stream()         → async generator 逐帧产出
  │     ├── disconnect()     → 优雅关闭
  │     └── reconnect()      → 断流自动重连
  └── Frame(camera_id, timestamp, jpeg_bytes, width, height, fps)
```

**关键设计：**
- FFmpeg 子进程通过 `subprocess.PIPE` 读取 stdout 帧数据
- 用 `asyncio.create_subprocess_exec` 实现异步非阻塞
- 断流检测：FFmpeg 进程退出 → 等待 5s → 重新 spawn
- 帧队列用 `asyncio.Queue` 缓冲，大小可配

### M2: `detector/` — 目标检测

**职责：** 对帧进行目标检测和人脸识别

```
Detector
  ├── ObjectDetector
  │     └── detect(frame) → DetectionResult
  ├── FaceRecognizer
  │     └── recognize(frame, whitelist) → FaceResult
  └── DetectionResult(objects[], faces[], motion_score, timestamp)
```

**关键设计：**
- ObjectDetector 使用 ONNX Runtime 加载检测模型
- **不绑定具体模型** — 通过配置指定模型路径（符合 spec.md 的 Constraints 精神）
- 默认模型：轻量级人脸检测 + 通用目标检测（后续可换）
- FaceRecognizer 用特征向量比对白名单，余弦相似度阈值 0.6
- 检测器线程池执行，不阻塞主事件循环
- 无检测结果时返回空列表，不抛异常

### M3: `analyzer/` — 异常分析引擎

**职责：** 维护基线、运行规则、计算异常评分

```
Analyzer
  ├── BaselineManager
  │     ├── build(detection_history)           → Baseline
  │     ├── update(baseline, new_samples)      → updated Baseline
  │     └── get(time_slot, camera_id)          → Baseline
  ├── RuleEngine
  │     ├── register(name, rule_fn)
  │     ├── evaluate(name, context)            → RuleResult
  │     └── list_rules()                       → str[]
  ├── Scorer
  │     └── score(detection, baseline, rules)  → AnomalyScore
  └── AnomalyScore(value: float, reason: str, triggered_rules: str[])
```

**内置规则（M3 一期）：**
1. `unknown_person` — 画面中检测到人且人脸不在白名单
2. `off_hours_motion` — 当前时间在 active_hours 之外且有移动目标
3. `prolonged_stay` — 同一区域同一目标停留超过阈值（默认 5 分钟）

**关键设计：**
- 规则引擎采用注册制，新增规则只需写一个函数 + 注册
- 评分归一化到 [0, 1]，阈值可配置（默认 0.7）
- 冷却机制：按 (camera_id, rule_name) 键记录最后触发时间
- 基线按时间段分桶（15 分钟为一个 slot），滑动窗口更新

### M4: `notifier/` — 告警通知

**职责：** 生成 Number 告警、推送到 QQ

```
Notifier
  ├── NumberEvent(id, camera_id, timestamp, event_type, score, reason, evidence_path)
  ├── QQNotifier
  │     ├── format(event)          → 格式化的 QQ 消息字符串
  │     └── send(event)            → 通过 OpenClaw QQ Bot 推送
  ├── QuietMode
  │     ├── is_quiet()             → bool
  │     └── set_dnd(start, end)
  └── EventStore
        └── save(event)            → 写入 SQLite
```

**QQ 消息模板：**
```
🚨 Number #42 | 14:23:05
区域：前门
类型：未知人员
置信度：0.89
详情：检测到 1 名未知人员在门口停留 15 秒
[截图附件]
```

### M5: `config/` — 配置管理

**职责：** 加载、校验、热重载配置

```
ConfigManager
  ├── load(path)                    → Config
  ├── validate(config)              → errors[] or None
  ├── get(key_path)                 → value
  ├── hot_reload()
  ├── Watchdog                      → 文件变更监听，自动热重载
  └── WhitelistManager
        ├── add(name, face_label)
        ├── remove(name)
        └── list()                  → Person[]
```

**关键设计：**
- `watchdog` 库监听配置文件变更 → 自动热重载
- 校验使用 JSON Schema（`jsonschema` 库）
- 热重载不中断正在处理的帧流水线

### M6: `main.py` — 入口 / 编排

**职责：** 组装所有模块、启动流水线、暴露 Admin 接口

```
TheMachine
  ├── start()
  ├── stop()
  ├── status()                     → 运行状态摘要
  ├── add_camera(id, rtsp_url)
  ├── remove_camera(id)
  ├── process_one_frame(...)       → 内部流水线（单帧全链路）
  └── _pipeline_loop()             → async 主循环
```

**Admin 交互（通过 QQ Bot）：**
```
Admin → "状态"
Machine → "📊 运行 2h | 3 摄像头 | 0 告警 | 2 事件"

Admin → "门口设为安静"
Machine → "✅ 门口已静音"

Admin → "添加白名单：张三"
Machine → "✅ 张三已加入白名单"
```

---

## Interface Contracts

### 内部接口

```
# sensor → detector
Frame(camera_id, timestamp, jpeg_bytes) → Frame（透传，不变）

# detector → analyzer
DetectionResult(objects, faces, motion_score) → Analyzer.evaluate()

# analyzer → notifier
AnomalyScore(score, reason, triggered_rules) | None → Notifier.send()

# notifier → output
NumberEvent → QQ 消息字符串（已格式化）
```

### 外部接口

配置文件 `config.json`：
```json
{
  "cameras": [
    {"id": "front_door", "name": "门口", "rtsp": "rtsp://...", "interval_sec": 2}
  ],
  "whitelist": [{"name": "老大", "face_label": "laoda"}],
  "anomaly": {"score_threshold": 0.7, "cooldown_sec": 300},
  "notifier": {"dnd_start": "23:00", "dnd_end": "07:00"}
}
```

---

## Risk Assessment

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| CPU 推理过慢，帧堆积 | 中 | 高 | 丢帧策略：队列满时丢弃旧帧；支持 GPU 加速 |
| 人脸识别误匹配 | 中 | 中 | 可配置阈值；白名单可增删；告警附截图供人工确认 |
| FFmpeg 进程泄漏 | 低 | 高 | 每个 Camera 对象生命周期内只 spawn 一次；graceful shutdown 确保 kill |
| SQLite 写入竞争 | 低 | 低 | 使用单连接 + WAL 模式；写入异步非阻塞 |
| 长时间运行内存泄漏 | 中 | 高 | 限制检测结果历史记录条数；定期清理证据文件 |

---

## 依赖清单

| 依赖 | 用途 | 理由 |
|------|------|------|
| `opencv-python-headless` | 图像处理、帧解码 | 成熟稳定，无 GUI 依赖 |
| `onnxruntime` | 模型推理 | CPU 友好，支持 GPU |
| `numpy` | 数组运算 | 检测模型依赖 |
| `Pillow` | 图像编码/截图 | 轻量，Python 标准 |
| `jsonschema` | 配置校验 | 零运行时开销 |
| `watchdog` | 配置文件热重载监听 | 文件系统事件驱动 |

---

## 非功能性设计

### 错误处理
- 自定义异常层级：`MachineError` → `CameraError` / `DetectionError` / `AnalysisError` / `NotifyError`
- 相机断流、检测失败等不影响其他模块运行
- 所有外部进程（FFmpeg）超时强制 Kill

### 日志
- 结构化日志输出到文件 + stdout
- 日志级别：INFO（常规运行）/ WARNING（断流、重连）/ ERROR（模块故障）

### 测试策略
- 单元测试：mock frame 数据测试各模块核心逻辑
- 集成测试：使用测试视频文件跑通全链路
- Spec 中的 Acceptance Criteria 对应 1~N 个 pytest 用例
