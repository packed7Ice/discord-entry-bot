import os
import time
import requests
import cv2
from dotenv import load_dotenv

load_dotenv()
WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]

def send_discord(message: str) -> None:
    r = requests.post(WEBHOOK_URL, json={"content": message}, timeout=5)
    r.raise_for_status()

def main() -> None:
    cap = cv2.VideoCapture(0)  # 内蔵カメラ。映らないなら 1 や 2 に変える
    detector = cv2.QRCodeDetector()

    last_sent = {}
    cooldown_sec = 5  # 同じQRを連投しないためのクールダウン

    while True:
        ret, frame = cap.read()
        if not ret:
            print("カメラからフレーム取得に失敗しました。")
            break

        data, bbox, _ = detector.detectAndDecode(frame)

        if data:
            now = time.time()
            last = last_sent.get(data, 0)

            if now - last >= cooldown_sec:
                print("QR検出:", data)

                # ===== 判定例（好きに変更OK）=====
                if data.startswith("ROOM_IN:"):
                    key = data.split(":", 1)[1]
                    send_discord(f"✅ 入室：{key}")
                elif data.startswith("ROOM_OUT:"):
                    key = data.split(":", 1)[1]
                    send_discord(f"🚪 退室：{key}")
                else:
                    # 動作確認用：そのまま送る（不要なら消す）
                    send_discord(f"📷 QR検出: `{data}`")

                last_sent[data] = now

            # 枠を描画（見やすさ用）
            if bbox is not None:
                pts = bbox[0].astype(int)
                for i in range(len(pts)):
                    pt1 = tuple(pts[i])
                    pt2 = tuple(pts[(i + 1) % len(pts)])
                    cv2.line(frame, pt1, pt2, (0, 255, 0), 2)

        cv2.imshow("QR Scanner (press q to quit)", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
