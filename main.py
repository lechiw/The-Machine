#!/usr/bin/env python3
"""
The Machine — CLI 入口

Usage:
    python main.py -c config.json
    python main.py                   # 使用默认 config.json
"""
import argparse
import signal
import sys
from pathlib import Path

# 确保 src 在 path 中
sys.path.insert(0, str(Path(__file__).parent / "src"))

from the_machine.main import TheMachine


def main():
    parser = argparse.ArgumentParser(description="🎬 The Machine — 本地监控告警系统")
    parser.add_argument(
        "-c", "--config",
        default="config.json",
        help="配置文件路径 (默认: config.json)",
    )
    args = parser.parse_args()

    config_path = args.config
    if not Path(config_path).exists():
        print(f"⚠️  配置文件不存在: {config_path}")
        print(f"   参考 config.example.json 创建")
        sys.exit(1)

    machine = TheMachine(config_path)
    machine.start()

    def handle_signal(sig, frame):
        print("\n🛑 正在关闭...")
        machine.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # 主循环
    try:
        import time
        while machine.is_alive():
            time.sleep(10)
            status = machine.status()
            # 每隔一段时间打印状态
            print(f"  [{status['cameras_connected']}/{status['cameras']}] 帧: {status['total_frames']} 告警: {status['total_alerts']}")
    except KeyboardInterrupt:
        pass
    finally:
        machine.stop()


if __name__ == "__main__":
    main()
