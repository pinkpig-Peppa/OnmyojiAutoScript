"""Keep an unfinished business task ahead of subsequent scheduled tasks."""
import json
import os
from datetime import datetime
from pathlib import Path

from module.config.config import Function
from module.config.utils import convert_to_underscore
from module.logger import logger


def _dump_model(model) -> dict:
    if hasattr(model, 'model_dump'):
        return model.model_dump()
    return model.dict()


class TaskCompletionGate:
    def __init__(self, path):
        self.path = Path(path)
        self.task = ''
        self.released = {}
        self.not_before = None
        self.recovery_not_before = {}
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding='utf-8'))
            self.task = data.get('task', '')
            if not isinstance(self.task, str):
                raise ValueError('Invalid unfinished task checkpoint')
            self.released = data.get('released', {})
            if not isinstance(self.released, dict):
                raise ValueError('Invalid task release ledger')
            for task, released_at in self.released.items():
                if task not in ('GoldYoukai', 'ExperienceYoukai') or not isinstance(released_at, str):
                    raise ValueError('Invalid task release receipt')
                if datetime.fromisoformat(released_at).tzinfo is not None:
                    raise ValueError('Invalid task release clock')
            not_before = data.get('not_before')
            if not_before is not None:
                if not self.task or not isinstance(not_before, str):
                    raise ValueError('Invalid unfinished task retry clock')
                self.not_before = datetime.fromisoformat(not_before)
                if self.not_before.tzinfo is not None:
                    raise ValueError('Invalid unfinished task retry clock')
            recovery = data.get('recovery_not_before', {})
            if not isinstance(recovery, dict):
                raise ValueError('Invalid task recovery retry ledger')
            for task, not_before in recovery.items():
                if task not in ('Restart', 'GotoMain') or not isinstance(not_before, str):
                    raise ValueError('Invalid task recovery retry clock')
                retry_at = datetime.fromisoformat(not_before)
                if retry_at.tzinfo is not None:
                    raise ValueError('Invalid task recovery retry clock')
                self.recovery_not_before[task] = retry_at

    def _write(self, task, released, not_before=None, recovery_not_before=None):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        data = {'task': task}
        if released:
            data['released'] = released
        if task and not_before is not None:
            data['not_before'] = not_before.isoformat()
        recovery = self.recovery_not_before if recovery_not_before is None else recovery_not_before
        if recovery:
            data['recovery_not_before'] = {name: retry.isoformat() for name, retry in recovery.items()}
        with temporary.open('w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(self.path)

    def retain(self, task):
        if not isinstance(task, str) or not task:
            raise ValueError('Invalid unfinished task checkpoint')
        if self.task and task != self.task:
            logger.info(f'Keep unfinished task `{self.task}` instead of replacing it with `{task}`')
            return  # Recovery or another task must not replace the unfinished work.
        self._write(task, self.released, self.not_before)
        self.task = task
        logger.info(f'Task `{task}` checkpoint retained until completion')

    def defer(self, task, not_before):
        """Persist a failed task's earliest retry without shortening an existing wait."""
        if not isinstance(task, str) or not task:
            raise ValueError('Invalid unfinished task checkpoint')
        if not isinstance(not_before, datetime) or not_before.tzinfo is not None:
            raise ValueError('Invalid unfinished task retry clock')
        if self.task and task != self.task:
            logger.info(f'Keep unfinished task `{self.task}` instead of deferring unrelated task `{task}`')
            return False
        if self.not_before is not None:
            not_before = max(self.not_before, not_before)
        self._write(task, self.released, not_before)
        self.task = task
        self.not_before = not_before
        logger.info(f'Task `{task}` checkpoint retained; retry not before {not_before}')
        return True

    def defer_recovery(self, task, not_before):
        """Persist auxiliary recovery waits independently from unfinished work."""
        if task not in ('Restart', 'GotoMain'):
            raise ValueError('Invalid task recovery name')
        if not isinstance(not_before, datetime) or not_before.tzinfo is not None:
            raise ValueError('Invalid task recovery retry clock')
        recovery = dict(self.recovery_not_before)
        if task in recovery:
            not_before = max(recovery[task], not_before)
        recovery[task] = not_before
        self._write(self.task, self.released, self.not_before, recovery)
        self.recovery_not_before = recovery
        logger.info(f'Recovery `{task}` retained; retry not before {not_before}')
        return not_before

    def release_recovery(self, task):
        """A successful recovery clears only its own retry deadline."""
        if task not in ('Restart', 'GotoMain'):
            raise ValueError('Invalid task recovery name')
        if task not in self.recovery_not_before:
            return False
        recovery = dict(self.recovery_not_before)
        del recovery[task]
        if self.task or self.released or recovery:
            self._write(self.task, self.released, self.not_before, recovery)
        else:
            self.path.unlink(missing_ok=True)
        self.recovery_not_before = recovery
        return True

    def release(self, completed_task=None):
        if completed_task is not None and self.task and self.task != completed_task:
            return
        released = dict(self.released)
        if completed_task == self.task and completed_task in ('GoldYoukai', 'ExperienceYoukai'):
            released[completed_task] = datetime.now().isoformat()
        if released or self.recovery_not_before:
            self._write('', released)
        else:
            self.path.unlink(missing_ok=True)
        self.task = ''
        self.released = released
        self.not_before = None

    def select(self, config):
        if self.task:
            # GUI schedule data needs this timestamp when get_next is bypassed.
            config.update_scheduler()
            key = convert_to_underscore(self.task)
            task_model = getattr(config.model, key, None)
            if task_model is None or not task_model.scheduler.enable:
                logger.info(f'Unfinished task `{self.task}` was removed or disabled; release checkpoint')
                self.release()
            else:
                selected = Function(key, _dump_model(task_model))
                if self.not_before is not None:
                    selected.next_run = max(selected.next_run, self.not_before)
                now = datetime.now()
                restart = getattr(config.model, 'restart', None)
                if (selected.next_run <= now and self.task != 'Restart' and restart is not None
                        and restart.scheduler.enable and restart.scheduler.next_run <= now):
                    restart_fn = Function('restart', _dump_model(restart))
                    recovery_wait = self.recovery_not_before.get('Restart')
                    if recovery_wait is None or recovery_wait <= now:
                        return restart_fn
                logger.info(f'Unfinished task `{selected.command}` remains scheduled for {selected.next_run}')
                return selected
        selected = config.get_next()
        recovery_wait = self.recovery_not_before.get(selected.command)
        if recovery_wait is not None:
            selected.next_run = max(selected.next_run, recovery_wait)
        return selected
