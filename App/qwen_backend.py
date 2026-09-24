"""The model setup from test_qwen.py, loaded once on first use with configurable CPU offload."""
import gc
import os
import warnings
from pathlib import Path


class QwenBackend:
    def __init__(self):
        self.pipe = None
        self.cpu_offload = None

    def generate(self, request, images, output, step_callback=None):
        import inspect
        import torch
        from diffusers import QwenImage21Pipeline

        cpu_offload = request.get("cpu_offload", True)

        if self.pipe is None or (self.cpu_offload is not None and self.cpu_offload != cpu_offload):
            if not torch.cuda.is_available():
                raise RuntimeError("CUDA is unavailable. Run with the project's CUDA-enabled venv.")
            if self.pipe is not None:
                del self.pipe
                self.pipe = None
                gc.collect()
                if hasattr(torch.cuda, "empty_cache"):
                    torch.cuda.empty_cache()
            pipe = QwenImage21Pipeline.from_pretrained(
                os.environ.get("QWEN_MODEL_PATH", "Qwen/Qwen-Image-2.1"),
                torch_dtype=torch.bfloat16,
                local_files_only=True,
            )
            if cpu_offload:
                pipe.enable_model_cpu_offload()
            else:
                pipe.to("cuda")
            self.pipe = pipe
            self.cpu_offload = cpu_offload

        prompt = request["prompt"]
        if request.get("transparent"):
            prompt = ("This is an RGBA image with transparency. " + prompt
                      + ". The image has alpha channel and the background is transparent.")
        kwargs = dict(prompt=prompt, width=request["width"], height=request["height"],
                      num_inference_steps=request["steps"],
                      generator=torch.Generator("cuda").manual_seed(request["seed"]))
        if images:
            kwargs["image"] = images

        if step_callback is not None:
            try:
                sig = inspect.signature(self.pipe.__call__).parameters
                if "callback_on_step_end" in sig:
                    def _step_end_cb(pipe, step, timestep, callback_kwargs):
                        try:
                            step_callback(step + 1, request["steps"])
                        except Exception:
                            pass
                        return callback_kwargs
                    kwargs["callback_on_step_end"] = _step_end_cb
                elif "callback" in sig:
                    def _classic_cb(step, timestep, latents):
                        try:
                            step_callback(step + 1, request["steps"])
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
                try:
                    result = self.pipe(**kwargs).images[0]
                except TypeError as t_err:
                    if "callback" in str(t_err).lower() and ("callback_on_step_end" in kwargs or "callback" in kwargs):
                        kwargs.pop("callback_on_step_end", None)
                        kwargs.pop("callback", None)
                        kwargs.pop("callback_steps", None)
                        result = self.pipe(**kwargs).images[0]
                    else:
                        raise
        except RuntimeWarning as exc:
            raise RuntimeError(
                "Qwen returned invalid numeric image values. Try the documented 40 steps. "
                "If this persists, check the installed model/runtime; no invalid PNG was saved."
            ) from exc
        result.save(Path(output), format="PNG")
