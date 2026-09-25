import contextlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
from qwen_backend import QwenBackend
from ui_server import validate


class PerformanceTests(unittest.TestCase):
    def test_options_validation(self):
        for key, value in [('attention_mode', 'turbo'), ('use_kv_cache', 1), ('vae_tiling', 'yes')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate(dict(prompt='test', **{key: value}))

    def environment(self, fail=False):
        self.loads, self.calls, self.events = [], [], []
        outer = self
        class Pipe:
            def __init__(self):
                self.vae = SimpleNamespace(use_tiling=False)
                self.vae.enable_tiling = lambda: setattr(self.vae, 'use_tiling', True)
                self.transformer = SimpleNamespace(compile=lambda: outer.events.append('compile'),
                    set_attn_processor=lambda p: outer.events.append('flex'))
            def enable_model_cpu_offload(self):
                outer.events.append('offload')
            def __call__(self, callback_on_step_end=None, **kwargs):
                outer.calls.append(kwargs)
                if fail:
                    raise RuntimeError('compiler failed')
                for step in range(kwargs['num_inference_steps']):
                    callback_on_step_end(self, step, 0, {})
                return SimpleNamespace(images=[Image.new('RGB', (8, 8))])
        def load(*args, **kwargs):
            pipe = Pipe(); self.loads.append(pipe); return pipe
        cuda = SimpleNamespace(is_available=lambda: True, empty_cache=lambda: None,
            synchronize=lambda: None, reset_peak_memory_stats=lambda: None,
            max_memory_allocated=lambda: 2 * 1024**3,
            get_device_properties=lambda n: SimpleNamespace(total_memory=24 * 1024**3))
        torch = SimpleNamespace(cuda=cuda, bfloat16='bf16', inference_mode=contextlib.nullcontext,
            Generator=lambda device: SimpleNamespace(manual_seed=lambda seed: seed))
        return patch.dict('sys.modules', torch=torch,
            diffusers=SimpleNamespace(QwenImage21Pipeline=SimpleNamespace(from_pretrained=load)),
            **{'diffusers.models.transformers.transformer_qwenimage21': SimpleNamespace(QwenImage21FlexAttnProcessor=lambda: object())})

    def test_cache_tiling_metrics_and_reuse(self):
        with self.environment(), tempfile.TemporaryDirectory() as tmp:
            backend = QwenBackend()
            req, _ = validate(dict(prompt='test', steps=2, use_kv_cache=False, vae_tiling=True))
            backend.generate(req, [], Path(tmp)/'a.png')
            self.assertFalse(self.calls[0]['use_kv_cache'])
            self.assertTrue(backend.pipe.vae.use_tiling)
            self.assertEqual(backend.last_metrics['peak_vram_gib'], 2)
            self.assertIn('first_step_s', backend.last_metrics)
            req.update(use_kv_cache=True, vae_tiling=False)
            backend.generate(req, [], Path(tmp)/'b.png')
            self.assertFalse(backend.pipe.vae.use_tiling)
            self.assertNotIn('use_kv_cache', self.calls[1])
            self.assertEqual(len(self.loads), 1)
            self.assertFalse(backend.last_metrics['reloaded'])

    def test_switch_compute_mode_reloads_and_flex_is_compiled(self):
        with self.environment(), patch('qwen_backend.acceleration_support', return_value={'available': True}), tempfile.TemporaryDirectory() as tmp:
            backend = QwenBackend()
            req, _ = validate(dict(prompt='test', steps=1))
            for mode in ['standard', 'compiled', 'flex', 'standard']:
                req['attention_mode'] = mode
                backend.generate(req, [], Path(tmp)/'a.png')
            self.assertEqual(len(self.loads), 4)
            self.assertEqual(self.events, ['offload', 'compile', 'offload', 'flex', 'compile', 'offload', 'offload'])

    def test_unavailable_compiler_preserves_loaded_model(self):
        with self.environment(), patch('qwen_backend.acceleration_support', return_value={'available': False, 'reason': 'Triton missing'}):
            backend = QwenBackend(); backend.pipe = sentinel = object()
            req, _ = validate(dict(prompt='test', attention_mode='flex'))
            with self.assertRaisesRegex(RuntimeError, 'Triton missing'):
                backend.generate(req, [], 'unused.png')
            self.assertIs(backend.pipe, sentinel)

    def test_full_gpu_rejected_before_loading_on_24gb(self):
        with self.environment():
            backend = QwenBackend()
            req, _ = validate(dict(prompt='test', cpu_offload=False))
            with self.assertRaisesRegex(RuntimeError, 'does not fit'):
                backend.generate(req, [], 'unused.png')
            self.assertEqual(self.loads, [])

    def test_compile_failure_clears_pipeline_for_retry(self):
        with self.environment(fail=True), patch('qwen_backend.acceleration_support', return_value={'available': True}):
            backend = QwenBackend()
            req, _ = validate(dict(prompt='test', attention_mode='compiled'))
            with self.assertRaisesRegex(RuntimeError, 'Select Standard'):
                backend.generate(req, [], 'unused.png')
            self.assertIsNone(backend.pipe)

if __name__ == '__main__':
    unittest.main()
