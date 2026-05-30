"""HR Ajanı — Avans Yönetimi (Maaş Avansı / İş Avansı)."""
from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_current_user, require_hr_admin, require_hr_manager_or_admin
from database import get_db
from models import (
    ADVANCE_STATUSES, ADVANCE_TYPES, SALARY_ADVANCE_LIMIT_RATE,
    AdvanceRequest, Employee, HRUser, Notification,
)
from routers.notifications import create_notification
from templates_config import templates

router = APIRouter(prefix="/advances", tags=["advances"])


def _salary_advance_limit(employee: Employee) -> float:
    """Çalışanın kullanabileceği maaş avansı üst limiti."""
    return round(employee.gross_salary * SALARY_ADVANCE_LIMIT_RATE, 2)


def _active_salary_advances(db: Session, employee_id: str) -> float:
    """Henüz kapatılmamış maaş avansı toplamı (limit hesabı için)."""
    total = (
        db.query(func.sum(AdvanceRequest.amount))
        .filter(
            AdvanceRequest.employee_id == employee_id,
            AdvanceRequest.advance_type == "maas",
            AdvanceRequest.status.in_(["beklemede", "onaylandi", "odendi"]),
        )
        .scalar() or 0.0
    )
    repaid = (
        db.query(func.sum(AdvanceRequest.repaid_amount))
        .filter(
            AdvanceRequest.employee_id == employee_id,
            AdvanceRequest.advance_type == "maas",
            AdvanceRequest.status.in_(["onaylandi", "odendi"]),
        )
        .scalar() or 0.0
    )
    return max(0.0, total - repaid)


@router.get("", response_class=HTMLResponse)
async def list_advances(
    request: Request,
    advance_type: str = "",
    status: str = "",
    current_user: HRUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    unread_count = db.query(func.count(Notification.id)).filter(
        Notification.user_id == current_user.id, Notification.is_read == False
    ).scalar() or 0

    query = db.query(AdvanceRequest)
    if current_user.role == "employee" and current_user.employee:
        query = query.filter(AdvanceRequest.employee_id == current_user.employee.id)
    if advance_type:
        query = query.filter(AdvanceRequest.advance_type == advance_type)
    if status:
        query = query.filter(AdvanceRequest.status == status)
    advances = query.order_by(AdvanceRequest.created_at.desc()).all()

    # Çalışan için limit bilgisi
    salary_limit = None
    active_used = None
    available_limit = None
    if current_user.employee:
        salary_limit = _salary_advance_limit(current_user.employee)
        active_used = _active_salary_advances(db, current_user.employee.id)
        available_limit = max(0.0, salary_limit - active_used)

    return templates.TemplateResponse(
        "advances/list.html",
        {
            "request": request, "active": "advances", "user": current_user,
            "advances": advances, "advance_type_filter": advance_type, "status_filter": status,
            "advance_types": ADVANCE_TYPES, "advance_statuses": ADVANCE_STATUSES,
            "salary_limit": salary_limit, "active_used": active_used, "available_limit": available_limit,
            "SALARY_ADVANCE_LIMIT_RATE": SALARY_ADVANCE_LIMIT_RATE,
            "unread_count": unread_count,
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def new_advance_form(
    request: Request,
    advance_type: str = "maas",
    current_user: HRUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    unread_count = db.query(func.count(Notification.id)).filter(
        Notification.user_id == current_user.id, Notification.is_read == False
    ).scalar() or 0

    employees = []
    if current_user.role in ("hr_admin", "hr_manager"):
        employees = db.query(Employee).filter(Employee.status == "aktif").order_by(Employee.first_name).all()

    # Limit bilgisi (kendi adına açıyorsa)
    salary_limit = None
    available_limit = None
    if current_user.employee:
        salary_limit = _salary_advance_limit(current_user.employee)
        active_used = _active_salary_advances(db, current_user.employee.id)
        available_limit = max(0.0, salary_limit - active_used)

    return templates.TemplateResponse(
        "advances/form.html",
        {
            "request": request, "active": "advances", "user": current_user,
            "advance_types": ADVANCE_TYPES, "employees": employees,
            "preselected_type": advance_type,
            "salary_limit": salary_limit, "available_limit": available_limit,
            "SALARY_ADVANCE_LIMIT_RATE": SALARY_ADVANCE_LIMIT_RATE,
            "unread_count": unread_count, "error": None,
        },
    )


@router.post("/new")
async def create_advance(
    request: Request,
    employee_id: str = Form(""),
    advance_type: str = Form("maas"),
    amount: float = Form(...),
    reason: str = Form(""),
    needed_by: str = Form(""),
    repayment_months: int = Form(1),
    repayment_start_year: int = Form(0),
    repayment_start_month: int = Form(0),
    current_user: HRUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Çalışan rolü sadece kendi adına açabilir
    if current_user.role == "employee":
        if not current_user.employee:
            raise HTTPException(status_code=400, detail="Çalışan profili bulunamadı")
        employee_id = current_user.employee.id

    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Çalışan bulunamadı")

    unread_count = db.query(func.count(Notification.id)).filter(
        Notification.user_id == current_user.id, Notification.is_read == False
    ).scalar() or 0

    # Maaş avansı limit kontrolü
    if advance_type == "maas":
        salary_limit = _salary_advance_limit(emp)
        active_used = _active_salary_advances(db, employee_id)
        available = max(0.0, salary_limit - active_used)
        if amount > available:
            employees = []
            if current_user.role in ("hr_admin", "hr_manager"):
                employees = db.query(Employee).filter(Employee.status == "aktif").all()
            return templates.TemplateResponse(
                "advances/form.html",
                {
                    "request": request, "active": "advances", "user": current_user,
                    "advance_types": ADVANCE_TYPES, "employees": employees,
                    "preselected_type": advance_type,
                    "salary_limit": salary_limit, "available_limit": available,
                    "SALARY_ADVANCE_LIMIT_RATE": SALARY_ADVANCE_LIMIT_RATE,
                    "unread_count": unread_count,
                    "error": f"Talep tutarı mevcut limiti aşıyor. Kullanılabilir limit: ₺{available:,.2f}",
                },
                status_code=400,
            )

    advance = AdvanceRequest(
        employee_id=employee_id,
        advance_type=advance_type,
        amount=amount,
        reason=reason or None,
        request_date=date.today(),
        needed_by=date.fromisoformat(needed_by) if needed_by else None,
        status="beklemede",
        repayment_months=repayment_months if advance_type == "maas" else None,
        repayment_start_year=repayment_start_year if advance_type == "maas" and repayment_start_year else None,
        repayment_start_month=repayment_start_month if advance_type == "maas" and repayment_start_month else None,
    )
    db.add(advance)
    db.flush()

    # Yöneticilere bildirim
    adv_label = "Maaş Avansı" if advance_type == "maas" else "İş Avansı"
    managers = db.query(HRUser).filter(HRUser.role.in_(["hr_admin", "hr_manager"])).all()
    for mgr in managers:
        create_notification(
            db, mgr.id, "avans_talebi",
            f"Yeni {adv_label} Talebi: {emp.full_name}",
            f"₺{amount:,.2f} tutarında {adv_label} talebi",
            ref_type="advance", ref_id=advance.id,
        )

    db.commit()
    return RedirectResponse(url="/advances", status_code=302)


@router.get("/{advance_id}", response_class=HTMLResponse)
async def advance_detail(
    advance_id: str,
    request: Request,
    current_user: HRUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    adv = db.query(AdvanceRequest).filter(AdvanceRequest.id == advance_id).first()
    if not adv:
        raise HTTPException(status_code=404)
    if current_user.role == "employee":
        if not current_user.employee or current_user.employee.id != adv.employee_id:
            raise HTTPException(status_code=403)

    unread_count = db.query(func.count(Notification.id)).filter(
        Notification.user_id == current_user.id, Notification.is_read == False
    ).scalar() or 0

    today = date.today()
    return templates.TemplateResponse(
        "advances/detail.html",
        {
            "request": request, "active": "advances", "user": current_user,
            "advance": adv, "today": today, "unread_count": unread_count,
        },
    )


@router.post("/{advance_id}/approve")
async def approve_advance(
    advance_id: str,
    reviewer_note: str = Form(""),
    current_user: HRUser = Depends(require_hr_manager_or_admin),
    db: Session = Depends(get_db),
):
    adv = db.query(AdvanceRequest).filter(AdvanceRequest.id == advance_id).first()
    if not adv or adv.status != "beklemede":
        raise HTTPException(status_code=400)

    adv.status = "onaylandi"
    adv.reviewed_by = current_user.id
    adv.reviewed_at = datetime.utcnow()
    adv.reviewer_note = reviewer_note or None

    emp = db.query(Employee).filter(Employee.id == adv.employee_id).first()
    if emp and emp.user:
        adv_label = adv.advance_type_label
        create_notification(
            db, emp.user.id, "avans_onay",
            f"{adv_label} Talebiniz Onaylandı",
            f"₺{adv.amount:,.2f} tutarındaki {adv_label} talebiniz onaylandı.",
            ref_type="advance", ref_id=adv.id,
        )
    db.commit()
    return RedirectResponse(url=f"/advances/{advance_id}", status_code=302)


@router.post("/{advance_id}/reject")
async def reject_advance(
    advance_id: str,
    reviewer_note: str = Form(""),
    current_user: HRUser = Depends(require_hr_manager_or_admin),
    db: Session = Depends(get_db),
):
    adv = db.query(AdvanceRequest).filter(AdvanceRequest.id == advance_id).first()
    if not adv or adv.status != "beklemede":
        raise HTTPException(status_code=400)

    adv.status = "reddedildi"
    adv.reviewed_by = current_user.id
    adv.reviewed_at = datetime.utcnow()
    adv.reviewer_note = reviewer_note or None

    emp = db.query(Employee).filter(Employee.id == adv.employee_id).first()
    if emp and emp.user:
        create_notification(
            db, emp.user.id, "avans_onay",
            f"{adv.advance_type_label} Talebiniz Reddedildi",
            f"Not: {reviewer_note or '—'}",
            ref_type="advance", ref_id=adv.id,
        )
    db.commit()
    return RedirectResponse(url=f"/advances/{advance_id}", status_code=302)


@router.post("/{advance_id}/mark-paid")
async def mark_paid(
    advance_id: str,
    payment_date: str = Form(...),
    current_user: HRUser = Depends(require_hr_admin),
    db: Session = Depends(get_db),
):
    adv = db.query(AdvanceRequest).filter(AdvanceRequest.id == advance_id).first()
    if not adv or adv.status != "onaylandi":
        raise HTTPException(status_code=400)

    adv.status = "odendi"
    adv.payment_date = date.fromisoformat(payment_date)
    adv.paid_by = current_user.id
    adv.updated_at = datetime.utcnow()

    emp = db.query(Employee).filter(Employee.id == adv.employee_id).first()
    if emp and emp.user:
        create_notification(
            db, emp.user.id, "avans_odendi",
            f"{adv.advance_type_label} Ödendi",
            f"₺{adv.amount:,.2f} tutarındaki avansınız {adv.payment_date.strftime('%d.%m.%Y')} tarihinde ödendi.",
            ref_type="advance", ref_id=adv.id,
        )
    db.commit()
    return RedirectResponse(url=f"/advances/{advance_id}", status_code=302)


@router.post("/{advance_id}/repay")
async def record_repayment(
    advance_id: str,
    repayment_amount: float = Form(...),
    current_user: HRUser = Depends(require_hr_admin),
    db: Session = Depends(get_db),
):
    """Maaş avansı geri ödeme kaydı (bordrodan kesinti)."""
    adv = db.query(AdvanceRequest).filter(AdvanceRequest.id == advance_id).first()
    if not adv or adv.advance_type != "maas" or adv.status != "odendi":
        raise HTTPException(status_code=400)

    adv.repaid_amount = min(adv.amount, adv.repaid_amount + repayment_amount)
    if adv.repaid_amount >= adv.amount:
        adv.status = "kapandi"
        adv.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(url=f"/advances/{advance_id}", status_code=302)


@router.post("/{advance_id}/close")
async def close_advance(
    advance_id: str,
    closing_notes: str = Form(""),
    remaining_amount: float = Form(0.0),
    current_user: HRUser = Depends(require_hr_admin),
    db: Session = Depends(get_db),
):
    """İş avansını harcama belgesiyle kapat."""
    adv = db.query(AdvanceRequest).filter(AdvanceRequest.id == advance_id).first()
    if not adv or adv.advance_type != "is" or adv.status != "odendi":
        raise HTTPException(status_code=400)

    adv.status = "kapandi"
    adv.closed_at = datetime.utcnow()
    adv.closing_notes = closing_notes or None
    adv.remaining_amount = remaining_amount   # iade edilecek fark (pozitif: iade, negatif: ek ödeme)
    adv.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(url=f"/advances/{advance_id}", status_code=302)


@router.post("/{advance_id}/cancel")
async def cancel_advance(
    advance_id: str,
    current_user: HRUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    adv = db.query(AdvanceRequest).filter(AdvanceRequest.id == advance_id).first()
    if not adv:
        raise HTTPException(status_code=404)

    # Çalışan sadece kendi beklemede talebini iptal edebilir
    if current_user.role == "employee":
        if not current_user.employee or current_user.employee.id != adv.employee_id:
            raise HTTPException(status_code=403)
        if adv.status != "beklemede":
            raise HTTPException(status_code=400, detail="Sadece beklemede olan talepler iptal edilebilir")

    if adv.status in ("odendi", "kapandi"):
        raise HTTPException(status_code=400, detail="Ödenmiş veya kapatılmış avans iptal edilemez")

    adv.status = "iptal"
    adv.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(url="/advances", status_code=302)


@router.post("/{advance_id}/update-repayment")
async def update_repayment_plan(
    advance_id: str,
    repayment_months: int = Form(...),
    repayment_start_year: int = Form(...),
    repayment_start_month: int = Form(...),
    current_user: HRUser = Depends(require_hr_admin),
    db: Session = Depends(get_db),
):
    """Maaş avansı geri ödeme planını güncelle."""
    adv = db.query(AdvanceRequest).filter(AdvanceRequest.id == advance_id).first()
    if not adv or adv.advance_type != "maas":
        raise HTTPException(status_code=400)

    adv.repayment_months = repayment_months
    adv.repayment_start_year = repayment_start_year
    adv.repayment_start_month = repayment_start_month
    adv.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(url=f"/advances/{advance_id}", status_code=302)
