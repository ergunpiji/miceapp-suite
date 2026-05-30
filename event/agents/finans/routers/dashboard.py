"""Finans Ajanı — Dashboard"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import (
    ActualEntry, CashDayReport, CashEntry, CreditCard,
    CreditCardStatement, PaymentPlan, Project, SupplierAccount,
)
from templates_config import templates

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_class=HTMLResponse, name="dashboard")
async def dashboard(request: Request, db: Session = Depends(get_db)):
    today = date.today()

    # --- Projeler ---
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    active_projects = [p for p in projects if p.status == "aktif"]

    # --- Yaklaşan ödemeler (30 gün) ---
    upcoming_payments = (
        db.query(PaymentPlan)
        .filter(
            PaymentPlan.status == "bekliyor",
            PaymentPlan.due_date <= today + timedelta(days=30),
        )
        .order_by(PaymentPlan.due_date)
        .limit(10)
        .all()
    )
    overdue_payments = [p for p in upcoming_payments if p.due_date < today]

    # --- Toplam bekleyen ödeme tutarı ---
    pending_total = (
        db.query(func.sum(PaymentPlan.amount))
        .filter(PaymentPlan.status == "bekliyor")
        .scalar() or 0.0
    )

    # --- Bu ayki nakit akışı ---
    month_start = today.replace(day=1)
    month_in = (
        db.query(func.sum(CashEntry.amount))
        .filter(
            CashEntry.entry_type == "giris",
            CashEntry.entry_date >= month_start,
        )
        .scalar() or 0.0
    )
    month_out = (
        db.query(func.sum(CashEntry.amount))
        .filter(
            CashEntry.entry_type == "cikis",
            CashEntry.entry_date >= month_start,
        )
        .scalar() or 0.0
    )

    # --- Son gün sonu raporu ---
    last_day_report = (
        db.query(CashDayReport)
        .order_by(CashDayReport.report_date.desc())
        .first()
    )
    cash_balance = last_day_report.closing_balance if last_day_report else 0.0

    # --- Vadesi geçmiş ekstre ---
    overdue_statements = (
        db.query(CreditCardStatement)
        .filter(
            CreditCardStatement.status != "odendi",
            CreditCardStatement.due_date < today,
        )
        .all()
    )
    overdue_cc_total = sum(s.remaining for s in overdue_statements)

    # --- Son 5 gerçekleşen gider ---
    recent_entries = (
        db.query(ActualEntry)
        .order_by(ActualEntry.entry_date.desc(), ActualEntry.created_at.desc())
        .limit(5)
        .all()
    )

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "active": "dashboard",
            "today": today,
            "active_projects": active_projects,
            "upcoming_payments": upcoming_payments,
            "overdue_count": len(overdue_payments),
            "pending_total": pending_total,
            "month_in": month_in,
            "month_out": month_out,
            "month_net": month_in - month_out,
            "cash_balance": cash_balance,
            "overdue_cc_total": overdue_cc_total,
            "overdue_statements": overdue_statements,
            "recent_entries": recent_entries,
        },
    )
