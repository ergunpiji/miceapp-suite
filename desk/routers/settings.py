"""
E-dem — Firma & Sistem Ayarları (Admin only)
GET  /settings       → form
POST /settings       → kaydet (multipart: logo dosyası dahil)
"""
import base64
import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Settings, User
from templates_config import templates

router = APIRouter(prefix="/settings", tags=["settings"])

LOGO_DIR = os.path.join("static", "uploads", "company")
LOGO_PATH = os.path.join(LOGO_DIR, "logo")   # uzantı sonradan eklenir


def _require_admin(current_user: User):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Bu sayfa yalnızca Admin'e özeldir.")


def _get_or_create_settings(db: Session) -> Settings:
    s = db.query(Settings).filter(Settings.id == 1).first()
    if not s:
        s = Settings(id=1)
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


def _restore_logo_if_needed(s: Settings) -> None:
    """Railway restart'tan sonra base64'ten logo dosyasını yeniden yaz."""
    if not s.logo_b64:
        return
    if s.logo_path and os.path.exists(s.logo_path):
        return
    try:
        os.makedirs(LOGO_DIR, exist_ok=True)
        ext = os.path.splitext(s.logo_path or "logo.png")[1] or ".png"
        path = LOGO_PATH + ext
        with open(path, "wb") as f:
            f.write(base64.b64decode(s.logo_b64))
        s.logo_path = path
    except Exception as e:
        print(f"[SETTINGS] logo restore hatası: {e}", flush=True)


def _logo_src(s: Settings) -> str:
    """Template'de gösterilecek logo URL'i döner."""
    if s.logo_path and os.path.exists(s.logo_path):
        return "/" + s.logo_path.replace("\\", "/")
    if s.logo_url:
        return s.logo_url
    return ""


@router.get("", response_class=HTMLResponse, name="settings_form")
async def settings_form(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    saved: str = "",
):
    _require_admin(current_user)
    s = _get_or_create_settings(db)
    _restore_logo_if_needed(s)
    return templates.TemplateResponse("settings/form.html", {
        "request":      request,
        "current_user": current_user,
        "settings":     s,
        "logo_src":     _logo_src(s),
        "page_title":   "Firma & Sistem Ayarları",
        "saved":        saved == "1",
    })


@router.post("", name="settings_save")
async def settings_save(
    request: Request,
    company_name:        str = Form(""),
    company_trade_name:  str = Form(""),
    tax_number:          str = Form(""),
    tax_office:          str = Form(""),
    company_address:     str = Form(""),
    company_phone:       str = Form(""),
    company_email:       str = Form(""),
    email_signature:     str = Form(""),
    rfq_subject_tpl:     str = Form("{event_name} Fiyat Teklifi - {request_no}"),
    currency:            str = Form("₺"),
    invoice_mudur_limit: str = Form(""),
    remove_logo:         str = Form(""),        # "1" = logoyu kaldır
    logo_file: UploadFile = File(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(current_user)
    s = _get_or_create_settings(db)

    # ── Firma bilgileri ──────────────────────────────────────────────────────
    s.company_name       = company_name.strip()
    s.company_trade_name = company_trade_name.strip()
    s.tax_number         = tax_number.strip().replace(" ", "")
    s.tax_office         = tax_office.strip()
    s.company_address    = company_address.strip()
    s.company_phone      = company_phone.strip()
    s.company_email      = company_email.strip()

    # ── Logo ─────────────────────────────────────────────────────────────────
    if remove_logo == "1":
        s.logo_path = ""
        s.logo_b64  = ""
        s.logo_url  = ""
    elif logo_file and logo_file.filename:
        content = await logo_file.read()
        if content:
            ext = os.path.splitext(logo_file.filename)[1].lower() or ".png"
            if ext not in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
                return RedirectResponse(url="/settings?logo_err=ext", status_code=303)
            if len(content) > 2 * 1024 * 1024:  # 2 MB sınırı
                return RedirectResponse(url="/settings?logo_err=size", status_code=303)
            os.makedirs(LOGO_DIR, exist_ok=True)
            path = LOGO_PATH + ext
            with open(path, "wb") as f:
                f.write(content)
            s.logo_path = path
            s.logo_b64  = base64.b64encode(content).decode("utf-8")
            s.logo_url  = ""   # artık dosya kullanılıyor

    # ── E-posta & diğer ──────────────────────────────────────────────────────
    s.email_signature = email_signature.strip()
    s.rfq_subject_tpl = rfq_subject_tpl.strip() or "{event_name} Fiyat Teklifi - {request_no}"
    s.currency        = currency.strip() or "₺"

    limit_str = invoice_mudur_limit.strip().replace(".", "").replace(",", ".")
    try:
        s.invoice_mudur_limit = float(limit_str) if limit_str else None
    except ValueError:
        s.invoice_mudur_limit = None

    db.commit()
    return RedirectResponse(url="/settings?saved=1", status_code=status.HTTP_302_FOUND)
