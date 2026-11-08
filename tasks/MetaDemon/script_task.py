# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import random

from cached_property import cached_property

from module.base.timer import Timer
from module.exception import TaskEnd
from module.logger import logger

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.RightActivity.right_activity import RightActivity
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main, page_shikigami_records, random_click
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

    # 兜底按钮单个循环里最多处理的次数，避免触发连点风控
    MAX_FALLBACK_CLICKS = 5
    # 连续多少次挑战失败后结束本次任务
    MAX_BATTLE_FAILURES = 3
    # 一次主循环最多尝试召唤多少次
    MAX_SUMMON_ROUNDS = 8
    # 召唤队列最多关闭多少次后放弃任务
    MAX_SUMMON_DIALOG_CLOSE = 3
    # 单场战斗最长等待时间
    BATTLE_WAIT_TIMEOUT = 240
    # 连续多久没有任何有效动作就退出
    IDLE_TIMEOUT = 40
    # 活动栏“换一批”按钮最多点击次数，需要翻页到出现超鬼王图标
    MAX_TOGGLE_CLICKS = 12

    def run(self):
        if self.config.meta_demon.switch_soul.enable:
            self.goto_page(page_shikigami_records)
            self.run_switch_soul(self.config.meta_demon.switch_soul.switch_group_team)

        if self.config.meta_demon.switch_soul.enable_switch_by_name:
            self.goto_page(page_shikigami_records)
            self.run_switch_soul_by_name(self.config.meta_demon.switch_soul.switch_group_name,
                                         self.config.meta_demon.switch_soul.switch_team_name)

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

    def fallback_click(self, rule, interval: float, counts: dict, limit: int = None) -> int:
        """
        兜底点击：带次数上限，避免同一按钮触发连点风控
        @return: 0 规则没出现, 1 已处理, 2 超过次数上限
        """
        if not self.appear(rule):
            return 0
        limit = limit if limit is not None else self.MAX_FALLBACK_CLICKS
        name = str(getattr(rule, 'name', rule))
        if counts.get(name, 0) >= limit:
            return 2
        # 只有真正发生了点击才计数：interval 未到时 appear_then_click 不会点击
        if self.appear_then_click(rule, interval=interval):
            counts[name] = counts.get(name, 0) + 1
        return 1

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
        counts = {}
        act_entry_selected = False
        while 1:
            self.screenshot()
            if self.appear(self.I_MD_MAIN):
                logger.info('Enter MetaDemon main page')
                return True
            if timer.reached():
                logger.error('Enter MetaDemon time out')
                return False
            # 活动首页 -> 祸主降临
            result = self.fallback_click(self.I_MD_ENTER2, 1.5, counts)
            if result == 2:
                logger.error('Too many clicks on the activity entry')
                return False
            if result == 1:
                continue
            # 主界面右侧“超鬼王”活动图标，失败时展开活动栏
            result = self.fallback_click(self.I_MD_RIGHT_ENTER, 2, counts)
            if result == 2:
                logger.error('Too many clicks on the activity icon')
                return False
            if result == 1:
                continue
            # 活动栏翻页也可能找不到图标（展开状态没有“换一批”按钮），改走“活动总览”
            result = self.fallback_click(self.I_ACT_LIST_EXPAND, 2, counts)
            if result == 2:
                logger.error('Too many clicks on the activity overview button')
                return False
            if result == 1:
                continue
            if self.appear(self.I_CHECK_ACT_LIST):
                # 活动总览：先选中“祸至无日”，再点击“前往活动”
                if not act_entry_selected:
                    if self.ocr_appear(self.O_MD_ACT_ENTRY):
                        self.click(self.O_MD_ACT_ENTRY, interval=1.5)
                    else:
                        self.click(self.C_MD_ACT_FIRST_ITEM, interval=1.5)
                    act_entry_selected = True
                    continue
                result = self.fallback_click(self.I_ACT_LIST_GOTO_ACT, 2, counts, limit=8)
                if result == 2:
                    logger.error('Too many clicks on the go to activity button')
                    return False
                if result == 1:
                    continue
            result = self.fallback_click(self.I_MD_TOGGLE_BUTTON, 2, counts, limit=self.MAX_TOGGLE_CLICKS)
            if result == 2:
                logger.error('Too many clicks on the activity toggle')
                return False
            if result == 1:
                continue
            if self.ui_reward_appear_click():
                continue
            result = self.fallback_click(self.I_UI_BACK_RED, 1.5, counts)
            if result == 2:
                logger.error('Too many clicks on the red back button')
                return False
            if result == 1:
                continue
            result = self.fallback_click(self.I_MD_ENTER_ENSURE, 1.5, counts)
            if result == 2:
                logger.error('Too many clicks on the enter confirm button')
                return False
            if result == 1:
                continue
        return False

    def run_meta_demon(self):
        """
        玩法主循环：有鬼王就打，没有就协助好友或者召唤鬼王
        """
        logger.hr('MetaDemon battle loop', level=1)
        boss_timer = Timer(60)
        boss_timer.start()
        idle_timer = Timer(self.IDLE_TIMEOUT)
        idle_timer.start()
        battle_failures = 0
        result_page_fail = 0
        summon_count = 0
        summon_dialog_close = 0
        counts = {}
        while 1:
            self.screenshot()
            if boss_timer.reached():
                logger.info('No battle in 60s, exit')
                break
            if idle_timer.reached():
                logger.warning('Unable to leave current page, exit')
                break
            # 残留的战斗胜利结算页：点击屏幕继续，避免卡死
            if self.appear(self.I_WIN, threshold=0.8) or self.appear(self.I_DE_WIN):
                logger.info('Close battle result page')
                if self.appear(self.I_DE_WIN):
                    self.ui_click_until_disappear(self.I_DE_WIN)
                    closed = not self.appear(self.I_DE_WIN)
                else:
                    closed = self.click_win_result()
                if closed is False:
                    result_page_fail += 1
                    if result_page_fail >= 2:
                        logger.warning('Victory result page cannot be closed, exit')
                        break
                else:
                    result_page_fail = 0
                idle_timer.reset()
                continue
            # 自己或者好友的鬼王详情页
            if self.appear(self.I_MD_CHALLENGE):
                if self.exhaustion_full():
                    logger.info('Exhaustion is full, exit')
                    break
                if self.battle_from_detail():
                    battle_failures = 0
                    boss_timer.reset()
                    idle_timer.reset()
                    counts = {}
                else:
                    battle_failures += 1
                    logger.warning(f'Battle failed {battle_failures} time(s)')
                    if battle_failures >= self.MAX_BATTLE_FAILURES:
                        logger.warning('Too many battle failures, exit')
                        break
                    self.leave_detail()
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
                    idle_timer.reset()
                    continue
                logger.info('Summon ghost king')
                self.appear_then_click(self.I_MD_SUMMON_NOW, interval=2)
                summon_count += 1
                boss_timer.reset()
                idle_timer.reset()
                continue
            # 祸主降临主界面
            if self.appear(self.I_MD_MAIN):
                if self.exhaustion_full():
                    logger.info('Exhaustion is full, exit')
                    break
                if self.handle_meta_main():
                    boss_timer.reset()
                    idle_timer.reset()
                continue
            # 误退到活动首页
            result = self.fallback_click(self.I_MD_ENTER2, 1.5, counts)
            if result == 2:
                logger.warning('Too many clicks on the activity entry, exit')
                break
            if result == 1:
                continue
            # 通用兜底
            if self.ui_reward_appear_click():
                idle_timer.reset()
                continue
            result = self.fallback_click(self.I_MD_RED_BACK, 1.5, counts)
            if result == 2:
                logger.warning('Too many clicks on the red close button, exit')
                break
            if result == 1:
                continue
            result = self.fallback_click(self.I_UI_BACK_RED, 1.5, counts)
            if result == 2:
                logger.warning('Too many clicks on the back button, exit')
                break
            if result == 1:
                continue
            result = self.fallback_click(self.I_MD_ENTER_ENSURE, 1.5, counts)
            if result == 2:
                logger.warning('Too many clicks on the enter confirm button, exit')
                break
            if result == 1:
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
        for attempt in range(2):
            if self.appear(self.I_MD_CHALLENGE):
                return True
            # 第二次点击前确认仍在玩法主页，避免盲点详情页
            if attempt and not self.appear(self.I_MD_MAIN):
                return False
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
        等待进入战斗，避免在非战斗页面执行战斗等待。
        挑战按钮已经消失，所以这里只需确认战斗/准备页的资源命中。
        @return:
        """
        timer = Timer(timeout)
        timer.start()
        while not timer.reached():
            self.screenshot()
            if self.appear(self.I_BATTLE_INFO) or self.appear(self.I_PREPARE_HIGHLIGHT):
                return True
            if self.is_in_battle(False) or self.is_in_prepare(False):
                return True
        logger.warning('Wait battle enter time out')
        return False

    def leave_detail(self, timeout: float = 8) -> bool:
        """
        从鬼王详情页返回玩法主页
        @return: 是否离开了详情页
        """
        logger.info('Leave boss detail page')
        timer = Timer(timeout)
        timer.start()
        while not timer.reached():
            self.screenshot()
            if not self.appear(self.I_MD_CHALLENGE):
                return True
            self.appear_then_click(self.I_UI_BACK_YELLOW, interval=3)
        logger.warning('Still on boss detail page')
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
                else:
                    # 新版超鬼王的胜利结算页没有奖励按钮，需要点击屏幕继续
                    self.click_win_result()
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

    def click_win_result(self, timeout: float = 10) -> bool:
        """
        新版超鬼王的胜利结算页（胜利横幅 + 本次伤害/累计伤害）没有任何按钮，
        需要点击屏幕任意位置继续。这里持续点击胜利横幅直到它消失
        @return: 胜利横幅是否已经消失
        """
        logger.info('Click win result page')
        timer = Timer(timeout)
        timer.start()
        while not timer.reached():
            self.screenshot()
            if not self.appear(self.I_WIN, threshold=0.8):
                return True
            # 点击间隔 2.5s，避免同一控件在 15 次点击窗口内堆到连点上限
            self.appear_then_click(self.I_WIN,
                                   action=random.choice([self.C_WIN_1, self.C_WIN_2, self.C_WIN_3]),
                                   interval=2.5)
        result = not self.appear(self.I_WIN, threshold=0.8)
        if not result:
            logger.warning('Win result page is still visible')
        return result

    def collect_reward(self, timeout: float = 20):
        """
        点击战斗结算奖励，直到回到详情页或者主界面。
        点击逻辑对齐 GeneralBattle.battle_wait 的领奖段（鼓/金币/庆祝/特殊奖励）
        """
        # 与 GeneralBattle.battle_wait 一致：先等奖励图标出现，避免结算加载空帧直接跳过领奖
        if not self.wait_until_appear(self.I_REWARD, wait_time=5):
            if not self.appear(self.I_STATISTICS):
                logger.warning('No reward button appeared, skip collect')
                return
        timer = Timer(timeout)
        timer.start()
        missing_reward = 0
        while not timer.reached():
            self.screenshot()
            action_reward = random.choice([self.C_REWARD_1, self.C_REWARD_2, self.C_REWARD_3])
            if self.appear(self.I_OVER_GHOST):
                self.click(self.I_OVER_GHOST)
                missing_reward = 0
                continue
            if self.appear(self.I_REWARD) and \
                    self.appear_then_click(self.I_REWARD, action=action_reward, interval=1.5):
                missing_reward = 0
                continue
            if self.appear(self.I_REWARD_GOLD) and \
                    self.appear_then_click(self.I_REWARD_GOLD, action=action_reward, interval=1.5):
                missing_reward = 0
                continue
            if self._hook_special_reward():
                missing_reward = 0
                continue
            if self.appear(self.I_WIN) and \
                    self.appear_then_click(self.I_WIN,
                                           action=random.choice([self.C_WIN_1, self.C_WIN_2, self.C_WIN_3]),
                                           interval=1.0):
                missing_reward = 0
                continue
            if self.ui_reward_appear_click():
                missing_reward = 0
                continue
            # 奖励/胜利控件仍然可见时只是处于点击冷却期，不算消失
            if self.appear(self.I_REWARD) or self.appear(self.I_REWARD_GOLD) or \
                    self.appear(self.I_OVER_GHOST) or self.appear(self.I_WIN):
                missing_reward = 0
                continue
            missing_reward += 1
            # 奖励资源连续两帧都不出现，认为结算已经结束（回到详情页/主界面）
            if missing_reward >= 2:
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
        counts = {}
        no_action = 0
        random_clicks = 0
        while not timer.reached():
            self.screenshot()
            if self.appear(self.I_CHECK_MAIN):
                logger.info('Back to main page')
                return True
            # 胜利结算页没有返回按钮，只能点击屏幕继续
            if self.appear(self.I_WIN, threshold=0.8) or self.appear(self.I_DE_WIN):
                if self.appear(self.I_DE_WIN):
                    self.ui_click_until_disappear(self.I_DE_WIN)
                else:
                    self.click_win_result(timeout=6)
                no_action = 0
                continue
            if self.appear(self.I_REWARD, threshold=0.6) or self.appear(self.I_REWARD_GOLD, threshold=0.8):
                self.collect_reward(timeout=8)
                no_action = 0
                continue
            result = self.fallback_click(self.I_UI_BACK_YELLOW, 1.5, counts)
            if result == 2:
                logger.warning('Too many clicks on the back button, stop exiting')
                break
            if result == 1:
                no_action = 0
                continue
            result = self.fallback_click(self.I_UI_BACK_RED, 1.5, counts)
            if result == 2:
                logger.warning('Too many clicks on the red back button, stop exiting')
                break
            if result == 1:
                no_action = 0
                continue
            result = self.fallback_click(self.I_MD_RED_BACK, 1.5, counts)
            if result == 2:
                logger.warning('Too many clicks on the close button, stop exiting')
                break
            if result == 1:
                no_action = 0
                continue
            if self.ui_reward_appear_click():
                no_action = 0
                continue
            # 完全没有已知控件时有限次点击屏幕安全区域推进未知页面，避免连点风控
            no_action += 1
            if no_action >= 8 and random_clicks < 4:
                self.click(random_click())
                random_clicks += 1
                no_action = 0
        logger.warning('Exit MetaDemon time out, fallback to main page')
        # 兜底：交给页面导航器回到主界面，避免任务结束后游戏卡在未知页面
        try:
            self.goto_page(page_main)
        except Exception as e:
            logger.warning(f'Goto main page failed: {e}')
            return False
        return bool(self.appear(self.I_CHECK_MAIN))


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)

    t.run()