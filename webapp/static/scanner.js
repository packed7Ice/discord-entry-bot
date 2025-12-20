/**
 * scanner.js - QRコードスキャナー
 * 
 * カメラからQRコードを読み取り、サーバーに送信する
 */

// DOM要素
const video = document.getElementById('video');
const canvas = document.getElementById('canvas');
const statusEl = document.getElementById('status');
const statusIcon = statusEl.querySelector('.status-icon');
const statusText = statusEl.querySelector('.status-text');
const resultEl = document.getElementById('result');
const errorEl = document.getElementById('error');
const usernameEl = document.getElementById('username');

// 状態管理
let scanning = false;
let lastScannedCode = null;
let cooldownUntil = 0;

// 設定
const COOLDOWN_MS = 3000;  // 同じコードの再スキャン防止（3秒）
const SCAN_INTERVAL_MS = 100;  // スキャン間隔

/**
 * 初期化
 */
async function init() {
    // ユーザー情報を取得
    await loadUserInfo();

    // カメラを開始
    await startCamera();
}

/**
 * ユーザー情報を読み込む
 */
async function loadUserInfo() {
    try {
        const response = await fetch('/auth/me');
        const data = await response.json();
        if (data.logged_in && data.user) {
            usernameEl.textContent = data.user.username;
        } else {
            // 未ログインならログインページへ
            window.location.href = '/login.html';
        }
    } catch (e) {
        console.error('ユーザー情報取得エラー:', e);
    }
}

/**
 * カメラを開始
 */
async function startCamera() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({
            video: {
                facingMode: 'environment',  // 背面カメラ優先
                width: { ideal: 1280 },
                height: { ideal: 720 }
            }
        });

        video.srcObject = stream;
        video.onloadedmetadata = () => {
            video.play();
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;

            updateStatus('ready', '📷', 'QRコードを読み取り中...');
            scanning = true;
            requestAnimationFrame(scanLoop);
        };
    } catch (e) {
        console.error('カメラエラー:', e);
        showError('カメラにアクセスできません。\nカメラの権限を許可してください。');
    }
}

/**
 * スキャンループ
 */
function scanLoop() {
    if (!scanning) return;

    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const code = jsQR(imageData.data, imageData.width, imageData.height, {
        inversionAttempts: 'dontInvert'
    });

    if (code && code.data) {
        handleQRCode(code.data);
    }

    setTimeout(() => requestAnimationFrame(scanLoop), SCAN_INTERVAL_MS);
}

/**
 * QRコードを処理
 */
async function handleQRCode(data) {
    const now = Date.now();

    // クールダウン中は無視
    if (data === lastScannedCode && now < cooldownUntil) {
        return;
    }

    // クールダウン設定
    lastScannedCode = data;
    cooldownUntil = now + COOLDOWN_MS;

    updateStatus('scanning', '🔄', '送信中...');

    try {
        const response = await fetch('/api/scan', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ qr: data })
        });

        const result = await response.json();

        if (response.ok) {
            showResult('success', result.action, result.message);
        } else {
            showResult('error', 'エラー', result.detail || '不明なQRコード');
        }
    } catch (e) {
        console.error('送信エラー:', e);
        showResult('error', 'エラー', '送信に失敗しました');
    }

    // ステータスを戻す
    setTimeout(() => {
        updateStatus('ready', '📷', 'QRコードを読み取り中...');
    }, 2000);
}

/**
 * ステータスを更新
 */
function updateStatus(type, icon, text) {
    statusEl.className = `status status-${type}`;
    statusIcon.textContent = icon;
    statusText.textContent = text;
}

/**
 * 結果を表示
 */
function showResult(type, action, message) {
    resultEl.className = `result result-${type}`;

    const icon = resultEl.querySelector('.result-icon') || document.createElement('div');
    icon.className = 'result-icon';

    const text = resultEl.querySelector('.result-text') || document.createElement('div');
    text.className = 'result-text';

    if (type === 'success') {
        if (action === 'open') {
            icon.textContent = '🔓';
            text.textContent = 'あけた';
        } else if (action === 'close') {
            icon.textContent = '🔒';
            text.textContent = 'しめた';
        } else if (action === 'test') {
            icon.textContent = '✅';
            text.textContent = 'テスト成功';
        } else {
            icon.textContent = '✅';
            text.textContent = message;
        }
    } else {
        icon.textContent = '❌';
        text.textContent = message;
    }

    if (!resultEl.querySelector('.result-icon')) {
        resultEl.appendChild(icon);
        resultEl.appendChild(text);
    }

    resultEl.classList.remove('hidden');

    // 3秒後に非表示
    setTimeout(() => {
        resultEl.classList.add('hidden');
    }, 3000);
}

/**
 * エラーを表示
 */
function showError(message) {
    errorEl.querySelector('.error-text').textContent = message;
    errorEl.classList.remove('hidden');
    statusEl.classList.add('hidden');
}

// 開始
document.addEventListener('DOMContentLoaded', init);
