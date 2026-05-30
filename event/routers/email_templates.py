"""
E-dem — E-posta Şablon Yönetimi (Admin)
GET  /email-templates          → liste
GET  /email-templates/{id}     → düzenleme formu
POST /email-templates/{id}     → kaydet
POST /email-templates/{id}/toggle → aktif/pasif
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import EmailTemplate, EMAIL_TEMPLATE_VARS, _now
from templates_config import templates

router = APIRouter(prefix="/email-templates", tags=["email_templates"])


def _require_admin(current_user):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Bu sayfa yalnızca Admin'e özeldir.")


# ---------------------------------------------------------------------------
# Liste
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse, name="email_templates_list")
async def email_templates_list(
    request: Request,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(current_user)
    tpls = db.query(EmailTemplate).order_by(EmailTemplate.name).all()
    return templates.TemplateResponse("email_templates/list.html", {
        "request":      request,
        "current_user": current_user,
        "page_title":   "E-posta Şablonları",
        "tpls":         tpls,
    })


# ---------------------------------------------------------------------------
# Düzenleme formu
# ---------------------------------------------------------------------------

@router.get("/{tpl_id}", response_class=HTMLResponse, name="email_templates_edit_form")
async def email_templates_edit_form(
    tpl_id: str,
    request: Request,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(current_user)
    tpl = db.query(EmailTemplate).filter(EmailTemplate.id == tpl_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="Şablon bulunamadı.")
    return templates.TemplateResponse("email_templates/form.html", {
        "request":      request,
        "current_user": current_user,
        "page_title":   f"Şablon Düzenle — {tpl.name}",
        "tpl":          tpl,
        "vars":         EMAIL_TEMPLATE_VARS,
    })


# ---------------------------------------------------------------------------
# Kaydet
# ---------------------------------------------------------------------------

@router.post("/{tpl_id}", name="email_templates_update")
async def email_templates_update(
    tpl_id: str,
    request: Request,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
    name:        str = Form(...),
    description: str = Form(""),
    subject_tpl: str = Form(...),
    body_tpl:    str = Form(...),
):
    _require_admin(current_user)
    tpl = db.query(EmailTemplate).filter(EmailTemplate.id == tpl_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="Şablon bulunamadı.")

    tpl.name        = name.strip()
    tpl.description = description.strip()
    tpl.subject_tpl = subject_tpl.strip()
    tpl.body_tpl    = body_tpl  # boşlukları koru (multiline)
    tpl.updated_at  = _now()
    db.commit()
    return RedirectResponse(url="/email-templates?saved=1", status_code=303)


# ---------------------------------------------------------------------------
# Aktif / Pasif toggle
# ---------------------------------------------------------------------------

@router.post("/{tpl_id}/toggle", name="email_templates_toggle")
async def email_templates_toggle(
    tpl_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(current_user)
    tpl = db.query(EmailTemplate).filter(EmailTemplate.id == tpl_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="Şablon bulunamadı.")
    tpl.active     = not tpl.active
    tpl.updated_at = _now()
    db.commit()
    return RedirectResponse(url="/email-templates", status_code=303)
