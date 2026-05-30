"""
TCMB günlük döviz kuru çekimi
https://www.tcmb.gov.tr/kurlar/today.xml
"""
from __future__ import annotations

from datetime import date
from xml.etree import ElementTree

try:
    import httpx
    _HTTPX = True
except ImportError:
    _HTTPX = False

TCMB_URL = "https://www.tcmb.gov.tr/kurlar/today.xml"
_CODES = {"USD", "EUR", "GBP"}


def fetch_today_rates() -> dict:
    """
    TCMB'den bugünün satış kurlarını döner.
    Örnek: {"EUR": 42.15, "USD": 38.70, "GBP": 49.20, "date": "2026-04-12"}
    Hata olursa boş dict döner — editörde kullanıcı manuel girer.
    """
    if not _HTTPX:
        return {}
    try:
        r = httpx.get(TCMB_URL, timeout=5)
        r.raise_for_status()
        root = ElementTree.fromstring(r.content)
        rates: dict = {"date": date.today().isoformat()}
        for currency in root.findall("Currency"):
            code = currency.get("CurrencyCode")
            if code not in _CODES:
                continue
            selling = currency.findtext("ForexSelling") or ""
            try:
                rates[code] = round(float(selling.replace(",", ".")), 4)
            except ValueError:
                pass
        return rates
    except Exception:
        return {}
