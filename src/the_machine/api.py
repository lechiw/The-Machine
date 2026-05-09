"""
The Machine — HTTP API 服务

提供轻量 REST API，供 OpenClaw agent 轮询告警和发送命令。
"""
import asyncio
import json
from datetime import datetime
from typing import Optional

from .models import NumberEvent


class MachineAPI:
    """HTTP API 服务 — 使用 asyncio HTTP server"""

    def __init__(self, machine, host: str = "127.0.0.1", port: int = 18790):
        self._machine = machine
        self._host = host
        self._port = port
        self._server: Optional[asyncio.AbstractServer] = None
        self._pending_alerts: list[dict] = []

    # ── 告警管理 ──

    def push_alert(self, event: NumberEvent) -> None:
        """添加告警到待推送队列"""
        self._pending_alerts.append({
            "id": event.id,
            "camera_id": event.camera_id,
            "timestamp": event.timestamp.isoformat(),
            "event_type": event.event_type,
            "score": event.score,
            "reason": event.reason,
            "evidence_path": event.evidence_path,
            "message": f"🚨 Number #{event.id} | {event.timestamp.strftime('%H:%M:%S')}\n"
                       f"区域：{event.camera_id}\n"
                       f"类型：{event.event_type}\n"
                       f"置信度：{event.score:.0%}\n"
                       f"详情：{event.reason}",
        })

    def get_pending_alerts(self) -> list[dict]:
        """获取并清空待推送告警"""
        alerts = self._pending_alerts.copy()
        self._pending_alerts.clear()
        return alerts

    # ── HTTP 处理 ──

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """处理 HTTP 请求"""
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=5)
            if not request_line:
                writer.close()
                return

            method, path, _ = request_line.decode("utf-8", errors="replace").strip().split(" ", 2)

            # 读取请求头
            headers = {}
            while True:
                line = (await reader.readline()).decode("utf-8", errors="replace").strip()
                if not line:
                    break
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()

            # 读取请求体
            content_length = int(headers.get("content-length", 0))
            body = await reader.readexactly(content_length) if content_length > 0 else b""

            # 路由
            if path == "/alerts" and method == "GET":
                response = self._handle_get_alerts()
            elif path == "/command" and method == "POST":
                response = self._handle_post_command(body)
            elif path == "/status" and method == "GET":
                response = self._handle_get_status()
            elif path == "/health" and method == "GET":
                response = {"status": "ok"}
            else:
                response = {"error": f"not found: {method} {path}"}
                status = 404

            status = 200 if "error" not in response else response.get("_status", 200)
            body_bytes = json.dumps(response, ensure_ascii=False).encode("utf-8")

            writer.write(
                f"HTTP/1.1 {status} {'OK' if status == 200 else 'Error'}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body_bytes)}\r\n"
                f"Access-Control-Allow-Origin: *\r\n"
                f"\r\n".encode("utf-8")
            )
            writer.write(body_bytes)
        except Exception as e:
            error_body = json.dumps({"error": str(e)}).encode("utf-8")
            try:
                writer.write(
                    b"HTTP/1.1 500 Error\r\nContent-Type: application/json\r\n"
                    + f"Content-Length: {len(error_body)}\r\n\r\n".encode("utf-8")
                    + error_body
                )
            except Exception:
                pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    def _handle_get_alerts(self) -> dict:
        """获取待推送告警"""
        alerts = self.get_pending_alerts()
        return {"alerts": alerts, "count": len(alerts)}

    def _handle_post_command(self, body: bytes) -> dict:
        """处理 Admin 命令"""
        try:
            data = json.loads(body)
            command = data.get("command", "")
            if not command:
                return {"error": "missing 'command' field", "_status": 400}
            reply = self._machine.handle_admin_command(command)
            return {"reply": reply}
        except json.JSONDecodeError:
            return {"error": "invalid JSON", "_status": 400}

    def _handle_get_status(self) -> dict:
        """获取系统状态"""
        s = self._machine.status()
        return {
            "running": s["running"],
            "cameras": s["cameras"],
            "connected": s["cameras_connected"],
            "frames": s["total_frames"],
            "alerts": s["total_alerts"],
            "sent": s["notifications_sent"],
            "uptime_hours": s["uptime_hours"],
        }

    # ── 生命周期 ──

    async def start(self) -> None:
        """启动 HTTP 服务"""
        self._server = await asyncio.start_server(
            self._handle, self._host, self._port
        )
        addr = self._server.sockets[0].getsockname()
        print(f"  🌐 API: http://{addr[0]}:{addr[1]}")

    async def stop(self) -> None:
        """停止 HTTP 服务"""
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    @property
    def address(self) -> str:
        return f"http://{self._host}:{self._port}"
