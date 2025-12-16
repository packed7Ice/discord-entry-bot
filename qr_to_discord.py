import os
import time
import requests
import cv2
from dotenv import load_dotenv

load_dotenv()

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
OPEN_QR     = os.environ["OPEN_QR"]
CLOSE_QR    = os.environ["CLOSE_QR"]

COOLDOWN_SEC = 3

def send_discord(text: str) -> None:
    requests.post(WEBHOOK_URL, json={"content": text}, timeout=5)

def main() -> None:
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    detector = cv2.QRCodeDetector()

    last_sent = {"OPEN": 0.0, "CLOSE": 0.0}

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        data, _, _ = detector.detectAndDecode(frame)

        if data:
            now = time.time()

            if data == OPEN_QR and now - last_sent["OPEN"] >= COOLDOWN_SEC:
                print("OPEN検知")
                send_discord("あけた")
                last_sent["OPEN"] = now

            elif data == CLOSE_QR and now - last_sent["CLOSE"] >= COOLDOWN_SEC:
                print("CLOSE検知")
                send_discord("しめた")
                last_sent["CLOSE"] = now

        cv2.imshow("QR Scanner (q to quit)", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
