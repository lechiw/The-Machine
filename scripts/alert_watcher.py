#!/usr/bin/env python3
"""
告警推送守护 — 定期轮询 The Machine API，发现告警后写入日志文件
供 OpenClaw agent 读取并推送到 QQ。

启动:
    python3 scripts/alert_watcher.py

与 main.py 同时运行。
"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

# The Machine API 地址
API_HOST = "http://127.0.0.1:18790"
# 告警输出文件（OpenClaw agent 读取）
ALERT_FILE = str(Path(__file__).parent.parent / "data" / "pending_alerts.jsonl")


def fetch_alerts() -> list[dict]:
    """从 Machine API 获取待推送告警"""
    try:
        req = urllib.request.Request(f"{API_HOST}/alerts")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            return data.get("alerts", [])
    except Exception as e:
        return []


def append_alerts(alerts: list[dict]) -> None:
    """追加告警到文件"""
    if not alerts:
        return
    os.makedirs(os.path.dirname(ALERT_FILE), exist_ok=True)
    with open(ALERT_FILE, "a", encoding="utf-8") as f:
        for alert in alerts:
            f.write(json.dumps(alert, ensure_ascii=False) + "\n")
            f.flush()
    print(f"  📝 写入 {len(alerts)} 条告警到 {ALERT_FILE}", flush=True)


def main():
    print(f"👀 告警守护启动 | API: {API_HOST} → {ALERT_FILE}", flush=True)
    while True:
        try:
            alerts = fetch_alerts()
            if alerts:
                append_alerts(alerts)
            time.sleep(5)  # 每 5 秒轮询一次
        except KeyboardInterrupt:
            break
        except Exception as e:
            time.sleep(5)


if __name__ == "__main__":
    main()
