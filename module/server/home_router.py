# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import asyncio
import json
from fastapi import APIRouter, Body, HTTPException
from pathlib import Path

from module.config.utils import write_file
from module.logger import logger
from module.ocr.rpc import shutdown_ocr_server
from module.server.main_manager import MainManager
from module.server.updater import Updater
from module.server.i18n import I18n

home_app = APIRouter(
    prefix="/home",
    tags=["home"],
)


@home_app.get('/test')
async def home_test():
    return {'message': 'test'}


#  gcc -Wall -pedantic -shared -fPIC -o group_work.so group_work.c -lwiringPi
@home_app.get('/home_menu')
async def home_menu():
    return {'Home': [], 'Updater': [], 'Tool': []}


@home_app.post('/notify_test')
async def notify_test(setting: str, title: str, content: str):
    from module.notify.notify import Notifier
    def _send():
        notifier = Notifier(setting, True)
        try:
            return bool(notifier.push(title=title, content=content))
        finally:
            del notifier

    try:
        return await asyncio.to_thread(_send)
    except Exception as e:
        logger.exception(e)
        return str(e)


@home_app.post('/kill_server')
async def kill_server():
    await asyncio.to_thread(shutdown_ocr_server)
    MainManager.signal_kill_server = True
    return 'success'


@home_app.get('/update_info')
async def update_info():
    def _fetch():
        updater = Updater()
        return {
            'is_update': updater.check_update(),
            'branch': updater.current_branch(),
            'current_commit': updater.current_commit(),
            'latest_commit': updater.latest_commit(),
            'commit': updater.get_commit(n=15),
        }

    try:
        return await asyncio.to_thread(_fetch)
    except Exception as e:
        logger.error(e)
        return None


@home_app.post('/execute_update')
async def execute_update():
    # 下拉仓库 -> 关闭所有脚本进程 -> 最后重启oasx
    try:
        await asyncio.to_thread(lambda: Updater().execute_pull())
    except Exception as e:
        logger.error(e)
    return '手动更新将会立即结束运行中的脚本服务, 最后你还需重启oasx'


@home_app.put('/chinese_translate')
async def chinese_translate(data: dict = Body(...)):
    try:
        await asyncio.to_thread(I18n.save_zh_cn, data)
    except Exception as e:
        logger.error(e)
        raise HTTPException(status_code=400, detail=str(e))
    return True


@home_app.get('/additional_translate')
async def additional_translate() -> dict:
    try:
        return await asyncio.to_thread(I18n.load_additions)
    except Exception as e:
        logger.error(e)
    return {}


@home_app.get('/export_diagnostic')
async def export_diagnostic(config_name: str = ''):
    from module.server.diagnostic import build_diagnostic_zip
    try:
        zip_path = await asyncio.to_thread(build_diagnostic_zip, config_name)
        return {'success': True, 'path': str(zip_path)}
    except Exception as e:
        logger.exception(e)
        return {'success': False, 'path': '', 'error': str(e)}
