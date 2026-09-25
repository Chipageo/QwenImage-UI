"""Loopback-only Qwen UI. Uses Python stdlib and the existing Pillow install."""
import argparse
import base64
import binascii
import ctypes
import io
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import traceback
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image, ImageOps
from qwen_backend import QwenBackend, acceleration_support

# --- System hardware metrics collector (GPU, CPU, RAM) ---
class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]

class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]

def _filetime_to_int(ft):
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime

_last_cpu_times = None

def get_cpu_stats():
    global _last_cpu_times
    if sys.platform == "win32":
        try:
            idle = FILETIME()
            kernel = FILETIME()
            user = FILETIME()
            if ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
                idle_i = _filetime_to_int(idle)
                kern_i = _filetime_to_int(kernel)
                user_i = _filetime_to_int(user)
                if _last_cpu_times is not None:
                    last_idle, last_kern, last_user = _last_cpu_times
                    d_idle = idle_i - last_idle
                    d_kern = kern_i - last_kern
                    d_user = user_i - last_user
                    sys_time = d_kern + d_user
                    if sys_time > 0:
                        load = int(max(0, min(100, round((sys_time - d_idle) / sys_time * 100))))
                        _last_cpu_times = (idle_i, kern_i, user_i)
                        return {"load": load}
                _last_cpu_times = (idle_i, kern_i, user_i)
        except Exception:
            pass
    return {"load": 0}

def get_ram_stats():
    if sys.platform == "win32":
        try:
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                total_gb = round(stat.ullTotalPhys / (1024 ** 3), 1)
                used_gb = round((stat.ullTotalPhys - stat.ullAvailPhys) / (1024 ** 3), 1)
                return {
                    "load": int(stat.dwMemoryLoad),
                    "used_gb": used_gb,
                    "total_gb": total_gb
                }
        except Exception:
            pass
    return None

def get_gpu_stats():
    try:
        creationflags = 0x08000000 if sys.platform == "win32" else 0
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=1.5,
            creationflags=creationflags
        )
        if proc.returncode == 0 and proc.stdout:
            parts = [p.strip() for p in proc.stdout.strip().split(",")]
            if len(parts) >= 4:
                return {
                    "load": int(parts[0]),
                    "temp": int(parts[1]),
                    "mem_used": round(float(parts[2]) / 1024, 1),
                    "mem_total": round(float(parts[3]) / 1024, 1)
                }
    except Exception:
        pass
    return None

_stats_cache = {"time": 0, "data": None}
_stats_lock = threading.Lock()

def get_system_stats():
    now = time.monotonic()
    with _stats_lock:
        if _stats_cache["data"] is not None and (now - _stats_cache["time"]) < 1.2:
            return _stats_cache["data"]
        data = {
            "gpu": get_gpu_stats(),
            "cpu": get_cpu_stats(),
            "ram": get_ram_stats()
        }
        _stats_cache["data"] = data
        _stats_cache["time"] = now
        return data

ROOT = Path(__file__).resolve().parent
RESOLUTION_PRESETS = {
    "512": {
        "1:1": (512, 512), "4:3": (608, 448), "3:4": (448, 608),
        "3:2": (624, 416), "2:3": (416, 624), "16:9": (688, 384), "9:16": (384, 688)
    },
    "1k": {
        "1:1": (1024, 1024), "4:3": (1200, 896), "3:4": (896, 1200),
        "3:2": (1264, 848), "2:3": (848, 1264), "16:9": (1376, 768), "9:16": (768, 1376)
    },
    "2k": {
        "1:1": (2048, 2048), "4:3": (2400, 1792), "3:4": (1792, 2400),
        "3:2": (2528, 1696), "2:3": (1696, 2528), "16:9": (2752, 1536), "9:16": (1536, 2752)
    },
}
SIZES = RESOLUTION_PRESETS["2k"]
MAX_IMAGE = 15 * 1024 * 1024
MAX_BODY = 64 * 1024 * 1024
MAX_PIXELS = 25_000_000


def validate(data):
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object.")
    prompt = data.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 12000:
        raise ValueError("Enter a prompt between 1 and 12,000 characters.")
    scale = str(data.get("scale", data.get("res", "2k"))).lower()
    if scale not in RESOLUTION_PRESETS:
        scale = "2k"
    ratio = data.get("ratio", "1:1")
    if not isinstance(ratio, str) or ratio not in RESOLUTION_PRESETS[scale]:
        raise ValueError("Choose a supported aspect ratio.")
    steps = data.get("steps", 40)
    if type(steps) is not int or not 1 <= steps <= 100:
        raise ValueError("Steps must be a whole number from 1 to 100 (UI limit).")
    seed = data.get("seed")
    if seed is None:
        seed = secrets.randbelow(2**32)
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise ValueError("Seed must be a whole number from 0 to 4294967295.")
    transparent = data.get("transparent", False)
    if type(transparent) is not bool:
        raise ValueError("Invalid transparency option.")
    cpu_offload = data.get("cpu_offload", True)
    if type(cpu_offload) is not bool:
        cpu_offload = True
    attention_mode = data.get("attention_mode", "standard")
    if attention_mode not in ("standard", "compiled", "flex"):
        raise ValueError("Choose a supported attention mode.")
    use_kv_cache = data.get("use_kv_cache", True)
    vae_tiling = data.get("vae_tiling", False)
    if type(use_kv_cache) is not bool or type(vae_tiling) is not bool:
        raise ValueError("Cache and VAE tiling options must be booleans.")
    files = data.get("images", [])
    if not isinstance(files, list) or len(files) > 10:
        raise ValueError("Attach up to 10 reference images.")
    images = []
    try:
        for encoded in files:
            if not isinstance(encoded, str) or len(encoded) > (MAX_IMAGE * 4 // 3 + 4):
                raise ValueError("Each image must be at most 15 MB.")
            raw = base64.b64decode(encoded, validate=True)
            if len(raw) > MAX_IMAGE:
                raise ValueError("Each image must be at most 15 MB.")
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as source:
                    if source.format not in {"PNG", "JPEG", "WEBP"}:
                        raise ValueError("Use PNG, JPEG or WebP images.")
                    if source.width * source.height > MAX_PIXELS:
                        raise ValueError("Each image must be at most 25 megapixels.")
                    fixed = ImageOps.exif_transpose(source)
                    images.append(fixed.convert("RGBA" if "A" in fixed.getbands() or "transparency" in fixed.info else "RGB"))
    except Exception as exc:
        for image in images:
            image.close()
        raise ValueError("Invalid image upload.") from exc
    width, height = RESOLUTION_PRESETS[scale][ratio]
    return dict(prompt=prompt.strip(), scale=scale, ratio=ratio, width=width, height=height,
                steps=steps, seed=seed, transparent=transparent, cpu_offload=cpu_offload,
                attention_mode=attention_mode, use_kv_cache=use_kv_cache, vae_tiling=vae_tiling), images


class State:
    def __init__(self, backend=None, output_dir=None):
        self.backend = backend or QwenBackend()
        self.output_dir = Path(output_dir or ROOT.parent / "Generate images")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.jobs = {}
        self.busy = False
        self.last_heartbeat = time.monotonic()
        self.startup_time = time.monotonic()
        self.shutdown_requested = False
        self.shutdown_timer = None

    def cancel_shutdown(self):
        with self.lock:
            if self.shutdown_timer:
                self.shutdown_timer.cancel()
                self.shutdown_timer = None
            self.shutdown_requested = False

    def submit(self, data):
        # Hold the lock through validation so concurrent uploads cannot accumulate decoded images.
        with self.lock:
            if self.busy:
                raise BlockingIOError("Another image is generating. Please wait for it to finish.")
            request, images = validate(data)
            job_id = secrets.token_hex(16)
            start_monotonic = time.monotonic()
            job = dict(id=job_id, status="running", stage="preparing",
                       seed=request["seed"], steps=request["steps"],
                       step=0, progress=0,
                       width=request["width"], height=request["height"],
                       ratio=request["ratio"], scale=request["scale"],
                       start_time=start_monotonic,
                       settings={key: request[key] for key in ("cpu_offload", "attention_mode", "use_kv_cache", "vae_tiling")})
            # Bound in-memory metadata. PNG outputs remain on disk.
            while len(self.jobs) >= 100:
                self.jobs.pop(next(iter(self.jobs)))
            self.jobs[job_id] = job
            self.busy = True
            threading.Thread(target=self.run, args=(job_id, request, images), daemon=True).start()
            return dict(job)

    def run(self, job_id, request, images):
        def on_step(current_step, total_steps):
            with self.lock:
                if job_id in self.jobs:
                    pct = int(min(100, max(0, round((current_step / total_steps) * 100))))
                    self.jobs[job_id]["step"] = current_step
                    self.jobs[job_id]["total_steps"] = total_steps
                    self.jobs[job_id]["progress"] = pct
                    self.jobs[job_id]["stage"] = "generating"

        with self.lock:
            start_time = self.jobs.get(job_id, {}).get("start_time", time.monotonic())
        try:
            with self.lock:
                if job_id in self.jobs:
                    self.jobs[job_id]["stage"] = "generating"
            import inspect
            sig = inspect.signature(self.backend.generate).parameters
            if "step_callback" in sig:
                self.backend.generate(request, images, self.output_dir / (job_id + ".png"), step_callback=on_step)
            else:
                self.backend.generate(request, images, self.output_dir / (job_id + ".png"))
            duration = round(time.monotonic() - start_time, 2)
            time_str = f"{duration:.2f}s" if duration < 60 else f"{int(duration // 60)}m {duration % 60:.1f}s"
            result = dict(status="complete", progress=100, step=request["steps"], url="/outputs/" + job_id + ".png",
                          duration=duration, generation_time=duration, generation_time_formatted=time_str,
                          metrics=getattr(self.backend, "last_metrics", {}))
        except Exception as exc:
            traceback.print_exc()
            duration = round(time.monotonic() - start_time, 2)
            time_str = f"{duration:.2f}s" if duration < 60 else f"{int(duration // 60)}m {duration % 60:.1f}s"
            result = dict(status="failed", error=str(exc)[:1000] or "Generation failed. See the server terminal.",
                          duration=duration, generation_time=duration, generation_time_formatted=time_str,
                          metrics=getattr(self.backend, "last_metrics", {}))
        finally:
            for image in images:
                image.close()
        with self.lock:
            self.jobs[job_id].update(result)
            self.busy = False


def handler_for(state):
    class Handler(BaseHTTPRequestHandler):
        def send_bytes(self, status, body, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' blob: data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def json(self, status, value):
            self.send_bytes(status, json.dumps(value).encode(), "application/json")

        def allowed(self):
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.headers.get("Host") not in allowed:
                self.json(403, {"error": "Use the localhost URL printed by the server."})
                return False
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://" + host for host in allowed}:
                self.json(403, {"error": "Cross-origin requests are not allowed."})
                return False
            return True

        def do_GET(self):
            if not self.allowed():
                return
            path = urlsplit(self.path).path
            if path == "/api/config":
                state.cancel_shutdown()
                with state.lock:
                    venv_root = str(Path(sys.executable).parent.parent) if sys.executable else ""
                    self.json(200, dict(token=state.token, ratios=SIZES, resolutions=RESOLUTION_PRESETS,
                                        memory_opt=True, busy=state.busy, acceleration=acceleration_support(),
                                        loaded=state.backend.pipe is not None, app_root=str(ROOT),
                                        venv_root=venv_root))
            elif path == "/api/stats":
                self.json(200, get_system_stats())
            elif path.startswith("/api/jobs/"):
                with state.lock:
                    job = state.jobs.get(path.removeprefix("/api/jobs/"))
                    if job:
                        job_dict = dict(job)
                        if job_dict.get("status") == "running" and "start_time" in job_dict:
                            job_dict["elapsed"] = round(time.monotonic() - job_dict["start_time"], 1)
                        self.json(200, job_dict)
                    else:
                        self.json(404, {"error": "Job not found."})
            elif path.startswith("/outputs/"):
                name = path.removeprefix("/outputs/")
                if len(name) != 36 or not name.endswith(".png") or any(c not in "0123456789abcdef" for c in name[:-4]):
                    return self.json(404, {"error": "Not found."})
                file = state.output_dir / name
                if not file.is_file():
                    return self.json(404, {"error": "Image not found."})
                self.send_bytes(200, file.read_bytes(), "image/png")
            elif path.startswith("/api/open/"):
                name = path.removeprefix("/api/open/")
                if len(name) != 36 or not name.endswith(".png") or any(c not in "0123456789abcdef" for c in name[:-4]):
                    return self.json(404, {"error": "Not found."})
                file = state.output_dir / name
                if not file.is_file():
                    return self.json(404, {"error": "Image not found."})
                try:
                    if sys.platform == "win32":
                        os.startfile(str(file))
                    else:
                        subprocess.run(["xdg-open", str(file)])
                    self.json(200, {"status": "opened"})
                except Exception as exc:
                    self.json(500, {"error": str(exc)})
            else:
                files = {"/": ("index.html", "text/html; charset=utf-8"),
                         "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                         "/style.css": ("style.css", "text/css; charset=utf-8")}
                if path not in files:
                    return self.json(404, {"error": "Not found."})
                name, mime = files[path]
                self.send_bytes(200, (ROOT / "ui" / name).read_bytes(), mime)

        def do_POST(self):
            if not self.allowed():
                return
            if self.path == "/api/heartbeat":
                token = self.headers.get("X-Qwen-Token", "")
                if secrets.compare_digest(token, state.token):
                    with state.lock:
                        state.last_heartbeat = time.monotonic()
                    state.cancel_shutdown()
                    return self.json(200, {"status": "ok"})
                return self.json(403, {"error": "Invalid token."})
            if self.path.startswith("/api/shutdown"):
                token = self.headers.get("X-Qwen-Token", "")
                query = urlsplit(self.path).query
                query_token = query.split("token=")[-1] if "token=" in query else ""
                if secrets.compare_digest(token, state.token) or (query_token and secrets.compare_digest(query_token, state.token)) or not token:
                    with state.lock:
                        state.shutdown_requested = True
                        if state.shutdown_timer:
                            state.shutdown_timer.cancel()
                        def _delayed_shutdown():
                            with state.lock:
                                if not state.shutdown_requested:
                                    return
                            print("Browser window closed. Shutting down server...", flush=True)
                            self.server.shutdown()
                        state.shutdown_timer = threading.Timer(3.0, _delayed_shutdown)
                        state.shutdown_timer.daemon = True
                        state.shutdown_timer.start()
                    return self.json(200, {"status": "shutting_down"})
                return self.json(403, {"error": "Invalid token."})
            if self.path != "/api/jobs":
                return self.json(404, {"error": "Not found."})
            if not secrets.compare_digest(self.headers.get("X-Qwen-Token", ""), state.token):
                return self.json(403, {"error": "Refresh the page to reconnect to the server."})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.json(415, {"error": "Expected application/json."})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    return self.json(413, {"error": "Upload is too large. Use at most 45 MB of images in total."})
                self.connection.settimeout(30)
                payload = self.rfile.read(length)
                if len(payload) != length:
                    raise ValueError("Incomplete upload.")
                self.json(202, state.submit(json.loads(payload)))
            except BlockingIOError as exc:
                self.json(409, {"error": str(exc)})
            except (ValueError, UnicodeDecodeError) as exc:
                self.json(400, {"error": str(exc)})
            except TimeoutError:
                self.json(408, {"error": "Upload timed out."})
    return Handler


def start_watchdog(server, state, idle_timeout=7200, initial_grace=60):
    def watchdog():
        while not state.shutdown_requested:
            time.sleep(5)
            now = time.monotonic()
            if now - state.startup_time < initial_grace:
                continue
            with state.lock:
                if state.busy:
                    state.last_heartbeat = now
                    continue
                elapsed = now - state.last_heartbeat
            if elapsed > idle_timeout:
                print("No active client connection for 2 hours. Shutting down server...", flush=True)
                threading.Thread(target=server.shutdown, daemon=True).start()
                break
    thread = threading.Thread(target=watchdog, daemon=True)
    thread.start()
    return thread


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--no-watchdog", action="store_true", help="Disable auto-shutdown watchdog")
    args = parser.parse_args()
    state = State()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(state))
    if not args.no_watchdog:
        start_watchdog(server, state)
    print(f"Qwen Image Studio: http://127.0.0.1:{server.server_port}", flush=True)
    print("Model loads on first generation from existing local weights. Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
