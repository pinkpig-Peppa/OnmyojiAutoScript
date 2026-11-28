# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey

import inspect
import inflection
import random
from typing import Union
from datetime import datetime, timedelta
from pathlib import Path
from time import monotonic, sleep, time

from module.atom.animate import RuleAnimate
from module.atom.click import RuleClick
from module.atom.gif import RuleGif
from module.atom.image import RuleImage
from module.atom.list import RuleList
from module.atom.long_click import RuleLongClick
from module.atom.ocr import RuleOcr
from module.atom.swipe import RuleSwipe
from module.base.timer import Timer
from module.config.config import Config
from module.device.confirm_retry import click_confirm_once
from module.device.device import Device
from module.exception import ScriptError, TaskRecoveryFailed
from module.logger import logger
from module.ocr.base_ocr import OcrMode

from tasks.Component.Costume.costume_base import CostumeBase
from tasks.Component.config_base import Time
from tasks.GlobalGame.assets import GlobalGameAssets
from tasks.GlobalGame.config_emergency import FriendInvitation



class BaseTask(GlobalGameAssets, CostumeBase):
    config: Config = None
    device: Device = None

    folder: str
    name: str
    stage: str

    limit_time: timedelta = None  # 限制运行的时间，是软时间，不是硬时间
    limit_count: int = None  # 限制运行的次数
    current_count: int = None  # 当前运行的次数

    def __init__(self, config: Config, device: Device) -> None:
        """

        :rtype: object
        """
        self.config = config
        self.device = device

        self.interval_timer = {}  # 这个是用来记录每个匹配的运行间隔的，用于控制运行频率
        self.animates = {}  # 保存缓存
        self.start_time = datetime.now()  # 启动的时间
        self.check_costume(self.config.global_game.costume_config)
        # self.friend_timer = None  # 这个是用来记录勾协的时间的
        # if self.config.global_game.emergency.invitation_detect_interval:
        #     self.interval_time = self.config.global_game.emergency.invitation_detect_interval
        #     self.friend_timer = Timer(self.interval_time)
        #     self.friend_timer.start()

        # 战斗次数相关
        self.current_count = 0  # 战斗次数
        self._boss_mark_flag = False

    def get_task_name(self) -> str:
        model_task_name = getattr(self.config.model, 'running_task', '')
        class_file = inspect.getfile(type(self))
        path_task_name = Path(class_file).parent.name

        model_task_name = (
            inflection.camelize(model_task_name, uppercase_first_letter=True)
            if model_task_name else ''
        )
        path_task_name = inflection.camelize(
            path_task_name,
            uppercase_first_letter=True,
        )

        # if model_task_name and model_task_name != path_task_name:
        #     raise ScriptError(
        #         f'Task name mismatch: model={model_task_name}, path={path_task_name}'
        #     )
        return model_task_name or path_task_name

    def _perf_timeout(self, seconds: float) -> float:
        performance = getattr(self.device, 'performance', None)
        return performance.timeout(seconds) if performance is not None else seconds

    def _default_wait_timeout(self) -> float:
        """Bound implicit waits without shortening a configured long battle or gathering."""
        from math import isfinite
        global_battle = getattr(getattr(self.config, 'global_game', None), 'battle', None)
        context = getattr(self, '_battle_context', None)
        candidates = (
            420,
            getattr(global_battle, 'battle_timeout', None),
            getattr(getattr(context, 'battle_timer', None), 'limit', None),
        )
        limits = []
        for value in candidates:
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
            if isfinite(value) and value > 0:
                limits.append(value)
        return max(limits)

    def _invitation_identity(self):
        image = getattr(self.device, 'image', None)
        if image is None or not hasattr(image, 'shape') or image.shape[:2] != (720, 1280):
            return None
        # Exclude the animated avatar, monster illustration and close-button sparkle.
        return image[240:276, 578:772].copy()

    def _invitation_identity_changed(self, previous) -> bool:
        import numpy as np
        current = self._invitation_identity()
        if current is None or previous is None or current.shape != previous.shape:
            return False
        difference = np.max(np.abs(current.astype(np.int16) - previous.astype(np.int16)), axis=2)
        return float(np.mean(difference > 35)) > 0.12

    def _burst(self) -> bool:
        """
        游戏界面突发异常检测（有界单次点击与双新鲜帧确认）
        :return: 没有出现返回False, 其他True
        """
        appear_invitation = self.appear(self.I_G_ACCEPT)
        if not appear_invitation:
            return False
        identity = self._invitation_identity()
        logger.info('Invitation appearing')
        invite_type = self.config.global_game.emergency.friend_invitation
        detect_record = set(getattr(self.device, 'detect_record', ()))
        match invite_type:
            case FriendInvitation.ACCEPT:
                logger.info("Accept friend invitation")
                click_button = self.I_G_ACCEPT
            case FriendInvitation.REJECT:
                logger.info("Reject friend invitation")
                click_button = self.I_G_REJECT
            case FriendInvitation.ONLY_JADE:
                # 勾协
                logger.info("Only accept jade invitation")
                if self.appear(self.I_G_JADE):
                    click_button = self.I_G_ACCEPT
                else:
                    click_button = self.I_G_IGNORE
            case FriendInvitation.JADE_AND_FOOD:
                # 如果是接受勾协和粮协
                logger.info("Accept jade and food invitation")
                if self.appear(self.I_G_JADE) or self.appear(self.I_G_CAT_FOOD) or self.appear(self.I_G_DOG_FOOD):
                    click_button = self.I_G_ACCEPT
                else:
                    click_button = self.I_G_IGNORE
            case FriendInvitation.IGNORE:
                # 如果是忽略
                logger.info("Ignore friend invitation")
                click_button = self.I_G_IGNORE
            case _:
                raise ScriptError(f'Unknown friend invitation type: {invite_type}')
        if not click_button:
            raise ScriptError(f'Unknown click button type: {invite_type}')

        deadline = monotonic() + self._perf_timeout(12)
        generation = getattr(self.device, '_escape_generation', 0)
        clicked, stable = False, 0
        try:
            # Direct capture avoids recursively handling this invitation through screenshot().
            while monotonic() < deadline:
                self.device.screenshot()
                if getattr(self.device, '_escape_generation', 0) != generation:
                    raise TaskRecoveryFailed('Invitation verification interrupted by recovery')
                vanished = not self.appear(self.I_G_ACCEPT) and not self.appear(click_button)
                # A queued invitation can replace this card without hiding Accept.
                replaced = clicked and identity is not None and self._invitation_identity_changed(identity)
                vanished = vanished or replaced
                stable = stable + 1 if vanished else 0
                if stable >= 2:
                    if clicked:
                        confirm = getattr(self.device, 'confirm_control_progress', None)
                        if callable(confirm):
                            confirm([click_button])
                    logger.info('Deal with invitation done')
                    break
                if not clicked and not vanished:
                    if self.appear(click_button):
                        if not self.appear_then_click(click_button):
                            raise TaskRecoveryFailed('Invitation input was blocked')
                        clicked = True
            else:
                raise TaskRecoveryFailed('Invitation did not close after one click')
        finally:
            # Preserve the caller's battle guard even when invitation verification fails.
            self.device.detect_record = detect_record

        # 如果接受邀请则立即执行悬赏任务
        if clicked and click_button == self.I_G_ACCEPT:
            self.set_next_run(task='WantedQuests', target=datetime.now().replace(microsecond=0), server=False)
            self.device._accepted_invitation_generation = getattr(self.device, '_accepted_invitation_generation', 0) + 1
        return True

    def screenshot(self):
        """
        截图 引入中间函数的目的是 为了解决如协作的这类突发的事件
        :return:
        """
        self.device.screenshot()
        from module.device.escape_popup import game_exit_cancel_point
        from tasks.Component.escape_recovery import handle_escape_recovery
        cancel_point = game_exit_cancel_point(self.device.image)
        if cancel_point is not None:
            logger.warning('Cancel exit-game dialog before task page matching')
            self.device.click(*cancel_point, control_check=False, control_name='EXIT_GAME_CANCEL')
            self.device.screenshot()
        handle_escape_recovery(self)
        # 判断勾协
        self._burst()

        # # 判断网络异常
        # if self.appear(self.I_NETWORK_ABNORMAL):
        #     logger.warning(f"Network abnormal")
        #     raise GameStuckError
        #
        # # 判断网络错误
        # if self.appear(self.I_NETWORK_ERROR):
        #     logger.warning(f"Network error")
        #     raise GameStuckError

        return self.device.image

    def maybe_screenshot(self, soft_skip: bool = False):
        """
        可能截图
        :param soft_skip: True跳过截图(但保证设备一定有图才跳过,否则依然截图)
        :return:
        """
        if not soft_skip or not self.exist_image():
            return self.screenshot()
        return self.device.image

    def exist_image(self) -> bool:
        """
        判断当前设备是否有图片
        :return: 有返回True，没有返回False
        """
        return hasattr(self.device, 'image') and self.device.image is not None

    def appear(self,
               target: RuleImage | RuleGif | RuleOcr,
               interval: float = None,
               threshold: float = None):
        """

        :param target: 匹配的目标可以是RuleImage, 也可以是RuleOcr
        :param interval:
        :param threshold:
        :return: interval时间到达且匹配成功则返回True, 否则False
        """
        if interval:
            if target.name in self.interval_timer:
                if self.interval_timer[target.name].limit != interval:
                    self.interval_timer[target.name] = Timer(interval)
            else:
                self.interval_timer[target.name] = Timer(interval)
            if not self.interval_timer[target.name].reached():
                return False
        if isinstance(target, RuleOcr):
            appear = self.ocr_appear(target, interval)
        else:
            appear = target.match(self.device.image, threshold=threshold)

        if appear and interval:
            self.interval_timer[target.name].reset()

        return appear

    def appear_then_click(self,
                          target: RuleImage | RuleGif | RuleOcr,
                          action: Union[RuleClick, RuleLongClick] = None,
                          interval: float = None,
                          threshold: float = None,
                          duration: float = None):
        """
        出现了就点击，默认点击图片的位置，如果添加了click参数，就点击click的位置
        :param duration: 如果是长按，可以手动指定duration，不指定默认.单位是ms！！！！
        :param action: 可以是RuleClick, 也可以是RuleLongClick
        :param target: 可以是RuleImage后续支持RuleOcr
        :param interval:
        :param threshold:
        :return: True or False
        """
        appear = self.appear(target, interval=interval, threshold=threshold)
        if appear and not action:
            x, y = target.coord()
            if self.device.click(x, y, control_name=target.name) is False:
                return False

        elif appear and action:
            x, y = action.coord()
            if isinstance(action, RuleLongClick):
                if duration is None:
                    if self.device.long_click(x, y, duration=action.duration / 1000, control_name=target.name) is False:
                        return False
                else:
                    if self.device.long_click(x, y, duration=duration / 1000, control_name=target.name) is False:
                        return False
            elif isinstance(action, RuleClick):
                if self.device.click(x, y, control_name=target.name) is False:
                    return False

        return appear

    def appear_multi_scale(self,
                           target: RuleImage,
                           interval: float = None,
                           threshold: float = None,
                           scales: list = None,
                           scale_range: tuple = None):
        """
        多尺度图片识别，自动尝试多个缩放比例以适应图片大小的变化
        :param target: RuleImage对象
        :param interval: 匹配间隔时间
        :param threshold: 匹配阈值
        :param scales: 缩放比例列表
        :param scale_range: 缩放范围 (start, end, step)，例如 (0.8, 1.2, 0.1)
        :return: interval时间到达且匹配成功则返回True, 否则False
        """
        if interval:
            if target.name in self.interval_timer:
                if self.interval_timer[target.name].limit != interval:
                    self.interval_timer[target.name] = Timer(interval)
            else:
                self.interval_timer[target.name] = Timer(interval)
            if not self.interval_timer[target.name].reached():
                return False

        appear = target.match_multi_scale(self.device.image, threshold=threshold, scales=scales, scale_range=scale_range)

        if appear and interval:
            self.interval_timer[target.name].reset()

        return appear

    def appear_then_click_multi_scale(self,
                                      target: RuleImage,
                                      action: Union[RuleClick, RuleLongClick] = None,
                                      interval: float = None,
                                      threshold: float = None,
                                      scales: list = None,
                                      scale_range: tuple = None,
                                      duration: float = None):
        """
        多尺度图片识别并点击，自动尝试多个缩放比例以适应图片大小的变化
        :param target: RuleImage对象
        :param action: 点击位置，可以是RuleClick或RuleLongClick
        :param interval: 匹配间隔时间
        :param threshold: 匹配阈值
        :param scales: 缩放比例列表
        :param scale_range: 缩放范围 (start, end, step)，例如 (0.8, 1.2, 0.1)
        :param duration: 长按时间（毫秒）
        :return: True or False
        """
        appear = self.appear_multi_scale(target, interval=interval, threshold=threshold, scales=scales, scale_range=scale_range)

        if appear and not action:
            x, y = target.coord()
            if self.device.click(x, y, control_name=target.name) is False:
                return False
        elif appear and action:
            x, y = action.coord()
            if isinstance(action, RuleLongClick):
                hold = action.duration / 1000 if duration is None else duration / 1000
                if self.device.long_click(x, y, duration=hold, control_name=target.name) is False:
                    return False
            elif isinstance(action, RuleClick):
                if self.device.click(x, y, control_name=target.name) is False:
                    return False

        return appear

    def wait_until_appear(self,
                          target: RuleImage | RuleGif | RuleOcr,
                          skip_first_screenshot=False,
                          wait_time: int | float = None) -> bool:
        """
        等待直到出现目标（未指定 wait_time 时使用默认有界预算，超时抛 TaskRecoveryFailed）
        :param wait_time: 等待时间，单位秒
        :param target:
        :param skip_first_screenshot:
        :return:
        """
        implicit = wait_time is None
        budget = self._default_wait_timeout() if implicit else wait_time
        wait_timer = Timer(self._perf_timeout(budget)).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.screenshot()
            if isinstance(target, (RuleImage, RuleGif)) and self.appear(target):
                return True
            if isinstance(target, RuleOcr) and self.ocr_appear(target):
                return True
            if wait_timer.reached():
                logger.warning(f"Wait until appear {target.name} timeout")
                if implicit:
                    raise TaskRecoveryFailed(f'Expected {target.name} did not appear within {budget}s')
                return False

    def wait_until_appear_then_click(self,
                                     target: RuleImage | RuleGif,
                                     action: Union[RuleClick, RuleLongClick] = None,
                                     wait_time: int = None) -> bool:
        """
        等待直到出现目标，然后点击
        :param wait_time:
        :param action:
        :param target:
        :return:
        """
        if not self.wait_until_appear(target, wait_time=wait_time):
            return False
        click_x, click_y = target.coord()
        if action is None:
            if self.device.click(click_x, click_y, control_name=target.name) is False:
                return False
        elif isinstance(action, RuleLongClick):
            if self.device.long_click(click_x, click_y, duration=action.duration / 1000, control_name=target.name) is False:
                return False
        elif isinstance(action, RuleClick):
            if self.device.click(click_x, click_y, control_name=target.name) is False:
                return False
        return True

    def wait_until_disappear(self, target: RuleImage, wait_time: float = None, timeout: float = None) -> bool:
        """
        等待目标消失；兼容旧版 wait_time 与新版 timeout 参数。
        显式超时返回 False；默认使用有界等待，到期保留任务并抛出 TaskRecoveryFailed。
        """
        effective = timeout if timeout is not None else wait_time
        implicit = effective is None
        budget = self._default_wait_timeout() if implicit else effective
        timeout_timer = Timer(self._perf_timeout(budget)).start()
        while 1:
            self.screenshot()
            if not self.appear(target):
                return True
            if timeout_timer.reached():
                logger.warning(f'Wait disappear timeout: {target.name}')
                if implicit:
                    raise TaskRecoveryFailed(f'{target.name} did not disappear within {budget}s')
                return False

    def wait_until_pos_stable(self, target: RuleImage, stable_time: float = 0.3, timeout: float = 2,
                              threshold: float = None, skip_first_screenshot: bool = True) -> bool:
        """
        等待直到在同一位置稳定出现
        :param skip_first_screenshot:
        :param threshold: target匹配阈值
        :param target: 目标图像
        :param stable_time: 判断是否稳定的时间
        :param timeout: 等待稳定的超时时间
        :return: timer时间内稳定出现则返回True, 否则False
        """
        logger.info(f'Wait until {target.name} position stable')
        timeout_timer = Timer(self._perf_timeout(timeout)).start()
        stable_timer = Timer(stable_time).start()
        pre_roi_front, cur_roi_front = None, None
        origin_roi_back = target.roi_back
        while not timeout_timer.reached():
            self.maybe_screenshot(skip_first_screenshot)
            skip_first_screenshot = False
            # 当前页面能够匹配到target
            if target.match(self.device.image, threshold=threshold):
                cur_roi_front = target.roi_front
                logger.info(f'Current:{cur_roi_front}, pre:{pre_roi_front}')
                target.roi_back = pre_roi_front
                # 上一次匹配到的位置还能匹配到target
                if pre_roi_front is not None and target.match(self.device.image, threshold=threshold):
                    # 到达稳定时间
                    if stable_timer.reached():
                        logger.info(f'{target.name} position has stabilized')
                        target.roi_back = origin_roi_back
                        return True
                else:
                    stable_timer.reset()  # 上一次匹配到的位置这次匹配不到了, 重置定时器
            else:
                stable_timer.reset()  # 当前页面都匹配不到, 重置定时器
            # 记录这一次的target位置
            pre_roi_front = cur_roi_front
            # 还原target的匹配区域
            target.roi_back = origin_roi_back
        logger.warning(f'Wait until pos stable({target}) timeout')
        return False

    def wait_until_stable(self,
                          target: RuleImage,
                          timer=Timer(0.3, count=1),
                          timeout=Timer(5, count=10),
                          skip_first_screenshot=True):
        """
        等待目标稳定，即连续多次匹配成功
        :param target:
        :param timer:
        :param timeout:
        :param skip_first_screenshot:
        :return:
        """
        target._match_init = False
        # 使用局部 Timer 副本，防止跨次调用共享可变默认参数或叠加缩放倍率
        local_timer = Timer(timer.limit, count=timer.count)
        local_timeout = Timer(self._perf_timeout(timeout.limit), count=timeout.count).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.screenshot()

            if target._match_init:
                if target.match(self.device.image):
                    if local_timer.reached():
                        break
                else:
                    local_timer.reset()
            else:
                target._match_init = True

            if local_timeout.reached():
                logger.warning(f'Wait_until_stable({target}) timeout')
                break

    def wait_animate_stable(self, rule: RuleAnimate, interval: float = None, timeout: float = None):
        """
        不同与上面的wait_until_stable，这个将会匹配连续的两帧图片的特定区域
        @param rule:
        @param interval:
        @param timeout:
        @return:
        """
        if not isinstance(rule, RuleAnimate):
            rule = RuleAnimate(rule)
        implicit = timeout is None
        budget = self._default_wait_timeout() if implicit else timeout
        timeout_timer = Timer(self._perf_timeout(budget)).start()
        while 1:
            self.screenshot()

            if interval:
                if rule.name in self.interval_timer:
                    if self.interval_timer[rule.name].limit != interval:
                        self.interval_timer[rule.name] = Timer(interval)
                else:
                    self.interval_timer[rule.name] = Timer(interval)
                if not self.interval_timer[rule.name].reached():
                    return False

            stable = rule.stable(self.device.image)
            if stable:
                if interval:
                    self.interval_timer[rule.name].reset()
                return True

            if timeout_timer.reached():
                logger.info(f'Wait_animate_stable({rule}) timeout')
                if implicit:
                    raise TaskRecoveryFailed(f'Animation {rule.name} did not stabilize within {budget}s')
                return False

    def swipe(self, swipe: RuleSwipe, interval: float = None) -> bool:
        """

        :param interval:
        :param swipe:
        :return:
        """
        if not isinstance(swipe, RuleSwipe):
            return False

        if interval:
            if swipe.name in self.interval_timer:
                # 如果传入的限制时间不一样，则替换限制新的传入的时间
                if self.interval_timer[swipe.name].limit != interval:
                    self.interval_timer[swipe.name] = Timer(interval)
            else:
                # 如果没有限制时间，则创建限制时间
                self.interval_timer[swipe.name] = Timer(interval)
            # 如果时间还没到达，则不执行
            if not self.interval_timer[swipe.name].reached():
                return False

        x1, y1, x2, y2 = swipe.coord()
        if self.device.swipe(p1=(x1, y1), p2=(x2, y2), control_name=swipe.name) is False:
            return False

        # 执行后，如果有限制时间，则重置限制时间
        if interval:
            self.interval_timer[swipe.name].reset()
        return True

    def click(self, click: Union[RuleClick, RuleLongClick, RuleImage, RuleOcr] = None, interval: float = None) -> bool:
        """
        点击或者长按
        :param interval:
        :param click:
        :return: 返回值不是click是否成功，而是interval是否设置以及是否到时间
        """
        if not click:
            return False

        if interval:
            if click.name in self.interval_timer:
                # 如果传入的限制时间不一样，则替换限制新的传入的时间
                if self.interval_timer[click.name].limit != interval:
                    self.interval_timer[click.name] = Timer(interval)
            else:
                # 如果没有限制时间，则创建限制时间
                self.interval_timer[click.name] = Timer(interval)
            # 如果时间还没到达，则不执行
            if not self.interval_timer[click.name].reached():
                return False

        x, y = click.coord()
        if isinstance(click, RuleLongClick):
            if self.device.long_click(x=x, y=y, duration=click.duration / 1000, control_name=click.name) is False:
                return False
        elif isinstance(click, (RuleClick, RuleImage, RuleOcr)):
            if self.device.click(x=x, y=y, control_name=click.name) is False:
                return False

        # 执行后，如果有限制时间，则重置限制时间
        if interval:
            self.interval_timer[click.name].reset()
            return True
        return False

    def ocr_appear(self, target: RuleOcr, interval: float = None, exact: bool = False) -> bool:
        """
        ocr识别目标
        :param interval:
        :param target:
        :param exact: 是否只匹配完整的单个 OCR 文本， 加上这个参数是为了 https://github.com/runhey/OnmyojiAutoScript/issues/1782
        :return: 如果target有keyword或者是keyword存在，返回是True，否则返回False
                 但是没有指定keyword，返回的是匹配到的值，具体取决于target的mode
        """
        if not isinstance(target, RuleOcr):
            return None

        if interval:
            if target.name in self.interval_timer:
                # 如果传入的限制时间不一样，则替换限制新的传入的时间
                if self.interval_timer[target.name].limit != interval:
                    self.interval_timer[target.name] = Timer(interval)
            else:
                # 如果没有限制时间，则创建限制时间
                self.interval_timer[target.name] = Timer(interval)
            # 如果时间还没到达，则不执行
            if not self.interval_timer[target.name].reached():
                return None

        result = target.ocr(self.device.image, exact=exact)
        appear = False

        if not target.keyword or target.keyword == '':
            appear = False
        match target.mode:
            case OcrMode.FULL:  # 全匹配
                appear = result != (0, 0, 0, 0)
            case OcrMode.SINGLE:
                appear = result == target.keyword
            case OcrMode.DIGIT:
                appear = result == int(target.keyword)
            case OcrMode.DIGITCOUNTER:
                appear = result == target.ocr_str_digit_counter(target.keyword)
            case OcrMode.DURATION:
                appear = result == target.parse_time(target.keyword)

        if interval and appear:
            self.interval_timer[target.name].reset()

        return appear

    def ocr_appear_click(self,
                         target: RuleOcr,
                         action: Union[RuleClick, RuleLongClick] = None,
                         interval: float = None,
                         duration: float = None,
                         exact: bool = False) -> bool:
        """
        ocr识别目标，如果目标存在，则触发动作
        :param target:
        :param action:
        :param interval:
        :param duration:
        :param exact: 是否只匹配完整的单个 OCR 文本 ， 加上这个参数是为了 https://github.com/runhey/OnmyojiAutoScript/issues/1782
        :return:
        """
        appear = self.ocr_appear(target, interval, exact=exact)

        if not appear:
            return False

        if action:
            x, y = action.coord()
            if self.click(action, interval) is False and interval:
                return False
        else:
            x, y = target.coord()
            if self.device.click(x=x, y=y, control_name=target.name) is False:
                return False
        return True

    def list_find(self, target: RuleList, name: str | list[str], max_swipe: int = 10) -> bool | tuple:
        """
        会一致在列表寻找目标，找到了就退出。
        如果是图片列表会一直往下找
        如果是纯文字的，会自动识别自己的位置，根据位置选择向前还是向后翻
        :param max_swipe: 最大滑动次数
        :param target:
        :param name:
        :return:
        """
        swipe_down = False
        swipe_distance_ratio = None
        result = None
        if not target:
            return False
        appear = False
        for _ in range(max_swipe):
            self.screenshot()
            if target.is_image:
                result = target.image_appear(self.device.image, name=name)
                swipe_down = True
            elif target.is_ocr:
                result = target.ocr_appear(self.device.image, name=name)
                swipe_down = result is not None and isinstance(result, int) and result > 0
                swipe_distance_ratio = 1
            # 结果是坐标证明找到了, 非坐标都是没找到
            if result is not None and isinstance(result, tuple):
                appear = True
                break
            if swipe_distance_ratio:
                x1, y1, x2, y2 = target.swipe_pos(number=swipe_distance_ratio, after=swipe_down)
            else:
                x1, y1, x2, y2 = target.swipe_pos(after=swipe_down)
            self.device.swipe(p1=(x1, y1), p2=(x2, y2))
            sleep(random.uniform(0.8, 1.3))  # 等待滑动完成, 待优化
        if appear:
            return result
        return False

    def list_appear_click(self, target: RuleList, interval: float = None, max_swipe: int = 10) -> bool:
        if interval:
            if target.name in self.interval_timer:
                # 如果传入的限制时间不一样，则替换限制新的传入的时间
                if self.interval_timer[target.name].limit != interval:
                    self.interval_timer[target.name] = Timer(interval)
            else:
                # 如果没有限制时间，则创建限制时间
                self.interval_timer[target.name] = Timer(interval)
            # 如果时间还没到达，则不执行
            if not self.interval_timer[target.name].reached():
                return False
        appear = self.list_find(target, name=target.array[0], max_swipe=max_swipe)
        if isinstance(appear, tuple) and interval:
            x, y = appear
            self.device.click(x, y)
            self.interval_timer[target.name].reset()
            return True
        return False

    def set_next_run(self, task: str, finish: bool = False,
                     success: bool = None, server: bool = True, target: datetime = None) -> None:
        """
        设置下次运行时间  当然这个也是可以重写的
        :param target: 可以自定义的下次运行时间
        :param server: True
        :param success: 判断是成功的还是失败的时间间隔
        :param task: 任务名称，大驼峰的
        :param finish: 是完成任务后的时间为基准还是开始任务的时间为基准
        :return:
        """
        if finish:
            start_time = datetime.now().replace(microsecond=0)
        else:
            start_time = self.start_time
        self.config.task_delay(task, start_time=start_time, success=success, server=server, target=target)

    def custom_next_run(self, task: str, custom_time: Time = None, time_delta: float = 1) -> None:
        """
        设置下次自定义运行时间
        :param task: 任务名称，大驼峰的
        :param custom_time: 可以自定义的下次运行时间
        :param time_delta: 下次运行日期为几天后，默认为第二天
        :return:
        """
        target_time = (datetime.now() + timedelta(days=time_delta)).replace(hour=custom_time.hour,
                                                                            minute=custom_time.minute,
                                                                            second=custom_time.second)
        self.set_next_run(task, target=target_time)

    #  ---------------------------------------------------------------------------------------------------------------
    #
    #  ---------------------------------------------------------------------------------------------------------------
    def ui_reward_appear_click(self, screenshot=False) -> bool:
        """
        如果出现 ‘获得奖励’ 就点击（使用有界单次确认重试，不误触领取源按钮）
        :return:
        """
        if screenshot:
            self.screenshot()
        if not self.appear(self.I_UI_REWARD, interval=0.4, threshold=0.6):
            return False
        return self._dismiss_reward_once()

    def _dismiss_reward_once(self) -> bool:
        # This is the already displayed reward, never the source claim button.
        return click_confirm_once(
            self,
            lambda: self.C_UI_REWARD if self.appear(self.I_UI_REWARD, threshold=0.6) else None,
            [self.C_UI_REWARD, self.I_UI_REWARD],
            dismiss_anywhere=True,
        )

    def ui_get_reward(self, click_image: RuleImage | RuleOcr | RuleClick, click_interval: float = 1):
        """
        传进来一个点击图片或 OCR/区域，最多触发一次领取动作并等待‘获得奖励’弹窗出现与关闭验证。
        :param click_interval:
        :param click_image:
        :return:
        """
        _timer = Timer(self._perf_timeout(10)).start()
        source_clicked = False
        generation = getattr(self.device, '_escape_generation', 0)
        while 1:
            self.screenshot()
            if getattr(self.device, '_escape_generation', 0) != generation:
                raise TaskRecoveryFailed('Reward claim interrupted by recovery')

            if self.appear(self.I_UI_REWARD, threshold=0.6):
                if not self._dismiss_reward_once():
                    raise TaskRecoveryFailed('Reward dismiss input was blocked')
                self._ui_verify(lambda: not self.appear(self.I_UI_REWARD, threshold=0.6), [self.I_UI_REWARD])
                logger.info('Get reward success')
                return True
            if _timer.reached():
                logger.warning('Get reward timeout')
                if source_clicked:
                    raise TaskRecoveryFailed('Reward was not observed after one claim input')
                return False

            # A delayed reward is observed after one source input, never by re-clicking it.
            if not source_clicked:
                if isinstance(click_image, (RuleImage, RuleGif, RuleOcr)) and not self.appear(click_image):
                    continue
                if not self._ui_action_once(click_image, interval=None):
                    raise TaskRecoveryFailed('Reward claim input was blocked')
                source_clicked = True

    def _ui_action_once(self, control, interval=1) -> bool:
        if isinstance(control, (RuleImage, RuleGif)):
            return self.appear_then_click(control, interval=interval)
        if isinstance(control, RuleOcr):
            return self.ocr_appear_click(control, interval=interval)
        if interval is None and isinstance(control, RuleClick):
            x, y = control.coord()
            return self.device.click(x=x, y=y, control_name=control.name) is not False
        return self.click(control, interval=interval)

    def ui_click(self, click, stop, interval=1, timeout=None):
        """
        触发源控件并验证目标状态出现；未传 timeout 时有界失败抛 TaskRecoveryFailed，显式 timeout 返回 bool。
        """
        implicit = timeout is None
        action_budget = 12 if implicit else timeout
        verify_budget = 12 if implicit else timeout
        self.screenshot()
        if self.appear(stop):
            return self._ui_verify(lambda: self.appear(stop), [], timeout=verify_budget, fail=implicit)
        deadline = monotonic() + self._perf_timeout(action_budget)
        while monotonic() < deadline:
            if self._ui_action_once(click, interval):
                remaining = verify_budget if implicit else max(0.1, deadline - monotonic())
                return self._ui_verify(lambda: self.appear(stop), [click], timeout=remaining, fail=implicit)
            self.screenshot()
            if self.appear(stop):
                remaining = verify_budget if implicit else max(0.1, deadline - monotonic())
                return self._ui_verify(lambda: self.appear(stop), [], timeout=remaining, fail=implicit)
        if implicit:
            raise TaskRecoveryFailed('UI source control was not actionable')
        logger.warning(f'ui_click timeout after {timeout}s')
        return False

    def ui_clicks(self, clicks: list[RuleImage | RuleOcr | RuleClick], stop: RuleImage, interval=1):
        sent = set()
        deadline = monotonic() + self._perf_timeout(20)
        while monotonic() < deadline:
            self.screenshot()
            if self.appear(stop):
                return self._ui_verify(lambda: self.appear(stop), clicks)
            for index, click in enumerate(clicks):
                if index not in sent and self._ui_action_once(click, interval):
                    sent.add(index)
                    break
        raise TaskRecoveryFailed('UI sequence did not reach its destination')

    def _ui_verify(self, predicate, controls, timeout=12, fail=True):
        effective_timeout = self._perf_timeout(timeout)
        deadline = monotonic() + effective_timeout
        generation = getattr(self.device, '_escape_generation', 0)
        stable = 0
        while monotonic() < deadline:
            self.screenshot()
            if getattr(self.device, '_escape_generation', 0) != generation:
                raise TaskRecoveryFailed('UI state verification interrupted by recovery')
            stable = stable + 1 if predicate() else 0
            if stable >= 2:
                confirm = getattr(self.device, 'confirm_control_progress', None)
                if callable(confirm):
                    confirm(controls)
                logger.info('UI next state verified in two fresh frames')
                return True
        if fail:
            raise TaskRecoveryFailed('UI next state not reached after one click')
        return False

    def ui_click_until_disappear(self, click, interval: float = 1):
        """
        点击一个按钮直到消失
        :param interval:
        :param click:
        :return:
        """
        if click is self.I_UI_BACK_RED or click is getattr(self, 'I_SOU_SWITCH_SURE', None):
            return click_confirm_once(self, lambda: click if self.appear(click) else None, [click])
        self.screenshot()
        if not self.appear(click):
            return False
        deadline = monotonic() + self._perf_timeout(12)
        while monotonic() < deadline:
            if self.appear_then_click(click, interval=interval):
                self._ui_verify(lambda: not self.appear(click), [click])
                return True
            self.screenshot()
            if not self.appear(click):
                return False
        raise TaskRecoveryFailed('UI dismiss control was not actionable')

    def ui_click_until_appear_or_timeout(self, click, stop=None, interval: float = 1, timeout: float = 10) -> bool:
        deadline = monotonic() + self._perf_timeout(timeout)
        while monotonic() < deadline:
            self.screenshot()
            if stop is not None and self.appear(stop):
                return self._ui_verify(lambda: self.appear(stop), [], timeout=timeout, fail=False)
            if self._ui_action_once(click, interval):
                remaining = max(0.1, deadline - monotonic())
                return self._ui_verify(lambda: stop is not None and self.appear(stop),
                                       [click], timeout=remaining, fail=False)
        return False

    def ui_click_until_smt_disappear(self, click, stop, interval: float = 1):
        """
        点击一个按钮/区域/文字直到 stop 消失（有界单次触发 + 双新鲜帧确认）
        """
        self.screenshot()
        if not self.appear(stop):
            return
        deadline = monotonic() + self._perf_timeout(12)
        while monotonic() < deadline:
            if self._ui_action_once(click, interval):
                return self._ui_verify(lambda: not self.appear(stop), [click])
            self.screenshot()
            if not self.appear(stop):
                return
        raise TaskRecoveryFailed('UI close control was not actionable')

    def ui_click_multi_scale(self, click, stop, interval=1, scale_range=None, timeout=None):
        """
        触发操作直到出现 stop（支持多尺度图片识别，默认具备有界预算）
        """
        implicit = timeout is None
        budget = 12 if implicit else timeout
        self.screenshot()
        if self.appear(stop):
            return self._ui_verify(lambda: self.appear(stop), [], timeout=budget, fail=implicit)
        deadline = monotonic() + self._perf_timeout(budget)
        while monotonic() < deadline:
            acted = False
            if isinstance(click, RuleImage):
                acted = bool(self.appear_then_click_multi_scale(click, scale_range=scale_range, interval=interval))
            elif isinstance(click, (RuleClick, RuleOcr)):
                acted = bool(self._ui_action_once(click, interval=interval))
            if acted:
                remaining = 12 if implicit else max(0.1, deadline - monotonic())
                return self._ui_verify(lambda: self.appear(stop), [click], timeout=remaining, fail=implicit)
            self.screenshot()
            if self.appear(stop):
                remaining = 12 if implicit else max(0.1, deadline - monotonic())
                return self._ui_verify(lambda: self.appear(stop), [], timeout=remaining, fail=implicit)
        if implicit:
            raise TaskRecoveryFailed('Multi-scale UI source control was not actionable')
        logger.warning(f'ui_click_multi_scale timeout after {timeout}s')
        return False

    def push_notify(self, content='', title=None, level=3):
        logger.info(f'Push notify: {content}')

    def save_image(self, task_name=None, content=None, wait_time=2, image_type=False, push_flag=False, level=3):
        logger.info(f'Save image: {task_name}')
