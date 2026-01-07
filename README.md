# discord-entry-bot

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://python.org)
[![Discord](https://img.shields.io/badge/Discord-Webhook-5865F2.svg)](https://discord.com)

> **QRコードをスキャンしてDiscord Webhookに通知を送信するボット**
> 
> PCカメラでのスキャンに加え、スマートフォンのブラウザからもQRコードを読み取り可能。Discord OAuth2によるサーバーメンバー認証対応。

## 主な機能

- 🔍 **高速QR検出**: pyzbar優先（fallbackでOpenCV）
- 📱 **スマートフォン対応**: Webアプリでブラウザからスキャン
- 🔐 **Discord認証**: サーバーメンバーのみアクセス可能
- ⚡ **エッジトリガ方式**: 連続送信を防止
- 🔄 **カメラ自動リカバリ**: 接続切れ時に自動再接続
- 📝 **ログローテーション**: 1MB×5世代でログをローテーション

## 技術スタック

### バックエンド

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Uvicorn](https://img.shields.io/badge/Uvicorn-499848?logo=gunicorn&logoColor=white)](https://www.uvicorn.org)

### フロントエンド

[![HTML5](https://img.shields.io/badge/HTML5-E34F26?logo=html5&logoColor=white)](https://developer.mozilla.org/docs/Web/HTML)
[![CSS3](https://img.shields.io/badge/CSS3-1572B6?logo=css3&logoColor=white)](https://developer.mozilla.org/docs/Web/CSS)
[![JavaScript](https://img.shields.io/badge/JavaScript-F7DF1E?logo=javascript&logoColor=black)](https://developer.mozilla.org/docs/Web/JavaScript)

### QRコード処理

[![OpenCV](https://img.shields.io/badge/OpenCV-5C3EE8?logo=opencv&logoColor=white)](https://opencv.org)
[![pyzbar](https://img.shields.io/badge/pyzbar-QR%20Decode-green)](https://github.com/NaturalHistoryMuseum/pyzbar)
[![jsQR](https://img.shields.io/badge/jsQR-Web%20QR%20Scan-orange)](https://github.com/cozmo/jsQR)

### 認証・通信

[![Discord](https://img.shields.io/badge/Discord_OAuth2-5865F2?logo=discord&logoColor=white)](https://discord.com/developers/docs/topics/oauth2)
[![httpx](https://img.shields.io/badge/httpx-Async%20HTTP-blue)](https://www.python-httpx.org)

### デプロイ

[![Render](https://img.shields.io/badge/Render-46E3B7?logo=render&logoColor=white)](https://render.com)

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
- **ダッシュボード**: メインページからスキャナーや各機能にアクセス
- **テーマ切り替え**: ダーク/ライトモード対応（デバイス設定自動検出＋手動切り替え）
- **直接リンク送信**: QRスキャンなしでリンクからWebhook送信
- **レート制限**: 1分間に3回以上の送信を制限（スパム防止）
- **確認画面**: 送信前に確認ダイアログを表示
- **自動タブ閉じ**: 送信完了後5秒でタブを自動クローズ
- **Google Cloud Run**: 高速起動（5-10秒）でホスティング

### ファイル構成

```
webapp/
├── main.py           # FastAPI サーバー
├── auth.py           # Discord OAuth2 認証
├── config.py         # 設定読み込み
├── requirements.txt  # 依存パッケージ
└── static/
    ├── dashboard.html # メインダッシュボード
    ├── index.html    # QRスキャナーUI
    ├── login.html    # ログイン画面
    ├── style.css     # スタイル（テーマ対応）
    └── scanner.js    # QRスキャン処理
```

### URL 構成

| URL | 説明 |
|-----|------|
| `/` | ダッシュボードにリダイレクト |
| `/dashboard` | メインダッシュボード |
| `/scanner` | QRスキャナー |
| `/action/open` | 「あけた」を送信（確認画面あり） |
| `/action/close` | 「しめた」を送信（確認画面あり） |
| `/action/test` | 「test」を送信（確認画面あり） |

### セットアップ

#### 1. Discord Developer Portal でアプリを作成

1. [Discord Developer Portal](https://discord.com/developers/applications) にアクセス
2. 「New Application」をクリック
3. 左メニュー「OAuth2」→「General」を開く
4. 「Redirects」に以下を追加:
   - ローカル: `http://localhost:8000/auth/callback`
   - 本番: `https://your-app.run.app/auth/callback`
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

### Google Cloud Run へのデプロイ

#### 1. 前提条件

- Google Cloud アカウント
- gcloud CLI インストール済み

#### 2. デプロイ

```bash
# gcloud 認証
gcloud auth login
gcloud config set project your-project-id

# Docker 認証設定
gcloud auth configure-docker asia-northeast1-docker.pkg.dev

# ビルド & プッシュ
docker build -t discord-entry-bot .
docker tag discord-entry-bot asia-northeast1-docker.pkg.dev/your-project/cloud-run-source-deploy/discord-entry-bot:latest
docker push asia-northeast1-docker.pkg.dev/your-project/cloud-run-source-deploy/discord-entry-bot:latest

# Cloud Run にデプロイ
gcloud run deploy discord-entry-bot \
  --image asia-northeast1-docker.pkg.dev/your-project/cloud-run-source-deploy/discord-entry-bot:latest \
  --region asia-northeast1 \
  --allow-unauthenticated \
  --port 8080
```

#### 3. 環境変数を設定

Cloud Run コンソールで環境変数を設定：

| 変数名 | 値 |
|--------|-----|
| `DISCORD_WEBHOOK_URL` | Webhook URL |
| `OPEN_QR` | 開錠トークン |
| `CLOSE_QR` | 施錠トークン |
| `DISCORD_CLIENT_ID` | OAuth2 Client ID |
| `DISCORD_CLIENT_SECRET` | OAuth2 Client Secret |
| `DISCORD_GUILD_ID` | サーバーID |
| `SESSION_SECRET` | ランダム文字列 |
| `BASE_URL` | `https://your-app.run.app` |

#### 4. Discord Redirect URI を更新

Discord Developer Portal で Redirect URI に本番URLを追加。

### QRコード生成スクリプト

```bash
# QRトークン画像を生成
python make_qr_tokens.py

# 直接リンク用QRコードを生成
python make_action_qr.py
```

### 注意事項

- **Cloud Run**: コールドスタート 5-10秒（Render.comの30-60秒より高速）
- **HTTPS必須**: カメラアクセスにはHTTPS接続が必要
- **レート制限**: 1分間に3回以上送信すると一時的にブロック

## ライセンス

Apache License 2.0
