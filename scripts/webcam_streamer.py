"""
Windows 摄像头 → MJPEG HTTP 推流

在 Windows 上运行此脚本，把本地摄像头画面通过 HTTP 推流。
WSL2 中的 The Machine 可以通过 http://windows-ip:8090/video 拉流。

安装依赖：
    pip install opencv-python

用法：
    python webcam_streamer.py            # 默认摄像头 0, 端口 8090
    python webcam_streamer.py --cam 1    # 摄像头编号
    python webcam_streamer.py --port 8090
"""
import argparse
import cv2
import socket
import struct
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from io import BytesIO


class MJPEGHandler(BaseHTTPRequestHandler):
    """提供 MJPEG 流的 HTTP handler"""

    def do_GET(self):
        if self.path != '/video':
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'close')
        self.end_headers()

        global cap
        while cap and cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            frame_bytes = jpeg.tobytes()
            try:
                self.wfile.write(b'--frame\r\n')
                self.wfile.write(b'Content-Type: image/jpeg\r\n')
                self.wfile.write(f'Content-Length: {len(frame_bytes)}\r\n\r\n'.encode())
                self.wfile.write(frame_bytes)
                self.wfile.write(b'\r\n')
            except (BrokenPipeError, ConnectionResetError):
                break

    def log_message(self, format, *args):
        pass  # 安静运行


def get_windows_ip() -> str:
    """获取 Windows 主机的 WSL2 可访问 IP"""
    try:
        # 获取 WSL gateway IP（即 Windows 在 WSL2 网络中的 IP）
        import subprocess
        result = subprocess.run(
            ['ip', 'route', 'show', 'default'],
            capture_output=True, text=True
        )
        for line in result.stdout.split('\n'):
            parts = line.split()
            if 'default' in line and len(parts) >= 3:
                return parts[2]
    except Exception:
        pass
    return "127.0.0.1"


def main():
    parser = argparse.ArgumentParser(description='Windows 摄像头 MJPEG 推流器')
    parser.add_argument('--cam', type=int, default=0, help='摄像头编号 (默认: 0)')
    parser.add_argument('--port', type=int, default=8090, help='HTTP 端口 (默认: 8090)')
    parser.add_argument('--width', type=int, default=640, help='画面宽度')
    parser.add_argument('--height', type=int, default=480, help='画面高度')
    args = parser.parse_args()

    global cap
    cap = cv2.VideoCapture(args.cam)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

    if not cap.isOpened():
        print(f"❌ 无法打开摄像头 #{args.cam}")
        print("  试试 --cam 1, --cam 2 切换摄像头")
        return

    windows_ip = get_windows_ip()
    server = HTTPServer(('0.0.0.0', args.port), MJPEGHandler)

    print(f"""
╔══════════════════════════════════╗
║   📷 Windows → WSL2 摄像头推流   ║
╚══════════════════════════════════╝

    摄像头: #{args.cam}
    分辨率: {args.width}x{args.height}
    
    🌐 WSL2 中访问:
       http://{windows_ip}:{args.port}/video
    
    🔌 按 Ctrl+C 停止
    """)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 停止推流")
    finally:
        cap.release()
        server.shutdown()


if __name__ == '__main__':
    main()
