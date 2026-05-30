"""
Fatura onay limitleri yönetimi (admin paneli).
SystemSetting'taki invoice_approval_limit_* anahtarlarını TL bazında düzenler.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import require_admin
from database import get_db
from models import SystemSetting, User
from templates_config import templates

router = APIRouter(prefix="/admin/approval-limits", tags=["admin"])

ROLES = [
    ("kullanici",   "Kullanıcı (Satış Temsilcisi)"),
    ("mudur",       "Müdür"),
    ("genel_mudur", "Genel Müdür"),
]


def _get(db, role: str) -> str:
    row = db.query(SystemSetting).filter_by(
        key=f"invoice_approval_limit_{role}"
    ).first()
    return row.value if row else ""


@router.get("", response_class=HTMLResponse, name="approval_limits_get")
async def get_form(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    limits = {role: _get(db, role) for role, _ in ROLES}
    return templates.TemplateResponse(
        "admin/approval_limits.html",
        {
            "request": request, "current_user": current_user,
            "page_title": "Fatura Onay Limitleri",
            "roles": ROLES,
            "limits": limits,
        },
    )


@router.post("", name="approval_limits_save")
async def save_form(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    form = await request.form()
    for role, _ in ROLES:
        new_val = (form.get(f"limit_{role}") or "").strip().replace(",", "").replace(".", "")
        if not new_val or not new_val.isdigit():
            continue
        key = f"invoice_approval_limit_{role}"
        row = db.query(SystemSetting).filter_by(key=key).first()
        if row:
            row.value = new_val
        else:
            db.add(SystemSetting(key=key, value=new_val))
    db.commit()
    return RedirectResponse(url="/admin/approval-limits?saved=1", status_code=303)
