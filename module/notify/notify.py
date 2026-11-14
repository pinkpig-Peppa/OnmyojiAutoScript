# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey

import onepush.core
import yaml
from onepush import get_notifier
from onepush.core import Provider
from onepush.exceptions import OnePushException
from onepush.providers.custom import Custom
from requests import Response
from smtplib import SMTPResponseException

from module.logger import logger
onepush.core.log = logger


class Notifier:
    def __init__(self, _config: str, enable: bool=False) -> None:
        self.config_name: str = ""
        self.enable: bool = enable
        # 初始化失败会早退，这里先给出默认值，避免 push() 时访问不存在的属性
        self.config: dict = {}
        self.notifier = None
        self.required: list[str] = []
        self.provider_name = None
        self._apprise = None

        if not self.enable:
            return
        config = {}
        try:
            for item in yaml.safe_load_all(_config):
                config.update(item)
        except Exception as e:
            logger.error("Fail to load onepush config, skip sending")
            return
        self.config = config
        try:
            # 获取provider
            self.provider_name: str = self.config.pop("provider", None)
            if self.provider_name is None:
                logger.info("No provider specified, skip sending")
                return
            # Apprise 直连: 一份配置聚合多个渠道 (tgram:// discord:// gotify:// ...)
            # onepush 没有 apprise provider, 在这里单独处理
            if self.provider_name.lower() == "apprise":
                self._init_apprise()
                return
            # 获取notifier
            self.notifier: Provider = get_notifier(self.provider_name)
            # 获取notifier的必填参数
            self.required: list[str] = self.notifier.params["required"]
        except OnePushException:
            logger.exception("Init notifier failed")
            return
        except Exception as e:
            logger.exception(e)
            return

    def _init_apprise(self) -> None:
        try:
            import apprise
        except ImportError:
            logger.error("Apprise is not installed, run: pip install apprise")
            self.notifier = None
            return
        urls = self.config.get("urls", "")
        if isinstance(urls, list):
            url_list = [str(u).strip() for u in urls if str(u).strip()]
        else:
            url_list = [u.strip() for u in str(urls).replace("\n", ",").split(",") if u.strip()]
        self._apprise = apprise.Apprise()
        for u in url_list:
            if not self._apprise.add(u):
                logger.error(f"Apprise: invalid url skipped: {u[:32]}...")
        if not self._apprise.servers:
            logger.error("Apprise: no valid urls in config")
            self.notifier = None
            return
        # 非 None 即可通过 push() 的前置检查
        self.notifier = self._apprise
        self.required = []

    def push(self, **kwargs) -> bool:
        if not self.enable:
            return False
        if self.notifier is None:
            logger.warning("Notifier is not initialized, skip sending")
            return False
        # 更新配置
        kwargs["title"] = f"{self.config_name} {kwargs.get('title', '')}"
        self.config.update(kwargs)
        # pre check
        for key in self.required:
            if key not in self.config:
                logger.warning(
                    f"Notifier {self.notifier} require param '{key}' but not provided"
                )


        if self.provider_name and self.provider_name.lower() == "apprise":
            if self._apprise is None:
                return False
            try:
                ok = self._apprise.notify(
                    title=str(kwargs.get("title", "")),
                    body=str(kwargs.get("content", "")),
                )
            except Exception as e:
                logger.exception(e)
                return False
            if not ok:
                logger.warning("Push notify failed!")
                return False
            logger.info("Push notify success")
            return True

        if isinstance(self.notifier, Custom):
            if "method" not in self.config or self.config["method"] == "post":
                self.config["datatype"] = "json"
            if "data" not in self.config or not isinstance(self.config["data"], dict):
                self.config["data"] = {}
            if "title" in kwargs:
                self.config["data"]["title"] = kwargs["title"]
            if "content" in kwargs:
                self.config["data"]["content"] = kwargs["content"]

        if self.provider_name.lower() == "gocqhttp":
            access_token = self.config.get("access_token")
            if access_token:
                self.config["token"] = access_token


        try:
            resp = self.notifier.notify(**self.config)
            if isinstance(resp, Response):
                if resp.status_code != 200:
                    logger.warning("Push notify failed!")
                    logger.warning(f"HTTP Code:{resp.status_code}")
                    return False
                else:
                    if self.provider_name.lower() == "gocqhttp":
                        return_data: dict = resp.json()
                        if return_data["status"] == "failed":
                            logger.warning("Push notify failed!")
                            logger.warning(
                                f"Return message:{return_data['wording']}")
                            return False
        except SMTPResponseException:
            logger.warning("Appear SMTPResponseException")
            pass
        except OnePushException:
            logger.exception("Push notify failed")
            return False
        except Exception as e:
            logger.exception(e)
            return False

        logger.info("Push notify success")
        return True


