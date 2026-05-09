#!/usr/bin/env python3
"""
告警推送守护 — 轮询 Machine API，通过 OpenClaw CLI 推送到 QQ

同时运行：
    python main.py &                       # The Machine
    python scripts/alert_push.py &         # 本脚本（告警推送）

不需要用户手动操作任何东西。
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

API_HOST = "http://127.0.0.1:18790"
QQ_TARGET = "CCDC4A1709C211EDA20A77DFA54B115A"
POLL_INTERVAL = 3  # 每 3 秒检查一次

_seen_ids = set()


def send_qq(message: str, media_path: str = "") -> bool:
    """通过 OpenClaw CLI 发送 QQ 消息（支持图片附件）"""
    cmd = [
        "openclaw", "message", "send",
        "--channel", "qqbot",
        "--target", QQ_TARGET,
        "--message", message,
    ]
    if media_path and os.path.isfile(media_path):
        # 转存到 QQ media 目录
        qq_media_dir = "/home/dministrator/.openclaw/media/qqbot/downloads"
        os.makedirs(qq_media_dir, exist_ok=True)
        dest = os.path.join(qq_media_dir, f"alert_{os.path.basename(media_path)}")
        import shutil
        shutil.copy2(media_path, dest)
        cmd.extend(["--media", dest])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15,
            env={**os.environ, "HOME": os.path.expanduser("~")},
        )
        return result.returncode == 0
    except Exception as e:
        print(f"  ⚠️ 发送失败: {e}", flush=True)
        return False


def fetch_alerts() -> list[dict]:
    """获取新告警"""
    try:
        req = urllib.request.Request(f"{API_HOST}/alerts")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            return data.get("alerts", [])
    except Exception:
        return []


def push_alerts():
    """轮询并推送新告警"""
    alerts = fetch_alerts()
    for alert in alerts:
        alert_id = alert.get("id", "")
        if alert_id in _seen_ids:
            continue
        _seen_ids.add(alert_id)

        msg = (
            f"🚨 告警 #{alert_id[:6]}\n"
            f"类型：{alert.get('event_type', '?')}\n"
            f"时间：{alert.get('timestamp', '?')[11:19]}\n"
            f"区域：{alert.get('camera_id', '?')}\n"
            f"{alert.get('reason', '')}"
        )
        # 如果有截图证据则附带
        evidence = alert.get('evidence_path', '') or ''
        ok = send_qq(msg, media_path=evidence)
        print(f"  {'✅' if ok else '❌'} 推送: {alert.get('event_type')} @ {alert.get('timestamp','?')[:19]} {'📷' if evidence else ''}", flush=True)


def main():
    print(f"👀 告警推送守护启动 | API: {API_HOST} → QQ", flush=True)
    print(f"   每 {POLL_INTERVAL} 秒检查一次", flush=True)
    while True:
        try:
            push_alerts()
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"  ⚠️ 轮询异常: {e}", flush=True)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
