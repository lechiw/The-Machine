"""通知模块 — Number 告警生成、QQ 推送、事件存储"""
import json
import sqlite3
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

from ..models import NumberEvent


# ── 事件 ID 生成 ──

def _generate_event_id() -> str:
    """生成全局唯一的短 ID"""
    return uuid.uuid4().hex[:8]


# ── QQ 消息格式化 ──

_NUMBER_TEMPLATE = """🚨 Number #{id} | {time}
区域：{camera_id}
类型：{event_type}
置信度：{score:.0%}
详情：{reason}"""


class QQFormatter:
    """QQ 消息格式化器"""

    @staticmethod
    def format(event: NumberEvent) -> str:
        """将 NumberEvent 格式化为 QQ 消息字符串"""
        time_str = event.timestamp.strftime("%H:%M:%S")
        return _NUMBER_TEMPLATE.format(
            id=event.id,
            time=time_str,
            camera_id=event.camera_id,
            event_type=event.event_type,
            score=event.score,
            reason=event.reason,
        )


# ── 静默模式 + 免打扰 ──

class QuietMode:
    """静默模式与免打扰时段管理"""

    def __init__(self, dnd_start: str = "23:00", dnd_end: str = "07:00"):
        self._quiet = False
        self._dnd_start = self._parse_time(dnd_start)
        self._dnd_end = self._parse_time(dnd_end)

    @staticmethod
    def _parse_time(t_str: str) -> time:
        parts = t_str.split(":")
        return time(int(parts[0]), int(parts[1]))

    @property
    def is_quiet(self) -> bool:
        return self._quiet

    def set_quiet(self, quiet: bool) -> None:
        self._quiet = quiet

    def is_do_not_disturb(self, current: Optional[time] = None) -> bool:
        """检查当前是否为免打扰时段"""
        now = current or datetime.now().time()
        if self._dnd_start <= self._dnd_end:
            return self._dnd_start <= now <= self._dnd_end
        else:
            # 跨天：如 23:00 - 07:00
            return now >= self._dnd_start or now <= self._dnd_end

    def should_suppress(self) -> bool:
        """综合判断是否应压制告警"""
        if self._quiet:
            return True
        if self.is_do_not_disturb():
            return True
        return False


# ── 事件存储 ──

class EventStore:
    """SQLite 事件存储"""

    def __init__(self, db_path: str = "data/events.db"):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_db()

    def _init_db(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                camera_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                score REAL NOT NULL,
                reason TEXT,
                evidence_path TEXT,
                acknowledged INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        self._conn.commit()

    def save(self, event: NumberEvent) -> None:
        """保存告警事件"""
        self._conn.execute(
            """INSERT OR REPLACE INTO events
               (id, timestamp, camera_id, event_type, score, reason, evidence_path, acknowledged)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event.id,
                event.timestamp.isoformat(),
                event.camera_id,
                event.event_type,
                event.score,
                event.reason,
                event.evidence_path,
                1 if event.acknowledged else 0,
            ),
        )
        self._conn.commit()

    def query(self, camera_id: Optional[str] = None, days: int = 7) -> list[dict]:
        """查询事件记录"""
        sql = "SELECT * FROM events WHERE created_at >= datetime('now', ?)"
        params = [f"-{days} days"]

        if camera_id:
            sql += " AND camera_id = ?"
            params.append(camera_id)

        sql += " ORDER BY timestamp DESC"

        cursor = self._conn.execute(sql, params)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def close(self) -> None:
        self._conn.close()


# ── 通知器 ──

class Notifier:
    """通知器 — 接收异常事件、通过 OpenClaw CLI 推送 QQ"""

    # QQ 接收者（可通过配置修改）
    QQ_TARGET = "CCDC4A1709C211EDA20A77DFA54B115A"
    QQ_CHANNEL = "qqbot"

    def __init__(
        self,
        formatter: Optional[QQFormatter] = None,
        quiet_mode: Optional[QuietMode] = None,
        event_store: Optional[EventStore] = None,
        qq_target: Optional[str] = None,
    ):
        self._formatter = formatter or QQFormatter()
        self._quiet_mode = quiet_mode or QuietMode()
        self._event_store = event_store or EventStore()
        self._sent_count = 0
        self._suppressed_count = 0
        self._failed_count = 0
        if qq_target:
            self.__class__.QQ_TARGET = qq_target

    def _send_via_cli(self, message: str, media_path: str = "") -> bool:
        """通过 openclaw CLI 发送 QQ 消息"""
        import subprocess, os, shutil

        cmd = [
            "openclaw", "message", "send",
            "--channel", self.QQ_CHANNEL,
            "--target", self.QQ_TARGET,
            "--message", message,
        ]
        if media_path and os.path.isfile(media_path):
            # 转存到 QQ media 目录
            qq_media = "/home/dministrator/.openclaw/media/qqbot/downloads"
            os.makedirs(qq_media, exist_ok=True)
            dest = os.path.join(qq_media, f"notify_{os.path.basename(media_path)}")
            shutil.copy2(media_path, dest)
            cmd.extend(["--media", dest])

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15,
                env={**os.environ, "HOME": os.path.expanduser("~")},
            )
            return result.returncode == 0
        except Exception:
            return False

    def send(self, event: NumberEvent, dry_run: bool = False) -> dict:
        """处理告警事件：保存 → 检查压制 → 推送"""
        # 始终保存到数据库
        if not dry_run:
            self._event_store.save(event)

        # 检查是否应压制
        if self._quiet_mode.should_suppress():
            self._suppressed_count += 1
            return {"sent": False, "suppressed": True, "event_id": event.id}

        msg = self._formatter.format(event)

        if not dry_run:
            ok = self._send_via_cli(msg, event.evidence_path or "")
            if ok:
                self._sent_count += 1
            else:
                self._failed_count += 1

        return {
            "sent": True,
            "suppressed": False,
            "event_id": event.id,
            "message": msg,
            "has_evidence": event.evidence_path is not None,
        }

    @property
    def stats(self) -> dict:
        return {
            "sent": self._sent_count,
            "suppressed": self._suppressed_count,
            "failed": self._failed_count,
        }
