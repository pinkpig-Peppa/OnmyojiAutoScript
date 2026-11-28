# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from contextvars import ContextVar
from math import ceil
import random
from time import monotonic
import numpy as np

from module.base.decorator import cached_property
from module.base.utils.utils import random_normal_distribution_int
from module.device.human_click import TargetBox, reset_task, sample_point
from module.logger import logger


class RuleClick:
    _task_click_state = ContextVar('ruleclick_task_click_state', default=None)
    _recent_limit = 6
    _history_limit = 256
    _DENSITY_PROFILES = {
        None: (0.98, 0.02),
        'High': (1.0, 0.0),
        'More': (0.95, 0.05),
    }

    @classmethod
    def reset_task_points(cls):
        """每次任务启动清空各规则的近期落点和全局上一落点。"""
        RuleClick._task_click_state.set({
            'rules': {},
            'previous_point': None,
            'history': [],
        })
        reset_task()

    def __init__(
        self,
        roi_front: tuple,
        roi_back: tuple,
        name: str = None,
        functional: bool = True,
        profile: str = None,
    ) -> None:
        """
        初始化
        :param roi_front:
        :param roi_back:
        """
        self.roi_front = roi_front
        self.roi_back = roi_back
        if name:
            self.name = name
        else:
            self.name = 'click'
        self.functional = functional
        if profile in ('', 'Default'):
            profile = None
        if isinstance(profile, str):
            profile = {'high': 'High', 'more': 'More'}.get(profile.lower(), profile)
        if profile not in self._DENSITY_PROFILES:
            raise ValueError('RuleClick profile must be High, More, or omitted')
        self.profile = profile

    @classmethod
    def task_click_history(cls) -> tuple:
        state = cls._task_click_state.get()
        if state is None:
            cls.reset_task_points()
            state = cls._task_click_state.get()
        return tuple(state['history'])

    def _record_task_click(self, point: tuple[int, int]) -> None:
        task_state = RuleClick._task_click_state.get()
        if task_state is None:
            self.reset_task_points()
            task_state = RuleClick._task_click_state.get()
        task_state['previous_point'] = point
        history = task_state['history']
        history.append((point[0], point[1], monotonic(), self.functional))
        del history[:-self._history_limit]

    def coord(self) -> tuple:
        """
        获取坐标，在 roi_front 内按截断高斯采样。
        :return:
        """
        return self._circle_normal_coord(self.roi_front)

    def coord_more(self) -> tuple:
        """
        在 roi_back 内按截断高斯采样。
        :return:
        """
        return self._circle_normal_coord(self.roi_back)

    def _circle_normal_coord(self, roi: tuple) -> tuple:
        x, y, width, height = roi
        if width <= 0 or height <= 0:
            raise ValueError(f'RuleClick roi must have positive size: {roi}')
        left, right = ceil(x), ceil(x + width)
        top, bottom = ceil(y), ceil(y + height)
        if left >= right or top >= bottom:
            raise ValueError(f'RuleClick roi contains no integer pixel: {roi}')
        task_state = RuleClick._task_click_state.get()
        if task_state is None:
            self.reset_task_points()
            task_state = RuleClick._task_click_state.get()
        rules = task_state['rules']
        key = (self.name, tuple(roi), self.profile)
        if key not in rules:
            rules[key] = {'recent': [], 'count': 0}
        rule_state = rules[key]

        click_x, click_y = sample_point(TargetBox(x, y, width, height))
        recent = rule_state['recent']
        recent.append((click_x, click_y))
        del recent[:-self._recent_limit]
        rule_state['count'] += 1
        self._record_task_click((click_x, click_y))
        return click_x, click_y

    @property
    def center(self) -> tuple:
        """
        返回roi_front的中心坐标
        :return:
        """
        x, y, w, h = self.roi_front
        return x + w // 2, y + h // 2

    def move(self, x: int, y: int) -> None:
        """
        移动roi_front, 需要限幅x是0-1280, y是0-720
        :param x:
        :param y:
        :return:
        """
        # 入参是相对 roi_front 左上角的偏移量：先保存偏移，再取 roi 基址，
        # 原实现直接覆盖入参并自我累加，导致点击坐标翻倍且与入参无关
        offset_x, offset_y = x, y
        x, y, w, h = self.roi_front
        x += offset_x
        y += offset_y
        if x <= 0 :
            x = 0
        elif x >= 1280:
            x = 1280

        if y <= 0 :
            y = 0
        elif y >= 720:
            y = 720

        self.roi_front = x, y, w, h


class RuleClickExclude(RuleClick):
    """Randomly click within the screen while excluding other click regions."""

    SCREEN_WIDTH = 1280
    SCREEN_HEIGHT = 720

    def __init__(self, clicks, strategy: str | None = None, distribution: str | None = None,
                 max_attempts: int = 100, name: str = 'exclude_random_click') -> None:
        """
        初始化排除区域随机点击规则。

        :param clicks: 需要排除的 RuleClick，或 RuleClick 序列；使用其 roi_back 作为排除区域
        :param strategy: 取点策略，None 时在初始化时随机选择 rejection 或 complement
        :param distribution: 坐标分布，None 时在初始化时随机选择 uniform 或 normal
        :param max_attempts: 拒绝采样的最大尝试次数，耗尽后自动使用补集矩形采样
        :param name: 点击规则名称，用于 BaseTask.click 的间隔计时器
        :raises TypeError: clicks 不是 RuleClick 或 RuleClick 序列
        :raises ValueError: strategy、distribution 或 max_attempts 参数无效，或排除区域覆盖整个屏幕
        """
        super().__init__((0, 0, self.SCREEN_WIDTH, self.SCREEN_HEIGHT),
                         (0, 0, self.SCREEN_WIDTH, self.SCREEN_HEIGHT), name=name)
        if strategy is None:
            strategy = random.choice(('rejection', 'complement'))
        if distribution is None:
            distribution = random.choice(('uniform', 'normal'))
        if strategy not in ('rejection', 'complement'):
            raise ValueError("strategy must be 'rejection' or 'complement'")
        if distribution not in ('uniform', 'normal'):
            raise ValueError("distribution must be 'uniform' or 'normal'")
        if max_attempts < 1:
            raise ValueError('max_attempts must be positive')

        if isinstance(clicks, RuleClick):
            clicks = (clicks,)
        self.clicks = tuple(clicks)
        if not all(isinstance(click, RuleClick) for click in self.clicks):
            raise TypeError('clicks must contain RuleClick instances')
        self.strategy = strategy
        self.distribution = distribution
        self.max_attempts = max_attempts
        self._excluded = tuple(
            rect for click in self.clicks
            for rect in (self._clip_roi(click.roi_back),)
            if rect is not None
        )
        self._allowed = self._build_complement()
        if not self._allowed:
            raise ValueError('Excluded regions cover the whole screen')

    def __str__(self):
        click_names = ', '.join(click.name for click in self.clicks) or 'none'
        return (
            f'{self.name}(strategy={self.strategy}, '
            f'distribution={self.distribution}, clicks=[{click_names}])'
        )

    __repr__ = __str__

    @classmethod
    def _clip_roi(cls, roi):
        x, y, w, h = roi
        left, top = max(0, x), max(0, y)
        right, bottom = min(cls.SCREEN_WIDTH, x + w), min(cls.SCREEN_HEIGHT, y + h)
        if left >= right or top >= bottom:
            return None
        return left, top, right - left, bottom - top

    def _is_excluded(self, x, y):
        return any(left <= x < left + width and top <= y < top + height
                   for left, top, width, height in self._excluded)

    def _build_complement(self):
        x_edges = {0, self.SCREEN_WIDTH}
        y_edges = {0, self.SCREEN_HEIGHT}
        for x, y, width, height in self._excluded:
            x_edges.update((x, x + width))
            y_edges.update((y, y + height))

        x_edges, y_edges = sorted(x_edges), sorted(y_edges)
        allowed = []
        for x1, x2 in zip(x_edges, x_edges[1:]):
            for y1, y2 in zip(y_edges, y_edges[1:]):
                if not self._is_excluded(x1, y1):
                    allowed.append((x1, y1, x2 - x1, y2 - y1))
        return allowed

    def _sample_axis(self, start, size, distribution):
        if size == 1:
            return start
        if distribution == 'uniform':
            return random.randrange(start, start + size)
        return max(start, min(start + size - 1,
                              random_normal_distribution_int(start, start + size)))

    def _sample_point(self, rect, distribution):
        x, y, width, height = rect
        return self._sample_axis(x, width, distribution), self._sample_axis(y, height, distribution)

    def _coord_rejection(self, distribution):
        for _ in range(self.max_attempts):
            point = self._sample_point((0, 0, self.SCREEN_WIDTH, self.SCREEN_HEIGHT), distribution)
            if not self._is_excluded(*point):
                return point
        return self._coord_complement(distribution)

    def _coord_complement(self, distribution):
        total = sum(width * height for _, _, width, height in self._allowed)
        offset = random.randrange(total)
        for rect in self._allowed:
            area = rect[2] * rect[3]
            if offset < area:
                return self._sample_point(rect, distribution)
            offset -= area
        raise RuntimeError('Unable to select a click region')

    def coord(self) -> tuple:
        if self.strategy == 'rejection':
            return self._coord_rejection(self.distribution)
        return self._coord_complement(self.distribution)

    def coord_in_excluded(self, areas: list[str] | None = None) -> tuple:
        """
        
        """
        if not areas:
            areas = ['C_END_1_1', 'C_END_1_2', 'C_END_1_3', 'C_END_1_4', 'C_END_1_5', 'C_END_1_6',
                     'C_END_2_1', 'C_END_2_2', 'C_END_2_3', 'C_END_2_4', 'C_END_2_5', 'C_END_2_6']
        area_names = {area.casefold() for area in areas}
        matched = []
        for click in self.clicks:
            names = {str(click), click.name, click.name.upper(), f'C_{click.name.upper()}'}
            if area_names.intersection(name.casefold() for name in names):
                matched.append(click)
        if not matched:
            raise ValueError(f'No excluded click matches areas: {areas!r}')
        return random.choice(matched).coord()
