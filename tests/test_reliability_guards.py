"""Offline unit tests for high- and medium-priority reliability guards."""

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from module.atom.click import RuleClick
from module.config.config import Function
from module.device.click_verification import ClickResponseUnchanged, after_click, before_click
from module.device.confirm_retry import click_confirm_once
from module.device.device import Device
from module.exception import TaskRecoveryFailed
from module.script.task_completion import TaskCompletionGate
from module.script.task_flow_guard import TaskFlowGuard
from script import Script
from tasks.Component.preset_text import SOUL_CONFIRM, SOUL_ENTRY, SOUL_TEAM_TITLE, soul_slot_center
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.navigator import _NavigationBudget
from tasks.GameUi.page_definition import Page, Transition
from tasks.GameUi.session import NavigatorSession


def _solid_frame(value: int = 20, shape=(720, 1280, 3)) -> np.ndarray:
    return np.full(shape, value, dtype=np.uint8)


class _StubDevice:
    def __init__(self, frames=None):
        self.frames = list(frames) if frames is not None else [_solid_frame(20)]
        self._frame_idx = 0
        self.image = self.frames[0]
        self.image_frame_id = 'frame-0'
        self._escape_generation = 0
        self._accepted_invitation_generation = 0
        self._task_flow_progress_generation = 0
        self._task_flow_round_generation = 0
        self._task_flow_guard_disabled = False
        self._verified_click = None
        self._confirm_retry_permit = None
        self.click_record = []
        self.clicks = []
        self._click_callback = None

    def screenshot(self):
        guard = getattr(self, '_task_flow_guard', None)
        if guard is not None:
            guard.check()
        self._frame_idx += 1
        idx = min(self._frame_idx, len(self.frames) - 1)
        self.image = self.frames[idx]
        self.image_frame_id = f'frame-{self._frame_idx}'
        return self.image

    def click(self, x, y, control_check=True, control_name='Click'):
        before = before_click(self, x, y, control_name) if control_check else None
        self.clicks.append((x, y, control_name))
        if callable(self._click_callback):
            self._click_callback(x, y, control_name)
        if before is not None:
            after_click(self, x, y, control_name, before)
        return True

    def click_record_remove(self, button):
        self.click_record = [b for b in self.click_record if b != str(button)]

    def confirm_control_progress(self, buttons):
        Device.confirm_control_progress(self, buttons)

    def confirm_task_round_progress(self):
        Device.confirm_task_round_progress(self)

    def app_lost_login(self):
        return False

    def app_is_running(self):
        return True

    def get_orientation(self):
        return None


class TaskFlowGuardTests(unittest.TestCase):
    def test_no_progress_times_out_and_confirmed_progress_renews(self):
        now = [100.0]
        device = _StubDevice()
        task = SimpleNamespace(current_count=0, config=None)

        # Simulate frame under /tasks/ by defining helper via exec with fake filename.
        ns = {}
        exec(
            compile(
                "def fake_task_loop(device, steps):\n"
                "    for fn in steps:\n"
                "        fn()\n"
                "        device.screenshot()\n",
                "e:/Antigravity date/OnmyojiAutoScript/tasks/FakeTask/script_task.py",
                "exec",
            ),
            ns,
        )
        fake_task_loop = ns["fake_task_loop"]

        with TaskFlowGuard(task, device, clock=lambda: now[0], command='FakeTask'):
            # Advance 300s (< 420s), then confirm progress -> should renew started timer.
            def step_advance_300():
                now[0] += 300.0

            def step_confirm_and_advance_300():
                device.confirm_control_progress([])
                now[0] += 300.0

            fake_task_loop(device, [lambda: None, step_advance_300, step_confirm_and_advance_300])

            # Now advance 420s without progress -> must raise TaskRecoveryFailed.
            def step_stall_420():
                now[0] += 420.0

            with self.assertRaises(TaskRecoveryFailed):
                fake_task_loop(device, [lambda: None, step_stall_420])

    def test_hard_timeout_triggers_even_with_page_progress_until_round_advances(self):
        now = [1000.0]
        device = _StubDevice()
        task = SimpleNamespace(current_count=0, config=None)

        ns = {}
        exec(
            compile(
                "def run_loop(device, ticks):\n"
                "    for advance_round in ticks:\n"
                "        device.confirm_control_progress([])\n"
                "        if advance_round:\n"
                "            device.confirm_task_round_progress()\n"
                "        device.screenshot()\n",
                "e:/Antigravity date/OnmyojiAutoScript/tasks/FakeTask/script_task.py",
                "exec",
            ),
            ns,
        )

        # Every 300s page changes (renews 420s timeout), but no round advances -> hits 1800s hard cap.
        with TaskFlowGuard(task, device, clock=lambda: now[0], command='FakeTask'):
            with self.assertRaises(TaskRecoveryFailed):
                def drive():
                    for _ in range(10):
                        now[0] += 300.0
                        ns["run_loop"](device, [False])
                # Call inside a task frame so the outer residence tracks across iterations.
                outer = {}
                exec(
                    compile(
                        "def outer_run(device, advance_fn):\n"
                        "    for _ in range(8):\n"
                        "        advance_fn()\n"
                        "        device.confirm_control_progress([])\n"
                        "        device.screenshot()\n",
                        "e:/Antigravity date/OnmyojiAutoScript/tasks/FakeTask/script_task.py",
                        "exec",
                    ),
                    outer,
                )
                outer["outer_run"](device, lambda: now.__setitem__(0, now[0] + 300.0))

    def test_disabled_guard_does_not_raise(self):
        now = [0.0]
        device = _StubDevice()
        device._task_flow_guard_disabled = True
        task = SimpleNamespace(current_count=0, config=None)

        ns = {}
        exec(
            compile(
                "def stalled(device, bump):\n"
                "    device.screenshot()\n"
                "    bump()\n"
                "    device.screenshot()\n",
                "e:/Antigravity date/OnmyojiAutoScript/tasks/FakeTask/script_task.py",
                "exec",
            ),
            ns,
        )
        with TaskFlowGuard(task, device, clock=lambda: now[0], command='FakeTask'):
            ns["stalled"](device, lambda: now.__setitem__(0, 10000.0))


class TaskCompletionGateTests(unittest.TestCase):
    def test_retain_defer_reload_and_recovery_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            gate_path = Path(tmp) / 'oas1.json'
            gate = TaskCompletionGate(gate_path)
            gate.retain('Orochi')
            # Another task cannot overwrite pinned unfinished task.
            gate.retain('Exploration')
            self.assertEqual(gate.task, 'Orochi')

            retry_business = datetime(2026, 11, 27, 15, 0, 0)
            earlier = datetime(2026, 11, 27, 14, 0, 0)
            self.assertTrue(gate.defer('Orochi', retry_business))
            # Cannot shorten an existing wait.
            self.assertTrue(gate.defer('Orochi', earlier))
            self.assertEqual(gate.not_before, retry_business)

            # Recovery wait is tracked independently and does not overwrite business task.
            retry_home = datetime(2026, 11, 27, 14, 5, 0)
            gate.defer_recovery('GotoMain', retry_home)

            reloaded = TaskCompletionGate(gate_path)
            self.assertEqual(reloaded.task, 'Orochi')
            self.assertEqual(reloaded.not_before, retry_business)
            self.assertEqual(reloaded.recovery_not_before.get('GotoMain'), retry_home)

            reloaded.release_recovery('GotoMain')
            self.assertEqual(reloaded.task, 'Orochi')
            self.assertNotIn('GotoMain', reloaded.recovery_not_before)

            reloaded.release('Orochi')
            self.assertEqual(reloaded.task, '')
            self.assertFalse(gate_path.exists())

    def test_select_enforces_not_before_and_releases_disabled_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            gate_path = Path(tmp) / 'oas1.json'
            gate = TaskCompletionGate(gate_path)
            future = datetime.now().replace(microsecond=0) + timedelta(hours=2)
            gate.defer('Orochi', future)

            orochi_model = SimpleNamespace(
                scheduler=SimpleNamespace(enable=True, next_run=datetime(2020, 1, 1, 0, 0, 0), priority=5),
                model_dump=lambda: {
                    'scheduler': {'enable': True, 'next_run': datetime(2020, 1, 1, 0, 0, 0), 'priority': 5}
                },
            )
            fake_config = SimpleNamespace(
                model=SimpleNamespace(orochi=orochi_model, restart=None),
                update_scheduler=lambda: None,
                get_next=lambda: Function('exploration', {
                    'scheduler': {'enable': True, 'next_run': datetime(2020, 1, 1), 'priority': 5}
                }),
            )
            selected = gate.select(fake_config)
            self.assertEqual(selected.command, 'Orochi')
            self.assertEqual(selected.next_run, future)

            # Disabling pinned task releases checkpoint and falls back to config.get_next().
            orochi_model.scheduler.enable = False
            selected2 = gate.select(fake_config)
            self.assertEqual(selected2.command, 'Exploration')
            self.assertEqual(gate.task, '')

    def test_script_defer_failed_task_isolates_gotomain(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Script.__new__(Script)
            script.completion_gate = TaskCompletionGate(Path(tmp) / 'oas1.json')
            script._last_failure_scheduled = None
            script._task_failure_deadlines = {}
            script.completion_gate.retain('Orochi')

            retry_at = script._defer_failed_task('GotoMain')
            self.assertIsNotNone(retry_at)
            self.assertEqual(script.completion_gate.task, 'Orochi')
            self.assertIn('GotoMain', script.completion_gate.recovery_not_before)


class NavigationBudgetTests(unittest.TestCase):
    def test_budget_limits(self):
        budget = _NavigationBudget('page_main', max_steps=2, total_timeout=60, max_recoveries=1, max_polls=2)
        budget.check(step=True)
        budget.check(step=True)
        with self.assertRaises(TaskRecoveryFailed):
            budget.check(step=True)

        budget2 = _NavigationBudget('page_main', max_steps=10, total_timeout=60, max_recoveries=1, max_polls=2)
        budget2.check(poll=True)
        budget2.check(poll=True)
        with self.assertRaises(TaskRecoveryFailed):
            budget2.check(poll=True)

        budget3 = _NavigationBudget('page_main', max_steps=10, total_timeout=60, max_recoveries=1, max_polls=10)
        budget3.check(recovery=True)
        with self.assertRaises(TaskRecoveryFailed):
            budget3.check(recovery=True)

    def test_goto_page_oscillation_hits_max_steps_without_reset(self):
        page_a = Page(name='page_a', recognizer=None, category='global')
        page_b = Page(name='page_b', recognizer=None, category='global')
        page_c = Page(name='page_c', recognizer=None, category='global')
        page_a.transitions.append(Transition(source=page_a, destination=page_b, action=lambda: True))
        page_b.transitions.append(Transition(source=page_b, destination=page_c, action=lambda: True))

        ui = GameUi.__new__(GameUi)
        ui.device = _StubDevice()
        ui.interval_timer = {}
        ui.config = SimpleNamespace(script=SimpleNamespace(device=SimpleNamespace(control_method='minitouch')))
        ui.navigator = NavigatorSession(task_category='global')
        ui.navigator.bootstrap([page_a, page_b, page_c])

        toggle = [0]

        def refresh(destination, skip_first_screenshot):
            toggle[0] += 1
            return page_a if toggle[0] % 2 else page_b

        ui._refresh_current_page = refresh
        ui._execute_transition = lambda transition: False
        ui.close_unknown_pages = lambda skip_first_screenshot=False: False

        with self.assertRaises(TaskRecoveryFailed):
            ui.goto_page(page_c, max_steps=4, total_timeout=60)

    def test_goto_page_click_fenced_consumes_shared_recovery_budget(self):
        page_a = Page(name='page_a', recognizer=None, category='global')
        page_b = Page(name='page_b', recognizer=None, category='global')
        page_a.transitions.append(Transition(source=page_a, destination=page_b, action=lambda: True))

        ui = GameUi.__new__(GameUi)
        ui.device = _StubDevice()
        ui.interval_timer = {}
        ui.config = SimpleNamespace(script=SimpleNamespace(device=SimpleNamespace(control_method='minitouch')))
        ui.navigator = NavigatorSession(task_category='global')
        ui.navigator.bootstrap([page_a, page_b])

        ui._refresh_current_page = lambda destination, skip_first_screenshot: page_a
        ui._execute_transition = lambda transition: (_ for _ in ()).throw(
            ClickResponseUnchanged('fenced')
        )
        close_calls = [0]

        def fake_close(skip_first_screenshot=False):
            close_calls[0] += 1
            return True

        ui.close_unknown_pages = fake_close

        with self.assertRaises(TaskRecoveryFailed):
            ui.goto_page(page_b, max_steps=20, total_timeout=60)
        # Default max_recoveries=2 -> 2 recoveries happen, 3rd raises TaskRecoveryFailed.
        self.assertEqual(close_calls[0], 2)


class ClickVerificationAndConfirmRetryTests(unittest.TestCase):
    def setUp(self):
        for target in ('module.device.click_verification.time.sleep',):
            patcher = patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_repeated_unchanged_click_is_fenced(self):
        same = _solid_frame(40)
        device = _StubDevice(frames=[same] * 10)
        # First click runs and sees no visual change -> records changed=False.
        device.click(200, 200, control_name='BTN_A')
        self.assertFalse(device._verified_click['changed'])

        # Second click on same control & region without visual change must raise ClickResponseUnchanged.
        now = [0.0]

        def fake_monotonic():
            now[0] += 5.0
            return now[0]

        with patch('module.device.click_verification.time.monotonic', side_effect=fake_monotonic):
            with self.assertRaises(ClickResponseUnchanged):
                device.click(205, 205, control_name='BTN_A')

    def test_click_confirm_once_retries_exactly_once_on_unchanged_modal(self):
        modal_frame = _solid_frame(60)
        dismissed_frame = _solid_frame(220)
        btn = RuleClick(roi_front=(680, 400, 100, 50), roi_back=(680, 400, 100, 50), name='CONFIRM_BTN')
        visible = [True]

        device = _StubDevice(frames=[modal_frame] * 20)

        def on_click(x, y, name):
            # First click is ignored by the game; second click (retry) dismisses the modal.
            if len(device.clicks) >= 2:
                visible[0] = False
                device.frames = [dismissed_frame] * 40

        device._click_callback = on_click

        task = SimpleNamespace(device=device)
        task.screenshot = device.screenshot

        def ui_verify(predicate, controls, timeout=12, fail=True):
            stable = 0
            for _ in range(4):
                task.screenshot()
                stable = stable + 1 if predicate() else 0
                if stable >= 2:
                    device.confirm_control_progress(controls)
                    return True
            if fail:
                raise TaskRecoveryFailed('not reached')
            return False

        task._ui_verify = ui_verify

        ok = click_confirm_once(task, lambda: btn if visible[0] else None, [btn])
        self.assertTrue(ok)
        self.assertEqual(len(device.clicks), 2)

    def test_click_confirm_once_blocks_reentry_after_exhausted_retry(self):
        modal_frame = _solid_frame(60)
        btn = RuleClick(roi_front=(680, 400, 100, 50), roi_back=(680, 400, 100, 50), name='CONFIRM_BTN')
        device = _StubDevice(frames=[modal_frame] * 20)
        device._verified_click = {
            'name': 'CONFIRM_BTN',
            'x': 700,
            'y': 420,
            'before': None,
            'changed': False,
            'confirm_retry_used': True,
        }
        task = SimpleNamespace(device=device, screenshot=device.screenshot)
        with self.assertRaises(ClickResponseUnchanged):
            click_confirm_once(task, lambda: btn, [btn])


class SwitchSoulGuardTests(unittest.TestCase):
    def _make_switch_soul(self, device):
        task = SwitchSoul.__new__(SwitchSoul)
        task.device = device
        task.interval_timer = {}
        task.config = SimpleNamespace()
        task.screenshot = device.screenshot
        return task

    def test_soul_slot_center_does_not_shift_when_row1_missing(self):
        roi = (573, 140, 277, 481)
        # Only row 2 present around y = 140 + 20 + 150 = 310 (relative y = 170).
        row2 = SimpleNamespace(
            ocr_text='Team2',
            score=0.95,
            box=[[10, 160], [100, 160], [100, 180], [10, 180]],
        )
        self.assertIsNone(soul_slot_center([row2], roi, 1))
        self.assertEqual(soul_slot_center([row2], roi, 2), 310)

    def test_generation_guard_aborts_on_invitation_or_escape(self):
        device = _StubDevice(frames=[_solid_frame(30)] * 10)
        task = self._make_switch_soul(device)
        gen = task._soul_generation()
        device._accepted_invitation_generation += 1
        with self.assertRaises(TaskRecoveryFailed):
            task._soul_guard(gen)

    def test_stale_frame_id_rejected(self):
        device = _StubDevice()
        device.screenshot = lambda: device.image  # Does not advance image_frame_id
        task = self._make_switch_soul(device)
        gen = task._soul_generation()
        with self.assertRaises(TaskRecoveryFailed):
            task._soul_capture(gen)

    def test_golden_group_highlight_and_two_frame_exit(self):
        frame = _solid_frame(30)
        # Paint group 2's golden highlight band.
        _, y, _, h = SwitchSoul.C_SOU_GROUP_2.roi_front
        center = int(y + h / 2)
        for left in (1098, 1225):
            frame[center - 8:center + 8, left:left + 8] = (220, 185, 90)
        device = _StubDevice(frames=[frame] * 10)
        task = self._make_switch_soul(device)
        task._soul_preset_visible_ocr = lambda: True
        self.assertTrue(task._soul_selected_group(2))
        self.assertFalse(task._soul_selected_group(1))

        # Test exit_shikigami_records requires two fresh frames out of records.
        in_records = [True]

        def on_click(x, y, name):
            in_records[0] = False

        device._click_callback = on_click
        task.appear = lambda target, **kw: in_records[0] if target in (task.I_SOU_CHECK_IN, task.I_RECORD_SOUL_BACK) else False
        task._soul_preset_visible_ocr = lambda: in_records[0]
        with patch('module.device.click_verification.time.sleep'):
            task.exit_shikigami_records()
        self.assertEqual(len(device.clicks), 1)
        self.assertEqual(device.clicks[0][2], task.I_RECORD_SOUL_BACK.name)


if __name__ == '__main__':
    unittest.main()
