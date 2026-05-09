"""测试：通知模块 — QQ 格式化 / 静默模式 / 事件存储 / ID 生成"""
import tempfile
from datetime import datetime, time
from pathlib import Path

from the_machine.models import NumberEvent
from the_machine.notifier.notifier import (
    QQFormatter, QuietMode, EventStore, Notifier, _generate_event_id,
)


class TestEventID:
    """ID 唯一性"""

    def test_unique(self):
        ids = {_generate_event_id() for _ in range(1000)}
        assert len(ids) == 1000

    def test_length(self):
        eid = _generate_event_id()
        assert len(eid) == 8
        assert isinstance(eid, str)


class TestQQFormatter:
    """QQ 消息格式化"""

    def make_event(self, **kwargs) -> NumberEvent:
        return NumberEvent(
            id=_generate_event_id(),
            camera_id=kwargs.get("camera_id", "front_door"),
            timestamp=kwargs.get("timestamp", datetime.now()),
            event_type=kwargs.get("event_type", "unknown_person"),
            score=kwargs.get("score", 0.85),
            reason=kwargs.get("reason", "检测到陌生人"),
        )

    def test_format_starts_with_emoji(self):
        fmt = QQFormatter()
        msg = fmt.format(self.make_event())
        assert msg.startswith("🚨")

    def test_format_contains_number(self):
        fmt = QQFormatter()
        evt = self.make_event()
        msg = fmt.format(evt)
        assert f"Number #{evt.id}" in msg

    def test_format_contains_camera_id(self):
        fmt = QQFormatter()
        msg = fmt.format(self.make_event(camera_id="backyard"))
        assert "backyard" in msg

    def test_format_contains_event_type(self):
        fmt = QQFormatter()
        msg = fmt.format(self.make_event(event_type="off_hours_motion"))
        assert "off_hours_motion" in msg

    def test_format_contains_score(self):
        fmt = QQFormatter()
        msg = fmt.format(self.make_event(score=0.92))
        assert "92%" in msg or "0.92" in msg

    def test_format_contains_reason(self):
        fmt = QQFormatter()
        msg = fmt.format(self.make_event(reason="有人在门口徘徊"))
        assert "有人在门口徘徊" in msg

    def test_format_length_limit(self):
        fmt = QQFormatter()
        msg = fmt.format(self.make_event())
        assert len(msg) < 2000


class TestQuietMode:
    """静默模式 + 免打扰"""

    def test_normal_not_suppressed(self):
        qm = QuietMode()
        assert qm.should_suppress() is False

    def test_quiet_mode_suppresses(self):
        qm = QuietMode()
        qm.set_quiet(True)
        assert qm.should_suppress() is True
        qm.set_quiet(False)
        assert qm.should_suppress() is False

    def test_dnd_active(self):
        qm = QuietMode(dnd_start="23:00", dnd_end="07:00")
        # 凌晨 3 点应该是免打扰
        assert qm.is_do_not_disturb(time(3, 0)) is True

    def test_dnd_inactive(self):
        qm = QuietMode(dnd_start="23:00", dnd_end="07:00")
        # 下午 3 点不是免打扰
        assert qm.is_do_not_disturb(time(15, 0)) is False

    def test_dnd_cross_midnight(self):
        """跨天免打扰（23:00-07:00）"""
        qm = QuietMode(dnd_start="23:00", dnd_end="07:00")
        assert qm.is_do_not_disturb(time(23, 30)) is True
        assert qm.is_do_not_disturb(time(0, 30)) is True
        assert qm.is_do_not_disturb(time(6, 0)) is True
        assert qm.is_do_not_disturb(time(7, 30)) is False


class TestEventStore:
    """SQLite 事件存储"""

    def test_save_and_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "events.db"
            store = EventStore(str(db_path))
            evt = NumberEvent(
                id=_generate_event_id(),
                camera_id="front_door",
                timestamp=datetime.now(),
                event_type="unknown_person",
                score=0.85,
                reason="测试",
            )
            store.save(evt)
            results = store.query(days=7)
            assert len(results) >= 1
            assert results[0]["id"] == evt.id

    def test_query_by_camera(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EventStore(str(Path(tmp) / "events.db"))
            e1 = NumberEvent(id=_generate_event_id(), camera_id="cam1",
                             timestamp=datetime.now(), event_type="motion", score=0.5, reason="x")
            e2 = NumberEvent(id=_generate_event_id(), camera_id="cam2",
                             timestamp=datetime.now(), event_type="motion", score=0.5, reason="y")
            store.save(e1)
            store.save(e2)

            results = store.query(camera_id="cam1")
            assert len(results) == 1
            assert results[0]["camera_id"] == "cam1"

    def test_empty_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EventStore(str(Path(tmp) / "empty.db"))
            results = store.query(days=1)
            assert results == []


class TestNotifier:
    """通知器综合"""

    def make_event(self) -> NumberEvent:
        return NumberEvent(
            id=_generate_event_id(),
            camera_id="test",
            timestamp=datetime.now(),
            event_type="unknown_person",
            score=0.85,
            reason="test",
        )

    def test_send_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EventStore(str(Path(tmp) / "n.db"))
            notifier = Notifier(event_store=store)
            result = notifier.send(self.make_event(), dry_run=True)
            assert result["sent"] is True
            assert result["suppressed"] is False
            assert result["event_id"] is not None
            assert "🚨" in result["message"]

    def test_quiet_suppresses(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EventStore(str(Path(tmp) / "n2.db"))
            qm = QuietMode()
            qm.set_quiet(True)
            notifier = Notifier(event_store=store, quiet_mode=qm)
            result = notifier.send(self.make_event(), dry_run=True)
            assert result["sent"] is False
            assert result["suppressed"] is True

    def test_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EventStore(str(Path(tmp) / "n3.db"))
            notifier = Notifier(event_store=store)
            notifier.send(self.make_event(), dry_run=True)
            stats = notifier.stats
            assert stats["sent"] >= 0  # dry_run 不计入
            assert isinstance(stats["suppressed"], int)
