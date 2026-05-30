"""HR Ajanı — Jinja2 şablon yapılandırması."""
from datetime import date, datetime

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")


def _fmt_currency(value) -> str:
    try:
        return f"₺{float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "₺0,00"


def _fmt_date(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.strftime("%d.%m.%Y")
    return str(value)


def _fmt_month(value) -> str:
    months = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
              "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
    try:
        return months[int(value)]
    except Exception:
        return str(value)


def _fmt_hours(value) -> str:
    try:
        h = float(value)
        whole = int(h)
        minutes = int((h - whole) * 60)
        return f"{whole}s {minutes:02d}dk" if minutes else f"{whole}s"
    except Exception:
        return str(value)


templates.env.filters["currency"] = _fmt_currency
templates.env.filters["fmtdate"] = _fmt_date
templates.env.filters["fmtmonth"] = _fmt_month
templates.env.filters["fmthours"] = _fmt_hours
