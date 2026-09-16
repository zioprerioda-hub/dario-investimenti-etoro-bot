import json
import os
import urllib.parse
import urllib.request


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not token:
        raise RuntimeError("Missing GitHub secret: TELEGRAM_BOT_TOKEN")
    if not chat_id:
        raise RuntimeError("Missing GitHub secret: TELEGRAM_CHAT_ID")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": "ciao",
        }
    ).encode("utf-8")

    request = urllib.request.Request(url, data=payload, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))

    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error: {data}")

    print("Telegram message sent successfully.")


if __name__ == "__main__":
    main()
