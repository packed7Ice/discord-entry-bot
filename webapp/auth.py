"""
auth.py - Discord OAuth2 認証
"""
import secrets
from urllib.parse import urlencode
from typing import Optional

import httpx
from fastapi import Request, HTTPException
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from config import (
    DISCORD_CLIENT_ID,
    DISCORD_CLIENT_SECRET,
    DISCORD_GUILD_ID,
    DISCORD_AUTHORIZE_URL,
    DISCORD_TOKEN_URL,
    DISCORD_API_BASE,
    SESSION_SECRET,
    BASE_URL,
)

# セッションシリアライザー
serializer = URLSafeTimedSerializer(SESSION_SECRET)

# セッションCookie名
SESSION_COOKIE_NAME = "session"
SESSION_MAX_AGE = 60 * 60 * 24 * 180  # 180日間（半年）


def generate_state() -> str:
    """CSRF対策用のstate値を生成"""
    return secrets.token_urlsafe(32)


def get_authorize_url(state: str) -> str:
    """Discord OAuth2 認可URLを生成"""
    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": f"{BASE_URL}/auth/callback",
        "response_type": "code",
        "scope": "identify guilds.members.read",
        "state": state,
    }
    return f"{DISCORD_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code(code: str) -> dict:
    """認可コードをアクセストークンに交換"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            DISCORD_TOKEN_URL,
            data={
                "client_id": DISCORD_CLIENT_ID,
                "client_secret": DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": f"{BASE_URL}/auth/callback",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code != 200:
            raise HTTPException(400, f"トークン取得に失敗しました: {response.text}")
        return response.json()


async def get_user_info(access_token: str) -> dict:
    """Discord APIからユーザー情報を取得"""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{DISCORD_API_BASE}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if response.status_code != 200:
            raise HTTPException(400, "ユーザー情報の取得に失敗しました")
        return response.json()


async def check_guild_membership(access_token: str, user_id: str) -> bool:
    """ユーザーが指定のギルド（サーバー）のメンバーかどうか確認"""
    async with httpx.AsyncClient() as client:
        # ギルドメンバー情報を取得
        response = await client.get(
            f"{DISCORD_API_BASE}/users/@me/guilds/{DISCORD_GUILD_ID}/member",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        # 200: メンバー、404: メンバーではない
        return response.status_code == 200


def create_session(user_id: str, username: str) -> str:
    """セッショントークンを生成"""
    data = {"user_id": user_id, "username": username}
    return serializer.dumps(data)


def verify_session(token: str) -> Optional[dict]:
    """セッショントークンを検証"""
    try:
        data = serializer.loads(token, max_age=SESSION_MAX_AGE)
        return data
    except (BadSignature, SignatureExpired):
        return None


def get_current_user(request: Request) -> Optional[dict]:
    """リクエストからログイン中のユーザー情報を取得"""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    return verify_session(token)


def require_auth(request: Request) -> dict:
    """認証を必須化（未認証なら例外）"""
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "ログインが必要です")
    return user
