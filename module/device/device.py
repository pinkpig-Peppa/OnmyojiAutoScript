
from collections import deque
from contextlib import contextmanager
from datetime import datetime
import time

# Patch pkg_resources before importing adbutils and uiautomator2
from module.device.pkg_resources import get_distribution
# Just avoid being removed by import optimization
_ = get_distribution

from module.base.utils import get_color
from module.device.env import IS_WINDOWS
from module.base.timer import Timer
from module.config.utils import get_server_next_update
from module.device.app_control import AppControl
from module.device.control import Control
from module.device.performance import PerformanceProfile
if IS_WINDOWS:
    from module.device.desktop_device import DesktopDevice
else:
    class DesktopDevice:
        pass
from module.device.platform2 import Platform
from module.device.screenshot import Screenshot
from module.exception import (GameNotRunningError,
                              GameStuckError,
                              GameTooManyClickError,
                              TaskRecoveryFailed,
                              RequestHumanTakeover,
                              EmulatorNotRunningError)
from module.logger import logger


class Device(DesktopDevice, Platform, Screenshot, Control, AppControl):
    performance = PerformanceProfile()
    _login_deadline = None
    _last_control_time = None
    _error_learning = None
    _screen_size_checked = False
    _escape_attempts = 0
    _escape_generation = 0
    _accepted_invitation_generation = 0
    _task_flow_progress_generation = 0
    _task_flow_round_generation = 0
    _task_flow_guard_disabled = False
    _click_recovery_at = None
    _click_recovery_reason = ''
    _click_recovery_buttons = set()
    _await_recovery_frame = False
    _verified_click = None
    _confirm_retry_permit = None
    _click_verification_enabled = True
    detect_record = set()
    click_record = deque(maxlen=15)
    stuck_timer = Timer(60, count=60).start()
    stuck_timer_long = Timer(300, count=300).start()
    stuck_long_wait_list = ['BATTLE_STATUS_S', 'PAUSE', 'LOGIN_CHECK', 'PREPARE_BEFORE_BATTLE']

    def __init__(self, *args, **kwargs):
        for trial in range(4):
            try:
                super().__init__(*args, **kwargs)
                break
            except EmulatorNotRunningError:
                # 桌面客户端没有模拟器可拉：确保客户端在，再重跑一次基类完成窗口绑定
                if self.is_desktop:
                    if trial >= 1 or not self._desktop_ensure_launched():
                        logger.critical('Desktop client not found and auto-launch failed, '
                                        'please start the game and bind PID first')
                        raise RequestHumanTakeover from None
                    continue
                if trial >= 3:
                    logger.critical('Failed to start emulator after 3 trial')
                    raise RequestHumanTakeover
                # Try to start emulator
                if self.emulator_instance is not None:
                    self.emulator_start()
                else:
                    logger.critical(
                        f'No emulator with serial "{self.config.Emulator_Serial}" found, '
                        f'please set a correct serial'
                    )
                    raise RequestHumanTakeover

        self.performance = PerformanceProfile(bool(getattr(self.config.script.device, 'low_spec_mode', False)))
        self.detect_record = set()
        self.click_record = deque(maxlen=15)
        self.stuck_timer = Timer(self.performance.timeout(60), count=60).start()
        self.stuck_timer_long = Timer(300, count=300).start()
        self._login_deadline = None
        self._last_control_time = None
        self._error_learning = None
        self._screenshot_interval = Timer(0.1)
        self._accepted_invitation_generation = 0
        self._task_flow_progress_generation = 0
        self._task_flow_round_generation = 0
        self.reset_task_recovery()

        # 桌面客户端模式：无模拟器生命周期
        if self.is_desktop:
            self._init_desktop()
            return

        # Auto-fill emulator info
        if IS_WINDOWS and self.config.script.device.emulatorinfo_type == 'auto':
            _ = self.emulator_instance

        self.screenshot_interval_set()

        # Auto-select the fastest screenshot method
        if self.config.script.device.screenshot_method == 'auto':
            self.run_simple_screenshot_benchmark()

    def run_simple_screenshot_benchmark(self):
        """
        Perform a screenshot method benchmark, test 3 times on each method.
        The fastest one will be set into config.
        """
        logger.info('run_simple_screenshot_benchmark')
        # Check resolution first
        # self.resolution_check_uiautomator2()
        # Perform benchmark
        from module.daemon.benchmark import Benchmark
        bench = Benchmark(config=self.config, device=self)
        method = bench.run_simple_screenshot_benchmark()
        # Set
        self.config.script.device.screenshot_method = method
        self.config.save()

    def handle_night_commission(self, daily_trigger='21:00', threshold=30):
        """
        Args:
            daily_trigger (int): Time for commission refresh.
            threshold (int): Seconds around refresh time.

        Returns:
            bool: If handled.
        """
        update = get_server_next_update(daily_trigger=daily_trigger)
        now = datetime.now()
        diff = (update.timestamp() - now.timestamp()) % 86400
        if threshold < diff < 86400 - threshold:
            return False

        # if GET_MISSION.match(self.image, offset=True):
        #     logger.info('Night commission appear.')
        #     self.click(GET_MISSION)
        #     return True

        return False

    def screenshot(self):
        """
        Returns:
            np.ndarray:
        """
        flow_guard = getattr(self, '_task_flow_guard', None)
        if flow_guard is not None:
            flow_guard.check()

        # 桌面模式：窗口缺失说明客户端当前不可用（启动期未出窗口，或客户端崩了）。
        # 直接截图会抛 (1400, '无效的窗口句柄') 搞崩整个进程，必须先拦下；拉客户端
        # 是 Restart 的职责。最小化不算窗口缺失——BitBlt 截图前会先还原窗口。
        if self.is_desktop and not self.desktop_window_exists():
            raise GameNotRunningError('Desktop client window not found')

        try:
            super().screenshot()
        except RequestHumanTakeover as e:
            raise RequestHumanTakeover

        if self.handle_night_commission():
            super().screenshot()

        self._await_recovery_frame = False
        if not getattr(self, '_handling_invitation', False) and not getattr(self, '_recovery_handling', False):
            self.stuck_record_check()

        return self.image

    @contextmanager
    def login_wait(self):
        """Keep slow-login protection across clicks, with a finite total budget."""
        if not self.performance.low_spec:
            yield
            return
        previous = self._login_deadline
        self._login_deadline = previous or (time.monotonic() + self.performance.timeout(300))
        self.stuck_record_clear()
        try:
            yield
        finally:
            self._login_deadline = previous
            self.stuck_record_clear()
            self.click_record_clear()

    def _check_login_deadline(self) -> bool:
        if self._login_deadline is not None and time.monotonic() >= self._login_deadline:
            self.recover_by_escape('Low spec login exceeded 900 seconds')
            return True
        return False

    def reset_task_recovery(self):
        self._task_flow_guard_disabled = False
        self._escape_attempts = 0
        self._escape_generation = 0
        self._click_recovery_at = None
        self._click_recovery_reason = ''
        self._click_recovery_buttons = set()
        self._await_recovery_frame = False
        self._verified_click = None
        self._confirm_retry_permit = None

    def _recovery_timeout(self, seconds: float) -> float:
        performance = getattr(self, 'performance', None)
        return performance.timeout(seconds) if performance is not None else seconds

    def recover_by_escape(self, reason: str) -> None:
        if getattr(self, 'is_desktop', False) and self.app_lost_login():
            raise GameNotRunningError('Client dropped back to login')
        if not self.app_is_running():
            raise GameNotRunningError('Game died')
        if self._escape_attempts >= 3:
            raise TaskRecoveryFailed(f'ESC recovery failed after 3 attempts: {reason}')
        learning = getattr(self, '_error_learning', None)
        if learning is not None:
            try:
                learning_reason = (
                    'wait:' + ','.join(sorted(self.detect_record))
                    if reason.startswith('Wait too long:')
                    else reason
                )
                plan = learning.begin(learning_reason, getattr(self, 'image', None))
                if plan:
                    logger.info(
                        f'Learned recovery: {plan["action"]}, verify page={plan["page"]}, '
                        f'settle={plan["settle"]:.1f}s'
                    )
            except Exception as exc:
                logger.warning(f'Error learning disabled for this task: {exc}')
                self._error_learning = None
        if not getattr(self, '_failed_original_page_captured', False):
            try:
                from module.script.failed_task_recovery import page_key
                self._failed_original_page = page_key(self.config, self)
            except Exception:
                self._failed_original_page = None
            self._failed_original_page_captured = True
        self._escape_attempts += 1
        logger.warning(f'ESC recovery {self._escape_attempts}/3: {reason}')
        try:
            self.press_escape()
        except Exception as exc:
            raise TaskRecoveryFailed(f'Unable to send ESC: {exc}') from exc
        self._escape_generation = getattr(self, '_escape_generation', 0) + 1
        self._await_recovery_frame = True
        self._click_recovery_at = None
        self._click_recovery_buttons.clear()
        self.click_record_clear()
        records = set(self.detect_record)
        if self._login_deadline is not None:
            self._login_deadline = time.monotonic() + self._recovery_timeout(300)
        self.stuck_record_clear()
        self.detect_record.update(records)

    def _check_click_recovery(self) -> bool:
        if self._click_recovery_at is None:
            return False
        if time.monotonic() - self._click_recovery_at >= self._recovery_timeout(60):
            self.recover_by_escape(self._click_recovery_reason)
        return True

    def confirm_task_round_progress(self):
        """Renew task residence only after a new round is confirmed in fresh frames."""
        self._task_flow_round_generation = getattr(self, '_task_flow_round_generation', 0) + 1
        self.confirm_control_progress(())

    def confirm_control_progress(self, buttons):
        """Call only after verifying a new page/round, never on a button match."""
        self._task_flow_progress_generation = getattr(self, '_task_flow_progress_generation', 0) + 1
        names = {getattr(button, 'name', str(button)) for button in buttons}
        pending = getattr(self, '_verified_click', None)
        if pending and pending['name'] in names:
            self._verified_click = None
        for button in buttons:
            self.click_record_remove(getattr(button, 'name', button))
        reason = getattr(self, '_click_recovery_reason', '')
        for prefix in ('Too many click for a button: ', 'Too many click between 2 buttons: '):
            if reason.startswith(prefix):
                blocked = set(reason[len(prefix):].split(', '))
                if blocked <= names:
                    self._click_recovery_at = None
                    self._click_recovery_reason = ''
                    self._click_recovery_buttons.clear()
                break

    def release_during_wait(self):
        # Scrcpy server is still sending video stream,
        # stop it during wait
        # self.config.script.device.screenshot_method = 'scrcpy'
        if self.config.script.device.screenshot_method == 'scrcpy':
            self._scrcpy_server_stop()
        if self.config.Emulator_ScreenshotMethod == 'nemu_ipc':
            self.nemu_ipc_release()

    def stuck_record_add(self, button):
        """
        当你要设置这个时候检测为长时间的时候，你需要在这里添加
        如果取消后，需要在`stuck_record_clear`中清除
        :param button:
        :return:
        """
        self.detect_record.add(str(button))
        logger.info(f'Add stuck record: {button}')

    def stuck_record_clear(self):
        self.detect_record = {'LOGIN_CHECK'} if self._login_deadline is not None else set()
        self.stuck_timer.reset()
        self.stuck_timer_long.reset()

    def stuck_record_check(self):
        """
        Trigger bounded ESC recovery (max 3 attempts) on stuck wait; raise GameNotRunningError if dead.
        """
        if self._check_login_deadline() or self._check_click_recovery():
            return False
        if self._login_deadline is not None:
            return False
        reached = self.stuck_timer.reached()
        reached_long = self.stuck_timer_long.reached()

        if not reached:
            return False
        if not reached_long:
            for button in self.stuck_long_wait_list:
                if button in self.detect_record:
                    return False

        logger.warning('Wait too long')
        logger.warning(f'Waiting for {self.detect_record}')
        self.recover_by_escape(f'Wait too long: {self.detect_record}')
        return False

    def handle_control_check(self, button):
        if self._await_recovery_frame or self._check_login_deadline():
            return False
        if self._check_click_recovery():
            if self._await_recovery_frame or str(button) in self._click_recovery_buttons:
                return False
            self._click_recovery_at = None
            self._click_recovery_buttons.clear()
        click_interval = self.performance.click_interval if hasattr(self, 'performance') else 0
        if click_interval and self._last_control_time is not None:
            remaining = click_interval - (time.monotonic() - self._last_control_time)
            if remaining > 0:
                time.sleep(remaining)
        if self._check_login_deadline():
            return False
        self._last_control_time = time.monotonic()
        self.stuck_record_clear()
        self.click_record_add(button)
        history = set(self.click_record)
        try:
            self.click_record_check()
        except GameTooManyClickError as exc:
            self._click_recovery_at = time.monotonic()
            self._click_recovery_reason = str(exc)
            self._click_recovery_buttons = history
            logger.warning(f'Repeated clicks paused; wait {self._recovery_timeout(60)}s before ESC')
            return False
        return True

    def click_record_add(self, button):
        self.click_record.append(str(button))

    def click_record_clear(self):
        self.click_record.clear()

    def click_record_remove(self, button):
        """
        Remove a button from `click_record`

        Args:
            button (Button):

        Returns:
            int: Number of button removed
        """
        removed = 0
        for _ in range(self.click_record.maxlen):
            try:
                self.click_record.remove(str(button))
                removed += 1
            except ValueError:
                # Value not in queue
                break

        return removed

    def click_record_check(self):
        """
        Raises:
            GameTooManyClickError:
        """
        from module.device.repeat_policy import chess_repeat_unrestricted
        if chess_repeat_unrestricted(self):
            return
        if not self.click_record:
            return
        count = {}
        for key in self.click_record:
            count[key] = count.get(key, 0) + 1
        count = sorted(count.items(), key=lambda item: item[1], reverse=True)
        click_limit = self.performance.click_limit if hasattr(self, 'performance') else 10
        alt_limit = self.performance.alternating_click_limit if hasattr(self, 'performance') else 6
        if count[0][1] >= click_limit:
            logger.warning(f'Too many click for a button: {count[0][0]}')
            logger.warning(f'History click: {[str(prev) for prev in self.click_record]}')
            self.click_record_clear()
            raise GameTooManyClickError(f'Too many click for a button: {count[0][0]}')
        if len(count) >= 2 and count[0][1] >= alt_limit and count[1][1] >= alt_limit:
            logger.warning(f'Too many click between 2 buttons: {count[0][0]}, {count[1][0]}')
            logger.warning(f'History click: {[str(prev) for prev in self.click_record]}')
            self.click_record_clear()
            raise GameTooManyClickError(f'Too many click between 2 buttons: {count[0][0]}, {count[1][0]}')

    def disable_stuck_detection(self):
        """
        Disable stuck detection and its handler. Usually uses in semi auto and debugging.
        """
        logger.info('Disable stuck detection')
        self._task_flow_guard_disabled = True

        def empty_function(*arg, **kwargs):
            return False

        self.click_record_check = empty_function
        self.stuck_record_check = empty_function

    def app_start(self):
        # 桌面模式：窗口缺失时自动启动客户端并绑定 PID（空闲关闭后由 Restart 重新拉起）
        if self.is_desktop:
            if not self._desktop_ensure_launched():
                logger.error('Desktop client not running and auto-launch failed, '
                             'please start the game manually or check game_path')
                raise GameNotRunningError('Desktop client auto-launch failed')
            # 这里必然早于 app_handle_login，且是拉起客户端的唯一入口：客户区没校准到
            # 1280x720 的话登录 OCR 与点击坐标全错。运行期重拉时 Device 对象是复用的，
            # _init_desktop 不会再跑，所以校准不能只挂在初始化路径上
            self.desktop_window_set_size()
            return
        if not self.config.script.error.handle_error:
            logger.critical('No app stop/start, because HandleError disabled')
            logger.critical('Please enable Alas.Error.HandleError or manually login to AzurLane')
            raise RequestHumanTakeover
        super().app_start()
        self.stuck_record_clear()
        self.click_record_clear()

    def app_stop(self):
        # 桌面模式：关闭客户端。desktop_stop_client 内部已做「窗口消失 且 进程退出」
        # 验证并多轮重杀，关不掉时它已记 ERROR，这里只把结论透出
        if self.is_desktop:
            if not self.desktop_stop_client():
                logger.warning('Desktop client not released, residual process may remain')
            return
        if not self.config.script.error.handle_error:
            logger.critical('No app stop/start, because HandleError disabled')
            logger.critical('Please enable Alas.Error.HandleError or manually login to AzurLane')
            raise RequestHumanTakeover
        super().app_stop()
        self.stuck_record_clear()
        self.click_record_clear()

    def wait_app_start_ready(self, timeout: float = 15.0, interval: float = 0.5) -> None:
        """
        Wait after app_start until the foreground app is running and screen is no longer pure black.
        """
        deadline = time.monotonic() + self._recovery_timeout(timeout)
        screenshot_method = self.screenshot_methods.get(
            self.config.script.device.screenshot_method,
            self.screenshot_adb,
        )

        while time.monotonic() < deadline:
            if not self.app_is_running():
                time.sleep(interval)
                continue
            try:
                image = screenshot_method()
            except Exception as e:
                logger.info(f'Wait game start ready: screenshot probe failed: {e}')
                time.sleep(interval)
                continue
            color = get_color(image, area=(0, 0, 1280, 720))
            if sum(color) >= 1:
                logger.info(f'Game start ready, frame color: {color}')
                return
            time.sleep(interval)

        logger.info('Wait game start ready timeout, continue with login flow')


if __name__ == "__main__":
    device = Device(config="oas1")
    # cv2.imshow("imgSrceen", device.screenshot())  # 显示
    # cv2.waitKey(0)
    # cv2.destroyAllWindows()
