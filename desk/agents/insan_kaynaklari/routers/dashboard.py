"""HR Ajanı — Dashboard."""
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import (
    AdvanceRequest, Employee, HRUser, LeaveRequest, Notification, OvertimeRecord, PayrollRecord,
)
from templates_config import templates

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_class=HTMLResponse, name="dashboard")
async def dashboard(
    request: Request,
    current_user: HRUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    today = date.today()

    # Bildirim sayısı (okunmamış)
    unread_count = (
        db.query(func.count(Notification.id))
        .filter(Notification.user_id == current_user.id, Notification.is_read == False)
        .scalar() or 0
    )

    if current_user.role in ("hr_admin", "hr_manager"):
        # --- Genel istatistikler ---
        total_employees = db.query(func.count(Employee.id)).filter(Employee.status == "aktif").scalar() or 0

        pending_leaves = (
            db.query(func.count(LeaveRequest.id))
            .filter(LeaveRequest.status == "beklemede")
            .scalar() or 0
        )
        pending_overtime = (
            db.query(func.count(OvertimeRecord.id))
            .filter(OvertimeRecord.status == "beklemede")
            .scalar() or 0
        )
        pending_advances = (
            db.query(func.count(AdvanceRequest.id))
            .filter(AdvanceRequest.status == "beklemede")
            .scalar() or 0
        )

        current_month = today.month
        current_year = today.year
        draft_payrolls = (
            db.query(func.count(PayrollRecord.id))
            .filter(
                PayrollRecord.period_year == current_year,
                PayrollRecord.period_month == current_month,
                PayrollRecord.status == "taslak",
            )
            .scalar() or 0
        )

        # Son bekleyen avans talepleri
        recent_advances = (
            db.query(AdvanceRequest)
            .filter(AdvanceRequest.status == "beklemede")
            .order_by(AdvanceRequest.request_date.desc())
            .limit(5)
            .all()
        )

        # Son bekleyen izin talepleri
        recent_leave_requests = (
            db.query(LeaveRequest)
            .filter(LeaveRequest.status == "beklemede")
            .order_by(LeaveRequest.created_at.desc())
            .limit(8)
            .all()
        )

        # Son bekleyen overtime
        recent_overtime = (
            db.query(OvertimeRecord)
            .filter(OvertimeRecord.status == "beklemede")
            .order_by(OvertimeRecord.created_at.desc())
            .limit(5)
            .all()
        )

        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "active": "dashboard",
                "user": current_user,
                "today": today,
                "unread_count": unread_count,
                "total_employees": total_employees,
                "pending_leaves": pending_leaves,
                "pending_overtime": pending_overtime,
                "pending_advances": pending_advances,
                "draft_payrolls": draft_payrolls,
                "recent_leave_requests": recent_leave_requests,
                "recent_overtime": recent_overtime,
                "recent_advances": recent_advances,
            },
        )
    else:
        # Çalışan dashboard'u
        emp = current_user.employee
        from models import LeaveBalance, MealCard, FlexibleBenefit, AdvanceRequest as AR

        leave_balance = None
        if emp:
            leave_balance = (
                db.query(LeaveBalance)
                .filter(LeaveBalance.employee_id == emp.id, LeaveBalance.year == today.year)
                .first()
            )

        my_leave_requests = (
            db.query(LeaveRequest)
            .filter(LeaveRequest.employee_id == emp.id if emp else False)
            .order_by(LeaveRequest.created_at.desc())
            .limit(5)
            .all()
        ) if emp else []

        last_payroll = (
            db.query(PayrollRecord)
            .filter(PayrollRecord.employee_id == emp.id if emp else False)
            .filter(PayrollRecord.status.in_(["onaylandi", "odendi"]))
            .order_by(PayrollRecord.period_year.desc(), PayrollRecord.period_month.desc())
            .first()
        ) if emp else None

        flex_benefit = (
            db.query(FlexibleBenefit)
            .filter(FlexibleBenefit.employee_id == emp.id if emp else False, FlexibleBenefit.year == today.year)
            .first()
        ) if emp else None

        my_advances = (
            db.query(AR)
            .filter(AR.employee_id == emp.id)
            .order_by(AR.request_date.desc())
            .limit(5)
            .all()
        ) if emp else []

        return templates.TemplateResponse(
            "dashboard_employee.html",
            {
                "request": request,
                "active": "dashboard",
                "user": current_user,
                "today": today,
                "unread_count": unread_count,
                "employee": emp,
                "leave_balance": leave_balance,
                "my_leave_requests": my_leave_requests,
                "last_payroll": last_payroll,
                "flex_benefit": flex_benefit,
                "my_advances": my_advances,
            },
        )
