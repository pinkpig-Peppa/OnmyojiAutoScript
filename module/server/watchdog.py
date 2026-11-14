# This Python file uses the following encoding: utf-8
# 看门狗: 检测脚本进程意外退出与任务超时未运行 (dead man's switch)
# 设计参考 Healthchecks.io: 失败队列管"跑失败了", 看门狗管"该跑没跑"。
# 判定规则:
#   - ScriptProcess.stop() 结束后会把 _process 置 None (正常停止/从未启动, 不告警)
#   - 进程意外退出时 _process 句柄仍在但已死亡 -> 连续两个周期确认后告警,
#     避免 stop() 秒级窗口内的误报
#   - 进程活着 = 正在跑长任务或正常调度, 队列积压不算故障 (避免误报)
# 告警走实例自己配置的 script.error 通知渠道; 未配置则只写日志。
import asyncio
from datetime import datetime, timedelta

from module.config.utils import read_file, deep_get
from module.logger import logger
from module.notify.notify import Notifier

# 检查周期(秒)
CHECK_INTERVAL = 300.0
# 任务超过 next_run 多久算"超时未运行"
OVERDUE_GRACE = timedelta(minutes=30)
# 同一异常的最短重复告警间隔
RE_ALERT_EVERY = timedelta(hours=1)


def _overdue_tasks(script_name: str, now: datetime) -> list[tuple[str, datetime]]:
    """列出该实例中已启用且超过宽限期还没运行的任务。"""
    tasks: list[tuple[str, datetime]] = []
    try:
        data = read_file(f'config/{script_name}.json')
    except Exception:
        return tasks
    if not isinstance(data, dict):
        return tasks
    for task, cfg in data.items():
        if not isinstance(cfg, dict) or deep_get(cfg, 'scheduler.enable') is not True:
            continue
        next_run = deep_get(cfg, 'scheduler.next_run')
        try:
            dt = datetime.strptime(str(next_run), '%Y-%m-%d %H:%M:%S')
        except (TypeError, ValueError):
            continue
        if dt < now - OVERDUE_GRACE:
            tasks.append((task, dt))
    return tasks


def _notify(script_name: str, title: str, content: str) -> None:
    """用该实例自己配置的 script.error 通知渠道推送; 未启用则只写日志。"""
    try:
        data = read_file(f'config/{script_name}.json')
    except Exception:
        return
    cfg = deep_get(data, 'script.error.notify_config')
    enable = deep_get(data, 'script.error.notify_enable') is True
    if not enable or not cfg:
        logger.info(f'watchdog: [{script_name}] notify not enabled, log only')
        return
    try:
        notifier = Notifier(str(cfg), enable=True)
        notifier.config_name = script_name.upper()
        notifier.push(title=title, content=content)
    except Exception as e:
        logger.warning(f'watchdog: [{script_name}] notify push failed: {e}')


async def watchdog_loop() -> None:
    from module.server.main_manager import mm
    last_alert: dict[str, datetime] = {}
    dead_prev: set[str] = set()
    logger.info(f'Watchdog started: interval={CHECK_INTERVAL:.0f}s grace={OVERDUE_GRACE}')
    while True:
        # 先等再查: 避开启动瞬间进程尚未拉起的窗口
        await asyncio.sleep(CHECK_INTERVAL)
        try:
            now = datetime.now()
            dead_now: set[str] = set()
            for name, sp in list(mm.script_process.items()):
                proc = getattr(sp, '_process', None)
                if proc is not None and not proc.is_alive():
                    dead_now.add(name)

            # 连续两个周期都死亡 -> 确认为意外退出
            for name in sorted(dead_now - dead_prev):
                logger.warning(f'watchdog: [{name}] process appears dead, confirming next cycle')
            for name in sorted(dead_now & dead_prev):
                key = f'{name}::crash'
                last = last_alert.get(key)
                if last is not None and now - last < RE_ALERT_EVERY:
                    continue
                last_alert[key] = now
                overdue = _overdue_tasks(name, now)
                if overdue:
                    detail = ', '.join(
                        f'{t} (planned {dt:%m-%d %H:%M}, {int((now - dt).total_seconds() // 60)}min late)'
                        for t, dt in overdue[:5]
                    )
                    content = (f'脚本进程意外退出, {len(overdue)} 个启用任务已超时未运行:\n{detail}')
                else:
                    content = '脚本进程意外退出, 任务调度已中断'
                logger.warning(f'watchdog: [{name}] {content}')
                _notify(name, 'Watchdog', content)

            dead_prev = dead_now
        except asyncio.CancelledError:
            logger.info('Watchdog stopped')
            raise
        except Exception as e:
            logger.exception(f'watchdog loop error: {e}')
