#!/usr/bin/env python3
"""
The Machine — CLI 入口

Usage:
    python main.py -c config.json

API (由 OpenClaw agent 轮询):
    GET  http://127.0.0.1:18790/alerts   → 获取待推送告警
    POST http://127.0.0.1:18790/command  → 发送 Admin 命令
    GET  http://127.0.0.1:18790/status   → 系统状态
"""
import argparse
import asyncio
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from the_machine.main import TheMachine


async def main_async():
    parser = argparse.ArgumentParser(description="🎬 The Machine — 本地监控告警系统")
    parser.add_argument("-c", "--config", default="config.json",
                        help="配置文件路径 (默认: config.json)")
    args = parser.parse_args()

    config_path = args.config
    if not Path(config_path).exists():
        print(f"⚠️  配置文件不存在: {config_path}")
        print(f"   参考 config.example.json 创建")
        sys.exit(1)

    machine = TheMachine(config_path)
    await machine.start_async()

    print(f"\n    📡 API: http://127.0.0.1:18790/")
    print(f"    📋 状态: http://127.0.0.1:18790/status")
    print(f"")

    stop_event = asyncio.Event()

    def handle_signal():
        print("\n🛑 正在关闭...")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except NotImplementedError:
            # Windows 不支持 add_signal_handler
            signal.signal(sig, lambda s, f: handle_signal())

    # 状态打印循环
    async def status_printer():
        while not stop_event.is_set():
            s = machine.status()
            print(f"  [{s['cameras_connected']}/{s['cameras']}] "
                  f"帧:{s['total_frames']} 告警:{s['total_alerts']} 推送:{s['notifications_sent']}")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=10)
            except asyncio.TimeoutError:
                pass

    await asyncio.gather(status_printer(), stop_event.wait())
    await machine.stop_async()


if __name__ == "__main__":
    asyncio.run(main_async())
