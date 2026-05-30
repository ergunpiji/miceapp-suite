"""
Avans Talep & Onay Sistemi
"""

import json
import os
from datetime import date, datetime
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user, get_company_id
from database import get_db
from email_helper import send_email, is_configured as smtp_configured
from models import Employee, EmployeeAdvance, Reference, User, CashBook, BankAccount
from notification_helper import notify
from templates_config import templates

router = APIRouter(prefix="/advances", tags=["advances"])

APPROVAL_STATUS_LABELS = {
    "talep":      ("Onay Bekliyor", "bg-warning text-dark"),
    "onaylandi":  ("Onaylandı",     "bg-success"),
    "reddedildi": ("Reddedildi",    "bg-danger"),
}

ADVANCE_TYPE_LABELS = {
    "maas": "Maaş Avansı",
    "is":   "İş Avansı",
}


def _my_employee(db: Session, user: User):
    """Giriş yapan kullanıcıya bağlı Employee kaydını döndürür."""
    return db.query(Employee).filter(Employee.user_id == user.id, Employee.active == True).first()  # noqa: E712


# ---------------------------------------------------------------------------
# Liste
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse, name="advance_list")
async def advance_list(
    request: Request,
    status_filter: str = "all",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    is_manager = current_user.is_admin or current_user.is_approver
    my_emp = _my_employee(db, current_user)

    q = db.query(EmployeeAdvance).filter(EmployeeAdvance.company_id == cid)
    if not is_manager:
        if not my_emp:
            # Bağlı çalışan yoksa boş sayfa
            return templates.TemplateResponse("advances/list.html", {
                "request": request, "current_user": current_user,
                "advances": [], "status_filter": status_filter,
                "is_manager": False, "no_employee": True,
                "approval_labels": APPROVAL_STATUS_LABELS,
                "type_labels": ADVANCE_TYPE_LABELS,
                "page_title": "Avans Taleplerim",
            })
        q = q.filter(EmployeeAdvance.employee_id == my_emp.id)
    else:
        if status_filter == "bekleyen":
            q = q.filter(EmployeeAdvance.approval_status == "talep")
        elif status_filter in ("onaylandi", "reddedildi"):
            q = q.filter(EmployeeAdvance.approval_status == status_filter)

    advances = q.order_by(EmployeeAdvance.id.desc()).all()

    pending_count = db.query(EmployeeAdvance).filter(
        EmployeeAdvance.approval_status == "talep",
        EmployeeAdvance.company_id == cid,
    ).count() if is_manager else 0

    return templates.TemplateResponse("advances/list.html", {
        "request": request, "current_user": current_user,
        "advances": advances, "status_filter": status_filter,
        "is_manager": is_manager, "no_employee": False,
        "pending_count": pending_count,
        "my_emp": my_emp,
        "approval_labels": APPROVAL_STATUS_LABELS,
        "type_labels": ADVANCE_TYPE_LABELS,
        "page_title": "Avans Talepleri" if is_manager else "Avans Taleplerim",
    })


# ---------------------------------------------------------------------------
# Yeni Talep
# ---------------------------------------------------------------------------

@router.get("/new", response_class=HTMLResponse, name="advance_new_get")
async def advance_new_get(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    is_manager = current_user.is_admin or current_user.is_approver
    my_emp = _my_employee(db, current_user)
    employees = db.query(Employee).filter(Employee.active == True, Employee.company_id == cid).order_by(Employee.name).all() if is_manager else []  # noqa: E712
    references = db.query(Reference).filter(Reference.status == "aktif", Reference.company_id == cid).order_by(Reference.ref_no).all()

    if not is_manager and not my_emp:
        return templates.TemplateResponse("advances/list.html", {
            "request": request, "current_user": current_user,
            "advances": [], "no_employee": True, "is_manager": False,
            "approval_labels": APPROVAL_STATUS_LABELS,
            "type_labels": ADVANCE_TYPE_LABELS,
            "page_title": "Avans Taleplerim",
        })

    return templates.TemplateResponse("advances/form.html", {
        "request": request, "current_user": current_user,
        "is_manager": is_manager, "my_emp": my_emp,
        "employees": employees, "references": references,
        "page_title": "Avans Talebi Oluştur",
    })


@router.post("/new", name="advance_new_post")
async def advance_new_post(
    employee_id: str = Form(None),
    advance_type: str = Form("maas"),
    amount: float = Form(...),
    reason: str = Form(""),
    ref_id: str = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    is_manager = current_user.is_admin or current_user.is_approver
    my_emp = _my_employee(db, current_user)

    if is_manager:
        emp_id = employee_id
    else:
        if not my_emp:
            raise HTTPException(status_code=403, detail="Bağlı çalışan profili yok.")
        emp_id = my_emp.id

    if not emp_id:
        raise HTTPException(status_code=400, detail="Çalışan seçilmedi.")

    adv = EmployeeAdvance(
        employee_id=emp_id,
        amount=amount,
        advance_date=None,       # ödeme yapılınca set edilir
        reason=reason.strip() or None,
        advance_type=advance_type,
        ref_id=ref_id if advance_type == "is" else None,
        approval_status="onaylandi" if is_manager else "talep",
        requested_by=current_user.id,
        approved_by_id=current_user.id if is_manager else None,
        approved_at=datetime.utcnow() if is_manager else None,
        status="open",
        company_id=cid,
    )
    db.add(adv)
    db.commit()
    return RedirectResponse(url="/advances", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Onayla / Reddet
# ---------------------------------------------------------------------------

@router.post("/{advance_id}/approve", name="advance_approve")
async def advance_approve(
    advance_id: str,
    approval_note: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    if not (current_user.is_admin or current_user.is_approver):
        raise HTTPException(status_code=403)
    adv = db.query(EmployeeAdvance).filter(
        EmployeeAdvance.id == advance_id, EmployeeAdvance.company_id == cid,
    ).first()
    if not adv or adv.approval_status != "talep":
        raise HTTPException(status_code=404)
    adv.approval_status = "onaylandi"
    adv.approved_by_id = current_user.id
    adv.approved_at = datetime.utcnow()
    adv.approval_note = approval_note.strip() or None
    notify(db, adv.employee.user_id if adv.employee else None,
           title="Avans talebiniz onaylandı",
           message=f"{current_user.name} avans talebinizi onayladı.",
           link=f"/advances/{advance_id}", notif_type="success", ref_id=advance_id)
    if smtp_configured() and adv.employee:
        emp_user = db.query(User).filter(User.id == adv.employee.user_id).first() if adv.employee.user_id else None
        if emp_user and emp_user.email:
            app_url = os.environ.get("APP_URL", "")
            send_email(
                emp_user.email,
                "Avans Talebiniz Onaylandı",
                f"<p>Sayın {emp_user.name},</p>"
                f"<p>Avans talebiniz onaylanmıştır.</p>"
                f"<p>Tutar: <b>₺{adv.amount:,.2f}</b></p>"
                + (f"<p>Not: {adv.approval_note}</p>" if adv.approval_note else "")
                + (f"<p><a href='{app_url}/advances/{advance_id}'>Detayı görüntüle</a></p>" if app_url else ""),
            )
    db.commit()
    return RedirectResponse(url="/advances?status_filter=bekleyen", status_code=status.HTTP_302_FOUND)


@router.post("/{advance_id}/reject", name="advance_reject")
async def advance_reject(
    advance_id: str,
    approval_note: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    if not (current_user.is_admin or current_user.is_approver):
        raise HTTPException(status_code=403)
    adv = db.query(EmployeeAdvance).filter(
        EmployeeAdvance.id == advance_id, EmployeeAdvance.company_id == cid,
    ).first()
    if not adv or adv.approval_status != "talep":
        raise HTTPException(status_code=404)
    adv.approval_status = "reddedildi"
    adv.approved_by_id = current_user.id
    adv.approved_at = datetime.utcnow()
    adv.approval_note = approval_note.strip() or None
    notify(db, adv.employee.user_id if adv.employee else None,
           title="Avans talebiniz reddedildi",
           message=f"{current_user.name} talebinizi reddetti." + (f" Not: {approval_note.strip()}" if approval_note.strip() else ""),
           link=f"/advances/{advance_id}", notif_type="danger", ref_id=advance_id)
    if smtp_configured() and adv.employee:
        emp_user = db.query(User).filter(User.id == adv.employee.user_id).first() if adv.employee.user_id else None
        if emp_user and emp_user.email:
            app_url = os.environ.get("APP_URL", "")
            send_email(
                emp_user.email,
                "Avans Talebiniz Reddedildi",
                f"<p>Sayın {emp_user.name},</p>"
                f"<p>Avans talebiniz reddedilmiştir.</p>"
                f"<p>Tutar: <b>₺{adv.amount:,.2f}</b></p>"
                + (f"<p>Red gerekçesi: {approval_note.strip()}</p>" if approval_note.strip() else "")
                + (f"<p><a href='{app_url}/advances/{advance_id}'>Detayı görüntüle</a></p>" if app_url else ""),
            )
    db.commit()
    return RedirectResponse(url="/advances?status_filter=bekleyen", status_code=status.HTTP_302_FOUND)
