# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import sys
import os
import json

from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType
from PySide6.QtCore import Qt, QObject, QTranslator, QLocale, Slot
from pathlib import Path

from module.gui.utils import get_work_path
from module.gui.Bridge import bridge
from module.logger import logger

# import module.gui.qml_rcc
import module.gui.res_rcc

class FluentApp():
    app = None
    engine = None
    translator = None
    dpi = None

    def __init__(self):
        super().__init__()
        # 适配高分辨率、声明、设置Logo、设置软件名字
        # 后面的这三条失效了 使用 QGuiApplication.setHighDpiScaleFactorRoundingPolicy
        # https://blog.weimo.info/archives/602/
        # QGuiApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
        # QGuiApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
        # QGuiApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
        os.putenv("QT_QUICK_CONTROLS_STYLE", "Basic")

        # G32: Qt6 的 HighDpiScaleFactorRoundingPolicy 只对“之后创建”的
        # QGuiApplication 生效，必须放在创建 app 之前
        FluentApp.apply_initial_dpi_strategy()
        FluentApp.app = QGuiApplication(sys.argv)
        QGuiApplication.setWindowIcon(QIcon(os.fspath(Path(__file__).resolve().parent / "res/icon.ico")))
        QGuiApplication.setApplicationName("oas")
        QGuiApplication.setOrganizationName("oas")

        FluentApp.engine = QQmlApplicationEngine()
        FluentApp.engine.addImportPath(os.fspath(Path(__file__).resolve().parent))

        FluentApp.translator = Translator(engine=FluentApp.engine, app=FluentApp.app)
        FluentApp.dpi = DpiScale()
        self.set_context_property(context=FluentApp.translator, name='translator')
        self.set_context_property(context=FluentApp.dpi, name='dpi')

    @staticmethod
    def apply_initial_dpi_strategy() -> None:
        """
        读取 setting.json 里的 dpiStrategy，在 QGuiApplication 创建前应用
        """
        strategy = ""
        setting_path = Path.cwd() / 'module' / 'config' / 'argument' / 'setting.json'
        try:
            if setting_path.exists():
                with open(setting_path, 'r', encoding='utf-8') as f:
                    strategy = str(json.load(f).get('dpiStrategy', '') or '')
        except Exception as e:
            logger.error(f'load dpiStrategy failed: {e}')
        policy = {
            "default": Qt.HighDpiScaleFactorRoundingPolicy.PassThrough,
            "round": Qt.HighDpiScaleFactorRoundingPolicy.Round,
            "floor": Qt.HighDpiScaleFactorRoundingPolicy.Floor,
            "ceil": Qt.HighDpiScaleFactorRoundingPolicy.Ceil,
            "round_prefer_floor": Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor,
        }.get(strategy, Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(policy)

    # G33: 退出前需要执行的清理（停脚本进程、停 OCR 服务等）
    on_quit_hooks = []

    @classmethod
    def add_quit_hook(cls, func) -> None:
        cls.on_quit_hooks.append(func)

    @classmethod
    def _run_quit_hooks(cls) -> None:
        for func in cls.on_quit_hooks:
            try:
                func()
            except Exception:
                logger.exception('FluentApp quit hook error')

    @classmethod
    def run(cls):
        FluentApp.app.aboutToQuit.connect(FluentApp._run_quit_hooks)
        FluentApp.engine.load(os.fspath(Path(get_work_path() / 'module' / 'gui' / 'qml' / 'app.qml')))
        if not FluentApp.engine.rootObjects():
            sys.exit(-1)
        sys.exit(FluentApp.app.exec())

    @classmethod
    def set_context_property(cls, context, name: str) -> None:
        """
        设置上下文
        :param name:
        :param context:
        :return:
        """
        FluentApp.engine.rootContext().setContextProperty(name, context)



    def qml_register_type(self, Class, qml_class: str) -> None:
        """
        注册qml类型
        :param Class:
        :param qml_class:
        :return:
        """
        qmlRegisterType(Class, "Oas", 1, 0, qml_class)


class Translator(QObject):

    def __init__(self, engine, app) -> None:
        super(Translator, self).__init__()
        self._engine = engine
        self._app = app
        self.path_en_US = str((Path.cwd() / "module" / "config" / "i18n" / "en_US.qm").resolve())
        self.path_zh_CN = str((Path.cwd() / "module" / "config" / "i18n" / "zh_CN.qm").resolve())

        self.translator = QTranslator()
        self._installed = False

    def _install_translator(self) -> None:
        if self._installed:
            QGuiApplication.removeTranslator(self.translator)
        QGuiApplication.installTranslator(self.translator)
        self._installed = True

    @Slot(str)
    def set_language(self, language: str) -> None:
        """
        设置语言
        :param language:
        :return:
        """
        if language == "简体中文":
            if not self.translator.load(self.path_zh_CN):
                logger.error("load language 简体中文 failed!")
            self._install_translator()
            self._engine.retranslate()
            return

        if language == "English":
            if not self.translator.load(self.path_en_US):
                logger.error("load language English failed!")
            self._install_translator()
            self._engine.retranslate()
            return

class DpiScale(QObject):
    def __init__(self) -> None:
        super().__init__()

    @Slot(str)
    def set_dpi_scale(self, strategy: str) -> None:
        """
        设置dpi缩放
        :param strategy:
        :return:
        """
        match strategy:
            case "default": QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)  # 不缩放
            case "round": QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.Round)  # 设备像素比0.5及以上的，进行缩放
            case "floor": QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.Floor)  # 始终不缩放
            case "ceil": QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.Ceil)  # 始终缩放
            case "round_prefer_floor": QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor)  # 设备像素比0.75及以上的，进行缩放
            case _: QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)



