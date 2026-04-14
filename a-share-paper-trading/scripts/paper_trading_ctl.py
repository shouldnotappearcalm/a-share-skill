#!/usr/bin/env python3
"""Control helper for the paper trading backend service."""

from __future__ import annotations

import argparse
import os
import plistlib
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from paper_trading_runtime import (
    APP_NAME,
    DEFAULT_HOST,
    DEFAULT_PORT,
    LAUNCH_AGENT_LABEL,
    ensure_runtime_dir,
    get_app_data_dir,
    get_default_db_path,
    get_default_log_path,
    get_default_pid_path,
    get_launch_agents_dir,
)

SCRIPT_DIR = Path(__file__).resolve().parent
SERVICE_SCRIPT = SCRIPT_DIR / "paper_trading_service.py"


def service_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def healthcheck(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"{service_url(host, port)}/health", timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def read_pid(pid_path: Path) -> int | None:
    try:
        return int(pid_path.read_text().strip())
    except Exception:
        return None


def is_pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def wait_until_healthy(host: str, port: int, timeout_seconds: float = 15) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if healthcheck(host, port, timeout=1.0):
            return True
        time.sleep(0.3)
    return False


def start_service(host: str, port: int, db_path: Path, log_path: Path, pid_path: Path) -> int:
    ensure_runtime_dir(db_path.parent)
    if healthcheck(host, port):
        return 0
    existing_pid = read_pid(pid_path)
    if is_pid_alive(existing_pid):
        raise RuntimeError(f"service already appears running with pid={existing_pid}, but healthcheck failed")
    with log_path.open("a", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            [
                sys.executable,
                str(SERVICE_SCRIPT),
                "--host",
                host,
                "--port",
                str(port),
                "--db-path",
                str(db_path),
            ],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=str(SCRIPT_DIR),
            start_new_session=True,
        )
    pid_path.write_text(str(proc.pid), encoding="utf-8")
    if not wait_until_healthy(host, port):
        raise RuntimeError(f"service failed to become healthy, inspect log: {log_path}")
    return proc.pid


def stop_service(host: str, port: int, pid_path: Path) -> bool:
    pid = read_pid(pid_path)
    stopped = False
    if pid and is_pid_alive(pid):
        os.kill(pid, signal.SIGTERM)
        deadline = time.time() + 8
        while time.time() < deadline and is_pid_alive(pid):
            time.sleep(0.2)
        if is_pid_alive(pid):
            os.kill(pid, signal.SIGKILL)
        stopped = True
    if pid_path.exists():
        pid_path.unlink()
    return stopped or not healthcheck(host, port)


def render_launch_agent(host: str, port: int, db_path: Path, log_path: Path) -> bytes:
    ensure_runtime_dir(db_path.parent)
    plist = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": [
            sys.executable,
            str(SERVICE_SCRIPT),
            "--host",
            host,
            "--port",
            str(port),
            "--db-path",
            str(db_path),
        ],
        "WorkingDirectory": str(SCRIPT_DIR),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(log_path),
    }
    return plistlib.dumps(plist)


def install_launch_agent(host: str, port: int, db_path: Path, log_path: Path) -> Path:
    agents_dir = get_launch_agents_dir()
    agents_dir.mkdir(parents=True, exist_ok=True)
    plist_path = agents_dir / f"{LAUNCH_AGENT_LABEL}.plist"
    plist_path.write_bytes(render_launch_agent(host, port, db_path, log_path))
    subprocess.run(["launchctl", "unload", str(plist_path)], check=False, capture_output=True)
    subprocess.run(["launchctl", "load", str(plist_path)], check=True)
    return plist_path


def uninstall_launch_agent() -> Path:
    plist_path = get_launch_agents_dir() / f"{LAUNCH_AGENT_LABEL}.plist"
    if plist_path.exists():
        subprocess.run(["launchctl", "unload", str(plist_path)], check=False, capture_output=True)
        plist_path.unlink()
    return plist_path


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Control {APP_NAME} service")
    parser.add_argument("action", choices=["start", "stop", "status", "install-launchd", "uninstall-launchd"])
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db-path", default=str(get_default_db_path()))
    parser.add_argument("--log-path", default=str(get_default_log_path()))
    parser.add_argument("--pid-path", default=str(get_default_pid_path()))
    args = parser.parse_args()

    db_path = Path(args.db_path).expanduser()
    log_path = Path(args.log_path).expanduser()
    pid_path = Path(args.pid_path).expanduser()

    if args.action == "start":
        pid = start_service(args.host, args.port, db_path, log_path, pid_path)
        print(f"started {APP_NAME} on {service_url(args.host, args.port)} pid={pid} db={db_path}")
        return
    if args.action == "stop":
        ok = stop_service(args.host, args.port, pid_path)
        print("stopped" if ok else "not running")
        return
    if args.action == "status":
        pid = read_pid(pid_path)
        print(
            {
                "app_dir": str(get_app_data_dir()),
                "db_path": str(db_path),
                "log_path": str(log_path),
                "pid_path": str(pid_path),
                "pid": pid,
                "pid_alive": is_pid_alive(pid),
                "healthy": healthcheck(args.host, args.port),
                "base_url": service_url(args.host, args.port),
            }
        )
        return
    if args.action == "install-launchd":
        plist_path = install_launch_agent(args.host, args.port, db_path, log_path)
        print(f"installed launchd agent: {plist_path}")
        return
    if args.action == "uninstall-launchd":
        plist_path = uninstall_launch_agent()
        print(f"removed launchd agent: {plist_path}")
        return


if __name__ == "__main__":
    main()
