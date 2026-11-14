# This Python file uses the following encoding: utf-8
"""OAS 一键体检: 只读检查运行环境, 不修改任何配置。

设计参考 brew doctor / npm doctor: 分类自查, 输出 pass/warn/fail + 可执行建议。
每项检查独立捕获异常, 单项失败不影响整体。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from importlib import metadata
from pathlib import Path
from typing import Any

from module.logger import logger

# 允许通过 OAS_ROOT 指定项目根目录 (便于在仓库外对部署目录做体检)
PROJECT_ROOT = Path(os.environ.get('OAS_ROOT') or Path.cwd()).resolve()
TOOLKIT = PROJECT_ROOT / 'toolkit'
ADB_BIN = TOOLKIT / 'Lib' / 'site-packages' / 'adbutils' / 'binaries' / 'adb.exe'
CONFIG_DIR = PROJECT_ROOT / 'config'
LOG_DIR = PROJECT_ROOT / 'log'

# OAS 硬性要求: 模拟器分辨率必须是 1280x720 (横屏)
EXPECTED_SIZE = (1280, 720)
MIN_FREE_GB = 1.0
WARN_FREE_GB = 5.0

# 必装依赖 / 可选依赖
REQUIRED_PACKAGES = [
    ('fastapi', 'fastapi'),
    ('uvicorn', 'uvicorn'),
    ('pydantic', 'pydantic'),
    ('opencv-python', 'opencv-python'),
    ('numpy', 'numpy'),
    ('adbutils', 'adbutils'),
    ('pyyaml', 'pyyaml'),
]
OPTIONAL_PACKAGES = [
    ('onepush', 'onepush'),
    ('apprise', 'apprise'),
]


def _result(check_id: str, title: str, status: str, detail: str, hint: str = '') -> dict[str, Any]:
    """status: pass / warn / fail / skip"""
    return {'id': check_id, 'title': title, 'status': status, 'detail': detail, 'hint': hint}


def _run(cmd: list[str], timeout: float = 15.0) -> tuple[int, str]:
    """执行外部命令, 返回 (退出码, 合并输出)。不抛异常。"""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            encoding='utf-8',
            errors='replace',
        )
        out = (proc.stdout or '') + (proc.stderr or '')
        return proc.returncode, out.strip()
    except FileNotFoundError:
        return -1, 'command not found'
    except subprocess.TimeoutExpired:
        return -2, f'timeout after {timeout:.0f}s'
    except Exception as e:  # noqa: BLE001 - 体检不应因单项异常中断
        return -3, str(e)


def _load_config(config_name: str) -> tuple[dict | None, str]:
    """读取实例配置, 返回 (data, 实际实例名)。"""
    name = (config_name or '').strip()
    if not name:
        try:
            from module.server.config_manager import ConfigManager
            files = ConfigManager.all_script_files()
        except Exception:
            files = []
        if not files:
            return None, ''
        name = files[0]
    path = CONFIG_DIR / f'{name}.json'
    # 只允许已存在的实例名, 防止路径穿越
    if not path.resolve().is_relative_to(CONFIG_DIR.resolve()):
        return None, ''
    if not path.is_file():
        return None, ''
    try:
        return json.loads(path.read_text(encoding='utf-8')), name
    except Exception as e:  # noqa: BLE001
        logger.warning(f'doctor: config {name} parse failed: {e}')
        return None, name


def _check_config(config_data: dict | None, name: str) -> dict[str, Any]:
    if not name:
        return _result('config', '实例配置', 'fail', 'config 目录下没有任何实例配置文件',
                       '在 OASX 面板新建一个配置后再体检')
    if config_data is None:
        return _result('config', '实例配置', 'fail', f'{name}.json 无法解析',
                       'JSON 损坏, 可用 .bak 备份恢复或重新生成配置')
    enabled = [
        task for task, cfg in config_data.items()
        if isinstance(cfg, dict) and isinstance(cfg.get('scheduler'), dict)
        and cfg['scheduler'].get('enable') is True
    ]
    if not enabled:
        return _result('config', '实例配置', 'warn', f'{name}: 配置可解析, 但没有任何启用中的任务',
                       '在面板中启用至少一个任务, 否则调度器会空转')
    return _result('config', '实例配置', 'pass', f'{name}: 配置可解析, 启用任务 {len(enabled)} 个')


def _check_adb_binary() -> dict[str, Any]:
    if ADB_BIN.is_file():
        return _result('adb_binary', 'ADB 可执行文件', 'pass', str(ADB_BIN))
    which = shutil.which('adb')
    if which:
        return _result('adb_binary', 'ADB 可执行文件', 'warn', f'toolkit 内置 adb 缺失, 回退系统 adb: {which}',
                       '建议重装 toolkit 以恢复内置 adb')
    return _result('adb_binary', 'ADB 可执行文件', 'fail', f'未找到 {ADB_BIN}, 系统 PATH 中也没有 adb',
                   '重新运行安装器修复 toolkit')


def _adb_cmd() -> list[str]:
    return [str(ADB_BIN)] if ADB_BIN.is_file() else ['adb']


def _check_adb_server() -> tuple[dict[str, Any], list[str]]:
    """返回 (检查结果, 在线设备列表)。"""
    code, out = _run(_adb_cmd() + ['devices'], timeout=20)
    if code != 0:
        hint = '启动 MuMu 模拟器后重试; 若仍失败, 检查 5037 端口是否被其他程序占用'
        return _result('adb_server', 'ADB 服务', 'fail', f'adb devices 执行失败: {out[:200]}', hint), []
    devices = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == 'device':
            devices.append(parts[0])
    if not devices:
        return _result('adb_server', 'ADB 服务', 'warn', 'ADB 服务正常, 但当前没有在线设备',
                       '启动 MuMu 模拟器并开启 ADB 调试'), []
    return _result('adb_server', 'ADB 服务', 'pass', f'在线设备 {len(devices)} 个: {", ".join(devices)}'), devices


def _check_device(config_data: dict | None, devices: list[str]) -> tuple[dict[str, Any], str]:
    """返回 (检查结果, 实际使用的 serial)。"""
    serial = ''
    if isinstance(config_data, dict):
        device_cfg = config_data.get('script', {}).get('device', {})
        if isinstance(device_cfg, dict):
            serial = str(device_cfg.get('serial') or '').strip()
    if not serial or serial.lower() == 'auto':
        if not devices:
            return _result('device', '模拟器设备', 'skip', 'serial 为 auto, 且当前无在线设备'), ''
        return _result('device', '模拟器设备', 'pass', f'serial=auto, 自动选用 {devices[0]}'), devices[0]
    if serial not in devices:
        return _result('device', '模拟器设备', 'fail', f'配置的 {serial} 不在在线设备中 (在线: {devices or "无"})',
                       '启动对应模拟器, 或在配置中改为 auto'), serial
    return _result('device', '模拟器设备', 'pass', f'{serial} 在线'), serial


def _check_resolution(serial: str) -> dict[str, Any]:
    if not serial:
        return _result('resolution', '模拟器分辨率', 'skip', '无在线设备, 跳过')
    code, out = _run(_adb_cmd() + ['-s', serial, 'shell', 'wm', 'size'])
    if code != 0:
        return _result('resolution', '模拟器分辨率', 'warn', f'读取分辨率失败: {out[:150]}',
                       '可手动在模拟器设置中确认分辨率为 1280x720')
    def _parse(line: str):
        if ':' not in line:
            return None
        raw = line.split(':', 1)[1].strip()
        if 'x' not in raw:
            return None
        try:
            w, h = raw.split('x', 1)
            return int(w), int(h)
        except ValueError:
            return None

    override = physical = None
    for line in out.splitlines():
        # Override size 才是实际生效的分辨率, 优先采用
        if 'Override size' in line:
            override = _parse(line)
        elif 'Physical size' in line:
            physical = _parse(line)
    size = override or physical
    if size is None:
        return _result('resolution', '模拟器分辨率', 'warn', f'无法解析输出: {out[:150]}')
    # 横屏 1280x720 或竖屏 720x1280
    if size == EXPECTED_SIZE or size == (EXPECTED_SIZE[1], EXPECTED_SIZE[0]):
        return _result('resolution', '模拟器分辨率', 'pass', f'{size[0]}x{size[1]} (OAS 要求 1280x720)')
    return _result('resolution', '模拟器分辨率', 'fail', f'当前 {size[0]}x{size[1]}, 不是 1280x720',
                   '在模拟器设置中把分辨率改为 1280x720 (横屏), OAS 只支持该分辨率')


def _check_game(config_data: dict | None, serial: str) -> dict[str, Any]:
    if not serial:
        return _result('game', '游戏安装', 'skip', '无在线设备, 跳过')
    package = ''
    if isinstance(config_data, dict):
        device_cfg = config_data.get('script', {}).get('device', {})
        if isinstance(device_cfg, dict):
            package = str(device_cfg.get('package_name') or '').strip()
    if not package:
        return _result('game', '游戏安装', 'warn', '配置中没有 package_name')
    code, out = _run(_adb_cmd() + ['-s', serial, 'shell', 'pm', 'path', package])
    if code == 0 and 'package:' in out:
        return _result('game', '游戏安装', 'pass', f'{package} 已安装')
    return _result('game', '游戏安装', 'fail', f'{package} 未安装或不可见',
                   '在模拟器中安装阴阳师客户端')


def _check_ocr() -> dict[str, Any]:
    engines = []
    for module_name, label in (('paddleocr', 'paddleocr'), ('ppocronnx', 'ppocr-onnx')):
        try:
            __import__(module_name)
            engines.append(label)
        except Exception:  # noqa: BLE001
            continue
    if not engines:
        return _result('ocr', 'OCR 引擎', 'fail', '未检测到可用 OCR 引擎 (paddleocr / ppocr-onnx)',
                       '运行 toolkit\\python.exe -m pip install -r requirements.txt')
    # 模型缓存: 不同引擎版本落在不同目录
    cache_hits = [
        p for p in (
            Path.home() / '.paddlex',
            Path.home() / '.paddleocr',
            Path.home() / '.cache' / 'ppocr',
            TOOLKIT / 'Lib' / 'site-packages' / 'ppocronnx',
        ) if p.exists()
    ]
    if not cache_hits:
        return _result('ocr', 'OCR 引擎', 'warn', f'引擎 {"/".join(engines)} 可用, 但未找到模型缓存',
                       '首次运行会自动下载模型, 请保持网络畅通')
    return _result('ocr', 'OCR 引擎', 'pass', f'引擎 {"/".join(engines)}, 模型缓存: {cache_hits[0].name}')


def _check_packages() -> dict[str, Any]:
    missing = []
    optional_missing = []
    versions = []
    for dist_name, label in REQUIRED_PACKAGES:
        try:
            versions.append(f'{label} {metadata.version(dist_name)}')
        except metadata.PackageNotFoundError:
            missing.append(label)
    for dist_name, label in OPTIONAL_PACKAGES:
        try:
            versions.append(f'{label} {metadata.version(dist_name)}')
        except metadata.PackageNotFoundError:
            optional_missing.append(label)
    if missing:
        return _result('packages', 'Python 依赖', 'fail', f'缺少: {", ".join(missing)}',
                       '运行 toolkit\\python.exe -m pip install -r requirements.txt')
    detail = ', '.join(versions[:6]) + (' ...' if len(versions) > 6 else '')
    if optional_missing:
        return _result('packages', 'Python 依赖', 'warn',
                       f'{detail}; 可选依赖缺失: {", ".join(optional_missing)}',
                       '可选依赖仅影响对应通知渠道, 不影响脚本运行')
    return _result('packages', 'Python 依赖', 'pass', detail)


def _check_disk() -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(str(PROJECT_ROOT))
    except OSError as e:
        return _result('disk', '磁盘空间', 'warn', f'无法读取: {e}')
    free_gb = usage.free / (1024 ** 3)
    total_gb = usage.total / (1024 ** 3)
    detail = f'剩余 {free_gb:.1f} GB / 共 {total_gb:.0f} GB'
    if free_gb < MIN_FREE_GB:
        return _result('disk', '磁盘空间', 'fail', detail, '清理 log 目录或扩容, 低于 1GB 会导致截图中断')
    if free_gb < WARN_FREE_GB:
        return _result('disk', '磁盘空间', 'warn', detail, '建议保留 5GB 以上, 长期运行日志增长较快')
    return _result('disk', '磁盘空间', 'pass', detail)


def _check_log_dir() -> dict[str, Any]:
    if not LOG_DIR.exists():
        return _result('log_dir', '日志目录', 'warn', f'{LOG_DIR} 不存在',
                       '首次运行会自动创建, 若持续缺失请检查目录权限')
    try:
        files = [p for p in LOG_DIR.glob('*.txt') if p.is_file()]
    except OSError as e:
        return _result('log_dir', '日志目录', 'warn', f'无法读取: {e}')
    if not files:
        return _result('log_dir', '日志目录', 'pass', '目录存在, 暂无日志文件 (尚未运行任务)')
    latest = max(files, key=lambda p: p.stat().st_mtime)
    size_mb = latest.stat().st_size / (1024 ** 2)
    return _result('log_dir', '日志目录', 'pass', f'{len(files)} 个日志, 最新 {latest.name} ({size_mb:.1f} MB)')


def run_doctor(config_name: str = '') -> dict[str, Any]:
    """执行全部体检项, 返回结构化报告。"""
    checks: list[dict[str, Any]] = []
    config_data, resolved_name = _load_config(config_name)

    checks.append(_check_config(config_data, resolved_name))
    checks.append(_check_adb_binary())
    adb_result, devices = _check_adb_server()
    checks.append(adb_result)
    device_result, serial = _check_device(config_data, devices)
    checks.append(device_result)
    checks.append(_check_resolution(serial))
    checks.append(_check_game(config_data, serial))
    checks.append(_check_ocr())
    checks.append(_check_packages())
    checks.append(_check_disk())
    checks.append(_check_log_dir())

    summary = {
        'pass': sum(1 for c in checks if c['status'] == 'pass'),
        'warn': sum(1 for c in checks if c['status'] == 'warn'),
        'fail': sum(1 for c in checks if c['status'] == 'fail'),
        'skip': sum(1 for c in checks if c['status'] == 'skip'),
    }
    report = {
        'ok': summary['fail'] == 0,
        'instance': resolved_name,
        'summary': summary,
        'checks': checks,
    }
    logger.info(f'doctor: instance={resolved_name or "-"} ok={report["ok"]} {summary}')
    return report
