"""Offline response-budget, background-process, and repeat-policy regressions."""
import ast
from collections import deque
from contextlib import contextmanager
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from module.base.timer import Timer
from module.device.click_verification import ClickResponseUnchanged, before_click
from module.device.performance import PerformanceProfile
from module.device.repeat_policy import chess_repeat_unrestricted
from module.exception import GameNotRunningError, GameStuckError, GameTooManyClickError, TaskRecoveryFailed

ROOT = Path(__file__).resolve().parents[1]


def load_method(path, cls, name, ns):
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    method = next(n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == name)
    method.decorator_list = []
    exec(compile(ast.Module(body=[method], type_ignores=[]), path, 'exec'), ns)
    return ns[name]


def device(low=False):
    ns = dict(
        deque=deque,
        Timer=Timer,
        PerformanceProfile=PerformanceProfile,
        contextmanager=contextmanager,
        time=time,
        logger=Mock(),
        IS_WINDOWS=False,
        get_color=lambda image, area: (0, 0, 0),
        GameStuckError=GameStuckError,
        GameNotRunningError=GameNotRunningError,
        GameTooManyClickError=GameTooManyClickError,
        TaskRecoveryFailed=TaskRecoveryFailed,
    )

    class Parent:
        is_desktop = False

        def __init__(self, config):
            self.config = config

        def screenshot_interval_set(self):
            pass

    for name in ('DesktopDevice', 'Screenshot', 'Control', 'AppControl'):
        ns[name] = type(name, (), {})
    ns['Platform'] = Parent
    tree = ast.parse((ROOT / 'module/device/device.py').read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Device')
    exec(compile(ast.Module(body=[cls], type_ignores=[]), 'device.py', 'exec'), ns)
    d = ns['Device'](
        SimpleNamespace(
            script=SimpleNamespace(
                device=SimpleNamespace(
                    low_spec_mode=low,
                    screenshot_method='ADB',
                    emulatorinfo_type='MuMuPlayer12',
                )
            )
        )
    )
    d.press_escape = Mock()
    d.app_is_running = lambda: True
    return d


class LowSpecAndRepeatPolicyTests(unittest.TestCase):
    def test_profiles_default_and_low(self):
        normal, low = PerformanceProfile(), PerformanceProfile(True)
        self.assertEqual(normal.timeout(60), 60)
        self.assertEqual(low.timeout(60), 180)
        self.assertEqual(low.timeout(300), 900)
        self.assertEqual(low.timeout(15), 45)
        self.assertEqual(low.screenshot_interval(0.1), 0.8)
        self.assertEqual(low.screenshot_interval(1, True), 1.5)
        self.assertEqual(low.screenshot_interval(3), 3)
        self.assertEqual(normal.click_interval, 0)
        self.assertEqual(low.click_interval, 1.2)

    def test_slow_idle_still_eventually_fails(self):
        for low, budget in [(False, 60), (True, 180)]:
            d = device(low)
            with patch('time.time', return_value=1000):
                d.stuck_record_clear()
            d.stuck_timer._reach_count = 1000
            d.stuck_timer_long._reach_count = 1000
            with patch('time.time', return_value=1000 + budget - 1):
                self.assertFalse(d.stuck_record_check())
            with patch('time.time', return_value=1000 + budget + 1):
                self.assertFalse(d.stuck_record_check())
                d.press_escape.assert_called_once()

    def test_long_wait_stays_at_300_seconds_in_both_modes(self):
        for low in (False, True):
            d = device(low)
            self.assertEqual(d.stuck_timer_long.limit, 300)
            with patch('time.time', return_value=1000):
                d.stuck_record_clear()
            d.stuck_record_add('BATTLE_STATUS_S')
            d.stuck_timer._reach_count = 1000
            d.stuck_timer_long._reach_count = 1000
            with patch('time.time', return_value=1299):
                self.assertFalse(d.stuck_record_check())
            with patch('time.time', return_value=1301):
                self.assertFalse(d.stuck_record_check())
                d.press_escape.assert_called_once()

    def test_login_can_wait_past_battle_budget(self):
        d = device(True)
        with patch('time.monotonic', return_value=100), patch('time.time', return_value=1000):
            with d.login_wait():
                d.stuck_timer._reach_count = 1000
                d.stuck_timer_long._reach_count = 1000
                with patch('time.time', return_value=1400), patch('time.monotonic', return_value=500):
                    self.assertFalse(d.stuck_record_check())
                with patch('time.monotonic', return_value=1000):
                    self.assertFalse(d.stuck_record_check())
                    d.press_escape.assert_called_once()

    def test_device_state_is_independent(self):
        a, b = device(True), device(False)
        a.click_record_add('A')
        a.stuck_record_add('BATTLE_STATUS_S')
        self.assertEqual(list(b.click_record), [])
        self.assertEqual(b.detect_record, set())
        self.assertIsNot(a.stuck_timer, b.stuck_timer)
        self.assertIsNot(a._screenshot_interval, b._screenshot_interval)

    def test_login_marker_survives_click_and_deadline_does_not_reset(self):
        d = device(True)
        with patch('time.monotonic', return_value=100), patch('time.sleep'):
            with d.login_wait():
                deadline = d._login_deadline
                for _ in range(d.performance.click_limit - 1):
                    d.handle_control_check('Skip animation')
                self.assertFalse(d.handle_control_check('Skip animation'))
                self.assertIn('LOGIN_CHECK', d.detect_record)
                self.assertEqual(d._login_deadline, deadline)
                with patch('time.monotonic', return_value=deadline):
                    self.assertFalse(d.stuck_record_check())
                    d.press_escape.assert_called_once()
                    self.assertFalse(d.handle_control_check('Skip animation'))
        self.assertIsNone(d._login_deadline)
        self.assertFalse(d.detect_record)
        self.assertFalse(d.click_record)

    def test_login_exception_cleans_up(self):
        d = device(True)
        with self.assertRaises(ValueError):
            with d.login_wait():
                raise ValueError('recognition failed')
        self.assertIsNone(d._login_deadline)
        self.assertFalse(d.detect_record)

    def test_repeat_and_alternating_click_protection(self):
        for low in (False, True):
            d = device(low)
            limit = d.performance.click_limit
            for _ in range(limit - 1):
                d.click_record_add('A')
                d.click_record_check()
            d.click_record_add('A')
            with self.assertRaises(GameTooManyClickError):
                d.click_record_check()

        d_alt = device(True)
        alt_limit = d_alt.performance.alternating_click_limit
        with patch('time.monotonic', return_value=100), patch('time.sleep'):
            for button in ('A', 'B') * (alt_limit - 1) + ('A',):
                self.assertTrue(d_alt.handle_control_check(button))
            self.assertFalse(d_alt.handle_control_check('B'))
        self.assertIn('between 2 buttons', d_alt._click_recovery_reason)
        self.assertIsNotNone(d_alt._click_recovery_at)

    def test_action_pacing_only_low_spec(self):
        for low in (False, True):
            d = device(low)
            with patch('time.monotonic', return_value=100), patch('time.sleep') as sleep:
                d.handle_control_check('A')
                d.handle_control_check('B')
                if low:
                    sleep.assert_called_once_with(1.2)
                else:
                    sleep.assert_not_called()

    def test_screenshot_backend_overrides_and_config_preserved(self):
        fn = load_method(
            'module/device/screenshot.py',
            'Screenshot',
            'screenshot_interval_set',
            dict(logger=Mock(), limit_in=lambda v, lo, hi: max(lo, min(hi, v)), ScriptError=RuntimeError),
        )
        for method in ('ADB', 'scrcpy', 'nemu_ipc'):
            for low in (False, True):
                opt = SimpleNamespace(screenshot_interval=0.3, combat_screenshot_interval=1.0)
                d = SimpleNamespace(
                    is_desktop=False,
                    performance=PerformanceProfile(low),
                    _screenshot_interval=Timer(0.1),
                    config=SimpleNamespace(
                        Emulator_ScreenshotMethod=method,
                        script=SimpleNamespace(
                            optimization=opt,
                            device=SimpleNamespace(screenshot_method=method),
                        ),
                    ),
                )
                fn(d)
                expected = 0.8 if low else (0.1 if method == 'scrcpy' else 0.2 if method == 'nemu_ipc' else 0.3)
                self.assertEqual(d._screenshot_interval.limit, expected)
                fn(d, 'combat')
                self.assertEqual(d._screenshot_interval.limit, 1.5 if low else 0.1 if method == 'scrcpy' else 1.0)
                self.assertEqual(opt.screenshot_interval, 0.2 if method == 'nemu_ipc' else 0.3)
                self.assertEqual(opt.combat_screenshot_interval, 1.0)

    def test_background_adb_no_console(self):
        fn = load_method(
            'module/device/connection.py',
            'Connection',
            'adb_command',
            dict(subprocess=subprocess, logger=Mock()),
        )
        process = Mock()
        process.communicate.return_value = (b'ok', None)
        with patch.object(subprocess, 'Popen', return_value=process) as popen:
            self.assertEqual(fn(SimpleNamespace(adb_binary='adb.exe', serial='test'), ['devices']), b'ok')
            self.assertEqual(popen.call_args.kwargs['creationflags'], getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertFalse(popen.call_args.kwargs['shell'])

    def test_startup_probe_uses_extended_budget(self):
        d = device(True)
        d.screenshot_adb = lambda: 'black'
        d.screenshot_methods = {'ADB': d.screenshot_adb}
        clock = [1000]
        with patch('time.monotonic', side_effect=lambda: clock[0]), patch(
            'time.sleep', side_effect=lambda n: clock.__setitem__(0, clock[0] + n)
        ):
            d.wait_app_start_ready()
        self.assertEqual(clock[0], 1045)

    def test_chess_repeat_policy_scoped_strictly_to_active_chess_guard(self):
        d = device(False)
        d.image = np.full((720, 1280, 3), 80, np.uint8)
        d.screenshot = lambda: d.image
        self.assertFalse(chess_repeat_unrestricted(d))

        # Active Chess guard allows repeated identical-region clicks without ClickResponseUnchanged
        d._task_flow_guard = SimpleNamespace(_entered=True, device=d, command='Chess')
        self.assertTrue(chess_repeat_unrestricted(d))
        sig = before_click(d, 200, 200, 'BET')
        d._verified_click = dict(name='BET', x=200, y=200, before=sig, changed=False, confirm_retry_used=False)
        before_click(d, 200, 200, 'BET')
        for _ in range(15):
            d.click_record_add('BET')
        d.click_record_check()

        # Friend invitation handling during Chess must NOT bypass repeat checks
        d._handling_invitation = True
        self.assertFalse(chess_repeat_unrestricted(d))
        with patch('module.device.click_verification.time.monotonic', side_effect=[0.0, 9.0]):
            with self.assertRaises(ClickResponseUnchanged):
                before_click(d, 200, 200, 'BET')


if __name__ == '__main__':
    unittest.main()
