"""
Finansal Tedarikçi (Vendor) yönetimi
"""

from datetime import date as _date
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload

from auth import get_current_user, require_module, get_company_id
from database import get_db
from models import (
    Vendor, Invoice, Cheque, User, CashBook, BankAccount, CreditCard,
    VendorPrepayment, CashEntry, BankMovement, CreditCardTxn, Reference,
    VendorType, PAYMENT_METHODS,
)
from templates_config import templates

router = APIRouter(prefix="/vendors", tags=["vendors"])


def _primary_iban(bank_accounts_json: str) -> str:
    import json as _j
    try:
        accounts = _j.loads(bank_accounts_json or "[]")
        if accounts:
            return (accounts[0].get("iban") or "").strip()
    except Exception:
        pass
    return ""


def _cities_to_json(cities_str: str) -> str:
    """Virgülle ayrılmış şehir stringini JSON array'e dönüştür."""
    import json as _j
    if not cities_str or not cities_str.strip():
        return "[]"
    # Zaten JSON array ise doğrudan döndür
    s = cities_str.strip()
    if s.startswith("["):
        try:
            parsed = _j.loads(s)
            if isinstance(parsed, list):
                return s
        except Exception:
            pass
    parts = [c.strip() for c in s.split(",") if c.strip()]
    return _j.dumps(parts, ensure_ascii=False)


def _get_vendor_types(db):
    rows = db.query(VendorType).filter(VendorType.active == True).order_by(  # noqa: E712
        VendorType.sort_order, VendorType.label
    ).all()
    return [(vt.value, vt.label) for vt in rows]


@router.get("", response_class=HTMLResponse, name="vendors_list")
async def vendors_list(
    request: Request,
    q: str = "",
    active_only: str = "1",
    current_user: User = Depends(require_module("vendors")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    from datetime import date
    from sqlalchemy import func
    from sqlalchemy import or_
    query = db.query(Vendor).filter(
        or_(Vendor.company_id == cid, Vendor.company_id == None)  # noqa: E711
    )
    if active_only == "1":
        query = query.filter(Vendor.active == True)  # noqa: E712
    if q:
        query = query.filter(Vendor.name.ilike(f"%{q}%"))
    vendors = query.order_by(Vendor.name).all()

    today = date.today()
    vendor_ids = [v.id for v in vendors]

    # Batch: approved/partial invoices per vendor — KDV dahil tutarlar
    from models import InvoicePayment
    open_invoices = (
        db.query(Invoice)
        .filter(Invoice.vendor_id.in_(vendor_ids), Invoice.status.in_(["approved", "partial"]),
                Invoice.company_id == cid)
        .all()
    )

    unpaid_map: dict = {}
    overdue_map: dict = {}
    for inv in open_invoices:
        remaining = inv.remaining
        unpaid_map[inv.vendor_id] = unpaid_map.get(inv.vendor_id, 0) + remaining
        if inv.due_date and inv.due_date < today:
            overdue_map[inv.vendor_id] = overdue_map.get(inv.vendor_id, 0) + remaining

    return templates.TemplateResponse(
        "vendors/list.html",
        {"request": request, "current_user": current_user,
         "vendors": vendors, "q": q, "active_only": active_only,
         "page_title": "Tedarikçiler",
         "unpaid_map": unpaid_map, "overdue_map": overdue_map},
    )


@router.post("/quick-add", name="vendor_quick_add")
async def vendor_quick_add(
    name: str = Form(...),
    tax_no: str = Form(""),
    tax_office: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    contact: str = Form(""),
    address: str = Form(""),
    payment_term: int = Form(30),
    vendor_type: str = Form("genel"),
    iban: str = Form(""),
    notes: str = Form(""),
    location_type: str = Form("turkiye"),
    cities: str = Form(""),
    bank_accounts_json: str = Form("[]"),
    current_user: User = Depends(require_module("vendors", edit=True)),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    from fastapi.responses import JSONResponse
    name = name.strip()
    if not name:
        return JSONResponse({"error": "Ad zorunludur."}, status_code=422)
    existing = db.query(Vendor).filter(
        Vendor.name.ilike(name),
        Vendor.company_id == cid,
    ).first()
    if existing:
        return JSONResponse(
            {"error": f'"{existing.name}" adında bir tedarikçi zaten var.',
             "existing": {"id": existing.id, "name": existing.name,
                          "payment_term": existing.payment_term or 30}},
            status_code=409,
        )
    primary_iban = _primary_iban(bank_accounts_json) or iban.strip() or None
    v = Vendor(
        name=name, supplier_type=vendor_type,
        tax_no=tax_no.strip(), tax_office=tax_office.strip(),
        phone=phone.strip(), email=email.strip(),
        contact=contact.strip(), address=address.strip(),
        iban=primary_iban,
        notes=notes.strip() or None,
        location_type=location_type, cities_json=_cities_to_json(cities),
        bank_accounts_json=bank_accounts_json if bank_accounts_json != "[]" else None,
        payment_term=payment_term, active=True,
        company_id=cid,
    )
    db.add(v)
    db.commit()
    return JSONResponse({"id": v.id, "name": v.name, "payment_term": v.payment_term or 30})


@router.get("/new", response_class=HTMLResponse, name="vendor_new_get")
async def vendor_new_get(
    request: Request,
    current_user: User = Depends(require_module("vendors", edit=True)),
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(
        "vendors/form.html",
        {"request": request, "current_user": current_user,
         "vendor": None, "vendor_types": _get_vendor_types(db),
         "page_title": "Yeni Tedarikçi"},
    )


@router.post("/new", name="vendor_new_post")
async def vendor_new_post(
    name: str = Form(...),
    vendor_type: str = Form("genel"),
    iban: str = Form(""),
    tax_no: str = Form(""),
    tax_office: str = Form(""),
    address: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    payment_term: int = Form(30),
    contact: str = Form(""),
    location_type: str = Form("turkiye"),
    cities: str = Form(""),
    bank_accounts_json: str = Form("[]"),
    notes: str = Form(""),
    current_user: User = Depends(require_module("vendors", edit=True)),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    primary_iban = _primary_iban(bank_accounts_json) or iban.strip()
    v = Vendor(
        name=name.strip(), supplier_type=vendor_type,
        iban=primary_iban, tax_no=tax_no.strip(),
        tax_office=tax_office.strip(), address=address.strip(),
        phone=phone.strip(), email=email.strip(),
        payment_term=payment_term, contact=contact.strip(),
        location_type=location_type, cities_json=_cities_to_json(cities),
        bank_accounts_json=bank_accounts_json if bank_accounts_json != "[]" else None,
        notes=notes.strip(), active=True,
        company_id=cid,
    )
    db.add(v)
    db.commit()
    return RedirectResponse(url=f"/vendors/{v.id}", status_code=status.HTTP_302_FOUND)


@router.get("/{vendor_id}", response_class=HTMLResponse, name="vendor_detail")
async def vendor_detail(
    vendor_id: str,
    request: Request,
    period: str = "all",
    current_user: User = Depends(require_module("vendors")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    from datetime import timedelta
    v = db.query(Vendor).filter(Vendor.id == vendor_id, Vendor.company_id == cid).first()
    if not v:
        raise HTTPException(status_code=404)

    today = _date.today()
    inv_q = db.query(Invoice).filter(Invoice.vendor_id == vendor_id, Invoice.company_id == cid)
    if period != "all":
        cutoff = today - timedelta(days=int(period))
        inv_q = inv_q.filter(Invoice.invoice_date >= cutoff)
    invoices = inv_q.options(joinedload(Invoice.payments)).order_by(Invoice.invoice_date.desc()).all()

    prepayments = (
        db.query(VendorPrepayment)
        .filter(VendorPrepayment.vendor_id == vendor_id, VendorPrepayment.company_id == cid)
        .order_by(VendorPrepayment.payment_date.desc())
        .all()
    )
    references = (
        db.query(Reference)
        .filter(Reference.status == "aktif", Reference.company_id == cid)
        .order_by(Reference.ref_no)
        .all()
    )
    cheques = db.query(Cheque).filter(Cheque.vendor_id == vendor_id, Cheque.company_id == cid).order_by(Cheque.due_date.desc()).all()

    cash_books    = db.query(CashBook).filter(CashBook.company_id == cid).all()
    bank_accounts = db.query(BankAccount).filter(BankAccount.company_id == cid).all()
    credit_cards  = db.query(CreditCard).filter(CreditCard.company_id == cid).all()

    # iade_kesilen: biz tedarikçiye iade faturası kestik → tedarikçi bize borçlu → negatif
    def _sign(inv):
        return -1 if inv.invoice_type == "iade_kesilen" else 1

    total_amount   = sum(i.total_with_vat * _sign(i) for i in invoices)
    paid_amount    = sum(i.paid_amount * _sign(i) for i in invoices) + sum(p.amount for p in prepayments)
    unpaid_amount  = sum(i.remaining * _sign(i) for i in invoices if i.status in ("approved", "partial"))
    overdue_amount = sum(
        i.remaining * _sign(i) for i in invoices
        if i.status in ("approved", "partial") and i.due_date and i.due_date < today
    )

    return templates.TemplateResponse(
        "vendors/detail.html",
        {
            "request": request, "current_user": current_user,
            "vendor": v, "invoices": invoices, "cheques": cheques,
            "prepayments": prepayments, "references": references,
            "total_amount": total_amount, "paid_amount": paid_amount,
            "unpaid_amount": unpaid_amount, "overdue_amount": overdue_amount,
            "period": period, "today": today,
            "cash_books": cash_books, "bank_accounts": bank_accounts,
            "credit_cards": credit_cards, "payment_methods": PAYMENT_METHODS,
            "page_title": v.name,
        },
    )


@router.post("/{vendor_id}/prepayment", name="vendor_prepayment")
async def vendor_prepayment(
    vendor_id: str,
    payment_type: str = Form("prepayment"),
    amount: float = Form(...),
    pay_date: str = Form(""),
    payment_method: str = Form(...),
    ref_id: str = Form(None),
    bank_account_id: str = Form(None),
    cash_book_id: str = Form(None),
    credit_card_id: str = Form(None),
    cheque_no: str = Form(""),
    cheque_bank: str = Form(""),
    cheque_date: str = Form(""),
    cheque_due_date: str = Form(""),
    notes: str = Form(""),
    current_user: User = Depends(require_module("vendors", edit=True)),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    v = db.query(Vendor).filter(Vendor.id == vendor_id, Vendor.company_id == cid).first()
    if not v:
        raise HTTPException(status_code=404)

    pdate = _date.fromisoformat(pay_date) if pay_date else _date.today()
    label = "Ön Ödeme" if payment_type == "prepayment" else "Ödeme"
    desc = f"{label} — {v.name}"

    pmt = VendorPrepayment(
        vendor_id=vendor_id,
        payment_type=payment_type,
        ref_id=ref_id or None,
        payment_date=pdate,
        amount=amount,
        payment_method=payment_method,
        bank_account_id=bank_account_id if payment_method == "banka" else None,
        cash_book_id=cash_book_id if payment_method == "nakit" else None,
        credit_card_id=credit_card_id if payment_method == "kredi_karti" else None,
        notes=notes.strip(),
        created_by=current_user.id,
        company_id=cid,
    )

    if payment_method == "nakit" and cash_book_id:
        db.add(CashEntry(
            book_id=cash_book_id, entry_date=pdate,
            entry_type="cikis", amount=amount, description=desc,
        ))
    elif payment_method == "banka" and bank_account_id:
        db.add(BankMovement(
            account_id=bank_account_id, movement_date=pdate,
            movement_type="cikis", amount=amount, description=desc,
        ))
    elif payment_method == "kredi_karti" and credit_card_id:
        db.add(CreditCardTxn(
            card_id=credit_card_id, txn_date=pdate,
            amount=amount, description=desc,
        ))
    elif payment_method == "cek":
        from models import Cheque as ChequeModel
        cheque = ChequeModel(
            vendor_id=vendor_id,
            cheque_type="verilen",
            cheque_no=cheque_no.strip(),
            bank=cheque_bank.strip(),
            amount=amount,
            currency="TRY",
            cheque_date=_date.fromisoformat(cheque_date) if cheque_date else pdate,
            due_date=_date.fromisoformat(cheque_due_date) if cheque_due_date else pdate,
            status="beklemede",
        )
        db.add(cheque)
        db.flush()
        pmt.cheque_id = cheque.id

    db.add(pmt)
    db.commit()
    return RedirectResponse(url=f"/vendors/{vendor_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{vendor_id}/prepayment/{pmt_id}/delete", name="vendor_prepayment_delete")
async def vendor_prepayment_delete(
    vendor_id: str,
    pmt_id: str,
    current_user: User = Depends(require_module("vendors", edit=True)),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    pmt = db.query(VendorPrepayment).filter(
        VendorPrepayment.id == pmt_id,
        VendorPrepayment.vendor_id == vendor_id,
        VendorPrepayment.company_id == cid,
    ).first()
    if pmt:
        db.delete(pmt)
        db.commit()
    return RedirectResponse(url=f"/vendors/{vendor_id}", status_code=status.HTTP_302_FOUND)


@router.get("/{vendor_id}/edit", response_class=HTMLResponse, name="vendor_edit_get")
async def vendor_edit_get(
    vendor_id: str,
    request: Request,
    current_user: User = Depends(require_module("vendors", edit=True)),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    v = db.query(Vendor).filter(Vendor.id == vendor_id, Vendor.company_id == cid).first()
    if not v:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        "vendors/form.html",
        {"request": request, "current_user": current_user,
         "vendor": v, "vendor_types": _get_vendor_types(db),
         "page_title": f"Düzenle — {v.name}"},
    )


@router.post("/{vendor_id}/edit", name="vendor_edit_post")
async def vendor_edit_post(
    vendor_id: str,
    name: str = Form(...),
    vendor_type: str = Form("genel"),
    iban: str = Form(""),
    tax_no: str = Form(""),
    tax_office: str = Form(""),
    address: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    payment_term: int = Form(30),
    contact: str = Form(""),
    location_type: str = Form("turkiye"),
    cities: str = Form(""),
    bank_accounts_json: str = Form("[]"),
    notes: str = Form(""),
    active: str = Form("1"),
    current_user: User = Depends(require_module("vendors", edit=True)),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    v = db.query(Vendor).filter(Vendor.id == vendor_id, Vendor.company_id == cid).first()
    if not v:
        raise HTTPException(status_code=404)
    primary_iban = _primary_iban(bank_accounts_json) or iban.strip()
    v.name = name.strip()
    v.supplier_type = vendor_type
    v.iban = primary_iban
    v.tax_no = tax_no.strip()
    v.tax_office = tax_office.strip()
    v.address = address.strip()
    v.phone = phone.strip()
    v.email = email.strip()
    v.payment_term = payment_term
    v.contact = contact.strip()
    v.location_type = location_type
    v.cities_json = _cities_to_json(cities)
    v.bank_accounts_json = bank_accounts_json if bank_accounts_json != "[]" else None
    v.notes = notes.strip()
    v.active = (active == "1")
    db.commit()
    return RedirectResponse(url=f"/vendors/{vendor_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{vendor_id}/toggle-active", name="vendor_toggle_active")
async def vendor_toggle_active(
    vendor_id: str,
    current_user: User = Depends(require_module("vendors", edit=True)),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    v = db.query(Vendor).filter(Vendor.id == vendor_id, Vendor.company_id == cid).first()
    if v:
        v.active = not v.active
        db.commit()
    return RedirectResponse(url="/vendors", status_code=status.HTTP_302_FOUND)


@router.post("/{vendor_id}/delete", name="vendor_delete")
async def vendor_delete(
    vendor_id: str,
    current_user: User = Depends(require_module("vendors", edit=True)),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403)
    v = db.query(Vendor).filter(Vendor.id == vendor_id, Vendor.company_id == cid).first()
    if v:
        db.delete(v)
        db.commit()
    return RedirectResponse(url="/vendors", status_code=status.HTTP_302_FOUND)
