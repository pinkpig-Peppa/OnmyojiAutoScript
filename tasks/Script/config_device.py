# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from enum import Enum
from typing import Union
from pydantic import BaseModel, ValidationError, Field

from module.logger import logger

class PackageName(str, Enum):
    AUTO = 'auto'
    NETEASE_ONMYOJI = 'com.netease.onmyoji.wyzymnqsd_cps'  # 网易自家的阴阳师
    NETEASE_MI = 'com.netease.onmyoji.mi'  # 小米
    NETEASE = 'com.netease.onmyoji'
    NETEASE_HUAWEI = 'com.netease.onmyoji.huawei'
    NETEASE_BILIBILI = 'com.netease.onmyoji.bili'

class ScreenshotMethod(str, Enum):
    AUTO = 'auto'
    ADB = 'ADB'
    ADB_NC = 'ADB_nc'
    UIAUTOMATOR2 = 'uiautomator2'
    DROIDCAST = 'DroidCast'
    DROIDCAST_RAW = 'DroidCast_raw'
    SCRCPY = 'scrcpy'
    WINDOW_BACKGROUND = 'window_background'
    NEMU_IPC = 'nemu_ipc'

class ControlMethod(str, Enum):
    ADB = 'adb'
    UIAUTOMATOR2 = 'uiautomator2'
    MINITOUCH = 'minitouch'
    WINDOW_MESSAGE = 'window_message'

class EmulatorInfoType(str, Enum):
    # module.device.platform2.emulator_base.EmulatorBase
    AUTO = 'auto'
    NoxPlayer = 'NoxPlayer'
    NoxPlayer64 = 'NoxPlayer64'
    BlueStacks4 = 'BlueStacks4'
    BlueStacks5 = 'BlueStacks5'
    BlueStacks4HyperV = 'BlueStacks4HyperV'
    BlueStacks5HyperV = 'BlueStacks5HyperV'
    LDPlayer3 = 'LDPlayer3'
    LDPlayer4 = 'LDPlayer4'
    LDPlayer9 = 'LDPlayer9'
    MuMuPlayer = 'MuMuPlayer'
    MuMuPlayerX = 'MuMuPlayerX'
    MuMuPlayer12 = 'MuMuPlayer12'
    MEmuPlayer = 'MEmuPlayer'

class Device(BaseModel):
    # adb 序列号；桌面客户端模式（见 desktop 组）下本字段退场
    serial: str = Field(default="auto",
                        description='serial_help')
    # 模拟器模式：窗口标题或句柄编号；桌面客户端模式：客户端窗口标题（留空自动识别）
    handle: str = Field(default='',
                        description='handle_help')
    package_name: PackageName = Field(title='Package Name',
                                      default=PackageName.AUTO,
                                      description='package_name_help')
    screenshot_method: ScreenshotMethod = Field(default=ScreenshotMethod.AUTO,
                                                description='screenshot_method_help')
    control_method: ControlMethod = Field(default=ControlMethod.MINITOUCH,
                                          description='control_method_help')
    adb_restart: bool = Field(default=False,
                              description='adb_restart_help')
    emulatorinfo_type: Union[EmulatorInfoType, str] = Field(default=EmulatorInfoType.AUTO,
                                                description='emulatorinfo_type_help')
    emulatorinfo_name: str = Field(default='',
                                   description='emulatorinfo_name_help')
    emulatorinfo_path: str = Field(default='',
                                   description='emulatorinfo_path_help')
    # 举例, E:\ProgramFiles\MuMuPlayer-12.0\shell\MuMuPlayer.exe
    # 模拟器启动时最小化
    emulator_window_minimize: bool = Field(default=False,
                                             description='模拟器静默启动并最小化')
    # 启动时纯后台运行模拟器，不显示窗口和任务栏
    run_background_only: bool = Field(default=False,
                                             description='模拟器无UI后台运行，关掉后重启脚本会重新显示（无需重启OAS）')
    # 低端机适配：延长登录/响应等待、降低截图及点击频率；重启脚本生效
    low_spec_mode: bool = Field(
        default=False,
        title='低端机模式',
        description='默认关闭。开启后普通卡死等待延长为180秒，登录最多等待900秒，'
                    '通用界面等待延长为3倍；截图至少间隔0.8秒（战斗1.5秒），'
                    '操作至少间隔1.2秒。保留原OCR模型和识别阈值。重启脚本生效。',
    )
    human_click_enabled: bool = Field(
        default=True,
        title='拟人点击采样与节奏',
        description='启用截断高斯区域采样、后台悬停最小急动度轨迹（window_message）与会话级节奏停顿。',
    )
    error_learning_enabled: bool = Field(
        default=True,
        title='本地错误经验学习',
        description='记录界面异常及恢复结果。相同任务、设备和相似画面至少两次恢复后任务明确成功，'
                    '才优先复用等待时间和页面识别顺序；失败后停用该经验。仅本机保存，不改变点击上限、'
                    '战斗等待300秒及最多3次ESC限制。下次任务生效。',
    )



if __name__ == '__main__':
    d = Device()
    print(d.json())
    print(d.schema_json())
    try:
        d.control_method = 'adb'
    except ValidationError as e:
        print(e)
