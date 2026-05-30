"""Finans Ajanı — Tedarikçi Ödeme Yönetimi"""
from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from database import get_db
from models import (
    PaymentPlan, SupplierAccount, SupplierPayment,
    PAYMENT_METHODS, PAYMENT_METHOD_LABELS, SUPPLIER_STATUSES,
)
from templates_config import templates

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


# ---------------------------------------------------------------------------
# Tedarikçi listesi
# ---------------------------------------------------------------------------
@router.get("", response_class=HTMLResponse, name="suppliers_list")
async def suppliers_list(request: Request, db: Session = Depends(get_db)):
    suppliers = db.query(SupplierAccount).order_by(SupplierAccount.name).all()
    return templates.TemplateResponse(
        request,
        "suppliers/list.html",
        {
            "active": "suppliers",
            "suppliers": suppliers,
        },
    )


# ---------------------------------------------------------------------------
# Yeni tedarikçi
# ---------------------------------------------------------------------------
@router.get("/new", response_class=HTMLResponse, name="supplier_new")
async def supplier_new(request: Request):
    return templates.TemplateResponse(
        request,
        "suppliers/form.html",
        {
            "active": "suppliers",
            "supplier": None,
            "statuses": SUPPLIER_STATUSES,
        },
    )


@router.post("/new")
async def supplier_create(
    name: str = Form(...),
    tax_number: str = Form(""),
    tax_office: str = Form(""),
    contact_name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    iban: str = Form(""),
    status: str = Form("aktif"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    supplier = SupplierAccount(
        name=name,
        tax_number=tax_number or None,
        tax_office=tax_office or None,
        contact_name=contact_name or None,
        email=email or None,
        phone=phone or None,
        iban=iban or None,
        status=status,
        notes=notes or None,
    )
    db.add(supplier)
    db.commit()
    return RedirectResponse(url=f"/suppliers/{supplier.id}", status_code=303)


# ---------------------------------------------------------------------------
# Tedarikçi detay
# ---------------------------------------------------------------------------
@router.get("/{supplier_id}", response_class=HTMLResponse, name="supplier_detail")
async def supplier_detail(supplier_id: str, request: Request, db: Session = Depends(get_db)):
    supplier = db.query(SupplierAccount).filter(SupplierAccount.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Tedarikçi bulunamadı.")

    payments = (
        db.query(SupplierPayment)
        .filter(SupplierPayment.supplier_id == supplier_id)
        .order_by(SupplierPayment.payment_date.desc())
        .all()
    )
    pending_plans = (
        db.query(PaymentPlan)
        .filter(
            PaymentPlan.supplier_account_id == supplier_id,
            PaymentPlan.status == "bekliyor",
        )
        .order_by(PaymentPlan.due_date)
        .all()
    )

    return templates.TemplateResponse(
        request,
        "suppliers/detail.html",
        {
            "active": "suppliers",
            "supplier": supplier,
            "payments": payments,
            "pending_plans": pending_plans,
            "methods": PAYMENT_METHODS,
            "today": date.today(),
        },
    )


# ---------------------------------------------------------------------------
# Tedarikçi düzenle
# ---------------------------------------------------------------------------
@router.get("/{supplier_id}/edit", response_class=HTMLResponse, name="supplier_edit")
async def supplier_edit(supplier_id: str, request: Request, db: Session = Depends(get_db)):
    supplier = db.query(SupplierAccount).filter(SupplierAccount.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request,
        "suppliers/form.html",
        {
            "active": "suppliers",
            "supplier": supplier,
            "statuses": SUPPLIER_STATUSES,
        },
    )


@router.post("/{supplier_id}/edit")
async def supplier_update(
    supplier_id: str,
    name: str = Form(...),
    tax_number: str = Form(""),
    tax_office: str = Form(""),
    contact_name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    iban: str = Form(""),
    status: str = Form("aktif"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    supplier = db.query(SupplierAccount).filter(SupplierAccount.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404)
    supplier.name = name
    supplier.tax_number = tax_number or None
    supplier.tax_office = tax_office or None
    supplier.contact_name = contact_name or None
    supplier.email = email or None
    supplier.phone = phone or None
    supplier.iban = iban or None
    supplier.status = status
    supplier.notes = notes or None
    db.commit()
    return RedirectResponse(url=f"/suppliers/{supplier_id}", status_code=303)


# ---------------------------------------------------------------------------
# Ödeme kaydet
# ---------------------------------------------------------------------------
@router.post("/{supplier_id}/payments/add")
async def payment_add(
    supplier_id: str,
    payment_date: str = Form(...),
    amount: float = Form(0.0),
    method: str = Form("havale"),
    description: str = Form(""),
    reference_no: str = Form(""),
    invoice_no: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    supplier = db.query(SupplierAccount).filter(SupplierAccount.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404)
    payment = SupplierPayment(
        supplier_id=supplier_id,
        payment_date=date.fromisoformat(payment_date),
        amount=amount,
        method=method,
        description=description,
        reference_no=reference_no or None,
        invoice_no=invoice_no or None,
        notes=notes or None,
    )
    db.add(payment)
    db.commit()
    return RedirectResponse(url=f"/suppliers/{supplier_id}", status_code=303)


# ---------------------------------------------------------------------------
# Ödeme sil
# ---------------------------------------------------------------------------
@router.post("/{supplier_id}/payments/{payment_id}/delete")
async def payment_delete(supplier_id: str, payment_id: str, db: Session = Depends(get_db)):
    payment = db.query(SupplierPayment).filter(
        SupplierPayment.id == payment_id,
        SupplierPayment.supplier_id == supplier_id,
    ).first()
    if payment:
        db.delete(payment)
        db.commit()
    return RedirectResponse(url=f"/suppliers/{supplier_id}", status_code=303)
