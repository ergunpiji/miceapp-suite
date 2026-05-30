"""
Finans Ajanı — Jinja2 şablon yapılandırması.
Tüm router'lar buradan import eder.

Not: cache_size=0 — Python 3.14 ile Jinja2'nin weakref tabanlı
     LRU cache'i uyumsuz olduğu için devre dışı bırakıldı.
"""
from datetime import date, datetime
import jinja2
from fastapi.templating import Jinja2Templates

_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader("templates"),
    autoescape=True,
    cache_size=0,
)
templates = Jinja2Templates(env=_env)


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


def _abs_val(value) -> float:
    try:
        return abs(float(value))
    except Exception:
        return 0.0


templates.env.filters["currency"] = _fmt_currency
templates.env.filters["fmtdate"] = _fmt_date
templates.env.filters["absval"] = _abs_val
