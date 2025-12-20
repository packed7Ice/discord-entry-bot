"""
main.py - FastAPI Webアプリケーション

スマートフォンからQRコードをスキャンし、Discord Webhookへ通知を送信する。
Discord OAuth2でサーバーメンバーのみがアクセス可能。
"""
import httpx
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from config import (
    DISCORD_WEBHOOK_URL,
    OPEN_QR,
    CLOSE_QR,
    TEST_QR,
    DISCORD_GUILD_ID,
)
from auth import (
    generate_state,
    get_authorize_url,
    exchange_code,
    get_user_info,
    check_guild_membership,
    create_session,
    get_current_user,
    require_auth,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE,
)

app = FastAPI(title="QR Scanner Web App")

# 静的ファイルのディレクトリ
STATIC_DIR = Path(__file__).parent / "static"


# ---------------------------------------------------------------------------
# 認証ルート
# ---------------------------------------------------------------------------

@app.get("/auth/login")
async def login(request: Request):
    """Discord OAuth2 ログイン開始"""
    state = generate_state()
    response = RedirectResponse(url=get_authorize_url(state))
    response.set_cookie("oauth_state", state, max_age=600, httponly=True)
    return response


@app.get("/auth/callback")
async def callback(request: Request, code: str = None, state: str = None, error: str = None):
    """Discord OAuth2 コールバック"""
    if error:
        return HTMLResponse(f"<h1>認証エラー</h1><p>{error}</p>", status_code=400)
    
    if not code:
        return HTMLResponse("<h1>エラー</h1><p>認証コードがありません</p>", status_code=400)
    
    # state検証（CSRF対策）
    saved_state = request.cookies.get("oauth_state")
    if not saved_state or saved_state != state:
        return HTMLResponse("<h1>エラー</h1><p>不正なリクエストです</p>", status_code=400)
    
    # トークン取得
    token_data = await exchange_code(code)
    access_token = token_data.get("access_token")
    
    if not access_token:
        return HTMLResponse("<h1>エラー</h1><p>アクセストークンの取得に失敗しました</p>", status_code=400)
    
    # ユーザー情報取得
    user_info = await get_user_info(access_token)
    user_id = user_info.get("id")
    username = user_info.get("username")
    
    # サーバーメンバーシップ確認
    is_member = await check_guild_membership(access_token, user_id)
    if not is_member:
        return HTMLResponse(
            "<h1>アクセス拒否</h1>"
            "<p>このサーバーのメンバーではありません。</p>"
            "<p>サーバーに参加してから再度お試しください。</p>",
            status_code=403
        )
    
    # セッション作成
    session_token = create_session(user_id, username)
    
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie("oauth_state")
    return response


@app.get("/auth/logout")
async def logout():
    """ログアウト"""
    response = RedirectResponse(url="/login.html", status_code=302)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


@app.get("/auth/me")
async def get_me(request: Request):
    """現在のログインユーザー情報を取得"""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"logged_in": False}, status_code=200)
    return JSONResponse({"logged_in": True, "user": user})


# ---------------------------------------------------------------------------
# QRスキャン API
# ---------------------------------------------------------------------------

@app.post("/api/scan")
async def scan_qr(request: Request):
    """QRコードを検証してDiscordに送信"""
    user = require_auth(request)
    
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "リクエストボディが不正です")
    
    qr_content = body.get("qr", "").strip()
    
    if not qr_content:
        raise HTTPException(400, "QRコードが空です")
    
    # QRコード判定
    action = None
    message = None
    
    if qr_content == OPEN_QR:
        action = "open"
        message = "あけた"
    elif qr_content == CLOSE_QR:
        action = "close"
        message = "しめた"
    elif TEST_QR and qr_content == TEST_QR:
        action = "test"
        message = "test"
    else:
        raise HTTPException(400, "不明なQRコードです")
    
    # Discord Webhookに送信
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                DISCORD_WEBHOOK_URL,
                json={"content": message},
                timeout=10,
            )
            response.raise_for_status()
    except Exception as e:
        raise HTTPException(500, f"Discord送信に失敗しました: {str(e)}")
    
    return {
        "status": "ok",
        "action": action,
        "message": message,
        "user": user["username"],
    }


# ---------------------------------------------------------------------------
# 静的ファイル / ページ
# ---------------------------------------------------------------------------

@app.get("/")
async def index(request: Request):
    """メインページ（認証チェック付き）"""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login.html", status_code=302)
    
    # index.htmlを返す
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>スキャナー準備中</h1>")


# 静的ファイルをマウント（login.html, style.css, scanner.js など）
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


# ---------------------------------------------------------------------------
# エントリーポイント
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
