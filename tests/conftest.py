"""pytest 配置 — 自动添加 src 到 sys.path"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))
