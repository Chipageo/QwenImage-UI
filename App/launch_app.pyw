"""Open Qwen in an app window, with no terminal and automatic shutdown via watchdog."""
import ctypes
import json
import msvcrt
import os
import sys
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:7860"


def find_python():
    # 1. If currently executed by pythonw/python in a venv, reuse it
    current = Path(sys.executable)
    if current.is_file():
        pw = current.parent / "pythonw.exe"
        if pw.is_file():
            return pw
        if current.name.lower() in ("pythonw.exe", "python.exe"):
            return current

    # 2. Check saved venv_path.txt
    for cfg in (ROOT / "venv_path.txt", ROOT.parent / "venv_path.txt"):
        if cfg.is_file():
            try:
                raw = cfg.read_text(encoding="utf-8").strip()
                p = Path(raw)
                for candidate in (p / "Scripts/pythonw.exe", p / "venv/Scripts/pythonw.exe", p):
                    if candidate.is_file() and candidate.name.lower() in ("pythonw.exe", "python.exe"):
                        return candidate
            except Exception:
                pass

    # 3. Check adjacent venv
    for candidate in (
        ROOT.parent / "venv/Scripts/pythonw.exe",
        ROOT / "venv/Scripts/pythonw.exe",
        ROOT.parent.parent / "venv/Scripts/pythonw.exe",
    ):
        if candidate.is_file():
            return candidate

    # 4. Check known user locations
    home = Path.home()
    for candidate in (
        home / "Qwen-Image-2.1/venv/Scripts/pythonw.exe",
        Path("C:/Users/d.chipashvili/Qwen-Image-2.1/venv/Scripts/pythonw.exe"),
        Path("C:/Qwen-Image-2.1/venv/Scripts/pythonw.exe"),
        Path("D:/Qwen-Image-2.1/venv/Scripts/pythonw.exe"),
    ):
        if candidate.is_file():
            return candidate

    raise RuntimeError("The project's Python environment was not found. Run start-ui.cmd to select it.")


def get_server_config():
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(URL + "/api/config", timeout=1) as response:
            return json.load(response)
    except Exception:
        return None


def kill_port_7860():
    try:
        output = subprocess.check_output("netstat -ano", shell=True, text=True)
        for line in output.splitlines():
            if ":7860" in line and "LISTENING" in line:
                parts = line.strip().split()
                pid = parts[-1]
                if pid.isdigit() and int(pid) > 0:
                    subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
        time.sleep(1)
    except Exception:
        pass


def server_ready():
    config = get_server_config()
    if config is None:
        return False
    if not isinstance(config, dict) or not isinstance(config.get("token"), str) or config.get("ratios", {}).get("1:1") != [2048, 2048]:
        raise RuntimeError("Port 7860 is used by another application. Close it, then try again.")
    if Path(config.get("app_root", "")).resolve() != ROOT:
        # Automatically kill the old Qwen server so the new one can take over
        kill_port_7860()
        return False
    return True


def find_browser():
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise RuntimeError("Microsoft Edge or Google Chrome is required for the application window.")


def main():
    browser = find_browser()
    logs = ROOT / "ui_logs"
    logs.mkdir(exist_ok=True)

    # Serialise double-clicks so only one backend starts.
    with (logs / "launcher.lock").open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        deadline = time.monotonic() + 45
        while True:
            try:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Another launcher is still starting Qwen. Please try again shortly.")
                time.sleep(.2)
        try:
            if not server_ready():
                python = find_python()
                with (logs / "server.log").open("ab") as output:
                    server_process = subprocess.Popen(
                        [str(python), "-u", str(ROOT / "ui_server.py")], cwd=str(ROOT),
                        stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                deadline = time.monotonic() + 30
                while not server_ready():
                    if server_process.poll() is not None:
                        raise RuntimeError(f"Qwen could not start. Details: {logs / 'server.log'}")
                    if time.monotonic() >= deadline:
                        raise RuntimeError(f"Qwen is taking too long to start. Details: {logs / 'server.log'}")
                    time.sleep(.25)
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)

    # Launch browser window (server shutdown is managed cleanly by heartbeat watchdog & beforeunload)
    subprocess.Popen([
        str(browser), "--app=" + URL, "--window-size=1280,900", "--no-first-run",
        "--no-default-browser-check", "--user-data-dir=" + str(ROOT / "ui_browser_profile"),
    ], cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        ctypes.windll.user32.MessageBoxW(None, str(exc), "Qwen Image Studio", 0x10)
