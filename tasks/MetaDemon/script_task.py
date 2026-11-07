# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from cached_property import cached_property
from time import sleep

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
        先是默认的完全匹配，然后是1个字符不同，最后是2个字符不同
        @param strategies:
        @param detect_name:
        @return:
        """
        for i in range(2):
            for key_name in strategies:
                if len(key_name) != len(detect_name):
                    continue
                diff_count = sum(1 for c1, c2 in zip(key_name, detect_name) if c1 != c2)
                if diff_count <= i < len(detect_name):
                    return strategies[key_name]
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
        try:
            percent = self.O_MD_HP_PERCENT.ocr(self.device.image)
        except Exception as e:
            logger.warning(f'Detect boss hp percent failed: {e}')
            return None
        try:
            return int(percent)
        except (TypeError, ValueError):
            return None

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

    def run(self):
        if self.config.meta_demon.switch_soul.enable:
            self.goto_page(page_shikigami_records)
            self.run_switch_soul(self.config.meta_demon.switch_soul.switch_group_team)

        if self.config.meta_demon.switch_soul.enable_switch_by_name:
            self.goto_page(page_shikigami_records)
            self.run_switch_soul_by_name(self.config.meta_demon.switch_soul.group_name,
                                         self.config.meta_demon.switch_soul.team_name)

        self.enter_meta_demon()

        if self.config.meta_demon.meta_demon_config.meta_crafting_card:
            self.crafting()

        self.run_meta_demon()

        self.exit_meta_demon()
        logger.info('Exit MetaDemon')
        self.set_next_run(task="MetaDemon", success=True)
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
                if self.appear_then_click(self.I_MD_ENTER2, interval=1.5):
                    continue
            # 主界面右侧“超鬼王”活动图标，失败时展开活动栏
            if self.appear(self.I_MD_RIGHT_ENTER):
                if self.appear_then_click(self.I_MD_RIGHT_ENTER, interval=2):
                    continue
            if self.appear_then_click(self.I_MD_TOGGLE_BUTTON, interval=2):
                continue
            if self.ui_reward_appear_click():
                continue
            if self.appear_then_click(self.I_UI_BACK_RED, interval=1.5):
                continue
            if self.appear_then_click(self.I_MD_ENTER_ENSURE, interval=1.5):
                continue
        return False

    def run_meta_demon(self):
        """
        玩法主循环：有鬼王就打，没有就协助好友或者召唤鬼王
        """
        logger.hr('MetaDemon battle loop', level=1)
        boss_timer = Timer(60)
        boss_timer.start()
        summon_count = 0
        while 1:
            self.screenshot()
            if boss_timer.reached():
                logger.info('Time out, exit')
                break
            # 自己或者好友的鬼王详情页
            if self.appear(self.I_MD_CHALLENGE):
                self.battle_from_detail()
                summon_count = 0
                boss_timer.reset()
                continue
            # 召唤队列弹窗
            if self.appear(self.I_MD_SUMMON_NOW) or self.ocr_appear(self.O_MD_SUMMON_TITLE):
                if summon_count > 20:
                    logger.warning('Too many summon, close the queue')
                    self.appear_then_click(self.I_MD_RED_BACK, interval=2)
                    summon_count = 0
                    continue
                logger.info('Summon ghost king')
                self.appear_then_click(self.I_MD_SUMMON_NOW, interval=2)
                summon_count += 1
                boss_timer.reset()
                continue
            # 祸主降临主界面
            if self.appear(self.I_MD_MAIN):
                if self.exhaustion_full():
                    logger.info('Exhaustion is full, exit')
                    break
                if self.handle_meta_main():
                    boss_timer.reset()
                continue
            # 误退到活动首页
            if self.appear(self.I_MD_ENTER2):
                self.appear_then_click(self.I_MD_ENTER2, interval=1.5)
                continue
            # 通用兜底
            if self.ui_reward_appear_click():
                continue
            if self.appear_then_click(self.I_MD_RED_BACK, interval=1.5):
                continue
            if self.appear_then_click(self.I_UI_BACK_RED, interval=1.5):
                continue
            if self.appear_then_click(self.I_MD_ENTER_ENSURE, interval=1.5):
                continue

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

    def battle_boss(self, group_team: list[int] | None = None) -> bool:
        logger.info('Battle boss')
        self.ui_click_until_disappear(self.I_MD_CHALLENGE, interval=1.8)
        battle_config = GeneralBattleConfig()
        battle_config.lock_team_enable = False
        if group_team is None or len(group_team) < 2:
            battle_config.preset_enable = False
            success = self.run_general_battle(battle_config)
            return bool(success)
        # 使用预设队伍阵容
        battle_config.preset_enable = True
        battle_config.preset_group = group_team[0]
        battle_config.preset_team = group_team[1]
        tmp_battle_count = self.current_count
        self.current_count = 0
        success = self.run_general_battle(battle_config)
        self.current_count = tmp_battle_count + 1
        return bool(success)

    def battle_wait(self, random_click_swipt_enable: bool) -> bool:
        # 重写
        self.device.stuck_record_add('BATTLE_STATUS_S')
        self.device.click_record_clear()
        logger.info("Start battle process")
        self.boss_mark_reset()
        while 1:
            self.screenshot()
            if self.appear(self.I_WIN):
                logger.info('Win battle')
                self.ui_click_until_disappear(self.I_WIN)
                return True

            if self.appear(self.I_MD_BATTLE_FAILURE):
                logger.warning('False battle')
                self.ui_click_until_disappear(self.I_MD_BATTLE_FAILURE)
                return False
            if self.boss_mark():
                continue

    def current_exhaustion(self) -> int:
        """
        当前疲劳值
        @return:
        """
        self.screenshot()
        try:
            current, _, _ = self.O_MD_EXHAUSTION.ocr(self.device.image)
        except Exception as e:
            logger.warning(f'Detect exhaustion failed: {e}')
            return 0
        return int(current)

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

    def exit_meta_demon(self):
        """
        退出活动，回到主界面
        @return:
        """
        logger.hr('MetaDemon exit', level=1)
        timer = Timer(30)
        timer.start()
        while not timer.reached():
            self.screenshot()
            if self.appear(self.I_CHECK_MAIN):
                logger.info('Back to main page')
                return
            if self.appear_then_click(self.I_UI_BACK_YELLOW, interval=1.2):
                continue
            if self.appear_then_click(self.I_UI_BACK_RED, interval=1.2):
                continue
            if self.appear_then_click(self.I_MD_RED_BACK, interval=1.2):
                continue
            if self.ui_reward_appear_click():
                continue
        logger.warning('Exit MetaDemon time out')


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)

    t.run()