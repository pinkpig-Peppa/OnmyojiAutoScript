"""Offline regression tests for human_click sampling, hover trajectories, and DesktopDevice compatibility."""
import ast
from functools import cached_property
import importlib.util
import math
from pathlib import Path
import random
import sys
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('human_click_test_subject', ROOT / 'module/device/human_click.py')
human = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = human
spec.loader.exec_module(human)


def load_class(relative, class_name, namespace):
    tree = ast.parse((ROOT / relative).read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), relative, 'exec'), namespace)
    return namespace[class_name]


def control(method, human_enabled=True):
    namespace = dict(
        Session=human.Session,
        task_generation=human.task_generation,
        sampled_width=human.sampled_width,
        plan_move=human.plan_move,
        sample_dwell=human.sample_dwell,
        cached_property=property,
        IS_WINDOWS=True,
        time=types.SimpleNamespace(perf_counter=lambda: 1),
        logger=Mock(),
        ensure_int=lambda x, y: (int(x), int(y)),
        point2str=lambda x, y: str((x, y)),
        before_click=lambda device, x, y, name: 'before_sig',
        after_click=lambda device, x, y, name, before: None,
    )
    for name in ('Minitouch', 'Adb', 'Scrcpy', 'Window'):
        namespace[name] = type(name, (), {})
    cls = load_class('module/device/control.py', 'Control', namespace)
    device = cls()
    device.config = types.SimpleNamespace(
        script=types.SimpleNamespace(
            device=types.SimpleNamespace(control_method=method, human_click_enabled=human_enabled)
        )
    )
    for name in (
        'click_adb',
        'click_minitouch',
        'click_uiautomator2',
        'long_click_adb',
        'long_click_minitouch',
        'long_click_scrcpy',
        'long_click_uiautomator2',
        'long_click_window_message',
        'click_window_message',
        'hover_window_message',
        'sleep',
        'stuck_record_clear',
        'handle_control_check',
        'invalidate_image_batch_cache',
    ):
        setattr(device, name, Mock())
    return device


class HumanClickTests(unittest.TestCase):
    def setUp(self):
        human.reset_task()

    def test_integer_and_fractional_roi_bounds(self):
        rng = random.Random(2026)
        for box in (
            human.TargetBox(800, 450, 120, 40),
            human.TargetBox(10, 20, 1, 1),
            human.TargetBox(-4.3, 5.8, 2.1, 1.4),
        ):
            for _ in range(2000):
                x, y = human.sample_point(box, rng=rng)
                self.assertTrue(box.x <= x < box.x + box.w)
                self.assertTrue(box.y <= y < box.y + box.h)

    def test_invalid_and_empty_boxes(self):
        for values in ((0, 0, 0, 1), (0, 0, -1, 2), (math.nan, 0, 1, 1)):
            with self.assertRaises(ValueError):
                human.TargetBox(*values)
        with self.assertRaises(ValueError):
            human.sample_point(human.TargetBox(0.1, 0.1, 0.1, 0.1))

    def test_roi_metadata_is_consumed_and_reset(self):
        point = human.sample_point(human.TargetBox(0, 0, 100, 20))
        self.assertEqual(human.sampled_width(point), 20)
        self.assertEqual(human.sampled_width(point), 1)
        point = human.sample_point(human.TargetBox(0, 0, 100, 20))
        human.reset_task()
        self.assertEqual(human.sampled_width(point), 1)

    def test_path_endpoint_duration_and_short_moves(self):
        for seed in range(30):
            path = human.plan_move((100, 50), (500, 300), 40, random.Random(seed))
            self.assertEqual(path[-1][0], (500, 300))
            self.assertTrue(all(dt > 0 for _, dt in path))
            self.assertAlmostEqual(sum(dt for _, dt in path), human.fitts_time(math.hypot(400, 250), 40))
        self.assertEqual(human.plan_move((1, 2), (1, 2), 1)[-1][0], (1, 2))

    def test_backend_dispatch_dwell_and_toggle(self):
        expected = {
            'ADB': 'long_click_adb',
            'uiautomator2': 'long_click_uiautomator2',
            'minitouch': 'long_click_minitouch',
            'scrcpy': 'long_click_scrcpy',
            'unknown': 'long_click_adb',
            'window_message': 'click_window_message',
        }
        for method, handler in expected.items():
            with self.subTest(method=method), patch.object(human.time, 'sleep'):
                dev = control(method, human_enabled=True)
                dev.click(12, 34)
                args, kwargs = getattr(dev, handler).call_args
                self.assertEqual(args[:2], (12, 34))
                dwell = kwargs['duration'] if method == 'window_message' else args[2]
                self.assertGreaterEqual(dwell, 0.025)
                self.assertEqual(dev.hover_window_message.call_count, int(method == 'window_message'))
                dev.handle_control_check.assert_called_once()
                dev.invalidate_image_batch_cache.assert_called_once()

        # Disabling human_click_enabled falls back to direct click_methods
        dev_off = control('minitouch', human_enabled=False)
        dev_off.click(55, 66)
        dev_off.click_minitouch.assert_called_once_with(55, 66)
        dev_off.long_click_minitouch.assert_not_called()

    def test_rest_clears_stuck_timer_and_skips_when_time_critical(self):
        with patch.object(human.time, 'sleep'):
            dev = control('minitouch')
            session = dev.human_click_session
            session.rounds_per_burst = (1, 1)
            session.micro_pause = session.long_rest = (90, 90)
            dev.click(12, 34)
            dev.sleep.assert_called_once_with(90)
            dev.stuck_record_clear.assert_called_once()

            # Timed rounds (e.g. DraftDuel / Chess) skip burst sleep
            dev._time_critical_clicks = True
            dev.sleep.reset_mock()
            dev.click(12, 34)
            dev.sleep.assert_not_called()

            human.reset_task()
            self.assertIsNot(dev.human_click_session, session)
            self.assertIsNone(dev._human_click_last_point)

    def test_windows_emulator_and_desktop_hover_and_button_release_on_interrupt(self):
        namespace = dict(
            Handle=type('Handle', (), {}),
            DesktopWindow=type('DesktopWindow', (), {}),
            cached_property=cached_property,
            Config=types.SimpleNamespace(when=lambda **k: lambda f: f),
            SendMessage=Mock(),
            PostMessage=Mock(),
            MAKELONG=lambda x, y: (x, y),
            WM_ACTIVATE=6,
            WA_ACTIVE=1,
            WM_LBUTTONDOWN=513,
            WM_LBUTTONUP=514,
            WM_MOUSEMOVE=512,
            WM_CAPTURECHANGED=533,
            MK_LBUTTON=1,
            time=Mock(),
            random=Mock(),
        )
        window = load_class('module/device/method/windows_impl.py', 'Window', namespace)
        instance = object.__new__(window)
        instance.is_desktop_window = False
        instance.window_scale_rate = 2
        for handles, expected_handle in (([10], 10), ([10, 20], 20), ([10, 20, 30, 40], 40)):
            instance.control_handle_list = handles
            send = namespace['SendMessage']
            send.reset_mock()
            namespace['time'].sleep.side_effect = None
            instance.hover_window_message([((100, 200), 0.01)])
            send.assert_called_once_with(expected_handle, 512, 0, (50, 100))
            send.reset_mock()
            namespace['time'].sleep.side_effect = KeyboardInterrupt
            with self.assertRaises(KeyboardInterrupt):
                instance.click_window_message(100, 200, duration=0.075)
            self.assertEqual(send.call_args.args, (expected_handle, 514, 0, (50, 100)))

        # Desktop client window path
        desktop = object.__new__(window)
        desktop.is_desktop_window = True
        desktop.root_handle_num = 999
        desktop.screenshot_size = (1280, 720)
        desktop.desktop_client_size_virtual = lambda: (640, 360)
        desktop.desktop_window_restore_if_minimized = Mock()
        post = namespace['PostMessage']
        post.reset_mock()
        namespace['time'].sleep.side_effect = None
        desktop.hover_window_message([((200, 100), 0.01)])
        post.assert_called_once_with(999, 512, 0, (100, 50))
        self.assertEqual(desktop._desktop_cursor, (200, 100))


if __name__ == '__main__':
    unittest.main()
