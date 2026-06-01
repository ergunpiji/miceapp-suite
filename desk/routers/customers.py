"""
Müşteri yönetimi
"""

from datetime import date as _date
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload

from auth import get_current_user, get_company_id, require_admin, require_module
from database import get_db
from models import (
    Customer, CustomerPrepayment, Invoice, Cheque, Reference,
    User, CashBook, BankAccount, CreditCard, CashEntry, BankMovement,
    PAYMENT_METHODS,
)
from access_policy import visible_customers_query, can_access_customer
from templates_config import templates

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("", response_class=HTMLResponse, name="customers_list")
async def customers_list(
    request: Request,
    q: str = "",
    active_only: str = "1",
    current_user: User = Depends(require_module("customers")),
    db: Session = Depends(get_db),
):
    query = visible_customers_query(db, current_user)
    if active_only == "1":
        query = query.filter(Customer.active == True)  # noqa: E712
    if q:
        query = query.filter(Customer.name.ilike(f"%{q}%") | Customer.code.ilike(f"%{q}%"))
    customers = query.order_by(Customer.name).all()
    return templates.TemplateResponse(
        "customers/list.html",
        {"request": request, "current_user": current_user,
         "customers": customers, "q": q, "active_only": active_only,
         "page_title": "Müşteriler"},
    )


@router.get("/new", response_class=HTMLResponse, name="customer_new_get")
async def customer_new_get(
    request: Request,
    current_user: User = Depends(require_module("customers", edit=True)),
):
    return templates.TemplateResponse(
        "customers/form.html",
        {"request": request, "current_user": current_user,
         "customer": None, "page_title": "Yeni Müşteri", "error": None},
    )


@router.post("/new", name="customer_new_post")
async def customer_new_post(
    request: Request,
    name: str = Form(...),
    code: str = Form(...),
    sector: str = Form(""),
    tax_no: str = Form(""),
    tax_office: str = Form(""),
    address: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    payment_term: str = Form(""),
    payment_dow: str = Form(""),
    notes: str = Form(""),
    contacts_json: str = Form("[]"),
    current_user: User = Depends(require_module("customers", edit=True)),
    db: Session = Depends(get_db),
):
    code = code.strip().upper()[:3]
    if db.query(Customer).filter(Customer.code == code, Customer.company_id == current_user.company_id).first():
        return templates.TemplateResponse(
            "customers/form.html",
            {"request": request, "current_user": current_user,
             "customer": None, "page_title": "Yeni Müşteri",
             "error": f"'{code}' kodu zaten kullanılıyor."},
            status_code=400,
        )
    c = Customer(
        name=name.strip(), code=code, sector=sector.strip(),
        tax_no=tax_no.strip(), tax_office=tax_office.strip(),
        address=address.strip(), email=email.strip(), phone=phone.strip(),
        payment_term=payment_term.strip() or None,
        payment_dow=int(payment_dow) if payment_dow.strip() else None,
        notes=notes.strip(),
        contacts_json=contacts_json or "[]",
        company_id=current_user.company_id,
        owner_id=current_user.id,
    )
    db.add(c)
    db.commit()
    return RedirectResponse(url="/customers", status_code=status.HTTP_302_FOUND)


@router.get("/{customer_id}", response_class=HTMLResponse, name="customer_detail")
async def customer_detail(
    customer_id: str,
    request: Request,
    period: str = "all",
    current_user: User = Depends(require_module("customers")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    from datetime import timedelta
    if not can_access_customer(db, current_user, customer_id):
        raise HTTPException(status_code=404)
    c = db.query(Customer).filter(Customer.id == customer_id, Customer.company_id == cid).first()
    if not c:
        raise HTTPException(status_code=404)

    today = _date.today()
    inv_q = db.query(Invoice).filter(
        Invoice.customer_id == customer_id,
        Invoice.company_id == cid,
        Invoice.invoice_type.in_(["kesilen", "komisyon", "iade_gelen"]),
    )
    if period != "all":
        cutoff = today - timedelta(days=int(period))
        inv_q = inv_q.filter(Invoice.invoice_date >= cutoff)
    invoices = inv_q.options(joinedload(Invoice.payments)).order_by(Invoice.invoice_date.desc()).all()

    prepayments = (
        db.query(CustomerPrepayment)
        .filter(CustomerPrepayment.customer_id == customer_id, CustomerPrepayment.company_id == cid)
        .order_by(CustomerPrepayment.payment_date.desc())
        .all()
    )
    references = (
        db.query(Reference)
        .filter(Reference.customer_id == customer_id, Reference.company_id == cid)
        .order_by(Reference.ref_no)
        .all()
    )
    cheques = (
        db.query(Cheque)
        .filter(Cheque.customer_id == customer_id, Cheque.company_id == cid, Cheque.cheque_type == "alinan")
        .order_by(Cheque.due_date.desc())
        .all()
    )

    cash_books    = db.query(CashBook).filter(CashBook.company_id == cid).all()
    bank_accounts = db.query(BankAccount).filter(BankAccount.company_id == cid).all()

    # iade_gelen: müşteri iade yaptı → alacağımız azalır → negatif
    def _sign(inv):
        return -1 if inv.invoice_type == "iade_gelen" else 1

    total_amount   = sum(i.total_with_vat * _sign(i) for i in invoices)
    received_amount = sum(i.paid_amount * _sign(i) for i in invoices) + sum(p.amount for p in prepayments)
    unpaid_amount  = sum(i.remaining * _sign(i) for i in invoices if i.status in ("approved", "partial"))
    overdue_amount = sum(
        i.remaining * _sign(i) for i in invoices
        if i.status in ("approved", "partial") and i.collection_date and i.collection_date < today
    )

    return templates.TemplateResponse(
        "customers/detail.html",
        {
            "request": request, "current_user": current_user,
            "customer": c, "invoices": invoices, "cheques": cheques,
            "prepayments": prepayments, "references": references,
            "total_amount": total_amount, "received_amount": received_amount,
            "unpaid_amount": unpaid_amount, "overdue_amount": overdue_amount,
            "period": period, "today": today,
            "cash_books": cash_books, "bank_accounts": bank_accounts,
            "payment_methods": PAYMENT_METHODS,
            "page_title": c.name,
        },
    )


@router.get("/{customer_id}/edit", response_class=HTMLResponse, name="customer_edit_get")
async def customer_edit_get(
    customer_id: str,
    request: Request,
    current_user: User = Depends(require_module("customers", edit=True)),
    db: Session = Depends(get_db),
):
    c = db.query(Customer).filter(Customer.id == customer_id, Customer.company_id == current_user.company_id).first()
    if not c:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        "customers/form.html",
        {"request": request, "current_user": current_user,
         "customer": c, "page_title": f"Düzenle — {c.name}", "error": None},
    )


@router.post("/{customer_id}/edit", name="customer_edit_post")
async def customer_edit_post(
    customer_id: str,
    request: Request,
    name: str = Form(...),
    code: str = Form(...),
    sector: str = Form(""),
    tax_no: str = Form(""),
    tax_office: str = Form(""),
    address: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    payment_term: str = Form(""),
    payment_dow: str = Form(""),
    notes: str = Form(""),
    contacts_json: str = Form("[]"),
    current_user: User = Depends(require_module("customers", edit=True)),
    db: Session = Depends(get_db),
):
    c = db.query(Customer).filter(Customer.id == customer_id, Customer.company_id == current_user.company_id).first()
    if not c:
        raise HTTPException(status_code=404)
    code = code.strip().upper()[:3]
    existing = db.query(Customer).filter(Customer.code == code, Customer.id != customer_id, Customer.company_id == current_user.company_id).first()
    if existing:
        return templates.TemplateResponse(
            "customers/form.html",
            {"request": request, "current_user": current_user,
             "customer": c, "page_title": f"Düzenle — {c.name}",
             "error": f"'{code}' kodu zaten kullanılıyor."},
            status_code=400,
        )
    c.name = name.strip()
    c.code = code
    c.sector = sector.strip()
    c.tax_no = tax_no.strip()
    c.tax_office = tax_office.strip()
    c.address = address.strip()
    c.email = email.strip()
    c.phone = phone.strip()
    c.payment_term = payment_term.strip() or None
    c.payment_dow = int(payment_dow) if payment_dow.strip() else None
    c.notes = notes.strip()
    c.contacts_json = contacts_json or "[]"
    db.commit()
    return RedirectResponse(url=f"/customers/{customer_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{customer_id}/prepayment", name="customer_prepayment")
async def customer_prepayment(
    customer_id: str,
    payment_type: str = Form("prepayment"),
    amount: float = Form(...),
    pay_date: str = Form(""),
    payment_method: str = Form(...),
    ref_id: str = Form(None),
    bank_account_id: str = Form(None),
    cash_book_id: str = Form(None),
    cheque_no: str = Form(""),
    cheque_bank: str = Form(""),
    cheque_date: str = Form(""),
    cheque_due_date: str = Form(""),
    notes: str = Form(""),
    current_user: User = Depends(require_module("customers", edit=True)),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    if not can_access_customer(db, current_user, customer_id):
        raise HTTPException(status_code=404)
    c = db.query(Customer).filter(Customer.id == customer_id, Customer.company_id == cid).first()
    if not c:
        raise HTTPException(status_code=404)

    pdate = _date.fromisoformat(pay_date) if pay_date else _date.today()
    label = "Ön Tahsilat" if payment_type == "prepayment" else "Tahsilat"
    desc = f"{label} — {c.name}"

    pmt = CustomerPrepayment(
        customer_id=customer_id,
        payment_type=payment_type,
        ref_id=ref_id or None,
        payment_date=pdate,
        amount=amount,
        payment_method=payment_method,
        bank_account_id=bank_account_id if payment_method == "banka" else None,
        cash_book_id=cash_book_id if payment_method == "nakit" else None,
        notes=notes.strip(),
        created_by=current_user.id,
        company_id=cid,
    )

    if payment_method == "nakit" and cash_book_id:
        db.add(CashEntry(
            book_id=cash_book_id, entry_date=pdate,
            entry_type="giris", amount=amount, description=desc,
        ))
    elif payment_method == "banka" and bank_account_id:
        db.add(BankMovement(
            account_id=bank_account_id, movement_date=pdate,
            movement_type="giris", amount=amount, description=desc,
        ))
    elif payment_method == "cek":
        cheque = Cheque(
            customer_id=customer_id,
            cheque_type="alinan",
            cheque_no=cheque_no.strip(),
            bank=cheque_bank.strip(),
            amount=amount,
            currency="TRY",
            cheque_date=_date.fromisoformat(cheque_date) if cheque_date else pdate,
            due_date=_date.fromisoformat(cheque_due_date) if cheque_due_date else pdate,
            status="beklemede",
            company_id=cid,
        )
        db.add(cheque)
        db.flush()
        pmt.cheque_id = cheque.id

    db.add(pmt)
    db.commit()
    return RedirectResponse(url=f"/customers/{customer_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{customer_id}/prepayment/{pmt_id}/delete", name="customer_prepayment_delete")
async def customer_prepayment_delete(
    customer_id: str,
    pmt_id: str,
    current_user: User = Depends(require_module("customers", edit=True)),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    if not can_access_customer(db, current_user, customer_id):
        raise HTTPException(status_code=404)
    pmt = db.query(CustomerPrepayment).filter(
        CustomerPrepayment.id == pmt_id,
        CustomerPrepayment.customer_id == customer_id,
        CustomerPrepayment.company_id == cid,
    ).first()
    if pmt:
        db.delete(pmt)
        db.commit()
    return RedirectResponse(url=f"/customers/{customer_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{customer_id}/toggle-active", name="customer_toggle_active")
async def customer_toggle_active(
    customer_id: str,
    current_user: User = Depends(require_module("customers", edit=True)),
    db: Session = Depends(get_db),
):
    c = db.query(Customer).filter(Customer.id == customer_id, Customer.company_id == current_user.company_id).first()
    if c:
        c.active = not c.active
        db.commit()
    return RedirectResponse(url="/customers", status_code=status.HTTP_302_FOUND)


@router.post("/{customer_id}/delete", name="customer_delete")
async def customer_delete(
    customer_id: str,
    current_user: User = Depends(require_module("customers", edit=True)),
    db: Session = Depends(get_db),
):
    c = db.query(Customer).filter(Customer.id == customer_id, Customer.company_id == current_user.company_id).first()
    if c:
        try:
            db.delete(c)
            db.commit()
        except Exception:
            db.rollback()
            return RedirectResponse(
                url="/customers?err=delete_failed",
                status_code=status.HTTP_302_FOUND,
            )
    return RedirectResponse(url="/customers?ok=deleted", status_code=status.HTTP_302_FOUND)
