"""
E-dem — Sistem Ayarları (Admin only)
GET  /settings       → form
POST /settings       → kaydet
"""
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Settings, User
from templates_config import templates

router = APIRouter(prefix="/settings", tags=["settings"])


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


@router.get("", response_class=HTMLResponse, name="settings_form")
async def settings_form(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    saved: str = "",
):
    _require_admin(current_user)
    settings = _get_or_create_settings(db)
    return templates.TemplateResponse("settings/form.html", {
        "request":      request,
        "current_user": current_user,
        "settings":     settings,
        "page_title":   "Sistem Ayarları",
        "saved":        saved == "1",
    })


@router.post("", name="settings_save")
async def settings_save(
    request: Request,
    company_name:         str = Form(""),
    company_address:      str = Form(""),
    company_phone:        str = Form(""),
    company_email:        str = Form(""),
    logo_url:             str = Form(""),
    email_signature:      str = Form(""),
    rfq_subject_tpl:      str = Form("{event_name} Fiyat Teklifi - {request_no}"),
    currency:             str = Form("₺"),
    invoice_mudur_limit:  str = Form(""),   # boş = limitsiz (her zaman GM onayı)
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(current_user)
    s = _get_or_create_settings(db)
    s.company_name    = company_name.strip()
    s.company_address = company_address.strip()
    s.company_phone   = company_phone.strip()
    s.company_email   = company_email.strip()
    s.logo_url        = logo_url.strip()
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
