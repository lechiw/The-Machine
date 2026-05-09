# 🎬 The Machine

> *"You're being watched."*

受《疑犯追踪》(Person of Interest) 启发的本地监控告警系统原型。
从摄像头感知环境，检测异常行为，推送告警。

## 方法论：Spec-Driven Development

本仓库遵循 **SDD (Spec-Driven Development)** 开发方法论。

```
constitution.md  ← 不可变约束
     ↓
spec.md          ← 需求规格（WHAT + WHY）
     ↓
plan.md          ← 架构方案（HOW）
     ↓
tasks.md         ← 执行清单（原子任务）
     ↓
验收：specs/*.py ← 自动化测试
```

## Phase 1 — Spec ✅

- [`constitution.md`](./constitution.md) — 项目宪法：隐私、安全、设计约束
- [`spec.md`](./spec.md) — MVP 需求规格：Problem → Metrics → Stories → AC → Non-Goals → Constraints

## Phase 2 — Plan 🔜

（等待 Spec 审阅后生成）

## Phase 3 — Implement 🔜

（等待 Plan 确认后执行）

## 架构概要

```
摄像头 RTSP → FFmpeg 拉流 → 目标检测 → 异常评分 → QQ 告警
```

全部本地处理，不上云。

## 许可

MIT
