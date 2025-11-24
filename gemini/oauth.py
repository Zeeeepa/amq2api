"""
Gemini OAuth2 认证模块 - 使用 Antigravity 应用的 OAuth 流程
"""
import secrets
import httpx
from typing import Dict, Optional
from urllib.parse import urlencode

# Antigravity 应用的 OAuth 配置
GOOGLE_CLIENT_ID = "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# OAuth 作用域
SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/cclog",
    "https://www.googleapis.com/auth/experimentsandconfigs"
]


class GeminiOAuthManager:
    """Gemini OAuth 认证管理器"""

    def __init__(self, callback_port: int = 63902):
        self.callback_port = callback_port
        self.redirect_uri = f"http://localhost:{callback_port}/oauth-callback"
        self.pending_states: Dict[str, bool] = {}  # state -> is_completed
        self.auth_results: Dict[str, Dict] = {}  # state -> {code, error}

    def generate_auth_url(self) -> tuple[str, str]:
        """生成 OAuth 授权 URL

        Returns:
            (auth_url, state): 授权 URL 和状态码
        """
        state = secrets.token_urlsafe(32)
        self.pending_states[state] = False

        params = {
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state
        }

        auth_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
        return auth_url, state

    def handle_callback(self, code: str, state: str, error: Optional[str] = None):
        """处理 OAuth 回调

        Args:
            code: 授权码
            state: 状态码
            error: 错误信息(可选)
        """
        if state not in self.pending_states:
            raise ValueError(f"Invalid state: {state}")

        self.pending_states[state] = True
        self.auth_results[state] = {
            "code": code,
            "error": error
        }

    def get_auth_status(self, state: str) -> Dict:
        """获取认证状态

        Args:
            state: 状态码

        Returns:
            {"status": "ok"|"wait"|"error", "error": "..."}
        """
        if state not in self.pending_states:
            return {"status": "error", "error": "Invalid state"}

        if not self.pending_states[state]:
            return {"status": "wait"}

        result = self.auth_results.get(state, {})
        if result.get("error"):
            return {"status": "error", "error": result["error"]}

        if result.get("code"):
            return {"status": "ok"}

        return {"status": "wait"}

    async def exchange_code_for_tokens(self, code: str, client_secret: str) -> Dict:
        """交换授权码获取 tokens

        Args:
            code: 授权码
            client_secret: 客户端密钥

        Returns:
            {
                "access_token": "...",
                "refresh_token": "...",
                "expires_in": 3599,
                "token_type": "Bearer"
            }
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": self.redirect_uri
                }
            )

            if response.status_code != 200:
                raise Exception(f"Token exchange failed: {response.text}")

            return response.json()

    def cleanup_state(self, state: str):
        """清理状态数据"""
        self.pending_states.pop(state, None)
        self.auth_results.pop(state, None)