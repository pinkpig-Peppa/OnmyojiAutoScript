"""Offline unit tests for static loop inventory, multi-scale grid bounds, and BaseTask shared bounds."""

import ast
from datetime import datetime
from math import isfinite
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from dev_tools.audit_task_loops import inventory, main as audit_main, table
from module.atom.animate import RuleAnimate
from module.atom.click import RuleClick
from module.atom.gif import RuleGif
from module.atom.image import RuleImage, get_roi_match_padding, set_roi_match_padding
from module.atom.long_click import RuleLongClick
from module.atom.ocr import RuleOcr
from module.atom.swipe import RuleSwipe
from module.device.confirm_retry import click_confirm_once
from module.exception import ScriptError, TaskRecoveryFailed
from module.image.runtime import ImageRuntime
from module.image.scales import (
    MAX_MULTI_SCALE_SAMPLES,
    multi_scale_values,
    normalize_multi_scale_range,
)
from tasks.GlobalGame.config_emergency import FriendInvitation


ROOT = Path(__file__).resolve().parents[1]


class LoopAuditTests(unittest.TestCase):
    def test_repository_inventory_has_zero_parse_errors_and_bounded_base_task(self):
        report = inventory(ROOT)
        self.assertEqual(report['parse_errors'], [])
        self.assertEqual(len(report['task_scripts']), 54)
        base_unbounded = [
            loop for loop in report['loops']
            if loop['path'] == 'tasks/base_task.py' and not loop['guard_candidates']
        ]
        self.assertEqual(base_unbounded, [])
        doc_path = ROOT / 'docs' / 'task-loop-inventory.md'
        self.assertTrue(doc_path.exists())
        self.assertEqual(doc_path.read_text(encoding='utf-8'), table(report))

    def test_cli_check_detects_unbounded_base_task_loop(self):
        self.assertEqual(audit_main([str(ROOT), '--check']), 0)
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp)
            (fake_root / 'tasks').mkdir()
            (fake_root / 'module').mkdir()
            (fake_root / 'tasks' / 'base_task.py').write_text(
                'def spin():\n    while True:\n        pass\n',
                encoding='utf-8',
            )
            self.assertEqual(audit_main([str(fake_root), '--check']), 1)


class MultiScaleBoundsTests(unittest.TestCase):
    def setUp(self):
        set_roi_match_padding(0)
        rng = np.random.default_rng(123)
        self.template = rng.integers(0, 256, size=(10, 10, 3), dtype=np.uint8)
        self.image = rng.integers(0, 256, size=(70, 70, 3), dtype=np.uint8)
        self.image[27:37, 30:40] = self.template
        self.roi = (5, 7, 50, 50)
        self.rule = RuleImage(
            roi_front=(0, 0, 10, 10),
            roi_back=self.roi,
            method=RuleImage.METHOD_MULTI_SCALE_TEMPLATE_MATCH,
            threshold=0.99,
            file='offline-template.png',
        )
        self.rule._image = self.template
        self.runtime = ImageRuntime.__new__(ImageRuntime)

    def tearDown(self):
        set_roi_match_padding(2)

    def local(self, scale_range=None, scale_step=0.1):
        self.rule.scale_range = scale_range
        self.rule.scale_step = scale_step
        return self.rule.multi_scale_template_match(self.image)

    def service(self, scale_range=None, scale_step=0.1):
        return self.runtime._multi_scale_template_match(
            self.image, self.template, list(self.roi), 0.99, scale_range, scale_step, 'offline-template'
        )

    def test_default_local_and_service_match_same_center_with_seven_scales(self):
        for endpoint in (self.local, self.service):
            with self.subTest(endpoint=endpoint.__name__), patch('cv2.resize', wraps=cv2.resize) as resize:
                result = endpoint()
                self.assertEqual(resize.call_count, 7)
                if endpoint == self.local:
                    self.assertTrue(result)
                    self.assertEqual(self.rule.roi_front, [30, 27, 10, 10])
                    self.assertEqual(self.rule.last_scale, 1.0)
                else:
                    matched, score, roi = result
                    self.assertTrue(matched)
                    self.assertGreater(score, 0.99)
                    self.assertEqual(roi, [30, 27, 10, 10])

    def test_positive_step_that_cannot_advance_float_is_rejected_before_matching(self):
        self.assertEqual(1.0 + 1e-20, 1.0)
        for endpoint in (self.local, self.service):
            with self.subTest(endpoint=endpoint.__name__), patch('cv2.resize') as resize:
                with self.assertRaisesRegex(ValueError, '2048 samples'):
                    endpoint((1.0, 1.1), 1e-20)
                resize.assert_not_called()

    def test_oversized_grid_and_overflowing_grid_fail_before_opencv_work(self):
        for scale_range, step in (((0.5, 1.5), 1e-4), ((1e-300, 1e300), 1e-300)):
            for endpoint in (self.local, self.service):
                with self.subTest(endpoint=endpoint.__name__, bounds=scale_range), patch('cv2.resize') as resize:
                    with self.assertRaisesRegex(ValueError, '2048 samples'):
                        endpoint(scale_range, step)
                    resize.assert_not_called()

    def test_nonfinite_bounds_and_steps_fail_without_matching(self):
        for scale_range, step in (
            ((1.0, float('inf')), 0.1),
            ((float('nan'), 1.0), 0.1),
            ((1.0, 2.0), float('nan')),
            ((1.0, 2.0), float('inf')),
            ((1.0, 2.0), -float('inf')),
        ):
            for endpoint in (self.local, self.service):
                with self.subTest(endpoint=endpoint.__name__, bounds=scale_range, step=step), patch('cv2.resize') as resize:
                    with self.assertRaisesRegex(ValueError, 'finite'):
                        endpoint(scale_range, step)
                    resize.assert_not_called()

    def test_nonpositive_step_keeps_existing_default_fallback(self):
        for step in (0, -0.25):
            for scale_range in ((1.2, 0.6), (1.2, 0.6, step)):
                with self.subTest(bounds=scale_range, step=step):
                    self.rule.scale_range = scale_range
                    self.rule.scale_step = step
                    self.assertEqual(self.rule._get_multi_scale_range(), (0.6, 1.2, 0.1))
                    self.assertEqual(self.runtime._get_multi_scale_range(scale_range, step), (0.6, 1.2, 0.1))
                    self.assertTrue(self.local(scale_range, step))
                    self.assertTrue(self.service(scale_range, step)[0])

    def test_integer_enumeration_accepts_limit_and_rejects_one_more_sample(self):
        bounds = normalize_multi_scale_range((1.0, 2.0), 1.0 / (MAX_MULTI_SCALE_SAMPLES - 1))
        values = multi_scale_values(*bounds)
        self.assertEqual(len(values), MAX_MULTI_SCALE_SAMPLES)
        self.assertEqual(values[0], 1.0)
        self.assertEqual(values[-1], 2.0)
        with self.assertRaisesRegex(ValueError, '2048 samples'):
            normalize_multi_scale_range((1.0, 2.0), 1.0 / MAX_MULTI_SCALE_SAMPLES)

    def test_single_scale_and_oversized_template_remain_bounded(self):
        self.assertEqual(multi_scale_values(*normalize_multi_scale_range((1.0, 1.0), 1e-300)), (1.0,))
        self.assertTrue(self.local((1.0, 1.0), 1e-300))
        self.assertTrue(self.service((1.0, 1.0), 1e-300)[0])

        rng = np.random.default_rng(99)
        self.template = rng.integers(0, 256, size=(100, 100, 3), dtype=np.uint8)
        self.rule._image = self.template
        with patch('cv2.resize') as resize:
            self.assertFalse(self.local((1.0, 2.0), 0.1))
            self.assertFalse(self.service((1.0, 2.0), 0.1)[0])
            resize.assert_not_called()

    def test_roi_padding_preserves_declared_roi_back(self):
        self.assertEqual(self.rule.roi_back, (5, 7, 50, 50))
        set_roi_match_padding(2)
        self.assertEqual(get_roi_match_padding(), 2)
        self.assertEqual(tuple(self.rule._effective_roi()), (3, 5, 54, 54))


def _make_base_subject(step: float = 1.0, multiplier: int = 1):
    state = dict(
        frame=0,
        now=0.0,
        events=[],
        visible=set(),
        callback=None,
        blocked=False,
        keep_popup=False,
        scene=0,
        banner=20,
    )

    class FrameTimer:
        def __init__(self, limit, count=0):
            self.limit = limit
            self.count = count
            self.started = state['now']

        def start(self):
            self.started = state['now']
            return self

        def reset(self):
            return self.start()

        def reached(self):
            return state['now'] - self.started >= self.limit

    class NamedImg:
        def __init__(self, name):
            self.name = name

        def coord(self):
            return 640, 680

        def match(self, img, threshold=None):
            return self.name in state['visible']

    FakeRuleImage = type('FakeRuleImage', (NamedImg,), {})
    FakeRuleGif = type('FakeRuleGif', (FakeRuleImage,), {})
    FakeRuleOcr = type('FakeRuleOcr', (NamedImg,), {})
    FakeRuleClick = type('FakeRuleClick', (NamedImg,), {})
    FakeRuleAnimate = type('FakeRuleAnimate', (), {
        '__init__': lambda self, r=None: setattr(self, 'name', getattr(r, 'name', 'ANIM')),
        'stable': lambda self, img: 'ANIM_STABLE' in state['visible'],
    })

    methods = {
        '_perf_timeout',
        '_default_wait_timeout',
        '_invitation_identity',
        '_invitation_identity_changed',
        '_burst',
        'wait_until_appear',
        'wait_until_disappear',
        'wait_animate_stable',
        'ui_reward_appear_click',
        '_dismiss_reward_once',
        'ui_get_reward',
        '_ui_action_once',
        '_ui_verify',
        'ui_click',
        'ui_clicks',
        'ui_click_until_smt_disappear',
        'ui_click_multi_scale',
    }
    source = ast.parse((ROOT / 'tasks' / 'base_task.py').read_text(encoding='utf-8'))
    original = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == 'BaseTask')
    extracted = ast.ClassDef(
        name='Subject',
        bases=[],
        keywords=[],
        decorator_list=[],
        body=[n for n in original.body if isinstance(n, ast.FunctionDef) and n.name in methods],
    )
    namespace = dict(
        Timer=FrameTimer,
        monotonic=lambda: state['now'],
        isfinite=isfinite,
        datetime=datetime,
        logger=Mock(),
        Union=SimpleNamespace(__getitem__=lambda self, k: object),
        RuleImage=FakeRuleImage,
        RuleGif=FakeRuleGif,
        RuleOcr=FakeRuleOcr,
        RuleClick=FakeRuleClick,
        RuleLongClick=RuleLongClick,
        RuleAnimate=FakeRuleAnimate,
        RuleSwipe=RuleSwipe,
        TaskRecoveryFailed=TaskRecoveryFailed,
        ScriptError=ScriptError,
        FriendInvitation=FriendInvitation,
        click_confirm_once=click_confirm_once,
    )
    mod = ast.Module(
        body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), extracted],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(mod), 'shared_base_subject', 'exec'), namespace)

    def render_screen():
        img = np.full((720, 1280, 3), (state['scene'] * 53) % 256, dtype=np.uint8)
        img[240:276, 578:772] = state['banner']
        return img

    obj = namespace['Subject']()
    obj.config = SimpleNamespace(
        global_game=SimpleNamespace(
            battle=SimpleNamespace(battle_timeout=300),
            emergency=SimpleNamespace(friend_invitation=FriendInvitation.ACCEPT),
        )
    )
    obj.interval_timer = {}
    obj.I_UI_REWARD = FakeRuleImage('REWARD')
    obj.C_UI_REWARD = FakeRuleClick('CONTINUE')
    for inv_name in ('I_G_ACCEPT', 'I_G_REJECT', 'I_G_IGNORE', 'I_G_JADE', 'I_G_CAT_FOOD', 'I_G_DOG_FOOD'):
        setattr(obj, inv_name, FakeRuleImage(inv_name))

    obj.device = SimpleNamespace(
        image=render_screen(),
        image_frame_id=0,
        _escape_generation=0,
        _accepted_invitation_generation=0,
        _confirm_retry_permit=None,
        performance=SimpleNamespace(timeout=lambda v: v * multiplier),
        detect_record={'BATTLE_STATUS_S'},
        confirm_control_progress=Mock(),
    )

    def take_screenshot():
        state['frame'] += 1
        state['now'] += step
        if state['frame'] > 1500:
            raise AssertionError('Helper did not terminate finitely')
        if state['callback']:
            state['callback'](obj, state)
        obj.device.image = render_screen()
        obj.device.image_frame_id = state['frame']
        state['events'].append(('screenshot', state['frame']))
        return obj.device.image

    def dispatch(control, **kwargs):
        state['events'].append(('input', state['frame'], control.name))
        obj.device.detect_record = {'MUTATED_BY_CLICK'}
        if state['blocked']:
            return False
        if not state['keep_popup']:
            if control.name in ('REWARD', 'CONTINUE'):
                state['visible'].discard('REWARD')
                state['scene'] += 1
            elif control.name.startswith('I_G_'):
                state['visible'].difference_update({'I_G_ACCEPT', 'I_G_REJECT', 'I_G_IGNORE'})
                state['scene'] += 1
            elif control.name == 'CLAIM_SRC':
                state['visible'].discard('CLAIM_SRC')
                state['visible'].add('REWARD')
                state['scene'] += 1
            elif control.name == 'OPEN_BTN':
                state['visible'].add('STOP_TARGET')
                state['scene'] += 1
            elif control.name == 'CLOSE_BTN':
                state['visible'].discard('MODAL_STOP')
                state['scene'] += 1
        return True

    obj.device.screenshot = take_screenshot
    obj.device.click = lambda x, y, control_check=True, control_name='Click': dispatch(FakeRuleClick(control_name))
    obj.screenshot = take_screenshot
    obj.appear = lambda target, interval=None, threshold=None: target.name in state['visible']
    obj.ocr_appear = lambda target, interval=None: target.name in state['visible']
    obj.appear_then_click = lambda target, **kw: dispatch(target) if obj.appear(target) else False
    obj.appear_then_click_multi_scale = lambda target, **kw: dispatch(target) if obj.appear(target) else False
    obj.ocr_appear_click = lambda target, **kw: dispatch(target) if obj.ocr_appear(target) else False
    obj.click = lambda target, interval=None: dispatch(target)
    obj.set_next_run = Mock()
    return obj, state, FakeRuleImage, FakeRuleClick, FakeRuleAnimate


class SharedBaseTaskBoundsTests(unittest.TestCase):
    def test_implicit_waits_raise_finitely_and_explicit_waits_return_bool(self):
        obj, state, FakeRuleImage, _, FakeRuleAnimate = _make_base_subject(step=100.0)
        target = FakeRuleImage('MISSING')
        with self.assertRaises(TaskRecoveryFailed):
            obj.wait_until_appear(target)
        self.assertFalse(obj.wait_until_appear(target, wait_time=50))

        state['visible'].add('STUCK_MODAL')
        modal = FakeRuleImage('STUCK_MODAL')
        with self.assertRaises(TaskRecoveryFailed):
            obj.wait_until_disappear(modal)
        self.assertFalse(obj.wait_until_disappear(modal, wait_time=50))
        self.assertFalse(obj.wait_until_disappear(modal, timeout=50))

        anim = FakeRuleAnimate()
        with self.assertRaises(TaskRecoveryFailed):
            obj.wait_animate_stable(anim)
        self.assertFalse(obj.wait_animate_stable(anim, timeout=50))

    def test_default_wait_timeout_honors_longer_battle_timeout(self):
        obj, _, _, _, _ = _make_base_subject()
        self.assertEqual(obj._default_wait_timeout(), 420.0)
        obj.config.global_game.battle.battle_timeout = 900
        self.assertEqual(obj._default_wait_timeout(), 900.0)

    def test_invitation_burst_clicks_once_verifies_two_frames_and_restores_detect_record(self):
        obj, state, _, _, _ = _make_base_subject(step=1.0)
        state['visible'].add('I_G_ACCEPT')
        self.assertTrue(obj._burst())
        inputs = [e for e in state['events'] if e[0] == 'input']
        self.assertEqual(len(inputs), 1)
        self.assertEqual(obj.device.detect_record, {'BATTLE_STATUS_S'})
        self.assertEqual(obj.device._accepted_invitation_generation, 1)
        obj.set_next_run.assert_called_once()
        self.assertFalse(obj.set_next_run.call_args.kwargs.get('server', True))

    def test_invitation_burst_handles_queued_sender_replacement_and_persistent_failure(self):
        obj, state, _, _, _ = _make_base_subject(step=1.0)
        state['visible'].add('I_G_ACCEPT')
        state['keep_popup'] = True

        def replace_sender(_, st):
            if any(e[0] == 'input' for e in st['events']):
                st['banner'] = 200

        state['callback'] = replace_sender
        self.assertTrue(obj._burst())

        # Persistent identical card must fail within 12s and STILL preserve detect_record.
        obj2, state2, _, _, _ = _make_base_subject(step=2.0)
        state2['visible'].add('I_G_ACCEPT')
        state2['keep_popup'] = True
        with self.assertRaises(TaskRecoveryFailed):
            obj2._burst()
        self.assertEqual(obj2.device.detect_record, {'BATTLE_STATUS_S'})
        inputs2 = [e for e in state2['events'] if e[0] == 'input']
        self.assertEqual(len(inputs2), 1)

    def test_ui_get_reward_clicks_source_once_and_verifies_dismissal(self):
        obj, state, FakeRuleImage, _, _ = _make_base_subject(step=0.5)
        claim = FakeRuleImage('CLAIM_SRC')
        state['visible'].add('CLAIM_SRC')
        self.assertTrue(obj.ui_get_reward(claim))
        claim_clicks = [e for e in state['events'] if e[0] == 'input' and e[2] == 'CLAIM_SRC']
        self.assertEqual(len(claim_clicks), 1)
        self.assertNotIn('REWARD', state['visible'])

        # Unappearing reward after 1 source click raises TaskRecoveryFailed without re-clicking source.
        obj2, state2, FakeRuleImage2, _, _ = _make_base_subject(step=2.0)
        claim2 = FakeRuleImage2('CLAIM_SRC')
        state2['visible'].add('CLAIM_SRC')
        state2['keep_popup'] = True
        with self.assertRaises(TaskRecoveryFailed):
            obj2.ui_get_reward(claim2)
        claim_clicks2 = [e for e in state2['events'] if e[0] == 'input' and e[2] == 'CLAIM_SRC']
        self.assertEqual(len(claim_clicks2), 1)

    def test_ui_click_helpers_bound_both_implicit_and_explicit_timeouts(self):
        obj, state, FakeRuleImage, _, _ = _make_base_subject(step=0.5)
        open_btn = FakeRuleImage('OPEN_BTN')
        stop_img = FakeRuleImage('STOP_TARGET')
        state['visible'].add('OPEN_BTN')
        self.assertTrue(obj.ui_click(open_btn, stop_img))

        # Unactionable source: explicit timeout returns False; implicit raises TaskRecoveryFailed.
        missing_btn = FakeRuleImage('NEVER_APPEARS')
        never_stop = FakeRuleImage('NEVER_STOP')
        self.assertFalse(obj.ui_click(missing_btn, never_stop, timeout=3))
        self.assertFalse(obj.ui_click_multi_scale(missing_btn, never_stop, timeout=3))
        with self.assertRaises(TaskRecoveryFailed):
            obj.ui_click(missing_btn, never_stop)
        with self.assertRaises(TaskRecoveryFailed):
            obj.ui_clicks([missing_btn], never_stop)

        # ui_click_until_smt_disappear closes modal in 2 verified frames or fails finitely.
        close_btn = FakeRuleImage('CLOSE_BTN')
        modal_stop = FakeRuleImage('MODAL_STOP')
        state['visible'].update({'CLOSE_BTN', 'MODAL_STOP'})
        self.assertTrue(obj.ui_click_until_smt_disappear(close_btn, modal_stop))
        state['visible'].add('MODAL_STOP')
        state['visible'].discard('CLOSE_BTN')
        with self.assertRaises(TaskRecoveryFailed):
            obj.ui_click_until_smt_disappear(close_btn, modal_stop)


if __name__ == '__main__':
    unittest.main()
