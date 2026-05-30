"""
İzin Yönetimi — çalışan talepleri, onay akışı, bakiye, takvim
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user, get_company_id
from database import get_db
from models import (
    Employee, LeaveBalance, LeaveRequest, LeaveType,
    PublicHoliday, User, LEAVE_STATUS_LABELS,
)
from notification_helper import notify
from templates_config import templates

router = APIRouter(prefix="/leaves", tags=["leaves"])

_TR_MONTHS = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------

def _get_employee(db: Session, user: User) -> Optional[Employee]:
    """Kullanıcıya bağlı çalışan kaydı."""
    return db.query(Employee).filter(Employee.user_id == user.id, Employee.active == True).first()  # noqa: E712


def _working_days(start: date, end: date, db: Session) -> float:
    """start–end arası iş günü sayısı (hafta sonu + resmi tatil hariç)."""
    if start > end:
        return 0.0
    holidays = {
        h.date for h in db.query(PublicHoliday).filter(
            PublicHoliday.date >= start, PublicHoliday.date <= end,
            PublicHoliday.is_half == False,  # noqa: E712
        ).all()
    }
    half_holidays = {
        h.date for h in db.query(PublicHoliday).filter(
            PublicHoliday.date >= start, PublicHoliday.date <= end,
            PublicHoliday.is_half == True,  # noqa: E712
        ).all()
    }
    days = 0.0
    cur = start
    while cur <= end:
        if cur.weekday() < 5:  # Pazartesi-Cuma
            if cur in holidays:
                pass
            elif cur in half_holidays:
                days += 0.5
            else:
                days += 1.0
        cur += timedelta(days=1)
    return days


def _active_balance(db: Session, employee_id: str, leave_type_id: str, ref_date: date) -> Optional[LeaveBalance]:
    """Verilen tarihi kapsayan bakiye kaydı."""
    return db.query(LeaveBalance).filter(
        LeaveBalance.employee_id == employee_id,
        LeaveBalance.leave_type_id == leave_type_id,
        LeaveBalance.period_start <= ref_date,
        LeaveBalance.period_end >= ref_date,
    ).first()


def _team_employee_ids(db: Session, manager_user_id: str) -> list[int]:
    """Müdürün ekibindeki çalışan id'leri."""
    team_users = db.query(User).filter(User.manager_id == manager_user_id, User.active == True).all()  # noqa: E712
    ids = []
    for u in team_users:
        emp = db.query(Employee).filter(Employee.user_id == u.id).first()
        if emp:
            ids.append(emp.id)
    return ids


def _check_overlap(
    db: Session, employee_id: str, start: date, end: date,
    exclude_id: str | None = None,
) -> LeaveRequest | None:
    """Çakışan aktif izin talebi varsa döndürür, yoksa None."""
    q = db.query(LeaveRequest).filter(
        LeaveRequest.employee_id == employee_id,
        LeaveRequest.status.in_(["talep", "mudur_onayladi", "onaylandi"]),
        LeaveRequest.start_date <= end,
        LeaveRequest.end_date >= start,
    )
    if exclude_id:
        q = q.filter(LeaveRequest.id != exclude_id)
    return q.first()


def _approval_context(user: User, leave: LeaveRequest, db: Session) -> dict:
    """Şablon için onay yetkisi bilgileri."""
    creator_user = db.query(User).get(leave.requested_by)
    is_gm = user.has_role_min("genel_mudur")
    is_mudur = user.role == "mudur"
    is_team_manager = (
        is_mudur and creator_user and creator_user.manager_id == user.id
    )
    can_approve_first  = is_team_manager and leave.status == "talep"
    can_approve_final  = is_gm and leave.status in ("talep", "mudur_onayladi")
    can_reject         = (is_team_manager and leave.status == "talep") or \
                         (is_gm and leave.status in ("talep", "mudur_onayladi"))
    return {
        "can_approve_first": can_approve_first,
        "can_approve_final": can_approve_final,
        "can_reject": can_reject,
    }


# ---------------------------------------------------------------------------
# Liste — kendi izinlerim
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse, name="leaves_list")
async def leaves_list(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    employee = _get_employee(db, current_user)
    my_requests = []
    balances = []
    if employee:
        my_requests = (
            db.query(LeaveRequest)
            .filter(LeaveRequest.employee_id == employee.id, LeaveRequest.company_id == cid)
            .order_by(LeaveRequest.created_at.desc())
            .all()
        )
        today = date.today()
        leave_types = db.query(LeaveType).filter(
            LeaveType.active == True, LeaveType.requires_balance == True  # noqa: E712
        ).order_by(LeaveType.sort_order).all()
        for lt in leave_types:
            bal = _active_balance(db, employee.id, lt.id, today)
            balances.append({"type": lt, "balance": bal})

    return templates.TemplateResponse(
        "leaves/list.html",
        {
            "request": request, "current_user": current_user,
            "employee": employee, "my_requests": my_requests,
            "balances": balances, "status_labels": LEAVE_STATUS_LABELS,
            "page_title": "İzinlerim",
        },
    )


# ---------------------------------------------------------------------------
# Yeni talep
# ---------------------------------------------------------------------------

@router.get("/new", response_class=HTMLResponse, name="leave_new_get")
async def leave_new_get(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    employee = _get_employee(db, current_user)
    if not employee:
        return RedirectResponse(url="/leaves?error=no_employee", status_code=302)
    leave_types = db.query(LeaveType).filter(LeaveType.active == True).order_by(LeaveType.sort_order).all()  # noqa: E712
    today = date.today()
    balances = {}
    for lt in leave_types:
        if lt.requires_balance:
            bal = _active_balance(db, employee.id, lt.id, today)
            if bal:
                balances[lt.id] = bal
    return templates.TemplateResponse(
        "leaves/form.html",
        {
            "request": request, "current_user": current_user,
            "employee": employee, "leave_types": leave_types,
            "balances": balances,
            "today": today.isoformat(), "leave": None,
            "page_title": "Yeni İzin Talebi",
        },
    )


@router.post("/new", name="leave_new_post")
async def leave_new_post(
    request: Request,
    leave_type_id: str = Form(...),
    start_date: str = Form(...),
    return_date: str = Form(""),
    half_day: str = Form("0"),
    half_day_period: str = Form(""),
    has_report: str = Form("0"),
    reason: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    employee = _get_employee(db, current_user)
    if not employee:
        raise HTTPException(status_code=400, detail="Çalışan kaydı bulunamadı.")
    lt = db.query(LeaveType).get(leave_type_id)
    if not lt:
        raise HTTPException(status_code=400, detail="Geçersiz izin türü.")

    is_half = (half_day == "1")
    sdate = date.fromisoformat(start_date)

    if is_half:
        edate = sdate
        total = 0.5
    else:
        # return_date = işe dönüş tarihi → son izin günü = return_date - 1 gün
        rdate = date.fromisoformat(return_date) if return_date else sdate + timedelta(days=1)
        edate = rdate - timedelta(days=1)
        if edate < sdate:
            edate = sdate
        total = _working_days(sdate, edate, db)

    if total <= 0:
        raise HTTPException(status_code=400, detail="Geçerli iş günü bulunamadı.")

    # Çakışma kontrolü
    conflict = _check_overlap(db, employee.id, sdate, edate)
    if conflict:
        leave_types = db.query(LeaveType).filter(LeaveType.active == True).order_by(LeaveType.sort_order).all()  # noqa: E712
        today = date.today()
        balances = {}
        for lt in leave_types:
            if lt.requires_balance:
                bal = _active_balance(db, employee.id, lt.id, today)
                if bal:
                    balances[lt.id] = bal
        from templates_config import templates as _tpl
        return _tpl.TemplateResponse(
            "leaves/form.html",
            {
                "request": request, "current_user": current_user,
                "employee": employee, "leave_types": leave_types,
                "balances": balances, "today": today.isoformat(), "leave": None,
                "page_title": "Yeni İzin Talebi",
                "error": (
                    f"Bu tarihler {conflict.start_date.strftime('%d.%m.%Y')}–"
                    f"{conflict.end_date.strftime('%d.%m.%Y')} arasındaki mevcut "
                    f"izin talebinizle çakışıyor."
                ),
            },
            status_code=400,
        )

    leave = LeaveRequest(
        employee_id=employee.id,
        leave_type_id=leave_type_id,
        start_date=sdate,
        end_date=edate,
        total_days=total,
        half_day=is_half,
        half_day_period=half_day_period if is_half and half_day_period else None,
        has_report=(has_report == "1"),
        reason=reason.strip() or None,
        status="talep",
        requested_by=current_user.id,
        payroll_period=sdate.strftime("%Y-%m") if not lt.is_paid else None,
        company_id=cid,
    )
    db.add(leave)
    db.commit()
    return RedirectResponse(url=f"/leaves/{leave.id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Ekip görünümü (müdür +)  ← BEFORE /{leave_id} to avoid route conflict
# ---------------------------------------------------------------------------

@router.get("/team/requests", response_class=HTMLResponse, name="leave_team")
async def leave_team(
    request: Request,
    status_filter: str = "pending",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    if not current_user.has_role_min("mudur"):
        raise HTTPException(status_code=403)

    is_gm = current_user.has_role_min("genel_mudur")
    if is_gm:
        q = db.query(LeaveRequest).filter(LeaveRequest.company_id == cid)
    else:
        team_ids = _team_employee_ids(db, current_user.id)
        q = db.query(LeaveRequest).filter(LeaveRequest.employee_id.in_(team_ids), LeaveRequest.company_id == cid)

    if status_filter == "pending":
        q = q.filter(LeaveRequest.status.in_(["talep", "mudur_onayladi"]))
    elif status_filter != "all":
        q = q.filter(LeaveRequest.status == status_filter)

    requests_list = q.order_by(LeaveRequest.created_at.desc()).all()
    return templates.TemplateResponse(
        "leaves/team.html",
        {
            "request": request, "current_user": current_user,
            "requests_list": requests_list, "status_filter": status_filter,
            "status_labels": LEAVE_STATUS_LABELS,
            "page_title": "Ekip İzin Talepleri",
        },
    )


# ---------------------------------------------------------------------------
# Takvim  ← BEFORE /{leave_id} to avoid route conflict
# ---------------------------------------------------------------------------

@router.get("/calendar/view", response_class=HTMLResponse, name="leave_calendar")
async def leave_calendar(
    request: Request,
    year: int = 0,
    month: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    today = date.today()
    if not year:
        year = today.year
    if not month:
        month = today.month

    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])

    # Onaylı izinler bu ayda
    is_gm = current_user.has_role_min("genel_mudur")
    is_mudur = current_user.role == "mudur"
    employee = _get_employee(db, current_user)

    q = db.query(LeaveRequest).filter(
        LeaveRequest.status == "onaylandi",
        LeaveRequest.start_date <= last_day,
        LeaveRequest.end_date >= first_day,
        LeaveRequest.company_id == cid,
    )
    if is_gm:
        pass  # tümü
    elif is_mudur:
        team_ids = _team_employee_ids(db, current_user.id)
        if employee:
            team_ids.append(employee.id)
        q = q.filter(LeaveRequest.employee_id.in_(team_ids))
    else:
        if employee:
            q = q.filter(LeaveRequest.employee_id == employee.id)
        else:
            q = q.filter(False)

    leaves = q.all()

    # Resmi tatiller bu ay
    holidays = db.query(PublicHoliday).filter(
        PublicHoliday.date >= first_day, PublicHoliday.date <= last_day
    ).all()
    holiday_map = {h.date: h for h in holidays}

    # Takvim grid — hafta satırları
    cal = calendar.monthcalendar(year, month)

    prev_month = (month - 1) or 12
    prev_year  = year - 1 if month == 1 else year
    next_month = (month % 12) + 1
    next_year  = year + 1 if month == 12 else year

    leave_types = db.query(LeaveType).filter(LeaveType.active == True).all()  # noqa: E712
    lt_map = {lt.id: lt for lt in leave_types}

    return templates.TemplateResponse(
        "leaves/calendar.html",
        {
            "request": request, "current_user": current_user,
            "year": year, "month": month,
            "month_name": _TR_MONTHS[month - 1],
            "cal": cal, "leaves": leaves,
            "holiday_map": holiday_map, "lt_map": lt_map,
            "today": today,
            "prev_year": prev_year, "prev_month": prev_month,
            "next_year": next_year, "next_month": next_month,
            "page_title": f"İzin Takvimi — {_TR_MONTHS[month-1]} {year}",
        },
    )


# ---------------------------------------------------------------------------
# AJAX — gün sayısı hesabı  ← BEFORE /{leave_id} to avoid route conflict
# ---------------------------------------------------------------------------

@router.get("/calc-days")
async def calc_days(
    start: str,
    end: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from fastapi.responses import JSONResponse
    try:
        sdate = date.fromisoformat(start)
        edate = date.fromisoformat(end)
        days = _working_days(sdate, edate, db)
    except Exception:
        days = 0.0
    return JSONResponse({"days": days})


# ---------------------------------------------------------------------------
# Bakiye yönetimi (müdür +)  ← BEFORE /{leave_id} to avoid route conflict
# ---------------------------------------------------------------------------

@router.get("/balances/manage", response_class=HTMLResponse, name="leave_balances")
async def leave_balances(
    request: Request,
    employee_id: str = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    if not current_user.has_role_min("mudur"):
        raise HTTPException(status_code=403)

    is_gm = current_user.has_role_min("genel_mudur")
    if is_gm:
        employees = db.query(Employee).filter(Employee.active == True, Employee.company_id == cid).order_by(Employee.name).all()  # noqa: E712
    else:
        team_ids = _team_employee_ids(db, current_user.id)
        employees = db.query(Employee).filter(Employee.id.in_(team_ids), Employee.active == True, Employee.company_id == cid).all()  # noqa: E712

    selected_emp = None
    emp_balances = []
    if employee_id:
        selected_emp = db.query(Employee).filter(Employee.id == employee_id, Employee.company_id == cid).first()
        if selected_emp:
            emp_balances = (
                db.query(LeaveBalance)
                .filter(LeaveBalance.employee_id == employee_id)
                .order_by(LeaveBalance.period_start.desc())
                .all()
            )

    leave_types = db.query(LeaveType).filter(
        LeaveType.active == True, LeaveType.requires_balance == True  # noqa: E712
    ).order_by(LeaveType.sort_order).all()

    return templates.TemplateResponse(
        "leaves/balances.html",
        {
            "request": request, "current_user": current_user,
            "employees": employees, "selected_emp": selected_emp,
            "emp_balances": emp_balances, "leave_types": leave_types,
            "page_title": "İzin Bakiyeleri",
        },
    )


@router.post("/balances/manage", name="leave_balance_save")
async def leave_balance_save(
    employee_id: str = Form(...),
    leave_type_id: str = Form(...),
    period_start: str = Form(...),
    entitled_days: float = Form(...),
    carried_over_days: float = Form(0.0),
    notes: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.has_role_min("mudur"):
        raise HTTPException(status_code=403)
    pstart = date.fromisoformat(period_start)
    pend = date(pstart.year + 1, pstart.month, pstart.day) - timedelta(days=1)

    existing = db.query(LeaveBalance).filter_by(
        employee_id=employee_id,
        leave_type_id=leave_type_id,
        period_start=pstart,
    ).first()
    if existing:
        existing.entitled_days = entitled_days
        existing.carried_over_days = carried_over_days
        existing.notes = notes.strip() or None
    else:
        db.add(LeaveBalance(
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            period_start=pstart,
            period_end=pend,
            entitled_days=entitled_days,
            carried_over_days=carried_over_days,
            notes=notes.strip() or None,
            created_by=current_user.id,
        ))
    db.commit()
    return RedirectResponse(
        url=f"/leaves/balances/manage?employee_id={employee_id}&saved=1",
        status_code=status.HTTP_302_FOUND,
    )


# ---------------------------------------------------------------------------
# Detay  ← AFTER all specific /leaves/* routes
# ---------------------------------------------------------------------------

@router.get("/{leave_id}", response_class=HTMLResponse, name="leave_detail")
async def leave_detail(
    leave_id: str,
    request: Request,
    overlap_warn: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id, LeaveRequest.company_id == cid).first()
    if not leave:
        raise HTTPException(status_code=404)

    employee = db.query(Employee).get(leave.employee_id)
    creator_user = db.query(User).get(leave.requested_by)
    is_gm = current_user.has_role_min("genel_mudur")
    is_own = (employee and employee.user_id == current_user.id)
    is_team_mgr = (
        current_user.role == "mudur"
        and creator_user and creator_user.manager_id == current_user.id
    )
    if not (is_gm or is_own or is_team_mgr):
        raise HTTPException(status_code=403)

    ctx = _approval_context(current_user, leave, db)
    balance = None
    if leave.leave_type.requires_balance and employee:
        balance = _active_balance(db, employee.id, leave.leave_type_id, leave.start_date)

    # Aynı tarihlerdeki diğer izinler (takvim mini-görünüm için)
    concurrent = (
        db.query(LeaveRequest)
        .filter(
            LeaveRequest.id != leave.id,
            LeaveRequest.status.in_(["talep", "mudur_onayladi", "onaylandi"]),
            LeaveRequest.start_date <= leave.end_date,
            LeaveRequest.end_date >= leave.start_date,
        )
        .all()
    )

    return templates.TemplateResponse(
        "leaves/detail.html",
        {
            "request": request, "current_user": current_user,
            "leave": leave, "employee": employee,
            "balance": balance, "status_labels": LEAVE_STATUS_LABELS,
            "page_title": f"İzin Talebi — {leave.leave_type.name}",
            "overlap_warn": bool(overlap_warn),
            "concurrent": concurrent,
            **ctx,
        },
    )


# ---------------------------------------------------------------------------
# Onayla (müdür birinci kademe)
# ---------------------------------------------------------------------------

@router.post("/{leave_id}/approve-first", name="leave_approve_first")
async def leave_approve_first(
    leave_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id, LeaveRequest.company_id == cid).first()
    if not leave or leave.status != "talep":
        raise HTTPException(status_code=400)
    creator_user = db.query(User).get(leave.requested_by)
    if not (current_user.role == "mudur" and creator_user and creator_user.manager_id == current_user.id):
        raise HTTPException(status_code=403)
    conflict = _check_overlap(db, leave.employee_id, leave.start_date, leave.end_date, exclude_id=leave_id)
    if conflict:
        return RedirectResponse(
            url=f"/leaves/{leave_id}?overlap_warn=1",
            status_code=status.HTTP_302_FOUND,
        )
    leave.status = "mudur_onayladi"
    leave.manager_approved_by = current_user.id
    leave.manager_approved_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(url=f"/leaves/{leave_id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Onayla (GM nihai)
# ---------------------------------------------------------------------------

@router.post("/{leave_id}/approve", name="leave_approve")
async def leave_approve(
    leave_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    if not current_user.has_role_min("genel_mudur"):
        raise HTTPException(status_code=403)
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id, LeaveRequest.company_id == cid).first()
    if not leave or leave.status not in ("talep", "mudur_onayladi"):
        raise HTTPException(status_code=400)
    conflict = _check_overlap(db, leave.employee_id, leave.start_date, leave.end_date, exclude_id=leave_id)
    if conflict:
        return RedirectResponse(
            url=f"/leaves/{leave_id}?overlap_warn=1",
            status_code=status.HTTP_302_FOUND,
        )
    leave.status = "onaylandi"
    leave.final_approved_by = current_user.id
    leave.final_approved_at = datetime.utcnow()
    notify(db, leave.requested_by,
           title="İzin talebiniz onaylandı",
           message=f"{current_user.name} izin talebinizi onayladı.",
           link=f"/leaves/{leave_id}", notif_type="success", ref_id=leave_id)
    db.commit()
    return RedirectResponse(url=f"/leaves/{leave_id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Reddet
# ---------------------------------------------------------------------------

@router.post("/{leave_id}/reject", name="leave_reject")
async def leave_reject(
    leave_id: str,
    rejection_note: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id, LeaveRequest.company_id == cid).first()
    if not leave or leave.status not in ("talep", "mudur_onayladi"):
        raise HTTPException(status_code=400)
    creator_user = db.query(User).get(leave.requested_by)
    is_gm = current_user.has_role_min("genel_mudur")
    is_team_mgr = (
        current_user.role == "mudur"
        and creator_user and creator_user.manager_id == current_user.id
        and leave.status == "talep"
    )
    if not (is_gm or is_team_mgr):
        raise HTTPException(status_code=403)
    leave.status = "reddedildi"
    leave.rejection_note = rejection_note.strip() or None
    leave.final_approved_by = current_user.id
    leave.final_approved_at = datetime.utcnow()
    notify(db, leave.requested_by,
           title="İzin talebiniz reddedildi",
           message=f"{current_user.name} izin talebinizi reddetti." + (f" Not: {rejection_note.strip()}" if rejection_note.strip() else ""),
           link=f"/leaves/{leave_id}", notif_type="danger", ref_id=leave_id)
    db.commit()
    return RedirectResponse(url=f"/leaves/{leave_id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# İptal (talep eden)
# ---------------------------------------------------------------------------

@router.post("/{leave_id}/cancel", name="leave_cancel")
async def leave_cancel(
    leave_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    leave = db.query(LeaveRequest).filter(LeaveRequest.id == leave_id, LeaveRequest.company_id == cid).first()
    if not leave:
        raise HTTPException(status_code=404)
    employee = db.query(Employee).get(leave.employee_id)
    is_own = employee and employee.user_id == current_user.id
    is_admin = current_user.has_role_min("admin")
    if not (is_own or is_admin):
        raise HTTPException(status_code=403)
    if leave.status not in ("talep", "mudur_onayladi"):
        raise HTTPException(status_code=400, detail="Bu talep iptal edilemez.")
    leave.status = "iptal"
    db.commit()
    return RedirectResponse(url="/leaves", status_code=status.HTTP_302_FOUND)
