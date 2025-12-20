# discord-entry-bot

QRコードをカメラでスキャンし、Discord Webhookへ通知を送信するサービス。

## 機能

- **高速QR検出**: pyzbar優先（fallbackでOpenCV）
- **エッジトリガ方式**: 連続送信を防止（一度検出したら一定時間見えなくなるまで再送信しない）
- **カメラ自動リカバリ**: 接続切れ時に自動再接続
- **ログローテーション**: 1MB×5世代でログをローテーション

## セットアップ

### 1. 依存関係のインストール

```bash
# システム依存（Ubuntu/Debian）
sudo apt update
sudo apt install python3-opencv libzbar0

# Python仮想環境
python3 -m venv .venv
source .venv/bin/activate

# Pythonパッケージ
pip install opencv-python pyzbar requests python-dotenv
```

### 2. .env ファイルの作成

プロジェクトディレクトリに `.env` ファイルを作成：

```env
# 必須
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxxx/yyyy
OPEN_QR=your_open_token_here
CLOSE_QR=your_close_token_here
TEST_QR=your_test_token_here

# オプション（デフォルト: false）
LOG_RAW_QR=false
SHOW_RAW_TEXT=false
```

QRトークンは `make_qr_tokens.py` で自動生成できます：

```bash
python3 make_qr_tokens.py
```

### 3. 実行

```bash
source .venv/bin/activate
python3 qr_scanner_service.py
```

終了するには **q** キーを押すか、`Ctrl+C` を入力。

## ファイル構成

| ファイル | 説明 |
|---------|------|
| `qr_scanner_service.py` | メインスキャナーサービス（推奨） |
| `make_qr_tokens.py` | QRコード画像とトークンを生成 |
| `qr_to_discord_linux.py` | 旧版スキャナー（互換性のため残存） |
| `logs/qr_scanner.log` | ログファイル（自動生成） |
| `qr_out/` | 生成されたQR画像 |

## パラメータ説明

`qr_scanner_service.py` 内の主要パラメータ：

| パラメータ | デフォルト | 説明 |
|-----------|-----------|------|
| `SCAN_EVERY_N_FRAMES` | 2 | N フレームごとにQR解析（CPU負荷軽減） |
| `REARM_MISS_SEC` | 1.0 | この秒数QRが見えなくなったら再度送信可能になる |
| `UI_HOLD_SEC` | 1.2 | 画面表示を保持する秒数 |
| `CAM_FAIL_THRESHOLD` | 30 | カメラ読み取り連続失敗でリカバリを試みる閾値 |
| `CAM_REOPEN_WAIT_SEC` | 3.0 | カメラ再接続前の待機時間 |
| `ROI_PADDING` | 40 | 検出領域の余白（px） |
| `ROI_TIMEOUT_SEC` | 2.0 | ROI（関心領域）を維持する秒数 |

## エッジトリガ方式の動作

連続検出による連投を防ぐため、以下のロジックを採用：

1. QRコードを検出すると、その種類（OPEN/CLOSE/TEST/UNKNOWN）を「非武装（armed=False）」にする
2. Discord送信は「武装中（armed=True）」の場合のみ実行
3. `REARM_MISS_SEC` 秒間その種類が見えなくなったら「再武装（armed=True）」する
4. 種類ごとに独立して管理するため、OPENを検出した直後にCLOSEを読むことは可能

## ログ

ログは `logs/qr_scanner.log` に出力されます。

```
2024-12-17 19:50:00 [INFO] QR_DETECTED: OPEN preview=9f2a7c1e4b...
2024-12-17 19:50:00 [INFO] SENT: OPEN -> あけた
2024-12-17 19:50:05 [DEBUG] REARM: OPEN が再アームされました
```

### ログレベル

| レベル | 出力先 | 内容 |
|--------|--------|------|
| DEBUG | ファイルのみ | 再アーム通知など詳細情報 |
| INFO | コンソール+ファイル | 検出・送信などの主要イベント |
| WARNING | コンソール+ファイル | Webhook失敗など |
| ERROR | コンソール+ファイル | カメラエラーなど |

## トラブルシューティング

### カメラが開けない

```bash
# 利用可能なカメラを確認
ls /dev/video*

# 別のデバイスを試す場合、コード内の device_id を変更
# CameraManager(device_id=1)
```

### pyzbarが使えない

```bash
# libzbarがインストールされているか確認
dpkg -l | grep libzbar

# 再インストール
sudo apt install libzbar0
pip install pyzbar
```

### Wayland警告

```
Warning: Ignoring XDG_SESSION_TYPE=wayland on Gnome.
```

これは無視しても動作します。消したい場合：

```bash
QT_QPA_PLATFORM=wayland python3 qr_scanner_service.py
```

## 旧版からの移行

`qr_to_discord_linux.py` から `qr_scanner_service.py` への移行：

1. `.env` に `TEST_QR` を追加（`make_qr_tokens.py` を再実行すれば自動生成）
2. `qr_scanner_service.py` を使用
3. 旧版はそのまま残るため、必要に応じて削除

---

## 📱 Web アプリ版（スマートフォン対応）

スマートフォンのブラウザから QR コードをスキャンできる Web アプリ版も利用可能です。

### 特徴

- **スマートフォン対応**: ブラウザからカメラでQRスキャン
- **Discord認証**: サーバーメンバーのみがアクセス可能
- **無料ホスティング**: Render.com で無料運用可能

### ファイル構成

```
webapp/
├── main.py           # FastAPI サーバー
├── auth.py           # Discord OAuth2 認証
├── config.py         # 設定読み込み
├── requirements.txt  # 依存パッケージ
└── static/
    ├── index.html    # スキャナーUI
    ├── login.html    # ログイン画面
    ├── style.css     # スタイル
    └── scanner.js    # QRスキャン処理
```

### セットアップ

#### 1. Discord Developer Portal でアプリを作成

1. [Discord Developer Portal](https://discord.com/developers/applications) にアクセス
2. 「New Application」をクリック
3. 左メニュー「OAuth2」→「General」を開く
4. 「Redirects」に以下を追加:
   - ローカル: `http://localhost:8000/auth/callback`
   - 本番: `https://your-app.onrender.com/auth/callback`
5. **Client ID** と **Client Secret** をメモ

#### 2. 環境変数を設定

`.env.example` をコピーして `.env` を作成し、以下を設定：

```env
# 既存設定
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxxx/yyyy
OPEN_QR=your_open_token
CLOSE_QR=your_close_token

# Web アプリ用（新規追加）
DISCORD_CLIENT_ID=your_client_id
DISCORD_CLIENT_SECRET=your_client_secret
DISCORD_GUILD_ID=your_server_id
SESSION_SECRET=your_random_secret
BASE_URL=http://localhost:8000
```

SESSION_SECRET の生成:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

#### 3. ローカルで実行

```bash
cd webapp
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

ブラウザで http://localhost:8000 にアクセス。

### Render.com へのデプロイ

#### 1. GitHub にプッシュ

```bash
git add .
git commit -m "Add web app"
git push origin main
```

#### 2. Render.com で新規 Web Service 作成

1. [Render.com](https://render.com) にログイン
2. 「New」→「Web Service」
3. GitHub リポジトリを接続
4. 設定:
   - **Name**: `discord-entry-bot`
   - **Runtime**: Python
   - **Build Command**: `pip install -r webapp/requirements.txt`
   - **Start Command**: `cd webapp && uvicorn main:app --host 0.0.0.0 --port $PORT`

#### 3. 環境変数を設定

Render のダッシュボードで Environment Variables を追加:

| 変数名 | 値 |
|--------|-----|
| `DISCORD_WEBHOOK_URL` | Webhook URL |
| `OPEN_QR` | 開錠トークン |
| `CLOSE_QR` | 施錠トークン |
| `DISCORD_CLIENT_ID` | OAuth2 Client ID |
| `DISCORD_CLIENT_SECRET` | OAuth2 Client Secret |
| `DISCORD_GUILD_ID` | サーバーID |
| `SESSION_SECRET` | ランダム文字列 |
| `BASE_URL` | `https://your-app.onrender.com` |

#### 4. Discord Redirect URI を更新

Discord Developer Portal で Redirect URI に本番URLを追加:
```
https://your-app.onrender.com/auth/callback
```

### 注意事項

- **無料枠の制限**: 15分間アクセスがないとスリープ（初回アクセスに数秒かかる）
- **HTTPS必須**: カメラアクセスにはHTTPS接続が必要（Render.comは自動でHTTPS）

## ライセンス

Apache License 2.0

