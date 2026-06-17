"""
Koordinatör Fatura Onayı — micedesk'ten gelen kesilen faturalar
miceapp koordinatörü (yonetici/mudur/GM) onayla/reddet yapabilir.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette import status

from auth import get_current_user, require_pm
from database import SessionLocal, get_db
from models import Invoice, User, DeskReference, Customer
from templates_config import templates

router = APIRouter(prefix="/coordinator", tags=["coordinator"])


def _ref_map(db: Session, invoices: list) -> dict:
    """ref_id → DeskReference sözlüğü döndürür."""
    ids = [inv.ref_id for inv in invoices if inv.ref_id]
    if not ids:
        return {}
    refs = db.query(DeskReference).filter(DeskReference.id.in_(ids)).all()
    return {r.id: r for r in refs}


def _customer_map(db: Session, ref_map: dict) -> dict:
    """customer_id → Customer sözlüğü döndürür."""
    cids = {r.customer_id for r in ref_map.values() if r.customer_id}
    if not cids:
        return {}
    custs = db.query(Customer).filter(Customer.id.in_(cids)).all()
    return {c.id: c for c in custs}


# ── Liste ──────────────────────────────────────────────────────────────────

@router.get("/invoices", response_class=HTMLResponse, name="coordinator_invoices")
async def coordinator_invoice_list(
    request: Request,
    filter: str = "beklemede",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_pm),
):
    from tenant import scope
    _iq = lambda: scope(db.query(Invoice), Invoice, current_user)   # tenant izolasyonu
    query = _iq().filter(Invoice.coordinator_status.isnot(None))
    if filter == "beklemede":
        query = query.filter(Invoice.coordinator_status == "beklemede")
    elif filter == "onaylandi":
        query = query.filter(Invoice.coordinator_status == "onaylandi")
    elif filter == "reddedildi":
        query = query.filter(Invoice.coordinator_status == "reddedildi")

    invoices = query.order_by(Invoice.created_at.desc()).limit(200).all()
    rm = _ref_map(db, invoices)
    cm = _customer_map(db, rm)

    counts = {
        "beklemede":  _iq().filter(Invoice.coordinator_status == "beklemede").count(),
        "onaylandi":  _iq().filter(Invoice.coordinator_status == "onaylandi").count(),
        "reddedildi": _iq().filter(Invoice.coordinator_status == "reddedildi").count(),
    }

    return templates.TemplateResponse("coordinator/invoices.html", {
        "request": request,
        "current_user": current_user,
        "page_title": "Koordinatör Fatura Onayları",
        "invoices": invoices,
        "ref_map": rm,
        "customer_map": cm,
        "filter": filter,
        "counts": counts,
    })


# ── Onayla ────────────────────────────────────────────────────────────────

@router.post("/invoices/{invoice_id}/approve", name="coordinator_approve")
async def coordinator_approve(
    invoice_id: str,
    note: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_pm),
):
    from tenant import scope
    inv = scope(db.query(Invoice), Invoice, current_user).filter(Invoice.id == invoice_id).first()
    if not inv or inv.coordinator_status != "beklemede":
        raise HTTPException(404)
    inv.coordinator_status = "onaylandi"
    inv.coordinator_note = note.strip() or None
    inv.coordinator_reviewed_at = datetime.utcnow()
    inv.coordinator_reviewed_by = current_user.id
    db.commit()
    return RedirectResponse(
        url="/coordinator/invoices?filter=beklemede",
        status_code=status.HTTP_302_FOUND,
    )


# ── Reddet ────────────────────────────────────────────────────────────────

@router.post("/invoices/{invoice_id}/reject", name="coordinator_reject")
async def coordinator_reject(
    invoice_id: str,
    note: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_pm),
):
    from tenant import scope
    inv = scope(db.query(Invoice), Invoice, current_user).filter(Invoice.id == invoice_id).first()
    if not inv or inv.coordinator_status != "beklemede":
        raise HTTPException(404)
    inv.coordinator_status = "reddedildi"
    inv.coordinator_note = note.strip() or None
    inv.coordinator_reviewed_at = datetime.utcnow()
    inv.coordinator_reviewed_by = current_user.id
    db.commit()
    return RedirectResponse(
        url="/coordinator/invoices?filter=beklemede",
        status_code=status.HTTP_302_FOUND,
    )
