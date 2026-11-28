"""Offline regression tests for BattleWaitPlan, runtime context scoping, and battle_wait decorators."""
from copy import deepcopy
import unittest

from tasks.Component.GeneralBattle.battle_wait import (
    BattleResult,
    BattleWait,
    BattleWaitPlan,
    HookSignal,
    OptionPrepareDefault,
    OptionPresetDefault,
    PerBattleState,
    PerTaskPreset,
    PerTaskState,
    PublicContext,
    PrivateContext,
    _OPTION_CLASSES,
    battle_wait_options,
    battle_wait_strategy,
    runtime,
)


class BattleWaitPlanAndRuntimeTests(unittest.TestCase):
    def setUp(self):
        self._saved_plan = battle_wait_strategy.battle_wait_plan
        self._saved_options = deepcopy(battle_wait_options.options)
        battle_wait_strategy.battle_wait_plan = None
        battle_wait_options.options = {event: cls() for event, cls in _OPTION_CLASSES.items()}
        runtime.task_owner = None
        runtime.pub_ctx = None
        runtime.pri_ctx = {}

    def tearDown(self):
        battle_wait_strategy.battle_wait_plan = self._saved_plan
        battle_wait_options.options = self._saved_options
        runtime.task_owner = None
        runtime.pub_ctx = None
        runtime.pri_ctx = {}

    def test_default_plan_contains_all_11_default_hooks_and_sequence(self):
        plan = BattleWaitPlan()
        self.assertEqual(len(BattleWaitPlan.HOOKS_DEFAULT), 11)
        self.assertTrue(all(getattr(plan, hook) == 'default' for hook in BattleWaitPlan.HOOKS_DEFAULT))
        self.assertEqual(
            plan.sequence,
            'completion>interrupt>prepare>preset>green>red>echo>success>failure>idle',
        )
        self.assertEqual(plan.function_setup_name, '_bw_setup_default')

    def test_positional_and_keyword_event_configuration_and_duplicate_rejection(self):
        plan = BattleWaitPlan('yyy_default', abcd='edf')
        self.assertEqual(plan.yyy, 'default')
        self.assertEqual(plan.abcd, 'edf')
        names = plan.sequence_function_names()
        self.assertEqual(names[-3:], ['_bw_yyy_default', '_bw_abcd_edf', '_bw_idle_default'])

        with self.assertRaises(ValueError):
            BattleWaitPlan('success_default', success='custom')

    def test_custom_sequence_requires_all_core_events(self):
        plan = BattleWaitPlan(
            'yyy_default',
            sequence='failure > yyy > completion > interrupt > prepare > preset > green > red > echo > success > idle',
        )
        self.assertEqual(plan.sequence_function_names()[0], '_bw_failure_default')
        self.assertEqual(plan.sequence_function_names()[1], '_bw_yyy_default')

        with self.assertRaises(ValueError):
            BattleWaitPlan(sequence='completion > success > failure > idle')

    def test_strategy_decorator_context_manager_and_dynamic_randomclick_override(self):
        strategy = battle_wait_strategy('success_default')

        @strategy
        def dummy_wait(owner, *, battle_wait_plan, options=None):
            return battle_wait_plan

        default_plan = battle_wait_strategy.battle_wait_plan
        with battle_wait_strategy('success_default', failure='custom'):
            temp_plan = dummy_wait(object())
            self.assertEqual(temp_plan.failure, 'custom')
        self.assertIs(battle_wait_strategy.battle_wait_plan, default_plan)

        overridden = dummy_wait(object(), random_click_swipt_enable=True)
        self.assertIsNot(overridden, default_plan)
        self.assertEqual(overridden.randomclick, 'default')
        self.assertFalse(hasattr(default_plan, 'randomclick'))

    def test_options_context_manager_slices_into_private_context_and_restores(self):
        class NoopDefaultsBattleWait(BattleWait):
            def screenshot(self):
                pass

            def _bw_interrupt_default(self, pub: PublicContext, pri: PrivateContext) -> HookSignal:
                return HookSignal.CONTINUE

            def _bw_prepare_default(self, pub: PublicContext, pri: PrivateContext) -> HookSignal:
                return HookSignal.CONTINUE

            def _bw_preset_default(self, pub: PublicContext, pri: PrivateContext) -> HookSignal:
                return HookSignal.CONTINUE

            def _bw_green_default(self, pub: PublicContext, pri: PrivateContext) -> HookSignal:
                return HookSignal.CONTINUE

            def _bw_red_default(self, pub: PublicContext, pri: PrivateContext) -> HookSignal:
                return HookSignal.CONTINUE

            def _bw_echo_default(self, pub: PublicContext, pri: PrivateContext) -> HookSignal:
                return HookSignal.CONTINUE

            def _bw_failure_default(self, pub: PublicContext, pri: PrivateContext) -> HookSignal:
                return HookSignal.CONTINUE

            def _bw_idle_default(self, pub: PublicContext, pri: PrivateContext) -> HookSignal:
                return HookSignal.CONTINUE

        class StubOwner(NoopDefaultsBattleWait):
            def __init__(self):
                self.seen_lock = None
                self.seen_preset = None

            def _bw_setup_noop(self, pub: PublicContext, pri: PrivateContext) -> HookSignal:
                return HookSignal.CONTINUE

            def _bw_prepare_check(self, pub: PublicContext, pri: PrivateContext) -> HookSignal:
                self.seen_lock = pri.options.lock_team
                runtime.hook_enabled_update(enable=('preset',), disable=('prepare',))
                return HookSignal.CONTINUE

            def _bw_preset_check(self, pub: PublicContext, pri: PrivateContext) -> HookSignal:
                self.seen_preset = (pri.options.preset_enable, pri.options.preset_group, pri.options.preset_team)
                runtime.hook_enabled_update(enable=(), disable=('preset',))
                return HookSignal.CONTINUE

            def _bw_success_finish(self, pub: PublicContext, pri: PrivateContext) -> HookSignal:
                pub.per_battle.success = BattleResult.SUCCESS
                return runtime.hook_enabled_update(enable=('completion',), disable=('success', 'failure'))

            def _bw_completion_finish(self, pub: PublicContext, pri: PrivateContext) -> HookSignal:
                return HookSignal.DONE

            @battle_wait_strategy(
                setup='noop',
                prepare='check',
                preset='check',
                success='finish',
                completion='finish',
            )
            def run_once(self, *args, **kwargs):
                return self.battle_wait_with_strategy(*args, **kwargs)

        owner = StubOwner()
        with battle_wait_options(
            prepare=OptionPrepareDefault(lock_team=True),
            preset=OptionPresetDefault(preset_enable=True, preset_group=3, preset_team=4),
        ):
            self.assertTrue(owner.run_once())

        self.assertTrue(owner.seen_lock)
        self.assertEqual(owner.seen_preset, (True, 3, 4))
        self.assertFalse(battle_wait_options.options['prepare'].lock_team)

    def test_setup_and_custom_hooks_execute_in_sequence_and_track_task_vs_battle_state(self):
        class OrderedBattleWait(BattleWait):
            def __init__(self):
                self.events = []

            def screenshot(self):
                self.events.append('screenshot')

            def _bw_interrupt_default(self, pub: PublicContext, pri: PrivateContext) -> HookSignal:
                return HookSignal.CONTINUE

            def _bw_prepare_default(self, pub: PublicContext, pri: PrivateContext) -> HookSignal:
                return HookSignal.CONTINUE

            def _bw_preset_default(self, pub: PublicContext, pri: PrivateContext) -> HookSignal:
                return HookSignal.CONTINUE

            def _bw_green_default(self, pub: PublicContext, pri: PrivateContext) -> HookSignal:
                return HookSignal.CONTINUE

            def _bw_red_default(self, pub: PublicContext, pri: PrivateContext) -> HookSignal:
                return HookSignal.CONTINUE

            def _bw_echo_default(self, pub: PublicContext, pri: PrivateContext) -> HookSignal:
                return HookSignal.CONTINUE

            def _bw_failure_default(self, pub: PublicContext, pri: PrivateContext) -> HookSignal:
                return HookSignal.CONTINUE

            def _bw_idle_default(self, pub: PublicContext, pri: PrivateContext) -> HookSignal:
                return HookSignal.CONTINUE

            def _bw_setup_record(self, pub: PublicContext, pri: PrivateContext) -> HookSignal:
                self.events.append('setup')
                pub.per_task.count += 1
                return HookSignal.CONTINUE

            def _bw_yyy_record(self, pub: PublicContext, pri: PrivateContext) -> HookSignal:
                self.events.append('yyy')
                return HookSignal.CONTINUE

            def _bw_success_win(self, pub: PublicContext, pri: PrivateContext) -> HookSignal:
                self.events.append('success')
                pub.per_battle.success = BattleResult.SUCCESS
                return runtime.hook_enabled_update(enable=('completion',), disable=('success', 'failure', 'yyy'))

            def _bw_completion_done(self, pub: PublicContext, pri: PrivateContext) -> HookSignal:
                self.events.append('completion')
                return HookSignal.DONE

            @battle_wait_strategy(
                setup='record',
                yyy='record',
                success='win',
                completion='done',
                sequence='yyy > completion > interrupt > prepare > preset > green > red > echo > success > failure > idle',
            )
            def fight(self, *args, **kwargs):
                return self.battle_wait_with_strategy(*args, **kwargs)

        bw = OrderedBattleWait()
        self.assertTrue(bw.fight())
        self.assertEqual(
            bw.events,
            ['setup', 'screenshot', 'yyy', 'success', 'screenshot', 'completion'],
        )
        self.assertEqual(runtime.pub_ctx.per_task.count, 1)

        # Second fight on same task owner preserves per_task.count while resetting per_battle
        bw.events.clear()
        self.assertTrue(bw.fight())
        self.assertEqual(runtime.pub_ctx.per_task.count, 2)


if __name__ == '__main__':
    unittest.main()
