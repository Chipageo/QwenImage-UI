import base64
import io
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from PIL import Image

from ui_server import State, handler_for, validate, SIZES
from qwen_backend import QwenBackend


def encoded_image(mode="RGBA"):
    buffer = io.BytesIO()
    Image.new(mode, (16, 16)).save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue()).decode()


class FakeBackend:
    pipe = None

    def __init__(self):
        self.calls = []
        self.release = threading.Event()

    def generate(self, request, images, output, step_callback=None):
        self.calls.append((request, [im.mode for im in images]))
        if step_callback:
            step_callback(10, request.get("steps", 40))
        self.release.wait(3)
        if request["prompt"] == "fail":
            raise RuntimeError("Test model failure")
        Image.new("RGBA", (32, 32), (150, 100, 200, 128)).save(output)


class ValidationTests(unittest.TestCase):
    def test_ten_references_preserve_alpha_and_order(self):
        request, images = validate(dict(prompt="edit", images=[encoded_image("RGB"), encoded_image()] * 5))
        self.assertEqual([im.mode for im in images], ["RGB", "RGBA"] * 5)
        self.assertEqual(request["steps"], 40)
        for image in images:
            image.close()

    def test_documented_sizes(self):
        for ratio, size in SIZES.items():
            request, images = validate(dict(prompt="hello", ratio=ratio, seed=0))
            self.assertEqual((request["width"], request["height"]), size)
            self.assertEqual(request["seed"], 0)

    def test_scale_sizes(self):
        req_512, _ = validate(dict(prompt="hello", scale="512", ratio="1:1"))
        self.assertEqual((req_512["width"], req_512["height"]), (512, 512))
        req_1k, _ = validate(dict(prompt="hello", scale="1k", ratio="16:9"))
        self.assertEqual((req_1k["width"], req_1k["height"]), (1376, 768))

    def test_cpu_offload_toggle(self):
        req_default, _ = validate(dict(prompt="test"))
        self.assertTrue(req_default["cpu_offload"])
        req_off, _ = validate(dict(prompt="test", cpu_offload=False))
        self.assertFalse(req_off["cpu_offload"])

    def test_bad_inputs(self):
        cases = [dict(prompt=" "), dict(prompt="x", images=[encoded_image()] * 11),
                 dict(prompt="x", images=["garbage"]), dict(prompt="x", ratio=[]),
                 dict(prompt="x", steps=True), dict(prompt="x", steps=0),
                 dict(prompt="x", seed=-1), dict(prompt="x", seed=1.1),
                 dict(prompt="x", transparent="true"), []]
        for data in cases:
            with self.subTest(data=str(data)[:100]), self.assertRaises(ValueError):
                validate(data)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = FakeBackend()
        self.state = State(self.backend, self.temp.name)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.state))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.backend.release.set()
        deadline = time.time() + 5
        while self.state.busy and time.time() < deadline:
            time.sleep(.01)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def call(self, path, data=None, headers=None):
        req_headers = {"Content-Type": "application/json", "X-Qwen-Token": self.state.token}
        req_headers.update(headers or {})
        request = urllib.request.Request(self.url + path, None if data is None else json.dumps(data).encode(), req_headers)
        try:
            response = urllib.request.urlopen(request)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            body = response.read()
            return response.status, json.loads(body) if "application/json" in response.headers.get("Content-Type", "") else body

    def wait_job(self, job):
        for _ in range(100):
            status, result = self.call('/api/jobs/' + job['id'])
            if result['status'] != 'running':
                return result
            time.sleep(.01)
        self.fail("Job did not finish")

    def test_generation_edit_download_and_busy(self):
        self.assertEqual(self.call('/')[0], 200)
        self.assertIn('token', self.call('/api/config')[1])
        status, job = self.call('/api/jobs', dict(prompt='edit', images=[encoded_image()], seed=42,
                                                use_kv_cache=False, vae_tiling=True, attention_mode='standard'))
        self.assertEqual(status, 202)
        self.assertEqual(self.call('/api/jobs', dict(prompt='other'))[0], 409)
        self.backend.release.set()
        result = self.wait_job(job)
        self.assertEqual(result['status'], 'complete')
        status, png = self.call(result['url'])
        self.assertEqual(status, 200)
        self.assertEqual(Image.open(io.BytesIO(png)).mode, 'RGBA')
        self.assertEqual(self.backend.calls[0][1], ['RGBA'])
        self.assertFalse(self.backend.calls[0][0]['use_kv_cache'])
        self.assertTrue(result['settings']['vae_tiling'])
        self.assertEqual(result['settings']['attention_mode'], 'standard')
        self.assertEqual(result['seed'], 42)
        self.assertIn('generation_time', result)
        self.assertIn('duration', result)
        self.assertIn('generation_time_formatted', result)
        self.assertGreaterEqual(result['generation_time'], 0)
        self.assertTrue(result['generation_time_formatted'].endswith('s'))

    def test_failure_releases_model_for_retry(self):
        self.backend.release.set()
        status, job = self.call('/api/jobs', dict(prompt='fail'))
        self.assertEqual(self.wait_job(job)['status'], 'failed')
        status, job = self.call('/api/jobs', dict(prompt='retry'))
        self.assertEqual(status, 202)
        self.assertEqual(self.wait_job(job)['status'], 'complete')

    def test_validation_and_local_boundary(self):
        self.assertEqual(self.call('/api/jobs', dict(prompt='x'), {'X-Qwen-Token':'wrong'})[0], 403)
        self.assertEqual(self.call('/api/config', headers={'Host':'evil.example'})[0], 403)
        self.assertEqual(self.call('/api/jobs', dict(prompt='x'), {'Origin':'https://evil.example'})[0], 403)
        self.assertEqual(self.call('/api/jobs', dict(prompt=''))[0], 400)
        self.assertEqual(self.call('/outputs/../test_qwen.py')[0], 404)
        self.assertEqual(self.call('/test_qwen.py')[0], 404)
        self.assertEqual(self.call('/api/jobs/missing')[0], 404)

    def test_heartbeat_and_shutdown(self):
        status, res = self.call('/api/heartbeat', {})
        self.assertEqual(status, 200)
        self.assertEqual(res.get('status'), 'ok')
        status, bad = self.call('/api/heartbeat', {}, headers={'X-Qwen-Token': 'wrong'})
        self.assertEqual(status, 403)

    def test_hardware_stats_endpoint(self):
        status, res = self.call('/api/stats')
        self.assertEqual(status, 200)
        self.assertIn('gpu', res)
        self.assertIn('cpu', res)
        self.assertIn('ram', res)

    def test_job_progress_tracking(self):
        status, job = self.call('/api/jobs', dict(prompt='progress-test', steps=40))
        self.assertEqual(status, 202)
        self.assertIn('progress', job)
        self.assertIn('steps', job)
        self.backend.release.set()
        done = self.wait_job(job)
        self.assertEqual(done['status'], 'complete')
        self.assertEqual(done['progress'], 100)

    def test_open_system_image(self):
        with patch('os.startfile', create=True) as mock_startfile:
            # Test valid file opening
            filename = 'a' * 32 + '.png'
            test_file = self.state.output_dir / filename
            test_file.write_bytes(b'dummy')
            status, res = self.call(f'/api/open/{filename}')
            self.assertEqual(status, 200)
            self.assertEqual(res.get('status'), 'opened')
            mock_startfile.assert_called_once_with(str(test_file))

            # Test missing file
            status, res = self.call('/api/open/' + 'b' * 32 + '.png')
            self.assertEqual(status, 404)

            # Test invalid filename format (path traversal attempt)
            status, res = self.call('/api/open/evil.png')
            self.assertEqual(status, 404)


class AdapterTests(unittest.TestCase):
    def test_invalid_numeric_output_is_not_saved_as_success(self):
        import contextlib
        import warnings
        def invalid_pipe(**kwargs):
            warnings.warn('invalid value encountered in cast', RuntimeWarning)
            return SimpleNamespace(images=[Image.new('RGBA', (8, 8))])
        torch = SimpleNamespace(inference_mode=contextlib.nullcontext,
                                Generator=lambda device: SimpleNamespace(manual_seed=lambda seed: seed))
        diffusers = SimpleNamespace(QwenImage21Pipeline=None)
        with tempfile.TemporaryDirectory() as tmp, patch.dict('sys.modules', torch=torch, diffusers=diffusers):
            backend = QwenBackend()
            backend.pipe = invalid_pipe
            request, images = validate(dict(prompt='test'))
            output = Path(tmp) / 'invalid.png'
            with self.assertRaisesRegex(RuntimeError, 'invalid numeric'):
                backend.generate(request, images, output)
            self.assertFalse(output.exists())

    def test_load_once_and_documented_call_arguments(self):
        calls, loads = [], []
        class Pipe:
            def enable_model_cpu_offload(self):
                loads.append('offload')
            def __call__(self, **kwargs):
                calls.append(kwargs)
                return SimpleNamespace(images=[Image.new('RGBA', (8, 8))])
        def load(*args, **kwargs):
            loads.append((args, kwargs))
            return Pipe()
        class Generator:
            def __init__(self, device):
                self.device = device
            def manual_seed(self, seed):
                self.seed = seed
                return self
        import contextlib
        torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True), bfloat16='bfloat16',
                                Generator=Generator, inference_mode=contextlib.nullcontext)
        diffusers = SimpleNamespace(QwenImage21Pipeline=SimpleNamespace(from_pretrained=load))
        with tempfile.TemporaryDirectory() as tmp, patch.dict('sys.modules', torch=torch, diffusers=diffusers):
            backend = QwenBackend()
            request, images = validate(dict(prompt='a cutout', transparent=True, seed=7))
            backend.generate(request, images, Path(tmp) / 'one.png')
            request['transparent'] = False
            images = [Image.new('RGBA', (8, 8))]
            backend.generate(request, images, Path(tmp) / 'two.png')
        self.assertEqual(len(loads), 2)
        self.assertTrue(loads[0][1]['local_files_only'])
        self.assertNotIn('image', calls[0])
        self.assertIn('RGBA image with transparency', calls[0]['prompt'])
        self.assertEqual(calls[1]['image'], images)
        self.assertEqual(calls[1]['generator'].seed, 7)
        self.assertEqual(set(calls[1]), {'prompt','width','height','num_inference_steps','generator','image'})


if __name__ == '__main__':
    unittest.main()
