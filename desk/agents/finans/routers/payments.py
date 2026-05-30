"""Finans Ajanı — Ödeme Planı & Nakit Akışı"""
from datetime import date, timedelta
from collections import defaultdict

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import (
    CashEntry, PaymentPlan, Project, SupplierAccount,
    PAYMENT_METHODS, PAYMENT_PLAN_STATUSES, PAYMENT_METHOD_LABELS,
)
from templates_config import templates

router = APIRouter(prefix="/payments", tags=["payments"])


# ---------------------------------------------------------------------------
# Ödeme planı listesi
# ---------------------------------------------------------------------------
@router.get("", response_class=HTMLResponse, name="payments_list")
async def payments_list(
    request: Request,
    status: str = "all",
    db: Session = Depends(get_db),
):
    today = date.today()
    q = db.query(PaymentPlan).order_by(PaymentPlan.due_date)
    if status != "all":
        q = q.filter(PaymentPlan.status == status)
    plans = q.all()

    # Nakit akışı özeti (gelecek 90 gün)
    future_end = today + timedelta(days=90)
    upcoming = [p for p in plans if p.status == "bekliyor" and today <= p.due_date <= future_end]

    # Haftalık gruplama
    weekly: dict[str, float] = defaultdict(float)
    for p in upcoming:
        week_start = p.due_date - timedelta(days=p.due_date.weekday())
        weekly[week_start.isoformat()] += p.amount

    # Cash inflow (kasa girişleri bu ay)
    month_start = today.replace(day=1)
    cash_in = (
        db.query(func.sum(CashEntry.amount))
        .filter(CashEntry.entry_type == "giris", CashEntry.entry_date >= month_start)
        .scalar() or 0.0
    )
    cash_out = (
        db.query(func.sum(CashEntry.amount))
        .filter(CashEntry.entry_type == "cikis", CashEntry.entry_date >= month_start)
        .scalar() or 0.0
    )

    projects = db.query(Project).order_by(Project.name).all()
    suppliers = db.query(SupplierAccount).filter(SupplierAccount.status == "aktif").order_by(SupplierAccount.name).all()

    return templates.TemplateResponse(
        request,
        "payments/list.html",
        {
            "active": "payments",
            "plans": plans,
            "status_filter": status,
            "statuses": PAYMENT_PLAN_STATUSES,
            "methods": PAYMENT_METHODS,
            "today": today,
            "weekly": dict(sorted(weekly.items())),
            "upcoming_total": sum(p.amount for p in upcoming),
            "cash_in": cash_in,
            "cash_out": cash_out,
            "projects": projects,
            "suppliers": suppliers,
        },
    )


# ---------------------------------------------------------------------------
# Yeni ödeme planı
# ---------------------------------------------------------------------------
@router.post("/add")
async def payment_add(
    description: str = Form(...),
    amount: float = Form(0.0),
    due_date: str = Form(...),
    project_id: str = Form(""),
    supplier_account_id: str = Form(""),
    payment_method: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    plan = PaymentPlan(
        description=description,
        amount=amount,
        due_date=date.fromisoformat(due_date),
        project_id=project_id or None,
        supplier_account_id=supplier_account_id or None,
        payment_method=payment_method or None,
        notes=notes or None,
    )
    db.add(plan)
    db.commit()
    return RedirectResponse(url="/payments", status_code=303)


# ---------------------------------------------------------------------------
# Ödeme durumu güncelle
# ---------------------------------------------------------------------------
@router.post("/{plan_id}/mark-paid")
async def mark_paid(
    plan_id: str,
    payment_date: str = Form(""),
    payment_method: str = Form(""),
    db: Session = Depends(get_db),
):
    plan = db.query(PaymentPlan).filter(PaymentPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404)
    plan.status = "odendi"
    plan.payment_date = date.fromisoformat(payment_date) if payment_date else date.today()
    if payment_method:
        plan.payment_method = payment_method
    db.commit()
    return RedirectResponse(url="/payments", status_code=303)


@router.post("/{plan_id}/cancel")
async def cancel_payment(plan_id: str, db: Session = Depends(get_db)):
    plan = db.query(PaymentPlan).filter(PaymentPlan.id == plan_id).first()
    if plan:
        plan.status = "iptal"
        db.commit()
    return RedirectResponse(url="/payments", status_code=303)


@router.post("/{plan_id}/delete")
async def delete_payment(plan_id: str, db: Session = Depends(get_db)):
    plan = db.query(PaymentPlan).filter(PaymentPlan.id == plan_id).first()
    if plan:
        db.delete(plan)
        db.commit()
    return RedirectResponse(url="/payments", status_code=303)


# ---------------------------------------------------------------------------
# Nakit akışı takvimi (JSON)
# ---------------------------------------------------------------------------
@router.get("/cashflow/json")
async def cashflow_json(
    days: int = 90,
    db: Session = Depends(get_db),
):
    today = date.today()
    end = today + timedelta(days=days)
    plans = (
        db.query(PaymentPlan)
        .filter(
            PaymentPlan.status == "bekliyor",
            PaymentPlan.due_date >= today,
            PaymentPlan.due_date <= end,
        )
        .order_by(PaymentPlan.due_date)
        .all()
    )
    cash_entries = (
        db.query(CashEntry)
        .filter(CashEntry.entry_date >= today, CashEntry.entry_date <= end)
        .order_by(CashEntry.entry_date)
        .all()
    )

    # Günlük nakit akışı
    daily: dict[str, dict] = defaultdict(lambda: {"out": 0.0, "in": 0.0})
    for p in plans:
        daily[p.due_date.isoformat()]["out"] += p.amount
    for e in cash_entries:
        key = "in" if e.entry_type == "giris" else "out"
        daily[e.entry_date.isoformat()][key] += e.amount

    return {"cashflow": dict(sorted(daily.items()))}
