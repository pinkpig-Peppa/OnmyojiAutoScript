"""Offline security regression tests: pickle-free RPC codec, WebUI auth, shell=False, and path guards."""
import ast
from pathlib import Path
import pickle
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from deploy.config import ConfigModel as DeployConfigModel
from deploy.emulator import EmulatorConnect
from module.base.array_codec import decode_ndarray, encode_ndarray
from module.server.config_manager import safe_config_path
from module.server.setting import State
from module.server.updater import Updater

ROOT = Path(__file__).resolve().parents[1]


class SecurityHardeningTests(unittest.TestCase):
    def test_array_codec_roundtrip_and_rejects_pickle_or_malformed_payloads(self):
        for dtype in (np.uint8, np.int16, np.float32):
            original = np.arange(720 * 1280 * 3, dtype=np.uint32).reshape((720, 1280, 3)).astype(dtype)
            # Test non-contiguous slice too
            sliced = original[::2, ::2, :]
            encoded = encode_ndarray(sliced)
            decoded = decode_ndarray(encoded)
            self.assertTrue(np.array_equal(sliced, decoded))
            self.assertEqual(decoded.dtype, sliced.dtype)

        # Reject any pickle payload (including crafted RCE payloads)
        malicious_pickle = pickle.dumps(np.zeros((4, 4, 3), dtype=np.uint8), protocol=4)
        with self.assertRaises(ValueError):
            decode_ndarray(malicious_pickle)

        # Reject object arrays
        obj_arr = np.array([{'a': 1}], dtype=object)
        with self.assertRaises(ValueError):
            encode_ndarray(obj_arr)

        # Reject truncated or oversized payloads
        valid = encode_ndarray(np.zeros((10, 10, 3), dtype=np.uint8))
        with self.assertRaises(ValueError):
            decode_ndarray(valid[:-1])
        with self.assertRaises(ValueError):
            decode_ndarray(valid, max_bytes=32)

    def test_rpc_modules_contain_zero_pickle_imports_or_calls(self):
        for rel in ('module/ocr/rpc.py', 'module/image/rpc.py', 'module/image/runtime.py'):
            source = (ROOT / rel).read_text(encoding='utf-8')
            tree = ast.parse(source, filename=rel)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertNotIn('pickle', [alias.name for alias in node.names], f'pickle imported in {rel}')
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotEqual(node.module, 'pickle', f'from pickle import in {rel}')

    def test_rpc_servers_bind_loopback_by_default_and_respect_remote_config(self):
        from module.image import rpc as image_rpc
        from module.ocr import rpc as ocr_rpc

        fake_proc = Mock()
        fake_proc.is_alive.return_value = True
        with patch.object(ocr_rpc, '_is_port_in_use', side_effect=[False, True]), patch.object(
            ocr_rpc, '_OCR_SERVER_PROCESS', None
        ), patch.object(ocr_rpc.multiprocessing, 'Process', return_value=fake_proc) as mp_proc:
            fake_state = SimpleNamespace(
                deploy_config=SimpleNamespace(
                    StartOcrServer=True,
                    OcrServerPort=22268,
                    OcrClientAddress='127.0.0.1:22268',
                    OcrServerWorkerCount=1,
                )
            )
            with patch('module.server.setting.State', fake_state):
                self.assertTrue(ocr_rpc.ensure_ocr_server_started())
                self.assertEqual(mp_proc.call_args.kwargs['args'][0], '127.0.0.1')

        with patch.object(image_rpc, '_is_port_in_use', side_effect=[False, True]), patch.object(
            image_rpc, '_IMAGE_SERVER_PROCESS', None
        ), patch.object(image_rpc._IMAGE_SERVER_CONTEXT, 'Process', return_value=fake_proc) as img_proc:
            fake_state = SimpleNamespace(
                deploy_config=SimpleNamespace(
                    StartImageServer=True,
                    ImageServerPort=22269,
                    ImageClientAddress='127.0.0.1:22269',
                    ImageFrameCacheExpireSeconds=3.0,
                    ImageFrameCacheMaxCount=24,
                    ImageTemplateCacheExpireSeconds=3600,
                    ImageTemplateCacheMaxCount=200,
                    ImageServerWorkerCount=1,
                )
            )
            with patch('module.server.setting.State', fake_state):
                self.assertTrue(image_rpc.ensure_image_server_started())
                self.assertEqual(img_proc.call_args.kwargs['args'][0], '127.0.0.1')

    def test_webui_defaults_to_loopback_and_blocks_unauthenticated_lan_access(self):
        self.assertEqual(DeployConfigModel.WebuiHost, '127.0.0.1')
        previous_key = State.webui_key
        try:
            State.webui_key = ''
            self.assertTrue(State.check_webui_key(None, client_host='127.0.0.1'))
            self.assertTrue(State.check_webui_key(None, client_host='::1'))
            self.assertFalse(State.check_webui_key(None, client_host='192.168.1.88'))

            State.webui_key = 's3cr3t-token'
            self.assertFalse(State.check_webui_key(None, client_host='127.0.0.1'))
            self.assertFalse(State.check_webui_key('wrong', client_host='127.0.0.1'))
            self.assertTrue(State.check_webui_key('s3cr3t-token', client_host='192.168.1.88'))
        finally:
            State.webui_key = previous_key

    def test_updater_and_emulator_execute_with_shell_false(self):
        updater = Updater.__new__(Updater)
        updater.config = {'Branch': 'master'}
        updater.write = Mock()
        updater.git = 'C:/Git/bin/git.exe'
        updater.Branch = 'master'
        with patch('module.server.updater.subprocess.run') as mock_run:
            mock_run.return_value = SimpleNamespace(stdout='deadbeef---dev---2026-11-28---msg', returncode=0)
            sha1, author, _, msg = updater.get_commit(short_sha1=True)
            self.assertEqual((sha1, author, msg), ('deadbeef', 'dev', 'msg'))
            self.assertFalse(mock_run.call_args.kwargs['shell'])
            self.assertIsInstance(mock_run.call_args.args[0], list)

        # Reject option injection or shell metacharacters in Branch / revision
        updater.Branch = '--upload-pack=evil'
        with self.assertRaises(ValueError):
            updater.check_update()
        with self.assertRaises(ValueError):
            updater.get_commit(revision='--output=/tmp/pwn')
        with self.assertRaises(ValueError):
            updater.execute_output('git status %TEMP%')

        conn = EmulatorConnect(adb='adb.exe')
        fake_popen = Mock()
        fake_popen.communicate.return_value = (b'List of devices attached\n', b'')
        fake_popen.returncode = 0
        with patch('deploy.emulator.subprocess.Popen', return_value=fake_popen) as popen:
            self.assertEqual(conn._execute(['adb.exe', 'connect', '127.0.0.1:16384'], output=False), 0)
            self.assertFalse(popen.call_args.kwargs['shell'])
            self.assertEqual(popen.call_args.kwargs['stdout'], subprocess.DEVNULL)
            self.assertNotIn('>nul', popen.call_args.args[0])

    def test_autocheckin_tls_enabled_and_safe_config_path_enforced(self):
        source = (ROOT / 'tasks/AutoCheckinBigGod/script_task.py').read_text(encoding='utf-8')
        self.assertNotIn('verify = False', source)
        self.assertNotIn('disable_warnings()', source)

        for bad in ('../secret', '..\\secret', 'a/b', 'CON', ''):
            with self.assertRaises(ValueError):
                safe_config_path(bad)


if __name__ == '__main__':
    unittest.main()
