import requests
import logging
from config import TELEGRAM_TOKEN

logger = logging.getLogger(__name__)

class TelegramAPI:
    """Manual Telegram API wrapper for synchronous use in background threads."""
    
    BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

    @classmethod
    def send_message(cls, chat_id, text, parse_mode="Markdown"):
        url = f"{cls.BASE_URL}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            return response.json().get("result", {})
        except Exception as e:
            logger.error(f"Error sending manual message: {e}")
            return None

    @classmethod
    def edit_message(cls, chat_id, message_id, text, parse_mode="Markdown"):
        url = f"{cls.BASE_URL}/editMessageText"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode
        }
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error editing manual message: {e}")
            return None

    @classmethod
    def send_video(cls, chat_id, video_path, caption="", parse_mode="Markdown"):
        url = f"{cls.BASE_URL}/sendVideo"
        try:
            with open(video_path, "rb") as video_file:
                files = {"video": video_file}
                data = {
                    "chat_id": chat_id,
                    "caption": caption,
                    "parse_mode": parse_mode,
                    "supports_streaming": True
                }
                response = requests.post(url, data=data, files=files, timeout=120)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Error sending manual video: {e}")
            return None

    @classmethod
    def delete_message(cls, chat_id, message_id):
        url = f"{cls.BASE_URL}/deleteMessage"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id
        }
        try:
            requests.post(url, json=payload, timeout=5)
        except:
            pass
