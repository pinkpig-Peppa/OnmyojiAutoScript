"""Offline regression tests for the post-PR #8 MetaDemon flow and battle_wait hooks."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from module.exception import TaskEnd, TaskRecoveryFailed
from tasks.Component.GeneralBattle.battle_wait import (
    BattleResult,
    HookSignal,
    PerTaskPreset,
    PublicContext,
    PrivateContext,
    runtime,
)
from tasks.MetaDemon.config import DefaultStrategy, MetaDemon, MetaDemonConfig, Strategy
from tasks.MetaDemon.script_task import ScriptTask, Star56


class OfflineMetaDemon(ScriptTask):
    """Offline harness exercising real MetaDemon ScriptTask methods without Device/OCR RPC."""

    def __init__(self, config_raw=None, default_raw=None, strategies_raw=None):
        self.events = []
        self.frames = 0
        self.pages = []
        self.exhaustion_values = [20]
        self.exhaustion_idx = 0
        self.full_names = ['鬼王名称']
        self.full_name_idx = 0
        self.device = SimpleNamespace(
            image=None,
            click=Mock(return_value=True),
            stuck_record_add=Mock(),
            click_record_clear=Mock(),
            performance=SimpleNamespace(timeout=lambda s: s),
        )
        raw_cfg = dict(config_raw or {})
        if strategies_raw:
            raw_cfg.setdefault('md_strategy_count', len(strategies_raw))
        md_cfg = MetaDemon(
            meta_demon_config=raw_cfg,
            md_default_strategy=dict(default_raw or {}),
            md_strategies=[dict(item) for item in (strategies_raw or [{}])],
        )
        self.config = SimpleNamespace(
            meta_demon=md_cfg,
            notifier=SimpleNamespace(push=Mock()),
        )
        self.next_run = None

    def set_next_run(self, task, finish=False, success=None, server=True, target=None):
        self.next_run = (task, success)

    def current_page_rules(self):
        if not self.pages:
            return set()
        return self.pages[min(self.frames, len(self.pages) - 1)]

    def screenshot(self):
        self.frames += 1
        if self.frames > 200:
            raise AssertionError('MetaDemon flow did not converge')

    def enter(self, rule):
        self.events.append(('enter', rule))

    def goto_page(self, page):
        self.events.append(('goto', page))

    def appear(self, rule, threshold=None, interval=None, **kwargs):
        return rule in self.current_page_rules()

    def appear_then_click(self, rule, interval=None, **kwargs):
        if rule not in self.current_page_rules():
            return False
        self.events.append(('click', rule))
        return True

    def ocr_appear(self, rule, **kwargs):
        return rule in self.current_page_rules()

    def click(self, rule, interval=None, **kwargs):
        self.events.append(('click', rule))
        return True

    def ui_click(self, click, stop, interval=1, timeout=None):
        self.events.append(('ui_click', click, stop))
        return True

    def ui_click_until_disappear(self, click, interval=1):
        self.events.append(('ui_click_until_disappear', click))
        return True

    def ui_reward_appear_click(self):
        return False

    def current_exhaustion(self) -> int:
        val = self.exhaustion_values[min(self.exhaustion_idx, len(self.exhaustion_values) - 1)]
        self.exhaustion_idx += 1
        return val


class MetaDemonFlowTests(unittest.TestCase):
    def setUp(self):
        runtime.task_owner = None
        runtime.pub_ctx = None
        runtime.pri_ctx = {}

    def test_strategy_fuzzy_matching_and_hp_threshold_selection(self):
        task = OfflineMetaDemon(
            config_raw={'md_use_strategy': True},
            default_raw={
                'md_preset_group_team_default_1': '1,1',
                'md_preset_group_team_default_2': '1,2',
            },
            strategies_raw=[
                {
                    'md_match_names': '炼狱茨木童子,铃鹿御前',
                    'md_preset_group_team_1': '2,3',
                    'md_preset_group_team_2': '4,5',
                }
            ],
        )
        # Exact match + 1-character OCR typo tolerance
        self.assertEqual(task.get_group_team('炼狱茨木童子'), [2, 3, 4, 5])
        self.assertEqual(task.get_group_team('炼狱茨木童孑'), [2, 3, 4, 5])
        # Unmatched falls back to default strategy
        self.assertEqual(task.get_group_team('大天狗'), [1, 1, 1, 2])

        # HP threshold check uses I_STAR56_HP_THRESHOLD_F without I_STAR56_HP_THRESHOLD_T
        task.pages = [{task.I_STAR56_HP_THRESHOLD_F}]
        self.assertTrue(task.hp_threshold_low(None))
        task.pages = [{task.I_STAR56_HP_THRESHOLD_F, task.I_STAR56_HP_THRESHOLD_T}]
        self.assertFalse(task.hp_threshold_low(None))

    def test_find_demon_summons_and_notifies_star56_with_ocr_fallback(self):
        task = OfflineMetaDemon()
        task.pages = [
            {task.I_FIND_DEMON, task.I_BOSS_EMPTY},
            {task.I_BATTLE_DEMON},
            {task.I_BATTLE_DEMON},
            {task.I_BATTLE_DEMON},
        ]
        task.O_MD_FULL_NAME = SimpleNamespace(ocr_single=Mock(return_value='SP荒骷髅'))
        with patch('tasks.MetaDemon.script_task.sleep'):
            self.assertTrue(task.find_demon())
        task.config.notifier.push.assert_called_once_with(
            content='召唤到高星鬼王: SP荒骷髅',
            title='超鬼王',
        )

    def test_run_battles_self_boss_and_exits_when_exhaustion_exceeds_limit(self):
        task = OfflineMetaDemon(
            config_raw={'md_use_strategy': True, 'auto_tea': False, 'meta_crafting_card': False},
            default_raw={
                'md_preset_group_team_default_1': '1,1',
                'md_preset_group_team_default_2': '1,2',
            },
            strategies_raw=[
                {
                    'md_match_names': '黑童子',
                    'md_preset_group_team_1': '3,1',
                    'md_preset_group_team_2': '3,2',
                }
            ],
        )
        # Frame 1: enter -> I_ENTER2; Frame 2: main + hard boss low HP; Frame 3: exhaustion > 100 -> exit
        task.pages = [
            {task.I_ENTER2},
            {task.I_BATTLE_DEMON, task.I_BOSS_CONVENE, task.I_STAR56_HP_THRESHOLD_F},
            {task.I_BATTLE_DEMON, task.I_BOSS_CONVENE, task.I_STAR56_HP_THRESHOLD_F},
            {task.I_FIND_DEMON, task.I_BOSS_EMPTY},
        ]
        task.exhaustion_values = [40, 120]
        task.O_MD_FULL_NAME = SimpleNamespace(ocr_single=Mock(return_value='黑童子'))
        battled_teams = []
        task.battle_boss = lambda g, t: (battled_teams.append((g, t)) or True)

        with self.assertRaises(TaskEnd):
            task.run()

        self.assertEqual(battled_teams, [(3, 2)])
        self.assertEqual(task.next_run, ('MetaDemon', True))

    def test_battle_wait_metademon_hooks_transition_to_completion(self):
        task = OfflineMetaDemon()
        runtime._ensure_pub_default()
        pub = runtime.pub_ctx

        # Victory hook sets BattleResult.SUCCESS and enables completion
        task.pages = [{task.I_MD_WIN}, set()]
        with patch('tasks.MetaDemon.script_task.sleep'):
            sig = task._bw_success_metademon()
        self.assertEqual(sig, HookSignal.CONTINUE)
        self.assertEqual(pub.per_battle.success, BattleResult.SUCCESS)
        self.assertIn('completion', pub.per_battle.hook_enabled)
        self.assertNotIn('success', pub.per_battle.hook_enabled)

        # Defeat hook sets BattleResult.FAILURE and enables completion
        runtime.reset_per_battle()
        pub = runtime.pub_ctx
        task.pages = [{task.I_MD_BATTLE_FAILURE}]
        sig_fail = task._bw_failure_metademon()
        self.assertEqual(sig_fail, HookSignal.CONTINUE)
        self.assertEqual(pub.per_battle.success, BattleResult.FAILURE)
        self.assertIn('completion', pub.per_battle.hook_enabled)

    def test_enter_timeout_raises_task_recovery_failed(self):
        task = OfflineMetaDemon()
        task.pages = [set()]
        fake_timer = Mock()
        fake_timer.start.return_value = fake_timer
        fake_timer.reached.return_value = True
        with patch('tasks.MetaDemon.script_task.Timer', return_value=fake_timer):
            with self.assertRaises(TaskRecoveryFailed):
                task.run()


if __name__ == '__main__':
    unittest.main()
