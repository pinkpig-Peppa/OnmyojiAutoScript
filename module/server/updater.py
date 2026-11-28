import datetime
import re
import shlex
import subprocess
import threading
import time
import requests
from typing import Generator, List, Sequence, Tuple

from deploy.config import ExecutionError
from deploy.git import GitManager
from deploy.pip import PipManager
from deploy.utils import DEPLOY_CONFIG
from module.logger import logger
from module.base.retry import retry
from module.server.config import DeployConfig


class Updater(DeployConfig, GitManager, PipManager):
    def __init__(self, file=DEPLOY_CONFIG):
        super().__init__(file=file)
        self.state = 0

    @property
    def delay(self):
        self.read()
        return int(self.CheckUpdateInterval) * 60

    @property
    def schedule_time(self):
        self.read()
        t = self.AutoRestartTime
        if t is not None:
            return datetime.time.fromisoformat(t)
        else:
            return None

    UNSAFE_SHELL_CHARS = ('|', '&', ';', '$', '`', '\n', '\r', '>', '<', '%', '^', '(', ')')
    _SAFE_REF_RE = re.compile(r'^[A-Za-z0-9._/]+$')

    @classmethod
    def _validate_git_ref(cls, ref: str) -> str:
        ref = str(ref or '').strip()
        if not ref or ref.startswith('-') or '..' in ref or not cls._SAFE_REF_RE.match(ref):
            raise ValueError(f'unsafe git ref: {ref!r}')
        return ref

    def _normalize_argv(self, command: str | Sequence[str]) -> list[str]:
        if isinstance(command, str):
            if any(ch in command for ch in self.UNSAFE_SHELL_CHARS):
                raise ValueError(f'unsafe characters in git command: {command!r}')
            normalized = command.replace(r"\\", "/").replace("\\", "/")
            argv = shlex.split(normalized, posix=True)
        else:
            argv = [str(part) for part in command]
            for part in argv:
                if any(ch in part for ch in ('\n', '\r', '\x00')):
                    raise ValueError(f'unsafe control character in git argument: {part!r}')
        if not argv:
            raise ValueError('empty git command')
        return argv

    def execute_output(self, command: str | Sequence[str]) -> str:
        argv = self._normalize_argv(command)
        creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf8",
            shell=False,
            creationflags=creationflags,
        )
        return result.stdout

    def _execute_git_checked(self, argv: Sequence[str]) -> bool:
        checked = self._normalize_argv(argv)
        creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        result = subprocess.run(
            checked,
            capture_output=True,
            text=True,
            encoding="utf8",
            shell=False,
            creationflags=creationflags,
        )
        return result.returncode == 0

    def get_commit(self, revision="", n=1, short_sha1=False) -> Tuple:
        """
        Return:
            (sha1, author, isotime, message,)
        """
        ph = "h" if short_sha1 else "H"
        argv = [self.git, "log"]
        if revision:
            if revision.startswith("-"):
                raise ValueError(f'unsafe git revision: {revision!r}')
            argv.append(revision)
        argv.extend([f"--pretty=format:%{ph}---%an---%ad---%s", "--date=iso", f"-{int(n)}"])
        log = self.execute_output(argv)

        if not log:
            return None, None, None, None

        logs = log.split("\n")
        logs = list(map(lambda item: tuple(item.split("---")), logs))

        if n == 1:
            return logs[0]
        else:
            return logs

    def current_branch(self) -> str:
        return self._validate_git_ref(self.Branch)

    def current_commit(self) -> str:
        return self.get_commit()

    def latest_commit(self) -> str:
        source = "origin"
        branch = self._validate_git_ref(self.Branch)
        return self.get_commit(f"{source}/{branch}")

    def check_update(self) -> bool:
        self.state = "checking"

        source = "origin"
        branch = self._validate_git_ref(self.Branch)
        for _ in range(3):
            if self._execute_git_checked([self.git, "fetch", "--", source, branch]):
                break
        else:
            logger.warning("Git fetch failed")
            return False

        log = self.execute_output(
            [self.git, "log", "--not", f"--remotes={source}/*", "-1", "--oneline"]
        )
        if log:
            logger.info(
                f"Cannot find local commit {log.split()[0]} in upstream, skip update"
            )
            return False

        sha1, _, _, message = self.get_commit(f"..{source}/{branch}")

        if sha1:
            logger.info("New update available")
            logger.info(f"{sha1[:8]} - {message}")
            return True
        else:
            logger.info("No update")
            return False

    def execute_pull(self) -> bool:
        source = "origin"
        branch = self._validate_git_ref(self.Branch)
        for _ in range(3):
            if self._execute_git_checked([self.git, "pull", "--no-rebase", "--", source, branch]):
                return True
        logger.warning("Git pull failed")
        return False



if __name__ == "__main__":
    updater = Updater()
    print(updater.latest_commit())



