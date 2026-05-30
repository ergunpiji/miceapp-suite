"""Finans Ajanı — Kasa (Giriş/Çıkış + Gün Sonu Raporu)"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import (
    CashDayReport, CashEntry,
    CASH_ENTRY_TYPES, CASH_CATEGORIES, CASH_ENTRY_TYPE_LABELS, CASH_CATEGORY_LABELS,
)
from templates_config import templates

router = APIRouter(prefix="/cashbook", tags=["cashbook"])


def _get_or_create_day_report(db: Session, for_date: date) -> CashDayReport:
    report = db.query(CashDayReport).filter(CashDayReport.report_date == for_date).first()
    if not report:
        # Önceki günün kapanış bakiyesini bul
        prev_report = (
            db.query(CashDayReport)
            .filter(CashDayReport.report_date < for_date)
            .order_by(CashDayReport.report_date.desc())
            .first()
        )
        opening = prev_report.closing_balance if prev_report else 0.0
        report = CashDayReport(report_date=for_date, opening_balance=opening)
        db.add(report)
        db.commit()
        db.refresh(report)
    return report


# ---------------------------------------------------------------------------
# Kasa hareketi listesi
# ---------------------------------------------------------------------------
@router.get("", response_class=HTMLResponse, name="cashbook_list")
async def cashbook_list(
    request: Request,
    date_from: str = "",
    date_to: str = "",
    entry_type: str = "all",
    db: Session = Depends(get_db),
):
    today = date.today()
    if not date_from:
        date_from = today.replace(day=1).isoformat()
    if not date_to:
        date_to = today.isoformat()

    d_from = date.fromisoformat(date_from)
    d_to   = date.fromisoformat(date_to)

    q = db.query(CashEntry).filter(
        CashEntry.entry_date >= d_from,
        CashEntry.entry_date <= d_to,
    )
    if entry_type != "all":
        q = q.filter(CashEntry.entry_type == entry_type)
    entries = q.order_by(CashEntry.entry_date.desc(), CashEntry.created_at.desc()).all()

    total_in  = sum(e.amount for e in entries if e.entry_type == "giris")
    total_out = sum(e.amount for e in entries if e.entry_type == "cikis")

    # Güncel kasa bakiyesi
    last_report = (
        db.query(CashDayReport)
        .order_by(CashDayReport.report_date.desc())
        .first()
    )
    current_balance = last_report.closing_balance if last_report else 0.0

    return templates.TemplateResponse(
        request,
        "cashbook/list.html",
        {
            "active": "cashbook",
            "entries": entries,
            "date_from": date_from,
            "date_to": date_to,
            "entry_type_filter": entry_type,
            "types": CASH_ENTRY_TYPES,
            "categories": CASH_CATEGORIES,
            "total_in": total_in,
            "total_out": total_out,
            "net": total_in - total_out,
            "current_balance": current_balance,
            "today": today.isoformat(),
        },
    )


# ---------------------------------------------------------------------------
# Kasa hareketi ekle
# ---------------------------------------------------------------------------
@router.post("/add")
async def cashentry_add(
    entry_date: str = Form(...),
    entry_type: str = Form(...),
    amount: float = Form(0.0),
    category: str = Form("diger"),
    description: str = Form(...),
    reference_no: str = Form(""),
    related_party: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    d = date.fromisoformat(entry_date)
    report = _get_or_create_day_report(db, d)

    entry = CashEntry(
        entry_date=d,
        entry_type=entry_type,
        amount=amount,
        category=category,
        description=description,
        reference_no=reference_no or None,
        related_party=related_party or None,
        day_report_id=report.id,
        notes=notes or None,
    )
    db.add(entry)

    # Rapor toplamlarını güncelle
    if not report.is_closed:
        if entry_type == "giris":
            report.total_in += amount
        else:
            report.total_out += amount
        report.closing_balance = report.opening_balance + report.total_in - report.total_out

    db.commit()
    return RedirectResponse(url="/cashbook", status_code=303)


# ---------------------------------------------------------------------------
# Kasa hareketi sil
# ---------------------------------------------------------------------------
@router.post("/{entry_id}/delete")
async def cashentry_delete(entry_id: str, db: Session = Depends(get_db)):
    entry = db.query(CashEntry).filter(CashEntry.id == entry_id).first()
    if entry and entry.day_report_id:
        report = db.query(CashDayReport).filter(CashDayReport.id == entry.day_report_id).first()
        if report and not report.is_closed:
            if entry.entry_type == "giris":
                report.total_in -= entry.amount
            else:
                report.total_out -= entry.amount
            report.closing_balance = report.opening_balance + report.total_in - report.total_out
    if entry:
        db.delete(entry)
        db.commit()
    return RedirectResponse(url="/cashbook", status_code=303)


# ---------------------------------------------------------------------------
# Gün sonu raporu listesi
# ---------------------------------------------------------------------------
@router.get("/day-reports", response_class=HTMLResponse, name="day_reports_list")
async def day_reports_list(request: Request, db: Session = Depends(get_db)):
    reports = (
        db.query(CashDayReport)
        .order_by(CashDayReport.report_date.desc())
        .limit(90)
        .all()
    )
    return templates.TemplateResponse(
        request,
        "cashbook/day_reports.html",
        {
            "active": "cashbook",
            "reports": reports,
            "today": date.today(),
        },
    )


# ---------------------------------------------------------------------------
# Gün sonu raporu detay / kapat
# ---------------------------------------------------------------------------
@router.get("/day-reports/{report_date}", response_class=HTMLResponse, name="day_report_detail")
async def day_report_detail(report_date: str, request: Request, db: Session = Depends(get_db)):
    d = date.fromisoformat(report_date)
    report = _get_or_create_day_report(db, d)
    db.refresh(report)

    # Bugünkü hareketleri yeniden hesapla (canlı)
    entries = (
        db.query(CashEntry)
        .filter(CashEntry.entry_date == d)
        .order_by(CashEntry.created_at)
        .all()
    )

    return templates.TemplateResponse(
        request,
        "cashbook/day_report.html",
        {
            "active": "cashbook",
            "report": report,
            "entries": entries,
            "categories": CASH_CATEGORIES,
            "category_labels": CASH_CATEGORY_LABELS,
            "type_labels": CASH_ENTRY_TYPE_LABELS,
        },
    )


@router.post("/day-reports/{report_date}/close")
async def close_day(
    report_date: str,
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    from datetime import datetime
    d = date.fromisoformat(report_date)
    report = _get_or_create_day_report(db, d)

    # Yeniden hesapla
    entries = db.query(CashEntry).filter(CashEntry.entry_date == d).all()
    report.total_in  = sum(e.amount for e in entries if e.entry_type == "giris")
    report.total_out = sum(e.amount for e in entries if e.entry_type == "cikis")
    report.closing_balance = report.opening_balance + report.total_in - report.total_out
    report.is_closed = True
    report.notes = notes or None
    report.closed_at = datetime.utcnow()
    db.commit()

    return RedirectResponse(url=f"/cashbook/day-reports/{report_date}", status_code=303)
