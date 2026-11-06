"""Regression tests for path traversal and generated-code injection fixes."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from dev_tools.assets_extract import safe_identifier, safe_str
from module.server.config_manager import ConfigManager


class ConfigNameValidationTests(unittest.TestCase):
    def test_rejects_path_traversal_names(self):
        for name in ('../escaped', 'a/b', '..', '', 'a.json', '.hidden', 'x' * 65):
            with self.assertRaises(ValueError):
                ConfigManager.validate_script_name(name)

    def test_accepts_normal_names(self):
        for name in ('oas1', 'oas_2', 'a-b'):
            self.assertEqual(ConfigManager.validate_script_name(name), name)

    def test_copy_rejects_traversal_without_creating_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / 'work'
            (work / 'config').mkdir(parents=True)
            (work / 'config' / 'template.json').write_text('{}', encoding='utf-8')
            cwd = os.getcwd()
            try:
                os.chdir(work)
                with self.assertRaises(ValueError):
                    ConfigManager.copy(file='../escaped')
                self.assertFalse((Path(tmp) / 'escaped.json').exists())
                self.assertFalse((work / 'config' / 'escaped.json').exists())
            finally:
                os.chdir(cwd)

    def test_rename_and_delete_reject_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / 'work'
            (work / 'config').mkdir(parents=True)
            (work / 'config' / 'oas1.json').write_text('{}', encoding='utf-8')
            outside = Path(tmp) / 'escaped.json'
            outside.write_text('{}', encoding='utf-8')
            cwd = os.getcwd()
            try:
                os.chdir(work)
                with self.assertRaises(ValueError):
                    ConfigManager.rename('oas1', '../escaped')
                with self.assertRaises(ValueError):
                    ConfigManager.delete('../escaped')
                self.assertTrue(outside.exists())
                self.assertTrue((work / 'config' / 'oas1.json').exists())
            finally:
                os.chdir(cwd)


class AssetGeneratorInjectionTests(unittest.TestCase):
    def test_identifier_is_sanitized(self):
        result = safe_identifier('x = 1\nimport os')
        self.assertTrue(result.isidentifier(), result)
        self.assertNotIn(' ', result)
        self.assertNotIn('\n', result)
        self.assertEqual(safe_identifier('normal_name'), 'NORMAL_NAME')
        self.assertEqual(safe_identifier('1abc'), '_1ABC')

    def test_string_escapes_quotes_and_newlines(self):
        payload = 'a")\nimport os; os.system("x")\n#\n'
        literal = safe_str(payload)
        self.assertTrue(literal.startswith('"') and literal.endswith('"'))
        self.assertNotIn('\n', literal)
        self.assertEqual(json.loads(literal), payload)


class DeviceInstanceStateTests(unittest.TestCase):
    def test_mutable_state_not_shared_at_class_level(self):
        from module.device.device import Device
        for attr in ('detect_record', 'click_record', 'stuck_timer', 'stuck_timer_long'):
            self.assertNotIn(attr, Device.__dict__, f'{attr} must be per-instance state')


if __name__ == '__main__':
    unittest.main()
