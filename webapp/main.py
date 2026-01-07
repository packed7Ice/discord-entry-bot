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
    user_id = user.get("user_id", "")
    username = user.get("username", "不明")
    
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "リクエストボディが不正です")
    
    qr_content = body.get("qr", "").strip()
    
    if not qr_content:
        raise HTTPException(400, "QRコードが空です")
    
    # デバッグ用ログ（環境変数との比較）
    print(f"[DEBUG] Received QR: '{qr_content}' (len={len(qr_content)})")
    print(f"[DEBUG] OPEN_QR: '{OPEN_QR}' (len={len(OPEN_QR)})")
    print(f"[DEBUG] CLOSE_QR: '{CLOSE_QR}' (len={len(CLOSE_QR)})")
    print(f"[DEBUG] Match OPEN: {qr_content == OPEN_QR}, Match CLOSE: {qr_content == CLOSE_QR}")
    
    # QRコード判定
    action = None
    base_message = None
    
    if qr_content == OPEN_QR:
        action = "open"
        base_message = "あけた"
    elif qr_content == CLOSE_QR:
        action = "close"
        base_message = "しめた"
    elif TEST_QR and qr_content == TEST_QR:
        action = "test"
        base_message = "test"
    else:
        raise HTTPException(400, "不明なQRコードです")
    
    # メンション形式でメッセージを作成
    message = f"{base_message} by <@{user_id}>"
    
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
        "user": username,
    }


# ---------------------------------------------------------------------------
# 直接リンクからアクション実行
# ---------------------------------------------------------------------------

@app.get("/action/{action_type}")
async def direct_action(request: Request, action_type: str):
    """リンクをクリックするだけでWebhookを送信（認証必須）"""
    user = require_auth(request)
    user_id = user.get("user_id", "")
    username = user.get("username", "不明")
    
    # アクションの判定
    action_map = {
        "open": "あけた",
        "close": "しめた",
        "test": "test",
    }
    
    if action_type not in action_map:
        raise HTTPException(400, "不明なアクションです")
    
    base_message = action_map[action_type]
    message = f"{base_message} by <@{user_id}>"
    
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
    
    # 成功ページを表示
    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>送信完了</title>
        <style>
            body {{
                font-family: 'Segoe UI', sans-serif;
                background: #1a1a2e;
                color: #fff;
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
                margin: 0;
            }}
            .container {{
                text-align: center;
                padding: 2rem;
            }}
            .icon {{ font-size: 4rem; margin-bottom: 1rem; }}
            h1 {{ color: #5865f2; }}
            a {{
                display: inline-block;
                margin-top: 1rem;
                padding: 0.75rem 1.5rem;
                background: #5865f2;
                color: #fff;
                text-decoration: none;
                border-radius: 0.5rem;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="icon">✅</div>
            <h1>{base_message}</h1>
            <p>Discordに送信しました</p>
            <p>by {username}</p>
            <a href="/">スキャナーに戻る</a>
        </div>
    </body>
    </html>
    """)


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
