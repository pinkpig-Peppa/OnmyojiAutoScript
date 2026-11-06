# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from pathlib import Path

from contextlib import asynccontextmanager

import argparse
from starlette import status
from starlette.responses import JSONResponse
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from module.logger import logger
from module.server.home_router import home_app
from module.server.script_router import script_app
from module.server.tool_router import tool_app
from module.server.setting import State
from module.server.main_manager import mm
from starlette.staticfiles import StaticFiles


def _cors_allow_origins() -> list[str]:
    """跨域白名单：默认不限制（兼容旧前端），可通过 deploy 配置收紧"""
    origins: list[str] = []
    raw = getattr(State, 'webui_cors_origins', '') or ''
    if not raw:
        try:
            raw = getattr(State.deploy_config, 'WebuiCorsOrigins', '') or ''
        except Exception:
            raw = ''
    if isinstance(raw, str):
        origins = [item.strip() for item in raw.split(',') if item.strip()]
    return origins or ["*"]


_CORS_ALLOW_ORIGINS = _cors_allow_origins()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await on_startup()
    yield
    await on_shutdown()

app = FastAPI(
    title='OAS',
    description='OAS web service',
    version='0.0.0',
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ALLOW_ORIGINS,
    # 通配来源时不能同时允许携带凭证，否则浏览器会直接拒绝该响应
    allow_credentials=_CORS_ALLOW_ORIGINS != ["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.middleware("http")
async def webui_key_middleware(request: Request, call_next):
    """配置了 --key 时强制校验口令，避免本机服务被任意页面/脚本调用"""
    # CORS preflight OPTIONS requests carry no custom headers; let them pass to CORS middleware.
    if request.method == "OPTIONS":
        return await call_next(request)
    if not State.check_webui_key(request.headers.get("x-oas-key") or request.query_params.get("key")):
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED,
                            content={'message': 'unauthorized'})
    return await call_next(request)

app.include_router(home_app)
app.include_router(script_app)
app.include_router(tool_app)

annotator_static_dir = Path(__file__).resolve().parent / "web" / "annotator" / "static"


class NoCacheStaticFiles(StaticFiles):
    """
    静态资源响应加 Cache-Control: no-cache：
    浏览器仍可缓存，但每次都携带 ETag 回源校验，未变更返回 304。
    StaticFiles 默认不下发 Cache-Control，Edge 等按启发式缓存旧 JS，
    前端更新后页面会继续执行旧脚本（表现为控件读不到数据/点了没反应）。
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


if annotator_static_dir.exists():
    app.mount("/tool/annotator/static", NoCacheStaticFiles(directory=str(annotator_static_dir)), name="annotator_static")


async def on_startup():
    """
    app.state 的生命周期在定义app的时候就有了
    :return:
    """
    logger.info('OAS web service startup done')
    if getattr(app.state, 'script_instances', None):
        await mm.restart_processes(app.state.script_instances)


async def on_shutdown():
    logger.info('OAS web service shutdown done')


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Internal Server Error: ", exc_info=True)

    # 只返回统一文案，避免把内部异常细节（路径 / 堆栈片段）暴露给 HTTP 调用方
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            'message': 'Internal Server Error'
        },
    )


def fastapi_app():
    parser = argparse.ArgumentParser(description="OAS web service")
    parser.add_argument(
        "-k", "--key", type=str, help="Password of OAS. No password by default"
    )
    parser.add_argument(
        "--cdn",
        action="store_true",
        help="Use jsdelivr cdn for pywebio static files (css, js). Self host cdn by default.",
    )
    parser.add_argument(
        "--run",
        nargs="+",
        type=str,
        help="Run OAS by config names on startup",
    )
    args, _ = parser.parse_known_args()
    State.webui_key = (args.key or '').strip()
    # ------------------------------------------------------------------------------------------------------------------

    runs = None
    if args.run:
        runs = args.run
    elif State.deploy_config.Run:
        # TODO: refactor poor_yaml_read() to support list
        tmp = State.deploy_config.Run.split(",")
        runs = [l.strip(" ['\"]") for l in tmp if len(l)]
    # ------------------------------------------------------------------------------------------------------------------
    app.state.script_instances = runs

    return app
