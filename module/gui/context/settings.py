# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import os
from pathlib import Path
from PySide6.QtCore import QObject, Slot, Signal

from module.logger import logger

class Setting(QObject):

    @classmethod
    def copy_from_template(cls) -> None:
        """
        从模板复制一个配置文件
        :return:
        """
        template_path = Path.cwd() / 'module' / 'config' / 'argument' / 'setting-template.json'
        if not template_path.exists():
            logger.error('template.json not exists')
            return
        with open(template_path, 'r', encoding='utf-8') as f:
            data = f.read()
        setting_path = Path.cwd() / 'module' / 'config' / 'argument' / 'setting.json'
        # 原子写入，避免写到一半退出导致 JSON 截断
        tmp_path = setting_path.with_name(setting_path.name + '.tmp')
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, setting_path)
        logger.info('setting.json copy from template.json success')

    @Slot(result="QString")
    def read(self) -> str:
        """
        读取配置文件的数据
        :return:
        """
        setting_path = Path.cwd() / 'module' / 'config' / 'argument' / 'setting.json'
        if not setting_path.exists():
            logger.error('setting.json not exists')
            self.copy_from_template()
        with open(setting_path, 'r', encoding='utf-8') as f:
            return f.read()

    @Slot(str)
    def update(self, data: str) -> None:
        """
        更新配置文件的数据
        :return:
        """
        setting_path = Path.cwd() / 'module' / 'config' / 'argument' / 'setting.json'
        if not setting_path.exists():
            logger.error('setting.json not exists')
            self.copy_from_template()
        # 原子写入，避免写到一半退出导致 JSON 截断
        tmp_path = setting_path.with_name(setting_path.name + '.tmp')
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, setting_path)
        logger.info('setting.json update success')
