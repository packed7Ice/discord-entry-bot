"""
config.py - 設定読み込み
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# .env ファイルを読み込み（webapp/../.env を参照）
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)


def get_required_env(key: str) -> str:
    """必須環境変数を取得"""
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(f"環境変数 {key} が設定されていません。.env を確認してください。")
    return val


def get_optional_env(key: str, default: str = "") -> str:
    """オプション環境変数を取得"""
    return os.environ.get(key, default)


# Discord Webhook (既存)
DISCORD_WEBHOOK_URL = get_required_env("DISCORD_WEBHOOK_URL")
OPEN_QR = get_required_env("OPEN_QR")
CLOSE_QR = get_required_env("CLOSE_QR")
TEST_QR = get_optional_env("TEST_QR", "")

# Discord OAuth2 (新規)
DISCORD_CLIENT_ID = get_required_env("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = get_required_env("DISCORD_CLIENT_SECRET")
DISCORD_GUILD_ID = get_required_env("DISCORD_GUILD_ID")

# セッション
SESSION_SECRET = get_required_env("SESSION_SECRET")

# アプリケーション設定
BASE_URL = get_optional_env("BASE_URL", "http://localhost:8000")

# Discord OAuth2 URLs
DISCORD_AUTHORIZE_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_API_BASE = "https://discord.com/api/v10"
