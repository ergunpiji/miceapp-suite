"""
Şirket Profili — admin tek formda firma bilgileri + logo upload.
SystemSetting('company_*') üzerinden saklanır; templates_config.company()
helper'ı her yerden okur (cache'li).
"""
import os
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import require_admin
from database import get_db
from models import User, SystemSetting, Company
from templates_config import templates, invalidate_company_cache


# Company model alanları — form POST'ta bu alanlar Company tablosuna da yazılır
_COMPANY_MODEL_KEYS = {"name", "short_name", "tax_no", "tax_office", "address", "phone", "email"}


def _sync_company_model(db, current_user, values: dict) -> None:
    """Form değerlerini Company tablosuna da yaz."""
    if not current_user.company_id:
        return
    obj = db.query(Company).filter(Company.id == current_user.company_id).first()
    if not obj:
        return
    for field in _COMPANY_MODEL_KEYS:
        if field in values and hasattr(obj, field):
            val = values[field] or None
            if val is not None:
                setattr(obj, field, val)


router = APIRouter(prefix="/admin/company-profile", tags=["company_profile"])


# Tek yerden yönetilen alan listesi — form + DB ile senkron
FIELDS = [
    # (key, label, group, type, placeholder)
    ("name",              "Ticari Unvan",        "marka", "text",  "Örn: Prizmatik Etkinlik Hizmetleri A.Ş."),
    ("short_name",        "Kısa Ad",             "marka", "text",  "Örn: Prizmatik"),
    ("brand_color",       "Marka Rengi",         "marka", "color", "#1A3A5C"),
    ("invoice_footer",    "Fatura Altı Notu",    "marka", "textarea", "Örn: Ödemelerinizi 30 gün içinde IBAN'a yapınız. Gecikmiş ödemelerde aylık %2 vade farkı uygulanır."),

    ("tax_no",            "Vergi No",            "kimlik", "text", "10 haneli"),
    ("tax_office",        "Vergi Dairesi",       "kimlik", "text", "Örn: Beşiktaş VD"),
    ("mersis_no",         "MERSIS No",           "kimlik", "text", "16 haneli"),
    ("trade_registry_no", "Ticaret Sicil No",    "kimlik", "text", ""),

    ("address",           "Adres",               "iletisim", "textarea", ""),
    ("phone",             "Telefon",             "iletisim", "text", "+90 5XX XXX XX XX"),
    ("email",             "E-posta",             "iletisim", "email", "info@firma.com"),
    ("website",           "Web Sitesi",          "iletisim", "text", "https://firma.com"),
    ("kep_address",       "KEP Adresi",          "iletisim", "email", "firma@hs01.kep.tr"),

    ("iban_1",            "IBAN 1",              "banka", "text", "TR00 0000 0000 0000 0000 0000 00"),
    ("iban_1_bank",       "Banka 1 (ad/şube)",   "banka", "text", "Örn: Garanti — Beşiktaş Şubesi"),
    ("iban_2",            "IBAN 2",              "banka", "text", ""),
    ("iban_2_bank",       "Banka 2 (ad/şube)",   "banka", "text", ""),
]


GROUPS = {
    "marka":    {"title": "Marka",      "icon": "bi-palette"},
    "kimlik":   {"title": "Kimlik & Vergi", "icon": "bi-card-text"},
    "iletisim": {"title": "İletişim",   "icon": "bi-telephone"},
    "banka":    {"title": "Banka Bilgileri", "icon": "bi-bank"},
}


def _get_setting(db: Session, key: str) -> str:
    s = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    return s.value if s else ""


def _set_setting(db: Session, key: str, value: str) -> None:
    s = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if s:
        s.value = value
    else:
        db.add(SystemSetting(key=key, value=value))


def _logo_dir() -> Path:
    p = Path(__file__).resolve().parent.parent / "static" / "uploads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _sanitize_logo(val: str) -> str:
    """Eski dosya yolu değerlerini filtrele — sadece data: URI veya http(s) kabul et."""
    if not val:
        return ""
    if val.startswith("data:") or val.startswith("http"):
        return val
    return ""


@router.get("", response_class=HTMLResponse, name="company_profile_form")
async def form_view(
    request: Request,
    saved: int = 0,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    values = {}
    for key, *_ in FIELDS:
        values[key] = _get_setting(db, f"company_{key}")
    logo_path      = _sanitize_logo(_get_setting(db, "company_logo_path"))
    logo_dark_path = _sanitize_logo(_get_setting(db, "company_logo_dark_path"))
    company_obj = None
    if current_user.company_id:
        company_obj = db.query(Company).filter(Company.id == current_user.company_id).first()

    return templates.TemplateResponse(
        "admin/company_profile.html",
        {
            "request": request,
            "current_user": current_user,
            "page_title": "Şirket Profili",
            "fields": FIELDS,
            "groups": GROUPS,
            "values": values,
            "logo_path":      logo_path,
            "logo_dark_path": logo_dark_path,
            "saved": bool(saved),
            "limit_kullanici": company_obj.ref_close_limit_kullanici if company_obj else None,
            "limit_mudur":     company_obj.ref_close_limit_mudur     if company_obj else None,
        },
    )


@router.post("", name="company_profile_save")
async def form_save(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    form = await request.form()
    values = {}
    for key, *_ in FIELDS:
        val = (form.get(key) or "").strip()
        _set_setting(db, f"company_{key}", val)
        values[key] = val
    _sync_company_model(db, current_user, values)
    db.commit()
    invalidate_company_cache()
    return RedirectResponse(url="/admin/company-profile?saved=1", status_code=303)


@router.post("/approval-limits", name="company_profile_approval_limits")
async def save_approval_limits(
    limit_kullanici: str = Form(""),
    limit_mudur: str = Form(""),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="Şirket atanmamış.")
    obj = db.query(Company).filter(Company.id == current_user.company_id).first()
    if not obj:
        raise HTTPException(status_code=404)
    obj.ref_close_limit_kullanici = float(limit_kullanici) if limit_kullanici.strip() else None
    obj.ref_close_limit_mudur = float(limit_mudur) if limit_mudur.strip() else None
    db.commit()
    return RedirectResponse(url="/admin/company-profile?saved=1", status_code=303)


_LOGO_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".svg": "image/svg+xml",
}


@router.post("/logo", name="company_profile_logo_upload")
async def upload_logo(
    file: UploadFile = File(...),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not file.filename:
        return RedirectResponse(url="/admin/company-profile", status_code=303)
    ext = os.path.splitext(file.filename)[1].lower() or ".png"
    if ext not in _LOGO_MIME:
        return RedirectResponse(url="/admin/company-profile?logo_err=ext", status_code=303)
    content = await file.read()
    import base64
    mime = _LOGO_MIME[ext]
    logo_data = f"data:{mime};base64,{base64.b64encode(content).decode()}"
    _set_setting(db, "company_logo_path", logo_data)
    # company_id varsa o şirket, yoksa ilk şirketi güncelle
    company_id = current_user.company_id
    obj = (
        db.query(Company).filter(Company.id == company_id).first()
        if company_id
        else db.query(Company).first()
    )
    if obj:
        obj.logo_path = logo_data
    db.commit()
    invalidate_company_cache()
    return RedirectResponse(url="/admin/company-profile?saved=1", status_code=303)


@router.post("/logo/delete", name="company_profile_logo_delete")
async def delete_logo(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    for old in _logo_dir().glob("company-logo.*"):
        try:
            old.unlink()
        except Exception:  # noqa: BLE001
            pass
    _set_setting(db, "company_logo_path", "")
    company_id = current_user.company_id
    obj = (
        db.query(Company).filter(Company.id == company_id).first()
        if company_id
        else db.query(Company).first()
    )
    if obj:
        obj.logo_path = None
    db.commit()
    invalidate_company_cache()
    return RedirectResponse(url="/admin/company-profile", status_code=303)


@router.post("/logo/dark", name="company_profile_logo_dark_upload")
async def upload_logo_dark(
    file: UploadFile = File(...),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not file.filename:
        return RedirectResponse(url="/admin/company-profile", status_code=303)
    ext = os.path.splitext(file.filename)[1].lower() or ".png"
    if ext not in _LOGO_MIME:
        return RedirectResponse(url="/admin/company-profile?logo_err=ext", status_code=303)
    content = await file.read()
    import base64
    mime = _LOGO_MIME[ext]
    logo_data = f"data:{mime};base64,{base64.b64encode(content).decode()}"
    _set_setting(db, "company_logo_dark_path", logo_data)
    db.commit()
    invalidate_company_cache()
    return RedirectResponse(url="/admin/company-profile?saved=1", status_code=303)


@router.post("/logo/dark/delete", name="company_profile_logo_dark_delete")
async def delete_logo_dark(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    for old in _logo_dir().glob("company-logo-dark.*"):
        try:
            old.unlink()
        except Exception:  # noqa: BLE001
            pass
    _set_setting(db, "company_logo_dark_path", "")
    db.commit()
    invalidate_company_cache()
    return RedirectResponse(url="/admin/company-profile", status_code=303)
