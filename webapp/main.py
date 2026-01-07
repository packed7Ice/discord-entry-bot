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
# 直接リンクからアクション実行（確認画面 + レート制限 + ワンタイムトークン）
# ---------------------------------------------------------------------------

# レート制限用のインメモリストア（user_id -> [timestamp, timestamp, ...]）
from collections import defaultdict
import time
import secrets

rate_limit_store: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_WINDOW = 60  # 秒
RATE_LIMIT_MAX = 3  # 1分間の最大リクエスト数


def check_rate_limit(user_id: str) -> tuple[bool, int]:
    """レート制限をチェック。(許可されるか, 残り秒数)"""
    now = time.time()
    # 古いエントリを削除
    rate_limit_store[user_id] = [
        ts for ts in rate_limit_store[user_id] 
        if now - ts < RATE_LIMIT_WINDOW
    ]
    
    if len(rate_limit_store[user_id]) >= RATE_LIMIT_MAX:
        # 最も古いリクエストからの経過時間を計算
        oldest = min(rate_limit_store[user_id])
        wait_time = int(RATE_LIMIT_WINDOW - (now - oldest)) + 1
        return False, wait_time
    
    return True, 0


def record_request(user_id: str):
    """リクエストを記録"""
    rate_limit_store[user_id].append(time.time())


# ワンタイムトークン管理（再送信防止）
# token -> (user_id, action_type, created_at)
form_tokens: dict[str, tuple[str, str, float]] = {}
TOKEN_EXPIRY = 60  # トークンの有効期限（秒）


def generate_form_token(user_id: str, action_type: str) -> str:
    """フォーム用のワンタイムトークンを生成"""
    # 古いトークンを削除
    now = time.time()
    expired_tokens = [
        token for token, (_, _, created_at) in form_tokens.items()
        if now - created_at > TOKEN_EXPIRY
    ]
    for token in expired_tokens:
        del form_tokens[token]
    
    # 新しいトークンを生成
    token = secrets.token_urlsafe(32)
    form_tokens[token] = (user_id, action_type, now)
    return token


def validate_form_token(token: str, user_id: str, action_type: str) -> bool:
    """トークンを検証し、有効なら消費する（一度きり）"""
    if token not in form_tokens:
        return False
    
    stored_user_id, stored_action_type, created_at = form_tokens[token]
    
    # トークンの検証
    if stored_user_id != user_id or stored_action_type != action_type:
        return False
    
    if time.time() - created_at > TOKEN_EXPIRY:
        del form_tokens[token]
        return False
    
    # トークンを消費（一度きり）
    del form_tokens[token]
    return True


# アクションマッピング
ACTION_MAP = {
    "open": "あけた",
    "close": "しめた",
    "test": "test",
}


@app.get("/action/{action_type}")
async def direct_action_confirm(request: Request, action_type: str):
    """確認画面を表示（認証必須）"""
    user = require_auth(request)
    username = user.get("username", "不明")
    user_id = user.get("user_id", "")
    
    if action_type not in ACTION_MAP:
        raise HTTPException(400, "不明なアクションです")
    
    base_message = ACTION_MAP[action_type]
    
    # レート制限チェック
    allowed, wait_time = check_rate_limit(user_id)
    if not allowed:
        return HTMLResponse(f"""
        <!DOCTYPE html>
        <html lang="ja">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>送信制限中</title>
            <link rel="stylesheet" href="/style.css">
            <script>
                // 早期テーマ適用（ちらつき防止）
                (function() {{
                    var saved = localStorage.getItem('theme');
                    var theme = saved || (window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
                    document.documentElement.setAttribute('data-theme', theme);
                }})();
            </script>
            <style>
                .page-container {{
                    min-height: 100vh;
                    display: flex;
                    flex-direction: column;
                    justify-content: center;
                    align-items: center;
                    text-align: center;
                    padding: 2rem;
                }}
                .page-card {{
                    background: var(--bg-card);
                    backdrop-filter: blur(12px);
                    -webkit-backdrop-filter: blur(12px);
                    border: 1px solid var(--border-glass);
                    border-radius: 24px;
                    padding: 3rem 2.5rem;
                    max-width: 400px;
                    width: 100%;
                    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
                    animation: fade-in 0.4s ease-out;
                }}
                @keyframes fade-in {{
                    from {{ opacity: 0; transform: scale(0.95) translateY(10px); }}
                    to {{ opacity: 1; transform: scale(1) translateY(0); }}
                }}
                .warning-icon {{
                    width: 80px;
                    height: 80px;
                    background: linear-gradient(135deg, #FEE75C 0%, #FAA61A 100%);
                    border-radius: 50%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin: 0 auto 1.5rem;
                    font-size: 2.5rem;
                    box-shadow: 0 0 30px rgba(250, 166, 26, 0.4);
                }}
                h1 {{
                    font-size: 1.75rem;
                    font-weight: 700;
                    margin-bottom: 0.75rem;
                    color: var(--error);
                }}
                .description {{
                    color: var(--text-secondary);
                    margin-bottom: 1.5rem;
                }}
                .wait-time {{
                    font-size: 3rem;
                    font-weight: 700;
                    color: var(--primary);
                    margin-bottom: 0.5rem;
                }}
                .wait-label {{
                    color: var(--text-muted);
                    font-size: 0.9rem;
                }}
                .back-link {{
                    display: inline-block;
                    margin-top: 1.5rem;
                    padding: 0.875rem 1.75rem;
                    background: var(--bg-tertiary);
                    color: var(--text-primary);
                    text-decoration: none;
                    border-radius: 12px;
                    font-weight: 600;
                    transition: all 0.2s;
                }}
                .back-link:hover {{
                    background: var(--primary);
                }}
            </style>
            <script>
                setTimeout(() => location.reload(), {wait_time * 1000});
            </script>
        </head>
        <body>
            <div class="theme-toggle" onclick="toggleTheme()" title="テーマ切り替え">
                <span class="theme-icon">🌙</span>
            </div>
            <div class="page-container">
                <div class="page-card">
                    <div class="warning-icon">⏳</div>
                    <h1>送信制限中</h1>
                    <p class="description">短時間に複数回送信されました</p>
                    <div class="wait-time" id="countdown">{wait_time}</div>
                    <p class="wait-label">秒後に再試行可能</p>
                    <a href="/dashboard" class="back-link">ダッシュボードに戻る</a>
                </div>
            </div>
            <script>
                function getPreferredTheme() {{
                    const saved = localStorage.getItem('theme');
                    if (saved) return saved;
                    return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
                }}
                function setTheme(theme) {{
                    document.documentElement.setAttribute('data-theme', theme);
                    localStorage.setItem('theme', theme);
                    document.querySelector('.theme-icon').textContent = theme === 'light' ? '🌙' : '☀️';
                }}
                function toggleTheme() {{
                    const current = document.documentElement.getAttribute('data-theme') || 'dark';
                    setTheme(current === 'dark' ? 'light' : 'dark');
                }}
                setTheme(getPreferredTheme());
                
                // カウントダウン表示
                let count = {wait_time};
                const countdownEl = document.getElementById('countdown');
                setInterval(() => {{
                    count--;
                    if (count > 0) countdownEl.textContent = count;
                }}, 1000);
            </script>
        </body>
        </html>
        """, status_code=429)
    
    # ワンタイムトークンを生成
    form_token = generate_form_token(user_id, action_type)
    
    # 確認画面を表示
    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>送信確認</title>
        <link rel="stylesheet" href="/style.css">
        <script>
            (function() {{
                var saved = localStorage.getItem('theme');
                var theme = saved || (window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
                document.documentElement.setAttribute('data-theme', theme);
            }})();
        </script>
        <style>
            .page-container {{
                min-height: 100vh;
                display: flex;
                flex-direction: column;
                justify-content: center;
                align-items: center;
                text-align: center;
                padding: 2rem;
            }}
            .page-card {{
                background: var(--bg-card);
                backdrop-filter: blur(12px);
                -webkit-backdrop-filter: blur(12px);
                border: 1px solid var(--border-glass);
                border-radius: 24px;
                padding: 3rem 2.5rem;
                max-width: 400px;
                width: 100%;
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
                animation: fade-in 0.4s ease-out;
            }}
            @keyframes fade-in {{
                from {{ opacity: 0; transform: scale(0.95) translateY(10px); }}
                to {{ opacity: 1; transform: scale(1) translateY(0); }}
            }}
            .action-icon {{
                width: 80px;
                height: 80px;
                background: linear-gradient(135deg, #5865F2 0%, #4752C4 100%);
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                margin: 0 auto 1.5rem;
                font-size: 2.5rem;
                box-shadow: 0 0 30px rgba(88, 101, 242, 0.4);
            }}
            h1 {{
                font-size: 1.75rem;
                font-weight: 700;
                margin-bottom: 1rem;
                color: var(--text-primary);
            }}
            .action-message {{
                font-size: 1.5rem;
                font-weight: 600;
                color: var(--primary);
                margin-bottom: 0.5rem;
                padding: 0.75rem 1.5rem;
                background: var(--bg-glass);
                border-radius: 12px;
                display: inline-block;
            }}
            .user-name {{
                color: var(--text-muted);
                font-size: 0.9rem;
                margin-top: 1rem;
            }}
            .button-group {{
                display: flex;
                flex-direction: column;
                gap: 0.75rem;
                margin-top: 2rem;
            }}
            .submit-btn {{
                padding: 1rem 2rem;
                font-size: 1.1rem;
                font-weight: 700;
                background: linear-gradient(135deg, #57F287 0%, #3BA55D 100%);
                color: #000;
                border: none;
                border-radius: 12px;
                cursor: pointer;
                transition: all 0.2s;
                font-family: inherit;
            }}
            .submit-btn:hover {{
                transform: translateY(-2px);
                box-shadow: 0 4px 16px rgba(87, 242, 135, 0.4);
            }}
            .submit-btn:active {{
                transform: translateY(0);
            }}
            .cancel-btn {{
                padding: 0.875rem 1.75rem;
                background: var(--bg-tertiary);
                color: var(--text-primary);
                text-decoration: none;
                border-radius: 12px;
                font-weight: 600;
                transition: all 0.2s;
            }}
            .cancel-btn:hover {{
                background: var(--bg-glass);
            }}
        </style>
    </head>
    <body>
        <div class="theme-toggle" onclick="toggleTheme()" title="テーマ切り替え">
            <span class="theme-icon">🌙</span>
        </div>
        <div class="page-container">
            <div class="page-card">
                <div class="action-icon">📤</div>
                <h1>送信確認</h1>
                <div class="action-message">{base_message}</div>
                <p class="user-name">by {username}</p>
                <div class="button-group">
                    <form method="POST" style="margin: 0;">
                        <input type="hidden" name="token" value="{form_token}">
                        <button type="submit" class="submit-btn">送信する</button>
                    </form>
                    <a href="/dashboard" class="cancel-btn">キャンセル</a>
                </div>
            </div>
        </div>
        <script>
            function getPreferredTheme() {{
                const saved = localStorage.getItem('theme');
                if (saved) return saved;
                return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
            }}
            function setTheme(theme) {{
                document.documentElement.setAttribute('data-theme', theme);
                localStorage.setItem('theme', theme);
                document.querySelector('.theme-icon').textContent = theme === 'light' ? '🌙' : '☀️';
            }}
            function toggleTheme() {{
                const current = document.documentElement.getAttribute('data-theme') || 'dark';
                setTheme(current === 'dark' ? 'light' : 'dark');
            }}
            setTheme(getPreferredTheme());
        </script>
    </body>
    </html>
    """)


@app.post("/action/{action_type}")
async def direct_action_execute(request: Request, action_type: str):
    """実際にWebhookを送信（認証必須、ワンタイムトークン検証）"""
    user = require_auth(request)
    user_id = user.get("user_id", "")
    username = user.get("username", "不明")
    
    if action_type not in ACTION_MAP:
        raise HTTPException(400, "不明なアクションです")
    
    # フォームデータからトークンを取得
    form_data = await request.form()
    token = form_data.get("token", "")
    
    # トークン検証（一度使用したトークンは無効）
    if not validate_form_token(token, user_id, action_type):
        # トークンが無効 = 既に送信済みまたは期限切れ
        base_message = ACTION_MAP[action_type]
        return HTMLResponse(f"""
        <!DOCTYPE html>
        <html lang="ja">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>送信エラー</title>
            <link rel="stylesheet" href="/style.css">
            <script>
                (function() {{
                    var saved = localStorage.getItem('theme');
                    var theme = saved || (window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
                    document.documentElement.setAttribute('data-theme', theme);
                }})();
            </script>
            <style>
                .page-container {{
                    min-height: 100vh;
                    display: flex;
                    flex-direction: column;
                    justify-content: center;
                    align-items: center;
                    text-align: center;
                    padding: 2rem;
                }}
                .page-card {{
                    background: var(--bg-card);
                    backdrop-filter: blur(12px);
                    -webkit-backdrop-filter: blur(12px);
                    border: 1px solid var(--border-glass);
                    border-radius: 24px;
                    padding: 3rem 2.5rem;
                    max-width: 400px;
                    width: 100%;
                    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
                }}
                .error-icon {{
                    width: 80px;
                    height: 80px;
                    background: linear-gradient(135deg, #ED4245 0%, #c03537 100%);
                    border-radius: 50%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin: 0 auto 1.5rem;
                    font-size: 2.5rem;
                    box-shadow: 0 0 30px rgba(237, 66, 69, 0.4);
                }}
                h1 {{
                    font-size: 1.75rem;
                    font-weight: 700;
                    margin-bottom: 0.75rem;
                    color: var(--error);
                }}
                .description {{
                    color: var(--text-secondary);
                    margin-bottom: 1.5rem;
                }}
                .retry-link {{
                    display: inline-block;
                    margin-top: 1rem;
                    padding: 0.875rem 1.75rem;
                    background: var(--primary);
                    color: #fff;
                    text-decoration: none;
                    border-radius: 12px;
                    font-weight: 600;
                    transition: all 0.2s;
                }}
                .retry-link:hover {{
                    transform: translateY(-2px);
                    box-shadow: 0 4px 16px rgba(88, 101, 242, 0.4);
                }}
            </style>
        </head>
        <body>
            <div class="theme-toggle" onclick="toggleTheme()" title="テーマ切り替え">
                <span class="theme-icon">🌙</span>
            </div>
            <div class="page-container">
                <div class="page-card">
                    <div class="error-icon">✕</div>
                    <h1>送信できません</h1>
                    <p class="description">
                        この送信は既に完了しているか、<br>
                        有効期限が切れています。
                    </p>
                    <a href="/action/{action_type}" class="retry-link">もう一度試す</a>
                </div>
            </div>
            <script>
                function getPreferredTheme() {{
                    const saved = localStorage.getItem('theme');
                    if (saved) return saved;
                    return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
                }}
                function setTheme(theme) {{
                    document.documentElement.setAttribute('data-theme', theme);
                    localStorage.setItem('theme', theme);
                    document.querySelector('.theme-icon').textContent = theme === 'light' ? '🌙' : '☀️';
                }}
                function toggleTheme() {{
                    const current = document.documentElement.getAttribute('data-theme') || 'dark';
                    setTheme(current === 'dark' ? 'light' : 'dark');
                }}
                setTheme(getPreferredTheme());
            </script>
        </body>
        </html>
        """, status_code=400)
    
    # レート制限チェック
    allowed, wait_time = check_rate_limit(user_id)
    if not allowed:
        raise HTTPException(429, f"送信制限中です。{wait_time}秒後に再試行してください。")
    
    base_message = ACTION_MAP[action_type]
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
    
    # リクエストを記録
    record_request(user_id)

    
    # 成功ページにリダイレクト（PRGパターン）
    return RedirectResponse(url=f"/action/{action_type}/done", status_code=303)


@app.get("/action/{action_type}/done")
async def direct_action_done(request: Request, action_type: str):
    """送信完了画面（5秒後にタブを閉じる、リダイレクトなし）"""
    user = require_auth(request)
    username = user.get("username", "不明")
    
    base_message = ACTION_MAP.get(action_type, "不明")
    
    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>送信完了</title>
        <link rel="stylesheet" href="/style.css">
        <script>
            (function() {{
                var saved = localStorage.getItem('theme');
                var theme = saved || (window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
                document.documentElement.setAttribute('data-theme', theme);
            }})();
        </script>
        <style>
            .done-container {{
                min-height: 100vh;
                display: flex;
                flex-direction: column;
                justify-content: center;
                align-items: center;
                text-align: center;
                padding: 2rem;
            }}
            .done-card {{
                background: var(--bg-card);
                backdrop-filter: blur(12px);
                -webkit-backdrop-filter: blur(12px);
                border: 1px solid var(--border-glass);
                border-radius: 24px;
                padding: 3rem 2.5rem;
                max-width: 400px;
                width: 100%;
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
                animation: fade-in 0.4s ease-out;
            }}
            @keyframes fade-in {{
                from {{ opacity: 0; transform: scale(0.95) translateY(10px); }}
                to {{ opacity: 1; transform: scale(1) translateY(0); }}
            }}
            .success-icon {{
                width: 80px;
                height: 80px;
                background: linear-gradient(135deg, #57F287 0%, #3BA55D 100%);
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                margin: 0 auto 1.5rem;
                font-size: 2.5rem;
                box-shadow: 0 0 30px rgba(87, 242, 135, 0.4);
            }}
            h1 {{
                font-size: 2rem;
                font-weight: 700;
                margin-bottom: 0.5rem;
                color: var(--text-primary);
            }}
            .sent-message {{
                color: var(--text-secondary);
                margin-bottom: 0.25rem;
            }}
            .user-name {{
                color: var(--text-muted);
                font-size: 0.9rem;
            }}
            .countdown {{
                margin-top: 2rem;
                padding: 1rem;
                background: var(--bg-glass);
                border-radius: 12px;
                color: var(--text-secondary);
                font-size: 0.9rem;
            }}
            .countdown-number {{
                color: var(--primary);
                font-weight: 700;
                font-size: 1.1rem;
            }}
            .close-failed {{
                display: none;
                margin-top: 1rem;
                color: var(--text-muted);
                font-size: 0.85rem;
            }}
            .close-failed.show {{
                display: block;
            }}
            .manual-close-btn {{
                display: none;
                margin-top: 1rem;
                padding: 0.75rem 1.5rem;
                background: var(--primary);
                color: #fff;
                border: none;
                border-radius: 10px;
                font-family: inherit;
                font-size: 1rem;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.2s;
            }}
            .manual-close-btn.show {{
                display: inline-block;
            }}
            .manual-close-btn:hover {{
                transform: translateY(-2px);
                box-shadow: 0 4px 16px rgba(88, 101, 242, 0.4);
            }}
        </style>
    </head>
    <body>
        <div class="theme-toggle" onclick="toggleTheme()" title="テーマ切り替え">
            <span class="theme-icon">🌙</span>
        </div>
        <div class="done-container">
            <div class="done-card">
                <div class="success-icon">✓</div>
                <h1>{base_message}</h1>
                <p class="sent-message">Discordに送信しました</p>
                <p class="user-name">by {username}</p>
                <div class="countdown">
                    <span class="countdown-number" id="countdown">5</span> 秒後にこのタブを閉じます
                </div>
                <p class="close-failed" id="closeFailed">
                    タブを自動で閉じられませんでした。<br>手動で閉じてください。
                </p>
                <button class="manual-close-btn" id="manualClose" onclick="window.close()">
                    タブを閉じる
                </button>
            </div>
        </div>
        <script>
            // テーマ管理
            function getPreferredTheme() {{
                const saved = localStorage.getItem('theme');
                if (saved) return saved;
                return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
            }}
            function setTheme(theme) {{
                document.documentElement.setAttribute('data-theme', theme);
                localStorage.setItem('theme', theme);
                document.querySelector('.theme-icon').textContent = theme === 'light' ? '🌙' : '☀️';
            }}
            function toggleTheme() {{
                const current = document.documentElement.getAttribute('data-theme') || 'dark';
                setTheme(current === 'dark' ? 'light' : 'dark');
            }}
            setTheme(getPreferredTheme());
            
            // 5秒後に自動タブ閉じ（リダイレクトなし）
            let count = 5;
            const countdownEl = document.getElementById('countdown');
            const closeFailedEl = document.getElementById('closeFailed');
            const manualCloseEl = document.getElementById('manualClose');
            
            const timer = setInterval(() => {{
                count--;
                countdownEl.textContent = count;
                if (count <= 0) {{
                    clearInterval(timer);
                    // タブを閉じる
                    window.close();
                    // 閉じられなかった場合（1秒後にまだ開いていれば）メッセージ表示
                    setTimeout(() => {{
                        closeFailedEl.classList.add('show');
                        manualCloseEl.classList.add('show');
                        document.querySelector('.countdown').style.display = 'none';
                    }}, 1000);
                }}
            }}, 1000);
        </script>
    </body>
    </html>
    """)


# ---------------------------------------------------------------------------
# 静的ファイル / ページ
# ---------------------------------------------------------------------------

@app.get("/")
async def index(request: Request):
    """ルート: ダッシュボードにリダイレクト"""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login.html", status_code=302)
    return RedirectResponse(url="/dashboard", status_code=302)


@app.get("/dashboard")
async def dashboard(request: Request):
    """メインダッシュボード（認証チェック付き）"""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login.html", status_code=302)
    
    dashboard_path = STATIC_DIR / "dashboard.html"
    if dashboard_path.exists():
        return HTMLResponse(dashboard_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>ダッシュボード準備中</h1>")


@app.get("/scanner")
async def scanner(request: Request):
    """QRスキャナーページ（認証チェック付き）"""
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login.html", status_code=302)
    
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

