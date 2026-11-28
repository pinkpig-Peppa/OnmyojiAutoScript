"""Offline unit tests for bounded ESC recovery, desktop/emulator routing, and failed-task recovery."""

from collections import deque
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
from types import ModuleType, SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from module.base.timer import Timer
from module.device.control import Control
from module.device.device import Device
from module.device.escape_popup import battle_exit_confirm_point, game_exit_cancel_point
from module.exception import GameNotRunningError, GameTooManyClickError, TaskRecoveryFailed
import module.script.failed_task_recovery as recovery
from module.script.task_completion import TaskCompletionGate
from script import Script
from tasks.Component.escape_recovery import handle_escape_recovery
from tasks.GameUi.navigator import GameUi
from tasks.GameUi.recovery_exit import ASSETS as RECOVERY_EXIT_ASSETS, click_exit, exit_point


ROOT = Path(__file__).resolve().parents[1]


class EscapePopupAndRecoveryExitTests(unittest.TestCase):
    def test_exit_game_dialog_cancel_requires_white_panel_and_both_teal_buttons(self):
        frame = np.zeros((720, 1280, 3), np.uint8)
        frame[239:481, 312:968] = 255
        frame[430:450, 785:820] = (0, 130, 130)
        frame[430:450, 880:915] = (0, 130, 130)
        point = game_exit_cancel_point(frame)
        self.assertIsNotNone(point)
        self.assertLess(abs(point[0] - 804), 5)
        self.assertLess(abs(point[1] - 441), 5)
        self.assertIsNone(game_exit_cancel_point(np.zeros((720, 1280, 3), np.uint8)))

        without_buttons = frame.copy()
        without_buttons[410:465, 750:945] = 255
        self.assertIsNone(game_exit_cancel_point(without_buttons))

    def test_battle_exit_dialog_requires_title_and_buttons_across_scales(self):
        asset = ROOT / 'module' / 'device' / 'recovery_assets' / 'exit_battle.png'
        original = cv2.imdecode(np.frombuffer(asset.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        original = cv2.cvtColor(original, cv2.COLOR_BGR2RGB)
        for scale in (1.0, 1.5, 2.0):
            dialog = cv2.resize(original, None, fx=scale, fy=scale)
            h, w = dialog.shape[:2]
            frame = np.zeros((720, 1280, 3), np.uint8)
            frame[180:180 + h, 360:360 + w] = dialog
            point = battle_exit_confirm_point(frame)
            self.assertIsNotNone(point)
            self.assertTrue(360 < point[0] < 360 + w)
            self.assertTrue(180 < point[1] < 180 + h)

            cropped = frame.copy()
            cropped[180 + int(h * 0.62):180 + h, 360:360 + w] = 0
            self.assertIsNone(battle_exit_confirm_point(cropped))

    def _exit_canvas(self, kind: str, x: int = 23, y: int = 15, scale: float = 1.0):
        template = cv2.imdecode(
            np.fromfile(RECOVERY_EXIT_ASSETS / f'recovery_{kind}.png', dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        template = cv2.cvtColor(template, cv2.COLOR_BGR2RGB)
        template = cv2.resize(template, None, fx=scale, fy=scale)
        image = np.full((720, 1280, 3), 65, np.uint8)
        h, w = template.shape[:2]
        image[y:y + h, x:x + w] = template
        return image, (x + w // 2, y + h // 2, kind)

    def test_recovery_exit_matching_and_single_click_observation(self):
        for kind in ('back_arrow', 'close_cross'):
            for scale in (0.75, 1.0, 1.25):
                image, expected = self._exit_canvas(kind, 841, 17, scale)
                self.assertEqual(exit_point(image), expected)

        self.assertIsNone(exit_point(np.full((720, 1280, 3), 65, np.uint8)))

        # Unchanged screen after 1 click -> returns False after 2 fresh screenshots.
        image, point = self._exit_canvas('back_arrow')
        dev = SimpleNamespace(image=image, click=Mock(return_value=True))
        task = SimpleNamespace(device=dev, screenshot=Mock())
        self.assertFalse(click_exit(task))
        dev.click.assert_called_once_with(point[0], point[1], control_name='RECOVERY_EXIT_BACK_ARROW')
        self.assertEqual(task.screenshot.call_count, 2)

        # Changed screen across 2 fresh frames -> returns True.
        image2, _ = self._exit_canvas('close_cross')
        dev2 = SimpleNamespace(image=image2, click=Mock(return_value=True))
        task2 = SimpleNamespace(
            device=dev2,
            screenshot=Mock(side_effect=lambda: setattr(dev2, 'image', np.full(image2.shape, 200, np.uint8))),
        )
        self.assertTrue(click_exit(task2))
        dev2.click.assert_called_once()
        self.assertEqual(task2.screenshot.call_count, 2)


def _make_device_stub(is_desktop: bool = False):
    d = Device.__new__(Device)
    d.config = SimpleNamespace(script=SimpleNamespace(device=SimpleNamespace(control_method='minitouch')))
    d.is_desktop = is_desktop
    d.is_desktop_window = is_desktop
    d.detect_record = {'BATTLE_STATUS_S'}
    d.click_record = deque(maxlen=15)
    d.stuck_timer = Timer(60, count=60).start()
    d.stuck_timer_long = Timer(300, count=300).start()
    d.press_escape = Mock()
    d.app_is_running = Mock(return_value=True)
    d.app_lost_login = Mock(return_value=False)
    d._failed_original_page = 'page_orochi'
    d._failed_original_page_captured = True
    d.reset_task_recovery()
    return d


class DeviceEscapeRecoveryAndDesktopTests(unittest.TestCase):
    def test_three_esc_attempts_then_fail_without_fourth_dispatch(self):
        d = _make_device_stub()
        for attempt in range(3):
            d.recover_by_escape('missing target')
            self.assertEqual(d._escape_attempts, attempt + 1)
            self.assertEqual(d._escape_generation, attempt + 1)
            self.assertTrue(d._await_recovery_frame)
            self.assertIn('BATTLE_STATUS_S', d.detect_record)
        with self.assertRaises(TaskRecoveryFailed):
            d.recover_by_escape('still missing')
        self.assertEqual(d.press_escape.call_count, 3)
        d.reset_task_recovery()
        self.assertEqual(d._escape_attempts, 0)
        self.assertFalse(d._await_recovery_frame)

    def test_stopped_game_or_desktop_lost_login_raises_game_not_running(self):
        d = _make_device_stub(is_desktop=True)
        d.app_lost_login.return_value = True
        with self.assertRaises(GameNotRunningError):
            d.recover_by_escape('stuck')
        d.press_escape.assert_not_called()

        d2 = _make_device_stub(is_desktop=False)
        d2.app_is_running.return_value = False
        with self.assertRaises(GameNotRunningError):
            d2.recover_by_escape('stuck')
        d2.press_escape.assert_not_called()

    def test_press_escape_routes_emulator_to_adb_and_desktop_to_window_message(self):
        for method in ('ADB', 'minitouch', 'uiautomator2', 'window_message'):
            ctrl = Control.__new__(Control)
            ctrl.config = SimpleNamespace(script=SimpleNamespace(device=SimpleNamespace(control_method=method)))
            ctrl.is_desktop = False
            ctrl.is_desktop_window = False
            ctrl.press_escape_window_message = Mock()
            ctrl.adb_shell = Mock(return_value='')
            ctrl.press_escape()
            ctrl.press_escape_window_message.assert_not_called()
            ctrl.adb_shell.assert_called_once_with(['input', 'keyevent', 'KEYCODE_BACK'])

            ctrl.adb_shell = Mock(return_value='Error: device offline')
            with self.assertRaises(RuntimeError):
                ctrl.press_escape()

        desktop_ctrl = Control.__new__(Control)
        desktop_ctrl.is_desktop = True
        desktop_ctrl.is_desktop_window = True
        desktop_ctrl.press_escape_window_message = Mock()
        desktop_ctrl.adb_shell = Mock()
        desktop_ctrl.press_escape()
        desktop_ctrl.press_escape_window_message.assert_called_once()
        desktop_ctrl.adb_shell.assert_not_called()

    def test_repeated_clicks_pause_until_timeout_and_different_button_cancels(self):
        d = _make_device_stub()
        with patch('module.device.device.time.monotonic', return_value=100.0):
            for _ in range(9):
                self.assertTrue(d.handle_control_check('BTN_A'))
            # 10th click triggers GameTooManyClickError -> pauses instead of crashing.
            self.assertFalse(d.handle_control_check('BTN_A'))
            self.assertFalse(d.handle_control_check('BTN_A'))

        with patch('module.device.device.time.monotonic', return_value=159.9):
            d.stuck_record_check()
            d.press_escape.assert_not_called()

        with patch('module.device.device.time.monotonic', return_value=160.0):
            d.stuck_record_check()
            d.press_escape.assert_called_once()
            # Pre-frame inputs remain blocked until a fresh screenshot arrives.
            self.assertFalse(d.handle_control_check('BTN_OTHER'))

        # Different button before 60s cancels pending click recovery.
        d2 = _make_device_stub()
        with patch('module.device.device.time.monotonic', return_value=200.0):
            for _ in range(10):
                d2.handle_control_check('OLD_BTN')
            self.assertIsNotNone(d2._click_recovery_at)
            self.assertTrue(d2.handle_control_check('NEW_BTN'))
            self.assertIsNone(d2._click_recovery_at)
            d2.press_escape.assert_not_called()

    def test_blocked_control_check_prevents_click_long_click_swipe_and_drag(self):
        ctrl = Control.__new__(Control)
        ctrl.config = SimpleNamespace(script=SimpleNamespace(device=SimpleNamespace(control_method='ADB')))
        ctrl.handle_control_check = Mock(return_value=False)
        ctrl.click_adb = Mock()
        ctrl.long_click_adb = Mock()
        ctrl.swipe_adb = Mock()
        self.assertFalse(ctrl.click(10, 20))
        self.assertFalse(ctrl.long_click(10, 20))
        self.assertFalse(ctrl.swipe((10, 20), (200, 220)))
        self.assertFalse(ctrl.drag((10, 20), (200, 220)))
        ctrl.click_adb.assert_not_called()
        ctrl.long_click_adb.assert_not_called()
        ctrl.swipe_adb.assert_not_called()

    def test_navigator_execute_action_drops_stale_pre_escape_action(self):
        ui = GameUi.__new__(GameUi)
        ui.device = SimpleNamespace(_escape_generation=0)
        ui.maybe_screenshot = lambda skip: setattr(ui.device, '_escape_generation', 1)
        self.assertFalse(ui._execute_action(Mock(), skip_first_screenshot=False))


class HandleEscapeRecoveryTests(unittest.TestCase):
    def _make_recovery_task(self, page_key_result=None, multiplier: int = 1):
        state = {'now': 0.0, 'screenshots': 0}

        class FakeGameUi:
            pass

        task = FakeGameUi()
        task.config = SimpleNamespace()
        task.device = SimpleNamespace(
            _escape_generation=1,
            _recovery_handling=False,
            _failed_original_page='result',
            _task_flow_guard=SimpleNamespace(command='ExperienceYoukai'),
            image=np.zeros((720, 1280, 3), np.uint8),
            performance=SimpleNamespace(timeout=lambda v: v * multiplier),
            sleep=Mock(),
            click=Mock(return_value=True),
            stuck_record_clear=Mock(),
            click_record_clear=Mock(),
        )

        def snap():
            state['screenshots'] += 1
            state['now'] += 15.0

        task.device.screenshot = Mock(side_effect=snap)
        task.interval_timer = {'a': 1}
        task.animates = {'b': 1}
        task.navigator = SimpleNamespace(current_page=None, last_enter_success_page_key='old', edge_penalties={'e': 1})
        task._detect_current_page = Mock(
            return_value=(SimpleNamespace(key=page_key_result) if page_key_result else None)
        )
        fake_mod = ModuleType('tasks.GameUi.game_ui')
        fake_mod.GameUi = FakeGameUi
        return task, state, fake_mod

    def test_unknown_page_expires_finitely_and_releases_handling_flag(self):
        task, state, fake_mod = self._make_recovery_task(page_key_result=None)
        with patch.dict(sys.modules, {'tasks.GameUi.game_ui': fake_mod}), \
             patch('tasks.Component.escape_recovery.monotonic', side_effect=lambda: state['now']), \
             patch('tasks.Component.escape_recovery.game_exit_cancel_point', return_value=None), \
             patch('tasks.Component.escape_recovery.battle_exit_confirm_point', return_value=None):
            with self.assertRaises(TaskRecoveryFailed):
                handle_escape_recovery(task)
        self.assertEqual(state['screenshots'], 4)
        self.assertFalse(task.device._recovery_handling)

    def test_same_page_resumes_but_changed_or_main_page_unwinds_business_task(self):
        for page_name, should_raise in (('result', False), ('room', True), ('main', True)):
            task, state, fake_mod = self._make_recovery_task(page_key_result=page_name)
            with patch.dict(sys.modules, {'tasks.GameUi.game_ui': fake_mod}), \
                 patch('tasks.Component.escape_recovery.monotonic', side_effect=lambda: state['now']), \
                 patch('tasks.Component.escape_recovery.game_exit_cancel_point', return_value=None), \
                 patch('tasks.Component.escape_recovery.battle_exit_confirm_point', return_value=None):
                if should_raise:
                    with self.assertRaises(TaskRecoveryFailed):
                        handle_escape_recovery(task)
                else:
                    handle_escape_recovery(task)
                    task.device.stuck_record_clear.assert_called_once()
                    task.device.click_record_clear.assert_called_once()
            self.assertFalse(task.device._recovery_handling)


class FailedTaskRecoveryAndSwitchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.page_path = Path(self.tmp.name) / 'Orochi.page.json'
        self.switch_path = Path(self.tmp.name) / 'switch.json'
        p1 = patch.object(recovery, 'checkpoint', return_value=self.page_path)
        p2 = patch.object(recovery, 'switch_checkpoint', return_value=self.switch_path)
        self.ui = Mock()
        self.ui.goto_page.return_value = True
        self.ui.match_page_once.return_value = False
        p3 = patch.object(recovery, 'GameUi', return_value=self.ui)
        p1.start()
        p2.start()
        p3.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)
        self.addCleanup(p3.stop)
        self.device = SimpleNamespace(
            _failed_original_page='result',
            _failed_original_page_captured=True,
            image=np.zeros((720, 1280, 3), np.uint8),
            screenshot=Mock(),
            reset_task_recovery=Mock(),
            recover_by_escape=Mock(side_effect=lambda *a: setattr(self.device, '_escape_generation', 5)),
        )
        self.ui.device = self.device

    def test_remember_prepare_and_clear_routes(self):
        # Normal task without failure checkpoint -> 'normal'
        self.assertEqual(recovery.prepare(None, self.device, 'oas1', 'Orochi'), 'normal')
        self.ui.goto_page.assert_not_called()

        # First failure saves original page and does not get overwritten by second remember().
        recovery.remember(None, self.device, 'oas1', 'Orochi')
        self.device._failed_original_page = 'other_room'
        recovery.remember(None, self.device, 'oas1', 'Orochi')
        self.assertEqual(json.loads(self.page_path.read_text(encoding='utf-8'))['page'], 'result')
        self.assertEqual(recovery.read_switch('oas1')['task'], 'Orochi')

        # Two consecutive matching frames -> 'original'
        with patch.object(recovery, 'page_key', side_effect=['result', 'result']):
            self.assertEqual(recovery.prepare(None, self.device, 'oas1', 'Orochi'), 'original')
        self.ui.goto_page.assert_not_called()

        # Changed page -> returns via verified home -> 'main'
        with patch.object(recovery, 'page_key', return_value='lobby'):
            self.assertEqual(recovery.prepare(None, self.device, 'oas1', 'DailyTrifles'), 'main')
        self.ui.goto_page.assert_called_once()
        self.ui._ui_verify.assert_called_once()

        recovery.clear('oas1', 'Orochi')
        self.assertFalse(self.page_path.exists())
        self.assertIsNone(recovery.read_switch('oas1'))

    def test_script_switch_guard_verifies_home_and_caps_backoff(self):
        script = Script.__new__(Script)
        script.config_name = 'oas1'
        script.config = SimpleNamespace(
            notifier=SimpleNamespace(push=Mock()),
            script=SimpleNamespace(error=SimpleNamespace(error_repeated=False)),
        )
        script.device = self.device
        script.failure_record = {}
        script._task_failure_deadlines = {}
        script._last_failure_scheduled = None
        script.completion_gate = TaskCompletionGate(Path(self.tmp.name) / 'gate.json')
        script.wait_until = Mock(return_value=True)

        # Same failed task skips prepare_switch so prepare() can resume on original page.
        recovery.write_switch('oas1', {'task': 'FrogBoss'})
        with patch.object(recovery, 'prepare_switch') as prep_sw:
            self.assertEqual(script._ensure_failed_task_switch_ready('FrogBoss'), (True, False))
            prep_sw.assert_not_called()

        # Switching from SoulsTidy -> FrogBoss requires prepare_switch.
        recovery.write_switch('oas1', {'task': 'SoulsTidy'})
        with patch.object(recovery, 'prepare_switch', return_value=True) as prep_sw:
            self.assertEqual(script._ensure_failed_task_switch_ready('FrogBoss'), (True, False))
            prep_sw.assert_called_once()

        # Failed prepare_switch defers GotoMain (~5 min), keeps FrogBoss untouched, and caps long backoff.
        long_future = datetime.now().replace(microsecond=0) + timedelta(hours=3)
        recovery.write_switch('oas1', {'task': 'SoulsTidy', 'not_before': long_future.isoformat(), 'policy': 2})
        self.assertEqual(script._ensure_failed_task_switch_ready('FrogBoss'), (False, False))
        waited = script.wait_until.call_args.args[0]
        self.assertLessEqual(waited, datetime.now() + timedelta(minutes=5, seconds=2))

        # Three consecutive switch home failures escalate to fatal_stop=True.
        recovery.write_switch('oas1', {'task': 'SoulsTidy'})
        with patch.object(recovery, 'prepare_switch', side_effect=TaskRecoveryFailed('stuck')), \
             patch('script.I18n.trans_zh_cn', return_value='回主界面'):
            self.assertEqual(script._ensure_failed_task_switch_ready('FrogBoss'), (False, False))
            recovery.write_switch('oas1', {'task': 'SoulsTidy'})
            self.assertEqual(script._ensure_failed_task_switch_ready('FrogBoss'), (False, False))
            recovery.write_switch('oas1', {'task': 'SoulsTidy'})
            self.assertEqual(script._ensure_failed_task_switch_ready('FrogBoss'), (False, True))


if __name__ == '__main__':
    unittest.main()
