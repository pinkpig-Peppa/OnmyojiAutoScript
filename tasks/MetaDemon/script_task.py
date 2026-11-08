# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from cached_property import cached_property

from module.base.timer import Timer
from module.exception import TaskEnd
from module.logger import logger

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.RightActivity.right_activity import RightActivity
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main, page_shikigami_records
from tasks.MetaDemon.assets import MetaDemonAssets
from tasks.MetaDemon.config import Strategy


class MetaDemonStrategy(GameUi, MetaDemonAssets):
    """鬼王名字/血量策略，适配新版祸主降临详情页"""

    @cached_property
    def cached_strategies(self) -> dict[str, list[int]]:
        return Strategy.parse_all(self.config.meta_demon.md_strategies)

    @cached_property
    def cached_default_group_team(self) -> list[int]:
        return Strategy.parse_group_team(self.config.meta_demon.md_default_strategy.md_preset_group_team_default_1) \
            + Strategy.parse_group_team(self.config.meta_demon.md_default_strategy.md_preset_group_team_default_2)

    @classmethod
    def strategy2group_team(cls, strategies: dict[str, list[int]], detect_name: str) -> list[int] | None:
        """
        先完全匹配，再容忍 OCR 的 1~2 个字符误差
        @param strategies: 鬼王名字 -> 预设组队
        @param detect_name: OCR 识别到的鬼王名字
        @return:
        """
        if not detect_name:
            return None
        for tolerance in range(3):
            for key_name, group_team in strategies.items():
                if len(key_name) != len(detect_name):
                    continue
                diff_count = sum(1 for c1, c2 in zip(key_name, detect_name) if c1 != c2)
                if diff_count <= tolerance:
                    return group_team
        return None

    def get_group_team(self, detect_name: str) -> list[int]:
        tmp = self.strategy2group_team(self.cached_strategies, detect_name)
        return tmp if tmp else self.cached_default_group_team

    def ocr_boss_name(self) -> str:
        try:
            name = self.O_MD_FULL_NAME.ocr_single(self.device.image)
        except Exception as e:
            logger.warning(f'Detect boss name failed: {e}')
            return ''
        if not name:
            return ''
        return str(name).strip()

    def ocr_hp_percent(self) -> int | None:
        """
        识别鬼王剩余血量百分比，识别失败或者数值异常时返回 None
        """
        try:
            percent = self.O_MD_HP_PERCENT.ocr(self.device.image)
        except Exception as e:
            logger.warning(f'Detect boss hp percent failed: {e}')
            return None
        try:
            value = int(percent)
        except (TypeError, ValueError):
            return None
        if value <= 0 or value > 100:
            logger.warning(f'Invalid boss hp percent: {value}')
            return None
        return value

    def choose_group_team(self) -> list[int] | None:
        """
        选择预设阵容，返回 [group, team]
        未开启策略 / 无法识别时返回 None，使用当前编队
        """
        if not self.config.meta_demon.meta_demon_config.md_use_strategy:
            return None
        detect_name = self.ocr_boss_name()
        logger.info(f'Detect boss name: {detect_name}')
        group_team = self.get_group_team(detect_name)
        if not group_team or len(group_team) < 4:
            return None
        percent = self.ocr_hp_percent()
        threshold = int(self.config.meta_demon.meta_demon_config.md_low_hp_threshold)
        logger.attr('Boss hp percent', percent)
        if percent is not None and percent <= threshold:
            logger.info(f'Hp percent {percent} <= {threshold}, use low hp preset')
            return group_team[2:4]
        logger.info('Use high hp preset')
        return group_team[0:2]


class ScriptTask(RightActivity, GeneralBattle, SwitchSoul, MetaDemonStrategy):

    # 主界面连续多少次无效动作后认为卡住
    MAX_IDLE_ACTIONS = 15
    # 连续多少次挑战失败后返回主界面
    MAX_BATTLE_FAILURES = 3
    # 一次主循环最多尝试召唤多少次
    MAX_SUMMON_ROUNDS = 8
    # 召唤队列最多关闭多少次后放弃任务
    MAX_SUMMON_DIALOG_CLOSE = 3
    # 单场战斗最长等待时间
    BATTLE_WAIT_TIMEOUT = 240

    def run(self):
        if self.config.meta_demon.switch_soul.enable:
            self.goto_page(page_shikigami_records)
            self.run_switch_soul(self.config.meta_demon.switch_soul.switch_group_team)

        if self.config.meta_demon.switch_soul.enable_switch_by_name:
            self.goto_page(page_shikigami_records)
            self.run_switch_soul_by_name(self.config.meta_demon.switch_soul.group_name,
                                         self.config.meta_demon.switch_soul.team_name)

        if not self.enter_meta_demon():
            logger.error('Unable to enter MetaDemon, task exits')
            self.set_next_run(task="MetaDemon", success=False)
            raise TaskEnd

        if self.config.meta_demon.meta_demon_config.meta_crafting_card:
            self.crafting()

        self.run_meta_demon()

        exit_success = self.exit_meta_demon()
        logger.info('Exit MetaDemon')
        self.set_next_run(task="MetaDemon", success=exit_success)
        raise TaskEnd

    def enter_meta_demon(self) -> bool:
        """
        从主界面进入新版祸主降临玩法界面
        新版活动没有“右侧进入”的独立按钮，改为直接点击主界面右侧的“超鬼王”活动图标
        @return: 是否进入成功
        """
        logger.hr('MetaDemon enter', level=1)
        if self.appear(self.I_MD_MAIN):
            return True
        self.goto_page(page_main)
        timer = Timer(60)
        timer.start()
        while 1:
            self.screenshot()
            if self.appear(self.I_MD_MAIN):
                logger.info('Enter MetaDemon main page')
                return True
            if timer.reached():
                logger.error('Enter MetaDemon time out')
                return False
            # 活动首页 -> 祸主降临
            if self.appear(self.I_MD_ENTER2):
                self.appear_then_click(self.I_MD_ENTER2, interval=1.5)
                continue
            # 主界面右侧“超鬼王”活动图标，失败时展开活动栏
            if self.appear(self.I_MD_RIGHT_ENTER):
                self.appear_then_click(self.I_MD_RIGHT_ENTER, interval=2)
                continue
            if self.appear(self.I_MD_TOGGLE_BUTTON):
                self.appear_then_click(self.I_MD_TOGGLE_BUTTON, interval=2)
                continue
            if self.ui_reward_appear_click():
                continue
            if self.appear(self.I_UI_BACK_RED):
                self.appear_then_click(self.I_UI_BACK_RED, interval=1.5)
                continue
            if self.appear(self.I_MD_ENTER_ENSURE):
                self.appear_then_click(self.I_MD_ENTER_ENSURE, interval=1.5)
                continue
        return False

    def run_meta_demon(self):
        """
        玩法主循环：有鬼王就打，没有就协助好友或者召唤鬼王
        """
        logger.hr('MetaDemon battle loop', level=1)
        boss_timer = Timer(60)
        boss_timer.start()
        idle_actions = 0
        battle_failures = 0
        summon_count = 0
        summon_dialog_close = 0
        while 1:
            self.screenshot()
            if boss_timer.reached():
                logger.info('No battle in 60s, exit')
                break
            # 自己或者好友的鬼王详情页
            if self.appear(self.I_MD_CHALLENGE):
                if self.exhaustion_full():
                    logger.info('Exhaustion is full, exit')
                    break
                if self.battle_from_detail():
                    battle_failures = 0
                else:
                    battle_failures += 1
                    logger.warning(f'Battle failed {battle_failures} time(s)')
                    if battle_failures >= self.MAX_BATTLE_FAILURES:
                        logger.warning('Too many battle failures, back to meta main page')
                        self.appear_then_click(self.I_UI_BACK_YELLOW, interval=1.5)
                        battle_failures = 0
                idle_actions = 0
                summon_count = 0
                boss_timer.reset()
                continue
            # 召唤队列弹窗
            if self.appear(self.I_MD_SUMMON_NOW) or self.ocr_appear(self.O_MD_SUMMON_TITLE):
                if summon_count >= self.MAX_SUMMON_ROUNDS:
                    logger.warning('Too many summon, close the summon queue')
                    self.appear_then_click(self.I_MD_RED_BACK, interval=2)
                    summon_count = 0
                    summon_dialog_close += 1
                    if summon_dialog_close >= self.MAX_SUMMON_DIALOG_CLOSE:
                        logger.warning('Summon queue is not usable, exit')
                        break
                    boss_timer.reset()
                    continue
                logger.info('Summon ghost king')
                self.appear_then_click(self.I_MD_SUMMON_NOW, interval=2)
                summon_count += 1
                idle_actions = 0
                boss_timer.reset()
                continue
            # 祸主降临主界面
            if self.appear(self.I_MD_MAIN):
                if self.exhaustion_full():
                    logger.info('Exhaustion is full, exit')
                    break
                self.handle_meta_main()
                idle_actions += 1
                if idle_actions >= self.MAX_IDLE_ACTIONS:
                    logger.warning('Unable to leave meta main page, exit')
                    break
                continue
            # 误退到活动首页
            if self.appear(self.I_MD_ENTER2):
                self.appear_then_click(self.I_MD_ENTER2, interval=1.5)
                continue
            # 通用兜底
            if self.ui_reward_appear_click():
                continue
            if self.appear(self.I_MD_RED_BACK):
                self.appear_then_click(self.I_MD_RED_BACK, interval=1.5)
                continue
            if self.appear(self.I_UI_BACK_RED):
                self.appear_then_click(self.I_UI_BACK_RED, interval=1.5)
                continue
            if self.appear(self.I_MD_ENTER_ENSURE):
                self.appear_then_click(self.I_MD_ENTER_ENSURE, interval=1.5)
                continue
        return

    def handle_meta_main(self) -> bool:
        """
        处理祸主降临主界面：先协助好友，再打自己的鬼王，最后召唤鬼王
        @return: 是否发生了操作
        """
        # 自己没有鬼王
        if self.appear(self.I_MD_BOSS_EMPTY):
            if self.battle_friend_boss():
                return True
            if self.appear_then_click(self.I_MD_FIND_DEMON, interval=2):
                return True
            return False
        # 自己发现里有鬼王，点进详情页
        logger.info('Try to battle boss from self')
        if self.click(self.C_MD_SELF_BOSS_SLOT, interval=1.5):
            return True
        return False

    def battle_friend_boss(self) -> bool:
        """
        好友发现列表里是否有可协助的鬼王，有就点进去
        @return: 是否进入了详情页
        """
        if self.appear(self.I_MD_FRIEND_EMPTY) or self.ocr_appear(self.O_MD_FRIEND_EMPTY_TEXT):
            return False
        if not self.appear(self.I_MD_MAIN):
            return False
        logger.info('Try to battle boss from friends')
        for _ in range(2):
            if self.appear(self.I_MD_CHALLENGE):
                return True
            self.click(self.C_MD_FRIEND_BOSS_AREA, interval=2)
            timer = Timer(4)
            timer.start()
            while not timer.reached():
                self.screenshot()
                if self.appear(self.I_MD_CHALLENGE):
                    return True
        logger.info('No boss from friends')
        return False

    def battle_from_detail(self) -> bool:
        """
        鬼王详情页：选择阵容并挑战
        @return: 战斗是否胜利
        """
        logger.hr('MetaDemon battle', level=2)
        group_team = self.choose_group_team()
        logger.info(f'Preset group team: {group_team}')
        return self.battle_boss(group_team)

    def click_challenge(self, timeout: float = 20, click_limit: int = 3) -> bool:
        """
        点击详情页的挑战按钮，直到按钮消失（进入战斗或者加载界面）
        @return: 按钮是否消失
        """
        clicks = 0
        timer = Timer(timeout)
        timer.start()
        while not timer.reached():
            self.screenshot()
            if not self.appear(self.I_MD_CHALLENGE):
                return True
            if clicks < click_limit and self.appear_then_click(self.I_MD_CHALLENGE, interval=3):
                clicks += 1
        logger.warning('Challenge button is still visible')
        return False

    def wait_battle_enter(self, timeout: float = 15) -> bool:
        """
        等待进入战斗，避免在非战斗页面执行战斗等待
        @return:
        """
        timer = Timer(timeout)
        timer.start()
        while not timer.reached():
            self.screenshot()
            if self.is_in_battle(False) or self.is_in_prepare(False):
                return True
        logger.warning('Wait battle enter time out')
        return False

    def battle_boss(self, group_team: list[int] | None = None) -> bool:
        logger.info('Battle boss')
        if not self.click_challenge():
            logger.warning('Unable to enter battle, skip this boss')
            return False
        if not self.wait_battle_enter():
            logger.warning('Not in battle after clicking challenge')
            return False
        battle_config = GeneralBattleConfig()
        battle_config.lock_team_enable = False
        if group_team is None or len(group_team) < 2:
            battle_config.preset_enable = False
            return bool(self.run_general_battle(battle_config))
        # 使用预设队伍阵容
        battle_config.preset_enable = True
        battle_config.preset_group = group_team[0]
        battle_config.preset_team = group_team[1]
        # 每场战斗都需要重新切换预设，因此把 current_count 归零后再恢复
        tmp_battle_count = self.current_count
        self.current_count = 0
        try:
            success = self.run_general_battle(battle_config)
        finally:
            self.current_count = tmp_battle_count + 1
        return bool(success)

    def battle_wait(self, random_click_swipt_enable: bool) -> bool:
        """
        战斗等待：保留胜负判定、鬼王标记与随机点击，并增加整体超时，
        避免战斗页面卡死时无限等待
        """
        self.device.stuck_record_add('BATTLE_STATUS_S')
        self.device.click_record_clear()
        logger.info('Start battle process')
        self.boss_mark_reset()
        timer = Timer(self.BATTLE_WAIT_TIMEOUT)
        timer.start()
        while not timer.reached():
            self.screenshot()
            if self.appear(self.I_WIN, threshold=0.8) or self.appear(self.I_DE_WIN):
                logger.info('Battle result is win')
                if self.appear(self.I_DE_WIN):
                    self.ui_click_until_disappear(self.I_DE_WIN)
                self.collect_reward()
                return True
            if self.appear(self.I_FALSE, threshold=0.8) or self.appear(self.I_MD_BATTLE_FAILURE):
                logger.warning('Battle result is false')
                if self.appear(self.I_FALSE, threshold=0.8):
                    self.ui_click_until_disappear(self.I_FALSE)
                else:
                    self.ui_click_until_disappear(self.I_MD_BATTLE_FAILURE)
                return False
            if self.appear(self.I_REWARD, threshold=0.6) or self.appear(self.I_REWARD_GOLD, threshold=0.8):
                logger.info('Battle result is win, reward appeared')
                self.collect_reward()
                return True
            if random_click_swipt_enable:
                self.random_click_swipt()
            self.boss_mark()
        logger.warning('Battle wait time out')
        return False

    def collect_reward(self, timeout: float = 15):
        """
        点击战斗结算奖励，直到回到详情页或者主界面
        """
        timer = Timer(timeout)
        timer.start()
        while not timer.reached():
            self.screenshot()
            if self.appear(self.I_MD_CHALLENGE) or self.appear(self.I_MD_MAIN) or self.appear(self.I_CHECK_MAIN):
                break
            if self.appear(self.I_WIN, threshold=0.8):
                self.ui_click_until_disappear(self.I_WIN)
                continue
            if self.appear(self.I_REWARD, threshold=0.6) or self.appear(self.I_REWARD_GOLD, threshold=0.8):
                self.ui_reward_appear_click()
                continue
            if not self.ui_reward_appear_click():
                break

    def exhaustion_full(self) -> bool:
        """
        疲劳值是否已满
        @return:
        """
        self.screenshot()
        try:
            current, _, total = self.O_MD_EXHAUSTION.ocr(self.device.image)
        except Exception as e:
            logger.warning(f'Detect exhaustion failed: {e}')
            return False
        logger.attr('Exhaustion', f'{current}/{total}')
        if not total:
            return False
        return int(current) >= int(total)

    def buy_tea(self):
        pass

    def crafting(self):
        """
        新版祸主降临的“合成”入口位于主界面右侧，合成界面没有对应的模板资源，
        这里保留配置项但不执行合成，避免误点消耗资源
        @return:
        """
        logger.info('Skip crafting: new crafting UI is not supported yet')

    def exit_meta_demon(self) -> bool:
        """
        退出活动，回到主界面
        @return: 是否回到主界面
        """
        logger.hr('MetaDemon exit', level=1)
        timer = Timer(30)
        timer.start()
        while not timer.reached():
            self.screenshot()
            if self.appear(self.I_CHECK_MAIN):
                logger.info('Back to main page')
                return True
            if self.appear(self.I_UI_BACK_YELLOW):
                self.appear_then_click(self.I_UI_BACK_YELLOW, interval=1.2)
                continue
            if self.appear(self.I_UI_BACK_RED):
                self.appear_then_click(self.I_UI_BACK_RED, interval=1.2)
                continue
            if self.appear(self.I_MD_RED_BACK):
                self.appear_then_click(self.I_MD_RED_BACK, interval=1.2)
                continue
            if self.ui_reward_appear_click():
                continue
        logger.warning('Exit MetaDemon time out')
        return False


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)

    t.run()