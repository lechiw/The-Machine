# Tasks — The Machine MVP

> 基于 [plan.md](./plan.md) 拆解为可独立验证的原子任务。

---

## Task Group 1：项目骨架

### Task 1.1 项目初始化
- [ ] 创建 `pyproject.toml`（setuptools 配置）
- [ ] 创建 `requirements.txt`
- [ ] 创建目录结构：`sensor/ detector/ analyzer/ notifier/ config/`
- [ ] 每个模块创建 `__init__.py`
- [ ] 创建自定义异常 `machine_error.py`
- [ ] 验证：`pip install -e .` 成功

### Task 1.2 配置管理模块
- [ ] 实现 `ConfigManager.load(path)` — 从 JSON 文件加载配置
- [ ] 实现 `ConfigManager.validate(config)` — JSON Schema 校验
- [ ] 实现 `ConfigManager.get(key_path)` — 点分路径取值
- [ ] 实现 `ConfigManager.hot_reload()` — watchdog 监听文件变更
- [ ] 实现 `WhitelistManager` — 白名单增删改
- [ ] 创建默认 `config.json` 模板
- [ ] 验证：单元测试覆盖 config 模块

---

## Task Group 2：摄像头感知

### Task 2.1 Camera 类
- [ ] 实现 `Camera.__init__` — 存储 id / rtsp / interval / active_hours
- [ ] 实现 `Camera.connect()` — 启动 FFmpeg 子进程拉 RTSP 流
- [ ] 实现 `Camera.stream()` — async generator 逐帧产出 Frame 对象
- [ ] 实现 `Camera.disconnect()` — 优雅关闭 FFmpeg 进程
- [ ] 实现 `Camera.reconnect()` — 断流检测 + 自动重连（最多 3 次）
- [ ] 实现 `Camera.active_hours_check()` — 判断当前是否为活动时段
- [ ] 验证：mock FFmpeg 进程测试帧产出

### Task 2.2 CameraManager
- [ ] 实现 `CameraManager.add_camera(id, rtsp_url, ...)`
- [ ] 实现 `CameraManager.remove_camera(id)`
- [ ] 实现 `CameraManager.start_all()` / `stop_all()`
- [ ] 实现 `CameraManager.get_status()` — 各摄像头在线状态
- [ ] 验证：多摄像头并发启动/停止测试

### Task 2.3 Frame 数据模型
- [ ] 定义 `Frame` dataclass（camera_id, timestamp, jpeg_bytes, width, height, fps）
- [ ] 实现帧队列 `asyncio.Queue` 缓冲管理
- [ ] 实现队列满时丢旧帧策略
- [ ] 验证：帧队列满时行为正确

---

## Task Group 3：目标检测

### Task 3.1 ObjectDetector
- [ ] 初始化 ONNX Runtime session（通过配置指定模型路径）
- [ ] 实现 `detect(frame) → DetectionResult`
- [ ] DetectionResult 包含 `objects: list[DetectedObject]`
- [ ] DetectedObject dataclass: class_id, label, confidence, bbox
- [ ] 空画面返回空列表
- [ ] 验证：用测试图片验证检测结果格式

### Task 3.2 FaceRecognizer
- [ ] 实现人脸检测（从帧中裁剪人脸区域）
- [ ] 实现特征提取（转换为 embedding 向量）
- [ ] 实现白名单比对（余弦相似度，阈值可配）
- [ ] 返回 FaceResult: known, name, confidence
- [ ] 已知人脸返回对应身份，未知标记为 unknown
- [ ] 无脸画面返回 None / faces=0
- [ ] 验证：用已知/未知人脸图片验证

### Task 3.3 检测器编排
- [ ] 实现线程池执行检测任务（不阻塞事件循环）
- [ ] 检测超时处理（单帧超时丢弃）
- [ ] 验证：检测结果正确传递到 analyzer

---

## Task Group 4：异常分析

### Task 4.1 基线管理
- [ ] 实现 `BaselineManager.build(detection_history)`
- [ ] 基线结构：avg_objects, std_objects, time_slot, samples
- [ ] 按时间段分桶（15 分钟 slot）
- [ ] 实现 `BaselineManager.update(baseline, new_samples)`
- [ ] 验证：不同 time slot 基线应有差异

### Task 4.2 规则引擎
- [ ] 实现规则注册制：`register(name, rule_fn)`
- [ ] 实现 `evaluate(name, context) → RuleResult(triggered, reason)`
- [ ] 实现 `list_rules()` / 规则不存在时返回明确错误
- [ ] 内置规则 1：`unknown_person` 规则逻辑
- [ ] 内置规则 2：`off_hours_motion` 规则逻辑
- [ ] 内置规则 3：`prolonged_stay` 规则逻辑
- [ ] 验证：每规则分别有触发/不触发测试用例

### Task 4.3 异常评分
- [ ] 实现 `Scorer.score(detection, baseline, rules) → AnomalyScore`
- [ ] AnomalyScore: value(float 0~1), reason(str), triggered_rules(list)
- [ ] 评分归一化到 [0, 1]
- [ ] 验证：正常活动低分、异常活动高分

### Task 4.4 冷却机制
- [ ] 按 (camera_id, rule_name) 键存储最后触发时间
- [ ] 冷却期内同类告警不重复触发
- [ ] 冷却期过后可再次触发
- [ ] 验证：冷却前/冷却中/冷却后三种状态

---

## Task Group 5：告警通知

### Task 5.1 NumberEvent 模型
- [ ] 定义 `NumberEvent` dataclass（必填 + 可选字段）
- [ ] 告警 ID 全局唯一生成（UUID 短格式）
- [ ] 验证：ID 唯一性测试

### Task 5.2 QQ 消息格式化
- [ ] 实现 `format(event) → str`（含 🚨 Number # 格式）
- [ ] 包含：时间、区域、类型、置信度、推理详情
- [ ] 消息长度 < 2000 字符
- [ ] 无证据时正常生成消息（不崩溃）
- [ ] 验证：格式化后内容完整

### Task 5.3 推送管理
- [ ] 实现 `QQNotifier.send(event)` — 调用 OpenClaw 消息接口
- [ ] 实现静默模式
- [ ] 实现免打扰时段（配置 start/end 时间）
- [ ] 验证：静默模式压制、免打扰压制、正常发送

### Task 5.4 事件存储
- [ ] SQLite 建表：events(id, timestamp, camera_id, event_type, score, detail, evidence_path, acknowledged)
- [ ] 实现 `EventStore.save(event)`
- [ ] 实现 `EventStore.query(filter)` — 支持按时间/摄像头筛选
- [ ] 验证：读写数据正确

---

## Task Group 6：主入口

### Task 6.1 TheMachine 编排
- [ ] 实现 `TheMachine.__init__` — 组装所有模块
- [ ] 实现 `TheMachine.start()` — 启动流水线
- [ ] 实现 `TheMachine.stop()` — 优雅关闭所有模块
- [ ] 实现 `TheMachine.status()` — 运行摘要
- [ ] 实现 `TheMachine.process_one_frame()` — 内部全链路
- [ ] 验证：启动 → 处理 mock 帧 → 停止，无异常

### Task 6.2 Admin 交互（QQ Bot 接口）
- [ ] "状态" → 返回运行摘要
- [ ] "静音/恢复" → 切换静默模式
- [ ] "添加白名单" / "删除白名单" → 管理白名单
- [ ] 验证：每条命令响应正确

### Task 6.3 主入口 CLI
- [ ] `python main.py` 启动服务
- [ ] 处理 Ctrl+C 优雅退出
- [ ] 加载配置 → 启动摄像头 → 开始检测

---

## 执行顺序

```
Task 1.1 (骨架)
   ↓
Task 1.2 (配置)  ← 其他 Task 依赖配置读取能力
   ↓
Task 2.x (摄像头)  ← 需要配置来获取摄像头列表
   ↓
Task 3.x (检测器)  ← 需要帧数据
   ↓
Task 4.x (分析器)  ← 需要检测结果
   ↓
Task 5.x (通知器)  ← 需要告警事件
   ↓
Task 6.x (入口)  ← 组装所有模块
```
