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
        self.click(rule, interval=interval)
        return True

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


if __name__ == "__main__":
    unittest.main()