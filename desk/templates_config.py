"""
Merkezi Jinja2Templates örneği — tüm router'lar bu modülden import eder.
Böylece app.py'de tanımlanan özel filter'lar her yerde çalışır.
"""

import json
from datetime import datetime
from typing import Any, Union
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")


def format_date_tr(value: Any) -> str:
    """YYYY-MM-DD → GG.AA.YYYY"""
    if not value:
        return "—"
    try:
        if hasattr(value, "strftime"):
            return value.strftime("%d.%m.%Y")
        # ISO formatındaki stringleri parse etmeye çalış (örn: "2023-10-27")
        dt = datetime.fromisoformat(str(value).split()[0])
        return dt.strftime("%d.%m.%Y")
    except Exception:
        return str(value)


def format_money(value: Any) -> str:
    if value is None:
        return "₺0,00"
    try:
        # Eğer değer string ve virgüllü ise noktaya çevir (örn: "15,50" -> 15.50)
        if isinstance(value, str):
            value = value.replace(".", "").replace(",", ".")
        amount = float(value)
        return f"₺{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "₺0,00"


def role_label(role: str) -> str:
    labels = {
        "kullanici":   "Kullanıcı",
        "mudur":       "Müdür",
        "genel_mudur": "Genel Müdür",
        "admin":       "Admin",
        "super_admin": "Süper Admin",
    }
    return labels.get(role, role)


def fromjson_filter(value: Any) -> Any:
    """JSON string → Python object (Jinja2 filter)"""
    try:
        if isinstance(value, str):
            return json.loads(value)
        return value or {}
    except Exception:
        return {}


def format_datetime_tr(value: Any) -> str:
    """datetime veya ISO string → GG.AA.YYYY SS:DD"""
    if not value:
        return "—"
    try:
        if hasattr(value, "strftime"):
            return value.strftime("%d.%m.%Y %H:%M")
        s = str(value)[:16].replace("T", " ")   # "2026-04-20T14:30" → "2026-04-20 14:30"
        dt = datetime.fromisoformat(s)
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(value)[:16]


def tojson_filter(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def next_day_filter(value: Any) -> Any:
    """date nesnesine 1 gün ekler — işe dönüş tarihi gösterimi için."""
    if not value:
        return value
    try:
        from datetime import timedelta
        return value + timedelta(days=1)
    except Exception:
        return value


templates.env.filters["date_tr"]      = format_date_tr
templates.env.filters["dateformat"]   = format_date_tr   # alias (bazı şablonlar dateformat kullanıyor)
templates.env.filters["datetime_tr"]  = format_datetime_tr
templates.env.filters["money"]        = format_money
templates.env.filters["currency"]     = format_money   # alias (bazı şablonlar currency kullanıyor)
templates.env.filters["role_label"]   = role_label
templates.env.filters["fromjson"]     = fromjson_filter
templates.env.filters["tojson"]       = tojson_filter
templates.env.filters["next_day"]     = next_day_filter


def module_enabled(request, module_key: str) -> bool:
    """Modül flag'ini template'lerden kontrol eder.
    Kullanım: {% if module_enabled(request, 'einvoice') %}...{% endif %}"""
    if request is None:
        return False
    enabled = getattr(request.state, "enabled_modules", None) or set()
    return module_key in enabled


templates.env.globals["module_enabled"] = module_enabled


def can_see(request, module_key: str) -> bool:
    """RBAC v2 — Bu user bu modülün sayfasını görür mü?
    Kullanım: {% if can_see(request, 'customers') %}...{% endif %}"""
    if request is None:
        return False
    user = getattr(request.state, "current_user", None)
    if user is None:
        return False
    from access_policy import user_can_see_module
    return user_can_see_module(user, module_key)


def can_edit(request, module_key: str) -> bool:
    """RBAC v2 — Bu user bu modülde yazma yapabilir mi?"""
    if request is None:
        return False
    user = getattr(request.state, "current_user", None)
    if user is None:
        return False
    from access_policy import user_can_edit_module
    return user_can_edit_module(user, module_key)


templates.env.globals["can_see"] = can_see
templates.env.globals["can_edit"] = can_edit


# --- Şirket profili ---

# Company modelindeki doğrudan alanlar — bu anahtar için request.state.current_company'ye bakılır
_COMPANY_MODEL_FIELDS = frozenset({
    "name", "short_name", "tax_no", "tax_office",
    "address", "phone", "email", "logo_path",
})

# SystemSetting fallback cache (Company modelinde olmayan genişletilmiş ayarlar için)
_company_settings_cache: dict[str, str] = {}
_company_cache_loaded = False


def _load_company_settings() -> dict:
    """SystemSetting 'company_*' anahtarlarını cache'e yükle."""
    global _company_cache_loaded
    if _company_cache_loaded:
        return _company_settings_cache
    try:
        from database import SessionLocal
        from models import SystemSetting
        db = SessionLocal()
        try:
            rows = db.query(SystemSetting).filter(
                SystemSetting.key.like("company_%")
            ).all()
            _company_settings_cache.clear()
            for r in rows:
                _company_settings_cache[r.key] = r.value or ""
            _company_cache_loaded = True
        finally:
            db.close()
    except Exception:  # noqa: BLE001
        pass
    return _company_settings_cache


def invalidate_company_cache() -> None:
    """Şirket profili güncellendikten sonra cache'i temizle."""
    global _company_cache_loaded
    _company_cache_loaded = False
    _company_settings_cache.clear()


def _sanitize_logo(val: str) -> str:
    """Dosya yolu olarak saklanan eski logo değerlerini filtrele — sadece data: URI veya http(s) kabul et."""
    if not val:
        return ""
    if val.startswith("data:") or val.startswith("http"):
        return val
    return ""


def company(key: str, default: str = "", request=None) -> str:
    """Template global: {{ company('name', request=request) }}
    Önce request.state.current_company (Company tablosu) → sonra SystemSetting fallback."""
    # Company tablosundan oku (request varsa)
    if request is not None and key in _COMPANY_MODEL_FIELDS:
        company_obj = getattr(request.state, "current_company", None)
        if company_obj is not None:
            val = getattr(company_obj, key, None) or ""
            if val:
                result = _sanitize_logo(str(val)) if "logo" in key else str(val)
                if result:
                    return result
            # Company alanı boşsa SystemSetting'e düş

    # SystemSetting fallback (brand_color, IBAN bilgileri, kep_address vb.)
    settings = _load_company_settings()
    full_key = f"company_{key}" if not key.startswith("company_") else key
    val = settings.get(full_key, "") or ""
    if "logo" in key:
        val = _sanitize_logo(val)
    return val or default


templates.env.globals["company"] = company


def make_date_filter(parts):
    """[year, month, day] listesinden date nesnesi üretir — takvim şablonu için."""
    from datetime import date as _date
    return _date(parts[0], parts[1], parts[2])


templates.env.filters["make_date"] = make_date_filter
