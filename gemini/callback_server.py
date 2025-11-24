"""
本地 OAuth 回调服务器
"""
import asyncio
import logging
from aiohttp import web
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class CallbackServer:
    """OAuth 回调服务器"""

    def __init__(self, port: int, callback_handler: Callable):
        self.port = port
        self.callback_handler = callback_handler
        self.app = web.Application()
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None

        # 注册路由
        self.app.router.add_get('/oauth-callback', self.handle_callback)

    async def handle_callback(self, request: web.Request) -> web.Response:
        """处理 OAuth 回调"""
        try:
            code = request.query.get('code')
            state = request.query.get('state')
            error = request.query.get('error')

            logger.info(f"收到 OAuth 回调: state={state}, code={'***' if code else None}, error={error}")

            # 调用回调处理器
            await self.callback_handler(code=code, state=state, error=error)

            # 返回成功页面
            html = """
            <!DOCTYPE html>
            <html>
            <head>
                <title>认证成功</title>
                <style>
                    body { font-family: Arial; text-align: center; padding: 50px; }
                    .success { color: #4CAF50; font-size: 24px; }
                </style>
            </head>
            <body>
                <div class="success">✓ 认证成功</div>
                <p>您可以关闭此窗口了</p>
            </body>
            </html>
            """
            return web.Response(text=html, content_type='text/html')

        except Exception as e:
            logger.error(f"处理回调失败: {e}")
            return web.Response(text=f"错误: {str(e)}", status=500)

    async def start(self):
        """启动服务器"""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, 'localhost', self.port)
        await self.site.start()
        logger.info(f"回调服务器已启动: http://localhost:{self.port}")

    async def stop(self):
        """停止服务器"""
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        logger.info("回调服务器已停止")