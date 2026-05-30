"""
Operasyon Ajanı Konfigürasyonu.

Sub-app olarak E-dem'e mount edilince:
  OA_URL_PREFIX = "/operasyon"

Standalone çalışınca:
  OA_URL_PREFIX = "" (boş string, davranış değişmez)
"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

URL_PREFIX: str = os.getenv("OA_URL_PREFIX", "")

_TZ = ZoneInfo("Europe/Istanbul")


def now_tr() -> datetime:
    """Türkiye saatiyle şimdiki zamanı döner (naive datetime, UTC+3)."""
    return datetime.now(_TZ).replace(tzinfo=None)


def url(path: str) -> str:
    """Redirect URL'lerini prefix ile oluştur."""
    return f"{URL_PREFIX}{path}"
