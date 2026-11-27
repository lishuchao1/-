"""Start backend and frontend together with one command.

Windows-safe: never goes through npm.cmd / shell wrappers, because
CreateProcess cannot execute .cmd files directly. Uses sys.executable
and the node binary explicitly.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND_PORT = 8000
FRONTEND_PORT = 5173
VITE_ENTRY = ROOT / "frontend" / "node_modules" / "vite" / "bin" / "vite.js"


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def find_node() -> str:
    node = shutil.which("node")
    if not node:
        raise SystemExit("node not found on PATH; install Node.js 18+ and retry")
    return node


def check_environment() -> None:
    missing = []
    if not (ROOT / "backend" / "app" / "main.py").is_file():
        missing.append("backend/app/main.py")
    if not VITE_ENTRY.is_file():
        missing.append("frontend/node_modules (run: npm install --prefix frontend)")
    if missing:
        raise SystemExit("missing prerequisites:\n  " + "\n  ".join(missing))
    for label, port in (("backend", BACKEND_PORT), ("frontend", FRONTEND_PORT)):
        if not port_free(port):
            raise SystemExit(f"{label} port {port} is already in use; stop that process first")


def spawn(cmd: list[str], cwd: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUNBUFFERED", "1")
    return subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=env,
        stdout=sys.stdout,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )


def main() -> int:
    check_environment()
    node = find_node()
    procs: list[tuple[str, subprocess.Popen]] = []

    backend = spawn(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(BACKEND_PORT), "--reload"],
        ROOT / "backend",
    )
    procs.append(("backend", backend))

    frontend = spawn(
        [node, str(VITE_ENTRY), "--host", "127.0.0.1", "--port", str(FRONTEND_PORT), "--strictPort"],
        ROOT / "frontend",
    )
    procs.append(("frontend", frontend))

    print(f"\n  backend  http://127.0.0.1:{BACKEND_PORT}/health")
    print(f"  frontend http://127.0.0.1:{FRONTEND_PORT}/")
    print("  press Ctrl+C to stop both\n")

    def shutdown(*_: object) -> None:
        for name, proc in procs:
            if proc.poll() is None:
                print(f"stopping {name} ...")
                proc.terminate()
        deadline = time.time() + 8
        for name, proc in procs:
            try:
                proc.wait(timeout=max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                print(f"killing {name}")
                proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    if os.name == "nt":
        signal.signal(signal.SIGBREAK, shutdown)

    while True:
        for name, proc in procs:
            code = proc.poll()
            if code is not None:
                print(f"{name} exited with code {code}; shutting down the other process")
                shutdown()
        time.sleep(0.5)


if __name__ == "__main__":
    raise SystemExit(main())