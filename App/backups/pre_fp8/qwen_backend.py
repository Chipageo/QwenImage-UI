"""The model setup from test_qwen.py, loaded once on first use with configurable CPU offload."""
import gc
import importlib.util
import os
import time
import warnings
from pathlib import Path


def acceleration_support():
    try:
        available = importlib.util.find_spec("triton") is not None
    except (ImportError, ValueError):
        available = False
    return {"available": available, "reason": "Compilation unavailable: Triton is not installed in this Python environment. Standard mode works normally. Installing a compatible compiler is a separate setup step." if not available else "Compiler package detected; runtime compatibility is not yet verified."}


class QwenBackend:
    def __init__(self):
        self.pipe = None
        self.cpu_offload = None
        self.attention_mode = "standard"
        self.last_metrics = {}

    def unload(self):
        self.pipe = None
        self.cpu_offload = None
        gc.collect()
        import torch
        if hasattr(torch, "cuda") and hasattr(torch.cuda, "empty_cache"):
            torch.cuda.empty_cache()

    def generate(self, request, images, output, step_callback=None):
        import inspect
        import torch
        from diffusers import QwenImage21Pipeline

        cpu_offload = request.get("cpu_offload", True)
        attention_mode = request.get("attention_mode", "standard")
        self.last_metrics = {}
        started = time.perf_counter()
        if attention_mode not in ("standard", "compiled", "flex"):
            raise ValueError("Unknown compute mode.")
        if attention_mode != "standard" and not acceleration_support()["available"]:
            raise RuntimeError(acceleration_support()["reason"])
        if not cpu_offload and torch.cuda.get_device_properties(0).total_memory < 30 * 1024**3:
            raise RuntimeError("Full GPU BF16 mode needs about 30 GiB for weights alone, plus working memory. It does not fit this GPU. Select CPU offload.")

        reloaded = self.pipe is None or (self.cpu_offload is not None and self.cpu_offload != cpu_offload) or self.attention_mode != attention_mode
        if reloaded:
            if not torch.cuda.is_available():
                raise RuntimeError("CUDA is unavailable. Run with the project's CUDA-enabled venv.")
            if self.pipe is not None:
                self.unload()
            pipe = QwenImage21Pipeline.from_pretrained(
                os.environ.get("QWEN_MODEL_PATH", "Qwen/Qwen-Image-2.1"),
                torch_dtype=torch.bfloat16,
                local_files_only=True,
            )
            try:
                if attention_mode == "flex":
                    from diffusers.models.transformers.transformer_qwenimage21 import QwenImage21FlexAttnProcessor
                    pipe.transformer.set_attn_processor(QwenImage21FlexAttnProcessor())
                if attention_mode != "standard":
                    pipe.transformer.compile()
                if cpu_offload:
                    pipe.enable_model_cpu_offload()
                else:
                    pipe.to("cuda")
                self.pipe = pipe
                self.cpu_offload = cpu_offload
                self.attention_mode = attention_mode
            except Exception as exc:
                del pipe
                self.unload()
                raise RuntimeError("Could not initialize this mode. Select CPU offload + Standard and retry. " + str(exc)[:350]) from exc

        if hasattr(self.pipe, "vae"):
            # The Qwen VAE exposes use_tiling and enable_tiling, but no disable_tiling.
            if request.get("vae_tiling", False):
                self.pipe.vae.enable_tiling()
            else:
                self.pipe.vae.use_tiling = False
        def sync():
            if hasattr(torch, "cuda") and hasattr(torch.cuda, "synchronize"):
                torch.cuda.synchronize()
        sync()
        setup_end = time.perf_counter()
        self.last_metrics = {"setup_s": round(setup_end - started, 2), "reloaded": reloaded}
        if hasattr(torch, "cuda") and hasattr(torch.cuda, "reset_peak_memory_stats"):
            torch.cuda.reset_peak_memory_stats()

        prompt = request["prompt"]
        if request.get("transparent"):
            prompt = ("This is an RGBA image with transparency. " + prompt
                      + ". The image has alpha channel and the background is transparent.")
        kwargs = dict(prompt=prompt, width=request["width"], height=request["height"],
                      num_inference_steps=request["steps"],
                      generator=torch.Generator("cuda").manual_seed(request["seed"]))
        if images:
            kwargs["image"] = images
        if not request.get("use_kv_cache", True):
            kwargs["use_kv_cache"] = False

        marks = []
        def on_step(step):
            if step == 1 or step == request["steps"]:
                sync()
                marks.append((step, time.perf_counter()))
            if step_callback is not None:
                step_callback(step, request["steps"])

        try:
            sig = inspect.signature(self.pipe.__call__).parameters
            if "callback_on_step_end" in sig:
                def _step_end_cb(pipe, step, timestep, callback_kwargs):
                    try:
                        on_step(step + 1)
                    except Exception:
                        pass
                    return callback_kwargs
                kwargs["callback_on_step_end"] = _step_end_cb
            elif "callback" in sig:
                def _classic_cb(step, timestep, latents):
                    try:
                        on_step(step + 1)
                    except Exception:
                        pass
                kwargs["callback"] = _classic_cb
                if "callback_steps" in sig:
                    kwargs["callback_steps"] = 1
        except Exception:
            pass

        try:
            with torch.inference_mode(), warnings.catch_warnings():
                warnings.filterwarnings("error", message="invalid value encountered in cast", category=RuntimeWarning)
                result = self.pipe(**kwargs).images[0]
        except RuntimeWarning as exc:
            raise RuntimeError(
                "Qwen returned invalid numeric image values. Try the documented 40 steps. "
                "If this persists, check the installed model/runtime; no invalid PNG was saved."
            ) from exc
        except Exception as exc:
            self.unload()
            if attention_mode != "standard":
                raise RuntimeError("Accelerated generation failed. Select Standard and retry; no fallback was silently applied. " + str(exc)[:350]) from exc
            raise
        result.save(Path(output), format="PNG")
        sync()
        finished = time.perf_counter()
        if marks:
            first, last = marks[0][1], marks[-1][1]
            self.last_metrics.update(first_step_s=round(first - setup_end, 2),
                                     remaining_steps_s=round(last - first, 2),
                                     finish_s=round(finished - last, 2))
        if hasattr(torch, "cuda") and hasattr(torch.cuda, "max_memory_allocated"):
            self.last_metrics["peak_vram_gib"] = round(torch.cuda.max_memory_allocated() / 1024**3, 2)
