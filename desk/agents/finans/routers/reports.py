"""Finans Ajanı — Gelir/Gider Raporları"""
from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import (
    ActualEntry, BudgetLine, CashEntry, EFatura, Project,
    SupplierPayment, BUDGET_CATEGORY_LABELS,
)
from templates_config import templates

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("", response_class=HTMLResponse, name="reports")
async def reports(
    request: Request,
    year: int = 0,
    month: int = 0,
    db: Session = Depends(get_db),
):
    today = date.today()
    if not year:
        year = today.year
    if not month:
        month = today.month

    period_start = date(year, month, 1)
    if month == 12:
        period_end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        period_end = date(year, month + 1, 1) - timedelta(days=1)

    # --- Kasa girişleri ---
    cash_in_entries = (
        db.query(CashEntry)
        .filter(
            CashEntry.entry_type == "giris",
            CashEntry.entry_date >= period_start,
            CashEntry.entry_date <= period_end,
        )
        .all()
    )
    cash_out_entries = (
        db.query(CashEntry)
        .filter(
            CashEntry.entry_type == "cikis",
            CashEntry.entry_date >= period_start,
            CashEntry.entry_date <= period_end,
        )
        .all()
    )
    total_cash_in  = sum(e.amount for e in cash_in_entries)
    total_cash_out = sum(e.amount for e in cash_out_entries)

    # --- Gerçekleşen giderler kategoriye göre ---
    actual_entries = (
        db.query(ActualEntry)
        .filter(
            ActualEntry.entry_date >= period_start,
            ActualEntry.entry_date <= period_end,
        )
        .all()
    )
    by_category: dict[str, float] = defaultdict(float)
    for ae in actual_entries:
        label = BUDGET_CATEGORY_LABELS.get(ae.category, ae.category)
        by_category[label] += ae.amount

    # --- Fatura özeti ---
    invoices = (
        db.query(EFatura)
        .filter(
            EFatura.invoice_date >= period_start,
            EFatura.invoice_date <= period_end,
            EFatura.status == "kesildi",
        )
        .all()
    )
    satis_toplam = sum(i.total_incl_vat for i in invoices if i.invoice_type == "satis")
    alis_toplam  = sum(i.total_incl_vat for i in invoices if i.invoice_type == "alis")

    # --- Tedarikçi ödemeleri bu dönem ---
    supplier_payments = (
        db.query(SupplierPayment)
        .filter(
            SupplierPayment.payment_date >= period_start,
            SupplierPayment.payment_date <= period_end,
        )
        .all()
    )
    supplier_payment_total = sum(p.amount for p in supplier_payments)

    # --- Aylık trend (son 12 ay) ---
    monthly_trend = []
    for i in range(11, -1, -1):
        m_date = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        for _ in range(i):
            m_date = (m_date - timedelta(days=1)).replace(day=1)
        m_end = date(m_date.year, m_date.month + 1, 1) - timedelta(days=1) if m_date.month < 12 else date(m_date.year + 1, 1, 1) - timedelta(days=1)
        m_in = (
            db.query(func.sum(CashEntry.amount))
            .filter(
                CashEntry.entry_type == "giris",
                CashEntry.entry_date >= m_date,
                CashEntry.entry_date <= m_end,
            )
            .scalar() or 0.0
        )
        m_out = (
            db.query(func.sum(CashEntry.amount))
            .filter(
                CashEntry.entry_type == "cikis",
                CashEntry.entry_date >= m_date,
                CashEntry.entry_date <= m_end,
            )
            .scalar() or 0.0
        )
        monthly_trend.append({
            "label": m_date.strftime("%b %Y"),
            "in": m_in,
            "out": m_out,
            "net": m_in - m_out,
        })

    # --- Proje bazlı özet ---
    projects = db.query(Project).filter(Project.status != "iptal").all()
    project_summary = [
        {
            "name": p.name,
            "budgeted": p.total_budgeted,
            "actual": p.total_actual,
            "variance": p.variance,
            "pct": p.completion_pct,
        }
        for p in projects
        if p.total_budgeted > 0 or p.total_actual > 0
    ]

    # Yıl/ay seçenekleri
    years  = list(range(today.year - 3, today.year + 2))
    months = [
        {"value": i, "label": f"{i:02d}"}
        for i in range(1, 13)
    ]

    return templates.TemplateResponse(
        request,
        "reports/index.html",
        {
            "active": "reports",
            "year": year,
            "month": month,
            "period_start": period_start,
            "period_end": period_end,
            "total_cash_in": total_cash_in,
            "total_cash_out": total_cash_out,
            "net_cash": total_cash_in - total_cash_out,
            "by_category": dict(sorted(by_category.items(), key=lambda x: -x[1])),
            "satis_toplam": satis_toplam,
            "alis_toplam": alis_toplam,
            "supplier_payment_total": supplier_payment_total,
            "monthly_trend": monthly_trend,
            "project_summary": project_summary,
            "years": years,
            "months": months,
        },
    )
