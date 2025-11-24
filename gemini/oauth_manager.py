"""
Gemini OAuth 管理器 - 整合 OAuth 流程和回调服务器
"""
import asyncio
import logging
from typing import Optional, Dict
from .oauth import GeminiOAuthManager
from .callback_server import CallbackServer

logger = logging.getLogger(__name__)


class GeminiOAuthService:
    """Gemini OAuth 服务 - 管理整个认证流程"""

    def __init__(self):
        self.oauth_manager = GeminiOAuthManager(callback_port=63902)
        self.callback_server: Optional[CallbackServer] = None
        self.server_running = False

    async def start_auth_flow(self) -> Dict[str, str]:
        """启动认证流程

        Returns:
            {"url": "授权URL", "state": "状态码"}
        """
        # 生成授权 URL
        auth_url, state = self.oauth_manager.generate_auth_url()

        # 启动回调服务器
        if not self.server_running:
            await self._start_callback_server()

        logger.info(f"认证流程已启动: state={state}")
        return {"url": auth_url, "state": state}

    async def _start_callback_server(self):
        """启动回调服务器"""
        if self.callback_server:
            return

        self.callback_server = CallbackServer(
            port=63902,
            callback_handler=self._handle_oauth_callback
        )
        await self.callback_server.start()
        self.server_running = True
        logger.info("OAuth 回调服务器已启动")

    async def _handle_oauth_callback(self, code: str, state: str, error: Optional[str] = None):
        """处理 OAuth 回调"""
        try:
            self.oauth_manager.handle_callback(code=code, state=state, error=error)
            logger.info(f"OAuth 回调处理成功: state={state}")
        except Exception as e:
            logger.error(f"OAuth 回调处理失败: {e}")

    def get_auth_status(self, state: str) -> Dict:
        """获取认证状态"""
        return self.oauth_manager.get_auth_status(state)

    async def exchange_code(self, state: str, client_secret: str) -> Dict:
        """交换授权码获取 tokens"""
        result = self.oauth_manager.auth_results.get(state, {})
        code = result.get("code")

        if not code:
            raise ValueError("No authorization code found")

        tokens = await self.oauth_manager.exchange_code_for_tokens(code, client_secret)

        # 清理状态
        self.oauth_manager.cleanup_state(state)

        return tokens

    async def stop(self):
        """停止服务"""
        if self.callback_server:
            await self.callback_server.stop()
            self.callback_server = None
            self.server_running = False


# 全局实例
_oauth_service: Optional[GeminiOAuthService] = None


def get_oauth_service() -> GeminiOAuthService:
    """获取全局 OAuth 服务实例"""
    global _oauth_service
    if _oauth_service is None:
        _oauth_service = GeminiOAuthService()
    return _oauth_service