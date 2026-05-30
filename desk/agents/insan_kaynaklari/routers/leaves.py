"""HR Ajanı — İzin Yönetimi."""
from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_current_user, require_hr_manager_or_admin
from database import get_db
from models import (
    LEAVE_STATUSES, LEAVE_TYPES,
    Employee, HRUser, LeaveBalance, LeaveRequest, Notification,
)
from routers.notifications import create_notification
from templates_config import templates

router = APIRouter(prefix="/leaves", tags=["leaves"])


def _calc_working_days(start: date, end: date) -> int:
    """Cumartesi/Pazar hariç iş günü sayısı."""
    days = 0
    current = start
    while current <= end:
        if current.weekday() < 5:  # 0=Pzt … 4=Cum
            days += 1
        from datetime import timedelta
        current = current + timedelta(days=1)
    return days


@router.get("", response_class=HTMLResponse)
async def list_leaves(
    request: Request,
    status: str = "",
    leave_type: str = "",
    current_user: HRUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    unread_count = db.query(func.count(Notification.id)).filter(
        Notification.user_id == current_user.id, Notification.is_read == False
    ).scalar() or 0

    query = db.query(LeaveRequest)
    if current_user.role == "employee" and current_user.employee:
        query = query.filter(LeaveRequest.employee_id == current_user.employee.id)
    if status:
        query = query.filter(LeaveRequest.status == status)
    if leave_type:
        query = query.filter(LeaveRequest.leave_type == leave_type)
    leaves = query.order_by(LeaveRequest.created_at.desc()).all()

    # Bakiye bilgisi (employee rolü için)
    leave_balance = None
    if current_user.role == "employee" and current_user.employee:
        leave_balance = (
            db.query(LeaveBalance)
            .filter(
                LeaveBalance.employee_id == current_user.employee.id,
                LeaveBalance.year == date.today().year,
            )
            .first()
        )

    return templates.TemplateResponse(
        "leaves/list.html",
        {
            "request": request, "active": "leaves", "user": current_user,
            "leaves": leaves, "status_filter": status, "leave_type_filter": leave_type,
            "leave_types": LEAVE_TYPES, "leave_statuses": LEAVE_STATUSES,
            "leave_balance": leave_balance, "unread_count": unread_count,
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def new_leave_form(
    request: Request,
    current_user: HRUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    unread_count = db.query(func.count(Notification.id)).filter(
        Notification.user_id == current_user.id, Notification.is_read == False
    ).scalar() or 0

    # Çalışan kendi adına, yönetici tüm çalışanlar adına açabilir
    employees = []
    if current_user.role in ("hr_admin", "hr_manager"):
        employees = db.query(Employee).filter(Employee.status == "aktif").order_by(Employee.first_name).all()

    leave_balance = None
    if current_user.employee:
        leave_balance = (
            db.query(LeaveBalance)
            .filter(
                LeaveBalance.employee_id == current_user.employee.id,
                LeaveBalance.year == date.today().year,
            )
            .first()
        )

    return templates.TemplateResponse(
        "leaves/form.html",
        {
            "request": request, "active": "leaves", "user": current_user,
            "leave_types": LEAVE_TYPES, "employees": employees,
            "leave_balance": leave_balance, "unread_count": unread_count, "error": None,
        },
    )


@router.post("/new")
async def create_leave(
    request: Request,
    employee_id: str = Form(""),
    leave_type: str = Form("yillik"),
    start_date: str = Form(...),
    end_date: str = Form(...),
    reason: str = Form(""),
    current_user: HRUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Çalışan rolü: sadece kendi adına
    if current_user.role == "employee":
        if not current_user.employee:
            raise HTTPException(status_code=400, detail="Çalışan profili bulunamadı")
        employee_id = current_user.employee.id

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if end < start:
        raise HTTPException(status_code=400, detail="Bitiş tarihi başlangıçtan önce olamaz")

    days = _calc_working_days(start, end)

    # Yıllık izin için bakiye kontrolü
    if leave_type == "yillik":
        balance = (
            db.query(LeaveBalance)
            .filter(LeaveBalance.employee_id == employee_id, LeaveBalance.year == start.year)
            .first()
        )
        if balance and balance.remaining_days < days:
            unread_count = db.query(func.count(Notification.id)).filter(
                Notification.user_id == current_user.id, Notification.is_read == False
            ).scalar() or 0
            employees = []
            if current_user.role in ("hr_admin", "hr_manager"):
                employees = db.query(Employee).filter(Employee.status == "aktif").all()
            return templates.TemplateResponse(
                "leaves/form.html",
                {"request": request, "active": "leaves", "user": current_user,
                 "leave_types": LEAVE_TYPES, "employees": employees,
                 "leave_balance": balance, "unread_count": unread_count,
                 "error": f"Yetersiz izin bakiyesi. Kalan: {balance.remaining_days} gün, Talep: {days} gün"},
                status_code=400,
            )

    leave = LeaveRequest(
        employee_id=employee_id,
        leave_type=leave_type,
        start_date=start,
        end_date=end,
        days=days,
        reason=reason or None,
        status="beklemede",
    )
    db.add(leave)
    db.flush()

    # Bakiyede pending güncelle
    if leave_type == "yillik":
        balance = db.query(LeaveBalance).filter(
            LeaveBalance.employee_id == employee_id, LeaveBalance.year == start.year
        ).first()
        if balance:
            balance.pending_days += days

    # Yöneticilere bildirim
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    managers = db.query(HRUser).filter(HRUser.role.in_(["hr_admin", "hr_manager"])).all()
    for mgr in managers:
        create_notification(
            db, mgr.id, "izin_talebi",
            f"Yeni İzin Talebi: {emp.full_name if emp else ''}",
            f"{leave.leave_type_label} — {start.strftime('%d.%m.%Y')} / {end.strftime('%d.%m.%Y')} ({days} gün)",
            ref_type="leave", ref_id=leave.id,
        )

    db.commit()
    return RedirectResponse(url="/leaves", status_code=302)


@router.get("/{leave_id}", response_class=HTMLResponse)
async def leave_detail(
    leave_id: str,
    request: Request,
    current_user: HRUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if not leave:
        raise HTTPException(status_code=404)
    if current_user.role == "employee":
        if not current_user.employee or current_user.employee.id != leave.employee_id:
            raise HTTPException(status_code=403)

    unread_count = db.query(func.count(Notification.id)).filter(
        Notification.user_id == current_user.id, Notification.is_read == False
    ).scalar() or 0

    return templates.TemplateResponse(
        "leaves/detail.html",
        {"request": request, "active": "leaves", "user": current_user,
         "leave": leave, "unread_count": unread_count},
    )


@router.post("/{leave_id}/approve")
async def approve_leave(
    leave_id: str,
    reviewer_note: str = Form(""),
    current_user: HRUser = Depends(require_hr_manager_or_admin),
    db: Session = Depends(get_db),
):
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if not leave or leave.status != "beklemede":
        raise HTTPException(status_code=400)

    leave.status = "onaylandi"
    leave.reviewed_by = current_user.id
    leave.reviewed_at = datetime.utcnow()
    leave.reviewer_note = reviewer_note or None

    # Bakiye güncelle
    if leave.leave_type == "yillik":
        balance = db.query(LeaveBalance).filter(
            LeaveBalance.employee_id == leave.employee_id,
            LeaveBalance.year == leave.start_date.year,
        ).first()
        if balance:
            balance.pending_days = max(0, balance.pending_days - leave.days)
            balance.used_days += leave.days

    # Çalışana bildirim
    emp = db.query(Employee).filter(Employee.id == leave.employee_id).first()
    if emp and emp.user:
        create_notification(
            db, emp.user.id, "izin_onay",
            "İzin Talebiniz Onaylandı",
            f"{leave.leave_type_label} ({leave.days} gün) onaylandı.",
            ref_type="leave", ref_id=leave.id,
        )

    db.commit()
    return RedirectResponse(url=f"/leaves/{leave_id}", status_code=302)


@router.post("/{leave_id}/reject")
async def reject_leave(
    leave_id: str,
    reviewer_note: str = Form(""),
    current_user: HRUser = Depends(require_hr_manager_or_admin),
    db: Session = Depends(get_db),
):
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if not leave or leave.status != "beklemede":
        raise HTTPException(status_code=400)

    leave.status = "reddedildi"
    leave.reviewed_by = current_user.id
    leave.reviewed_at = datetime.utcnow()
    leave.reviewer_note = reviewer_note or None

    # Pending geri al
    if leave.leave_type == "yillik":
        balance = db.query(LeaveBalance).filter(
            LeaveBalance.employee_id == leave.employee_id,
            LeaveBalance.year == leave.start_date.year,
        ).first()
        if balance:
            balance.pending_days = max(0, balance.pending_days - leave.days)

    # Çalışana bildirim
    emp = db.query(Employee).filter(Employee.id == leave.employee_id).first()
    if emp and emp.user:
        create_notification(
            db, emp.user.id, "izin_onay",
            "İzin Talebiniz Reddedildi",
            f"{leave.leave_type_label} talebi reddedildi. Not: {reviewer_note or '—'}",
            ref_type="leave", ref_id=leave.id,
        )

    db.commit()
    return RedirectResponse(url=f"/leaves/{leave_id}", status_code=302)


@router.post("/{leave_id}/cancel")
async def cancel_leave(
    leave_id: str,
    current_user: HRUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if not leave:
        raise HTTPException(status_code=404)
    # Sadece kendi talebi veya yönetici iptal edebilir
    if current_user.role == "employee":
        if not current_user.employee or current_user.employee.id != leave.employee_id:
            raise HTTPException(status_code=403)

    if leave.status not in ("beklemede", "onaylandi"):
        raise HTTPException(status_code=400)

    prev_status = leave.status
    leave.status = "iptal"

    # Bakiye geri al
    if leave.leave_type == "yillik":
        balance = db.query(LeaveBalance).filter(
            LeaveBalance.employee_id == leave.employee_id,
            LeaveBalance.year == leave.start_date.year,
        ).first()
        if balance:
            if prev_status == "beklemede":
                balance.pending_days = max(0, balance.pending_days - leave.days)
            elif prev_status == "onaylandi":
                balance.used_days = max(0, balance.used_days - leave.days)

    db.commit()
    return RedirectResponse(url="/leaves", status_code=302)
