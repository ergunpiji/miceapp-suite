"""Finans Ajanı — E-Fatura"""
from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from database import get_db
from models import (
    EFatura, EFaturaLine,
    EFATURA_TYPES, EFATURA_STATUSES, EFATURA_TYPE_LABELS, EFATURA_STATUS_LABELS,
    VAT_RATES,
)
from templates_config import templates

router = APIRouter(prefix="/efatura", tags=["efatura"])


def _next_invoice_no(db: Session, invoice_type: str) -> str:
    """Otomatik fatura numarası üret: FA-2506-001 formatı"""
    today = date.today()
    prefix = "FA" if invoice_type == "satis" else ("AL" if invoice_type == "alis" else "ID")
    ym = today.strftime("%y%m")
    count = (
        db.query(EFatura)
        .filter(EFatura.invoice_no.like(f"{prefix}-{ym}-%"))
        .count()
    ) + 1
    return f"{prefix}-{ym}-{count:03d}"


# ---------------------------------------------------------------------------
# Fatura listesi
# ---------------------------------------------------------------------------
@router.get("", response_class=HTMLResponse, name="efatura_list")
async def efatura_list(
    request: Request,
    type_filter: str = "all",
    status_filter: str = "all",
    q: str = "",
    db: Session = Depends(get_db),
):
    query = db.query(EFatura).order_by(EFatura.invoice_date.desc())
    if type_filter != "all":
        query = query.filter(EFatura.invoice_type == type_filter)
    if status_filter != "all":
        query = query.filter(EFatura.status == status_filter)
    if q:
        query = query.filter(
            EFatura.invoice_no.ilike(f"%{q}%")
            | EFatura.seller_name.ilike(f"%{q}%")
            | EFatura.buyer_name.ilike(f"%{q}%")
        )
    invoices = query.all()

    return templates.TemplateResponse(
        request,
        "efatura/list.html",
        {
            "active": "efatura",
            "invoices": invoices,
            "type_filter": type_filter,
            "status_filter": status_filter,
            "q": q,
            "types": EFATURA_TYPES,
            "statuses": EFATURA_STATUSES,
            "type_labels": EFATURA_TYPE_LABELS,
            "status_labels": EFATURA_STATUS_LABELS,
        },
    )


# ---------------------------------------------------------------------------
# Yeni fatura
# ---------------------------------------------------------------------------
@router.get("/new", response_class=HTMLResponse, name="efatura_new")
async def efatura_new(request: Request, invoice_type: str = "satis", db: Session = Depends(get_db)):
    suggested_no = _next_invoice_no(db, invoice_type)
    return templates.TemplateResponse(
        request,
        "efatura/form.html",
        {
            "active": "efatura",
            "invoice": None,
            "suggested_no": suggested_no,
            "types": EFATURA_TYPES,
            "statuses": EFATURA_STATUSES,
            "vat_rates": VAT_RATES,
            "today": date.today().isoformat(),
            "invoice_type": invoice_type,
        },
    )


@router.post("/new")
async def efatura_create(
    request: Request,
    db: Session = Depends(get_db),
):
    form = await request.form()
    invoice_no   = form.get("invoice_no", "").strip()
    invoice_date = form.get("invoice_date", "")
    invoice_type = form.get("invoice_type", "satis")
    seller_name  = form.get("seller_name", "")
    seller_tax_no    = form.get("seller_tax_no", "")
    seller_tax_office = form.get("seller_tax_office", "")
    buyer_name   = form.get("buyer_name", "")
    buyer_tax_no     = form.get("buyer_tax_no", "")
    buyer_tax_office  = form.get("buyer_tax_office", "")
    edem_request_no  = form.get("edem_request_no", "")
    notes        = form.get("notes", "")
    status       = form.get("status", "taslak")

    # Satırlar
    descriptions = form.getlist("line_description")
    units        = form.getlist("line_unit")
    qtys         = form.getlist("line_qty")
    unit_prices  = form.getlist("line_unit_price")
    vat_rates    = form.getlist("line_vat_rate")

    lines = []
    total_excl = 0.0
    total_vat  = 0.0

    for i, desc in enumerate(descriptions):
        if not desc.strip():
            continue
        qty        = float(qtys[i]) if i < len(qtys) else 1.0
        unit_price = float(unit_prices[i]) if i < len(unit_prices) else 0.0
        vat_rate   = int(vat_rates[i]) if i < len(vat_rates) else 20
        amount_excl = round(qty * unit_price, 2)
        vat_amount  = round(amount_excl * vat_rate / 100, 2)
        amount_incl = round(amount_excl + vat_amount, 2)
        total_excl += amount_excl
        total_vat  += vat_amount
        lines.append(EFaturaLine(
            description=desc.strip(),
            unit=units[i] if i < len(units) else "Adet",
            qty=qty,
            unit_price=unit_price,
            vat_rate=vat_rate,
            amount_excl=amount_excl,
            vat_amount=vat_amount,
            amount_incl=amount_incl,
        ))

    invoice = EFatura(
        invoice_no=invoice_no or _next_invoice_no(db, invoice_type),
        invoice_date=date.fromisoformat(invoice_date) if invoice_date else date.today(),
        invoice_type=invoice_type,
        status=status,
        seller_name=seller_name,
        seller_tax_no=seller_tax_no or None,
        seller_tax_office=seller_tax_office or None,
        buyer_name=buyer_name,
        buyer_tax_no=buyer_tax_no or None,
        buyer_tax_office=buyer_tax_office or None,
        total_excl_vat=round(total_excl, 2),
        total_vat=round(total_vat, 2),
        total_incl_vat=round(total_excl + total_vat, 2),
        edem_request_no=edem_request_no or None,
        notes=notes or None,
    )
    for line in lines:
        invoice.lines.append(line)
    db.add(invoice)
    db.commit()
    return RedirectResponse(url=f"/efatura/{invoice.id}", status_code=303)


# ---------------------------------------------------------------------------
# Fatura detay / yazdır
# ---------------------------------------------------------------------------
@router.get("/{invoice_id}", response_class=HTMLResponse, name="efatura_detail")
async def efatura_detail(invoice_id: str, request: Request, db: Session = Depends(get_db)):
    invoice = db.query(EFatura).filter(EFatura.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Fatura bulunamadı.")
    return templates.TemplateResponse(
        request,
        "efatura/detail.html",
        {
            "active": "efatura",
            "invoice": invoice,
            "type_labels": EFATURA_TYPE_LABELS,
            "status_labels": EFATURA_STATUS_LABELS,
        },
    )


# ---------------------------------------------------------------------------
# Durum güncelle (kesildi / iptal)
# ---------------------------------------------------------------------------
@router.post("/{invoice_id}/status")
async def update_status(
    invoice_id: str,
    status: str = Form(...),
    db: Session = Depends(get_db),
):
    invoice = db.query(EFatura).filter(EFatura.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404)
    invoice.status = status
    db.commit()
    return RedirectResponse(url=f"/efatura/{invoice_id}", status_code=303)


# ---------------------------------------------------------------------------
# Fatura sil
# ---------------------------------------------------------------------------
@router.post("/{invoice_id}/delete")
async def efatura_delete(invoice_id: str, db: Session = Depends(get_db)):
    invoice = db.query(EFatura).filter(EFatura.id == invoice_id).first()
    if invoice:
        db.delete(invoice)
        db.commit()
    return RedirectResponse(url="/efatura", status_code=303)
