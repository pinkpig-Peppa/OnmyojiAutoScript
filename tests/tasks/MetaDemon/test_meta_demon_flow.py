"""Exercise the new MetaDemon flow without a game, device or OCR service."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from module.exception import TaskEnd
from tasks.MetaDemon.config import MetaDemon
from tasks.MetaDemon.script_task import ScriptTask


class OfflineMetaDemon(ScriptTask):
    """跳过 Config/Device 初始化，只保留流程控制逻辑"""

    def __init__(self, config_raw=None, strategies_raw=None):
        self.events = []
        self.frames = 0
        self.pages = []
        self.friend_detail_at = None
        self.now = 100.0
        self.last_click = {}
        self.device = SimpleNamespace(
            image=None,
            click=lambda *args, **kwargs: None,
            stuck_record_add=lambda *args, **kwargs: None,
            click_record_clear=lambda *args, **kwargs: None,
        )
        self.config = SimpleNamespace(meta_demon=MetaDemon(
            meta_demon_config=config_raw or {},
            md_default_strategy={},
            md_strategies=strategies_raw or [{}],
        ))
        self.next_run = None

    def set_next_run(self, task, finish=False, success=None, server=True, target=None):
        self.next_run = (task, success)

    def page(self):
        if self.friend_detail_at is not None and self.frames >= self.friend_detail_at:
            return {self.I_MD_CHALLENGE}
        if not self.pages:
            return set()
        return self.pages[min(self.frames, len(self.pages) - 1)]

    def screenshot(self):
        self.frames += 1
        self.now += 0.5
        if self.frames > 300:
            raise AssertionError("MetaDemon flow did not converge")

    def goto_page(self, page):
        self.events.append(("goto",))

    def appear(self, rule, threshold=None, **kwargs):
        return rule in self.page()

    def appear_then_click(self, rule, interval=None, **kwargs):
        if rule not in self.page():
            return False
        # 对齐真实实现：interval 未到时不点击并返回 False
        name = str(getattr(rule, "name", rule))
        last = self.last_click.get(name)
        if interval and last is not None and self.now - last < interval:
            return False
        self.last_click[name] = self.now
        self.click(rule, interval=interval)
        return True

    def wait_until_appear(self, rule, wait_time=None, **kwargs):
        for _ in range(20):
            if self.appear(rule):
                return True
            self.screenshot()
        return self.appear(rule)

    def ocr_appear(self, rule, **kwargs):
        return rule in self.page()

    def click(self, rule, interval=None, **kwargs):
        self.events.append(rule)
        return True

    def ui_reward_appear_click(self):
        return False


class EnterFailedMetaDemon(OfflineMetaDemon):
    def enter_meta_demon(self):
        return False


class RunThroughMetaDemon(OfflineMetaDemon):
    """run() 主流程跑通，各阶段用桩替代"""

    exit_result = True

    def enter_meta_demon(self):
        return True

    def crafting(self):
        pass

    def run_meta_demon(self):
        pass

    def exit_meta_demon(self):
        return self.exit_result


class ExitFailedMetaDemon(RunThroughMetaDemon):
    exit_result = False


class BattlePathMetaDemon(OfflineMetaDemon):
    """补充战斗路径所需的桩"""

    def ui_click_until_disappear(self, rule, interval=1, **kwargs):
        self.click(rule)

    def is_in_battle(self, is_screenshot=True):
        return False

    def is_in_prepare(self, is_screenshot=True):
        return False

    def random_click_swipt(self):
        self.events.append("swipt")

    def boss_mark(self):
        return False

    def boss_mark_reset(self):
        pass

    def _hook_special_reward(self):
        return False

    def run_general_battle(self, config=None, buff=None):
        self.battle_config = config
        return True


class MetaDemonFlowTests(unittest.TestCase):
    def clicks(self, task):
        return [event for event in task.events if not isinstance(event, tuple)]

    def test_enter_uses_activity_icon_then_vertical_entry(self):
        task = OfflineMetaDemon()
        task.pages = [set(), {task.I_MD_RIGHT_ENTER}, {task.I_MD_ENTER2}, {task.I_MD_MAIN}]
        self.assertTrue(task.enter_meta_demon())
        self.assertEqual(self.clicks(task), [task.I_MD_RIGHT_ENTER, task.I_MD_ENTER2])

    def test_enter_expands_activity_bar_when_icon_is_hidden(self):
        task = OfflineMetaDemon()
        task.pages = [set(), {task.I_MD_TOGGLE_BUTTON}, {task.I_MD_RIGHT_ENTER},
                      {task.I_MD_ENTER2}, {task.I_MD_MAIN}]
        self.assertTrue(task.enter_meta_demon())
        self.assertEqual(self.clicks(task),
                         [task.I_MD_TOGGLE_BUTTON, task.I_MD_RIGHT_ENTER, task.I_MD_ENTER2])

    def test_summon_when_self_slot_empty_and_friends_have_no_boss(self):
        task = OfflineMetaDemon()
        task.pages = [{task.I_MD_MAIN, task.I_MD_BOSS_EMPTY, task.I_MD_FRIEND_EMPTY,
                       task.I_MD_FIND_DEMON}]
        self.assertTrue(task.handle_meta_main())
        self.assertEqual(self.clicks(task), [task.I_MD_FIND_DEMON])

    def test_friend_boss_is_entered_before_summoning(self):
        task = OfflineMetaDemon()
        task.pages = [{task.I_MD_MAIN, task.I_MD_BOSS_EMPTY}]
        task.friend_detail_at = 2
        self.assertTrue(task.handle_meta_main())
        self.assertEqual(self.clicks(task), [task.C_MD_FRIEND_BOSS_AREA])

    def test_self_boss_slot_is_clicked_when_not_empty(self):
        task = OfflineMetaDemon()
        task.pages = [{task.I_MD_MAIN}]
        self.assertTrue(task.handle_meta_main())
        self.assertEqual(self.clicks(task), [task.C_MD_SELF_BOSS_SLOT])

    def test_exhaustion_full_uses_total_value(self):
        task = OfflineMetaDemon()
        task.pages = [{task.I_MD_MAIN}]
        task.O_MD_EXHAUSTION = SimpleNamespace(ocr=lambda image: (30, 0, 100))
        self.assertFalse(task.exhaustion_full())
        task.O_MD_EXHAUSTION = SimpleNamespace(ocr=lambda image: (100, 0, 100))
        self.assertTrue(task.exhaustion_full())

    def test_group_team_switches_by_hp_threshold(self):
        strategies = [dict(md_match_names="黑童子", md_preset_group_team_1="2,3",
                           md_preset_group_team_2="4,5")]
        task = OfflineMetaDemon(config_raw=dict(md_use_strategy=True, md_low_hp_threshold=40),
                                strategies_raw=strategies)
        with patch.object(task, "ocr_boss_name", return_value="黑童子"), \
                patch.object(task, "ocr_hp_percent", return_value=30):
            self.assertEqual(task.choose_group_team(), [4, 5])
        with patch.object(task, "ocr_boss_name", return_value="黑童子"), \
                patch.object(task, "ocr_hp_percent", return_value=80):
            self.assertEqual(task.choose_group_team(), [2, 3])
        with patch.object(task, "ocr_boss_name", return_value="未知鬼王"), \
                patch.object(task, "ocr_hp_percent", return_value=80):
            self.assertEqual(task.choose_group_team(), [1, 1])

    def test_strategy_tolerates_one_char_ocr_error(self):
        strategies = [dict(md_match_names="黑童子", md_preset_group_team_1="2,3",
                           md_preset_group_team_2="4,5")]
        task = OfflineMetaDemon(config_raw=dict(md_use_strategy=True, md_low_hp_threshold=40),
                                strategies_raw=strategies)
        with patch.object(task, "ocr_boss_name", return_value="黑童于"), \
                patch.object(task, "ocr_hp_percent", return_value=80):
            self.assertEqual(task.choose_group_team(), [2, 3])

    def test_invalid_hp_percent_is_treated_as_unknown(self):
        task = OfflineMetaDemon()
        task.O_MD_HP_PERCENT = SimpleNamespace(ocr=lambda image: 0)
        self.assertIsNone(task.ocr_hp_percent())
        task.O_MD_HP_PERCENT = SimpleNamespace(ocr=lambda image: -5)
        self.assertIsNone(task.ocr_hp_percent())
        task.O_MD_HP_PERCENT = SimpleNamespace(ocr=lambda image: None)
        self.assertIsNone(task.ocr_hp_percent())
        task.O_MD_HP_PERCENT = SimpleNamespace(ocr=lambda image: 66)
        self.assertEqual(task.ocr_hp_percent(), 66)

    def test_no_strategy_keeps_current_team(self):
        task = OfflineMetaDemon()
        self.assertIsNone(task.choose_group_team())

    def test_summon_loop_gives_up_after_repeated_queue(self):
        task = OfflineMetaDemon()
        task.pages = [{task.I_MD_SUMMON_NOW}]
        task.run_meta_demon()
        self.assertLess(task.frames, 300)

    def test_enter_failure_ends_task_without_success(self):
        task = EnterFailedMetaDemon()
        with self.assertRaises(TaskEnd):
            task.run()
        self.assertEqual(task.next_run, ("MetaDemon", False))

    def test_run_through_marks_success(self):
        task = RunThroughMetaDemon()
        with self.assertRaises(TaskEnd):
            task.run()
        self.assertEqual(task.next_run, ("MetaDemon", True))

    def test_exit_failure_marks_task_failed(self):
        task = ExitFailedMetaDemon()
        with self.assertRaises(TaskEnd):
            task.run()
        self.assertEqual(task.next_run, ("MetaDemon", False))


    def test_click_challenge_returns_true_when_button_disappears(self):
        task = BattlePathMetaDemon()
        task.pages = [set(), {task.I_MD_CHALLENGE}, {task.I_MD_MAIN}]
        self.assertTrue(task.click_challenge())
        self.assertEqual(self.clicks(task), [task.I_MD_CHALLENGE])

    def test_battle_wait_detects_win_and_stops_at_detail_page(self):
        task = BattlePathMetaDemon()
        task.pages = [set(), {task.I_WIN}, {task.I_MD_CHALLENGE}]
        self.assertTrue(task.battle_wait(random_click_swipt_enable=False))

    def test_battle_wait_detects_failure(self):
        task = BattlePathMetaDemon()
        task.pages = [set(), {task.I_FALSE}, {task.I_MD_CHALLENGE}]
        self.assertFalse(task.battle_wait(random_click_swipt_enable=False))

    def test_collect_reward_clicks_reward_button(self):
        task = BattlePathMetaDemon()
        task.pages = [set(), {task.I_REWARD}, {task.I_REWARD}, {task.I_MD_MAIN}]
        task.collect_reward()
        self.assertIn(task.I_REWARD, task.events)

    def test_battle_boss_skips_when_challenge_is_not_clickable(self):
        task = BattlePathMetaDemon()
        task.current_count = 0
        with patch.object(task, "click_challenge", return_value=False):
            self.assertFalse(task.battle_boss([2, 3]))

    def test_battle_boss_restores_current_count_and_preset(self):
        task = BattlePathMetaDemon()
        task.current_count = 7
        with patch.object(task, "click_challenge", return_value=True), \
                patch.object(task, "wait_battle_enter", return_value=True):
            self.assertTrue(task.battle_boss([2, 3]))
        self.assertEqual(task.current_count, 8)
        self.assertTrue(task.battle_config.preset_enable)
        self.assertEqual((task.battle_config.preset_group, task.battle_config.preset_team), (2, 3))
        self.assertFalse(task.battle_config.lock_team_enable)

    def test_battle_boss_without_preset_disables_preset(self):
        task = BattlePathMetaDemon()
        task.current_count = 0
        with patch.object(task, "click_challenge", return_value=True), \
                patch.object(task, "wait_battle_enter", return_value=True):
            self.assertTrue(task.battle_boss(None))
        self.assertFalse(task.battle_config.preset_enable)

    def test_fallback_click_counts_only_real_clicks(self):
        task = BattlePathMetaDemon()
        task.pages = [{task.I_UI_BACK_RED}]
        counts = {}
        name = task.I_UI_BACK_RED.name
        self.assertEqual(task.fallback_click(task.I_UI_BACK_RED, 2, counts), 1)
        self.assertEqual(counts, {name: 1})
        # interval 未到：出现但未点击，不增加计数
        for _ in range(4):
            self.assertEqual(task.fallback_click(task.I_UI_BACK_RED, 2, counts), 1)
        self.assertEqual(counts, {name: 1})
        # interval 到点后继续累计，超过上限返回 2
        task.now += 3
        for expected in (2, 3, 4, 5):
            task.now += 3
            self.assertEqual(task.fallback_click(task.I_UI_BACK_RED, 2, counts), 1)
            self.assertEqual(counts[name], expected)
        task.now += 3
        self.assertEqual(task.fallback_click(task.I_UI_BACK_RED, 2, counts), 2)

    def test_collect_reward_waits_loading_frames_before_clicking_reward(self):
        task = BattlePathMetaDemon()
        task.pages = [set(), {task.I_REWARD}, {task.I_REWARD}, {task.I_MD_MAIN}]
        task.collect_reward()
        self.assertIn(task.I_REWARD, task.events)

    def test_collect_reward_returns_without_reward_when_statistics_shown(self):
        task = BattlePathMetaDemon()
        task.pages = [{task.I_STATISTICS}]
        task.collect_reward()
        self.assertNotIn(task.I_REWARD, task.events)

    def test_collect_reward_clicks_reward_multiple_times_during_cooldown(self):
        task = BattlePathMetaDemon()
        task.pages = [set(), {task.I_REWARD}, {task.I_REWARD}, {task.I_REWARD},
                      {task.I_REWARD}, {task.I_REWARD}, {task.I_MD_MAIN}]
        task.collect_reward()
        # 奖励图标连续出现时应持续点击，而不是在点击冷却期误判为“奖励消失”
        self.assertGreaterEqual(self.clicks(task).count(task.I_REWARD), 2)

    def test_run_meta_demon_stops_after_three_battle_failures(self):
        task = BattlePathMetaDemon()
        task.pages = [{task.I_MD_CHALLENGE}]
        with patch.object(task, "exhaustion_full", return_value=False), \
                patch.object(task, "battle_from_detail", return_value=False) as battle, \
                patch.object(task, "leave_detail", return_value=True):
            task.run_meta_demon()
        self.assertEqual(battle.call_count, 3)

    def test_enter_keeps_flipping_activity_bar_until_icon_appears(self):
        """活动栏需要翻多页才出现超鬼王图标时，不能因为兜底点击上限提前失败"""
        task = OfflineMetaDemon()
        task.pages = [{task.I_MD_TOGGLE_BUTTON}] * 35 + [
            {task.I_MD_RIGHT_ENTER}, {task.I_MD_ENTER2}, {task.I_MD_MAIN}]
        self.assertTrue(task.enter_meta_demon())
        toggle_clicks = self.clicks(task).count(task.I_MD_TOGGLE_BUTTON)
        self.assertGreaterEqual(toggle_clicks, 6)
        self.assertEqual(self.clicks(task)[-2:], [task.I_MD_RIGHT_ENTER, task.I_MD_ENTER2])

    def test_enter_uses_activity_overview_when_activity_bar_has_no_flip_button(self):
        """活动栏展开成大图标、看不到“换一批”按钮时，改走“活动总览”入口"""
        task = OfflineMetaDemon()
        act_page = {task.I_CHECK_ACT_LIST, task.O_MD_ACT_ENTRY, task.I_ACT_LIST_GOTO_ACT}
        task.pages = [set(), {task.I_ACT_LIST_EXPAND}, act_page, act_page,
                      {task.I_MD_ENTER2}, {task.I_MD_MAIN}]
        self.assertTrue(task.enter_meta_demon())
        clicked = self.clicks(task)
        self.assertIn(task.I_ACT_LIST_EXPAND, clicked)
        self.assertIn(task.O_MD_ACT_ENTRY, clicked)
        self.assertIn(task.I_ACT_LIST_GOTO_ACT, clicked)

    def test_click_win_result_page_taps_banner_until_it_disappears(self):
        task = BattlePathMetaDemon()
        task.pages = [{task.I_WIN}] * 12 + [set()]
        self.assertTrue(task.click_win_result())
        self.assertGreaterEqual(self.clicks(task).count(task.I_WIN), 2)

    def test_battle_wait_taps_victory_overlay_before_reward(self):
        """新版结算页没有奖励按钮，胜利横幅必须被点掉，不能直接返回"""
        task = BattlePathMetaDemon()
        task.pages = [set()] + [{task.I_WIN}] * 12 + [{task.I_MD_CHALLENGE}]
        self.assertTrue(task.battle_wait(random_click_swipt_enable=False))
        self.assertGreaterEqual(self.clicks(task).count(task.I_WIN), 2)
        self.assertLess(task.frames, 300)

    def test_exit_dismisses_victory_overlay_before_leaving(self):
        task = BattlePathMetaDemon()
        task.pages = [{task.I_WIN}] * 12 + [{task.I_CHECK_MAIN}]
        self.assertTrue(task.exit_meta_demon())
        self.assertGreaterEqual(self.clicks(task).count(task.I_WIN), 2)

    def test_run_meta_demon_waits_while_battle_reward_is_settling(self):
        """战斗结束后“击败奖励结算中”期间不能重复点击鬼王槽位"""
        task = BattlePathMetaDemon()
        task.pages = [{task.O_MD_SETTLING}] * 5 + [{task.I_MD_MAIN}]
        with patch.object(task, "exhaustion_full", return_value=True):
            task.run_meta_demon()
        self.assertEqual(self.clicks(task), [])
        self.assertLess(task.frames, 300)

    def test_run_meta_demon_closes_leftover_victory_overlay(self):
        task = BattlePathMetaDemon()
        task.pages = [{task.I_WIN}] * 12 + [{task.I_MD_CHALLENGE}]
        with patch.object(task, "exhaustion_full", return_value=True):
            task.run_meta_demon()
        self.assertGreaterEqual(self.clicks(task).count(task.I_WIN), 2)


if __name__ == "__main__":
    unittest.main()
