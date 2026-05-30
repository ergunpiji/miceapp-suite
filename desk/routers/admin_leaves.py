"""
Admin — İzin türü ve resmi tatil yönetimi
"""

from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from typing import Optional

from auth import require_admin, get_current_user
from database import get_db
from models import LeaveType, PublicHoliday, User
from templates_config import templates

router = APIRouter(prefix="/admin/leaves", tags=["admin_leaves"])


# ---------------------------------------------------------------------------
# İzin Türleri
# ---------------------------------------------------------------------------

@router.get("/types", response_class=HTMLResponse, name="admin_leave_types")
async def leave_types_list(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    types = db.query(LeaveType).order_by(LeaveType.sort_order, LeaveType.name).all()
    return templates.TemplateResponse(
        "admin/leave_types.html",
        {"request": request, "current_user": current_user,
         "types": types, "page_title": "İzin Türleri"},
    )


@router.post("/types/new", name="admin_leave_type_new")
async def leave_type_new(
    name: str = Form(...),
    is_paid: str = Form("1"),
    requires_balance: str = Form("0"),
    requires_report: str = Form("0"),
    default_days: str = Form(""),
    color: str = Form("#3b82f6"),
    sort_order: int = Form(99),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    import re, uuid
    code = "custom_" + re.sub(r"[^a-z0-9]", "_", name.lower().strip())[:20] + "_" + uuid.uuid4().hex[:4]
    db.add(LeaveType(
        code=code, name=name.strip(),
        is_paid=(is_paid == "1"),
        requires_balance=(requires_balance == "1"),
        requires_report=(requires_report == "1"),
        default_days=float(default_days) if default_days.strip() else None,
        color=color, sort_order=sort_order, active=True,
    ))
    db.commit()
    return RedirectResponse(url="/admin/leaves/types", status_code=status.HTTP_302_FOUND)


@router.post("/types/{lt_id}/edit", name="admin_leave_type_edit")
async def leave_type_edit(
    lt_id: str,
    name: str = Form(...),
    is_paid: str = Form("1"),
    requires_balance: str = Form("0"),
    requires_report: str = Form("0"),
    default_days: str = Form(""),
    color: str = Form("#3b82f6"),
    sort_order: int = Form(99),
    active: str = Form("1"),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    lt = db.query(LeaveType).get(lt_id)
    if not lt:
        raise HTTPException(status_code=404)
    lt.name = name.strip()
    lt.is_paid = (is_paid == "1")
    lt.requires_balance = (requires_balance == "1")
    lt.requires_report = (requires_report == "1")
    lt.default_days = float(default_days) if default_days.strip() else None
    lt.color = color
    lt.sort_order = sort_order
    lt.active = (active == "1")
    db.commit()
    return RedirectResponse(url="/admin/leaves/types", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Resmi Tatiller
# ---------------------------------------------------------------------------

@router.get("/holidays", response_class=HTMLResponse, name="admin_holidays")
async def holidays_list(
    request: Request,
    year: int = 0,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not year:
        year = date.today().year
    holidays = (
        db.query(PublicHoliday)
        .filter(PublicHoliday.date >= date(year, 1, 1), PublicHoliday.date <= date(year, 12, 31))
        .order_by(PublicHoliday.date)
        .all()
    )
    return templates.TemplateResponse(
        "admin/public_holidays.html",
        {"request": request, "current_user": current_user,
         "holidays": holidays, "year": year,
         "page_title": f"{year} Resmi Tatiller"},
    )


@router.post("/holidays/new", name="admin_holiday_new")
async def holiday_new(
    hdate: str = Form(...),
    name: str = Form(...),
    is_half: str = Form("0"),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    d = date.fromisoformat(hdate)
    existing = db.query(PublicHoliday).filter_by(date=d).first()
    if existing:
        existing.name = name.strip()
        existing.is_half = (is_half == "1")
    else:
        db.add(PublicHoliday(date=d, name=name.strip(), is_half=(is_half == "1")))
    db.commit()
    return RedirectResponse(url=f"/admin/leaves/holidays?year={d.year}", status_code=status.HTTP_302_FOUND)


@router.post("/holidays/{h_id}/delete", name="admin_holiday_delete")
async def holiday_delete(
    h_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    h = db.query(PublicHoliday).get(h_id)
    year = h.date.year if h else date.today().year
    if h:
        db.delete(h)
        db.commit()
    return RedirectResponse(url=f"/admin/leaves/holidays?year={year}", status_code=status.HTTP_302_FOUND)
