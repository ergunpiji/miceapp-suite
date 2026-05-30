"""Finans Ajanı — Kredi Kartı Takibi"""
from datetime import date, timedelta
from calendar import monthrange

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from database import get_db
from models import (
    CreditCard, CreditCardTxn, CreditCardStatement,
    CC_STATEMENT_STATUSES, CC_STATEMENT_LABELS,
)
from templates_config import templates

router = APIRouter(prefix="/credit-cards", tags=["credit_cards"])


def _billing_dates(card: CreditCard, ref_date: date) -> tuple[date, date]:
    """Verilen tarihe göre son ekstre kesim tarihi ve son ödeme tarihini hesapla."""
    billing_day = min(card.billing_day, monthrange(ref_date.year, ref_date.month)[1])
    if ref_date.day <= billing_day:
        stmt_date = date(ref_date.year, ref_date.month, billing_day)
    else:
        next_m = ref_date.replace(day=1) + timedelta(days=32)
        stmt_date = date(next_m.year, next_m.month, min(billing_day, monthrange(next_m.year, next_m.month)[1]))

    due = stmt_date + timedelta(days=card.due_day_offset)
    return stmt_date, due


# ---------------------------------------------------------------------------
# Kart listesi
# ---------------------------------------------------------------------------
@router.get("", response_class=HTMLResponse, name="credit_cards_list")
async def credit_cards_list(request: Request, db: Session = Depends(get_db)):
    cards = db.query(CreditCard).order_by(CreditCard.name).all()
    today = date.today()
    overdue_statements = (
        db.query(CreditCardStatement)
        .filter(
            CreditCardStatement.status != "odendi",
            CreditCardStatement.due_date < today,
        )
        .all()
    )
    return templates.TemplateResponse(
        request,
        "credit_cards/list.html",
        {
            "active": "credit_cards",
            "cards": cards,
            "overdue_statements": overdue_statements,
            "today": today,
        },
    )


# ---------------------------------------------------------------------------
# Yeni kart
# ---------------------------------------------------------------------------
@router.get("/new", response_class=HTMLResponse, name="credit_card_new")
async def credit_card_new(request: Request):
    return templates.TemplateResponse(
        request,
        "credit_cards/form.html",
        {"active": "credit_cards", "card": None},
    )


@router.post("/new")
async def credit_card_create(
    name: str = Form(...),
    bank: str = Form(""),
    last_four: str = Form(""),
    credit_limit: float = Form(0.0),
    billing_day: int = Form(1),
    due_day_offset: int = Form(10),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    card = CreditCard(
        name=name,
        bank=bank or None,
        last_four=last_four[-4:] if last_four else None,
        credit_limit=credit_limit,
        billing_day=billing_day,
        due_day_offset=due_day_offset,
        notes=notes or None,
    )
    db.add(card)
    db.commit()
    return RedirectResponse(url=f"/credit-cards/{card.id}", status_code=303)


# ---------------------------------------------------------------------------
# Kart detay
# ---------------------------------------------------------------------------
@router.get("/{card_id}", response_class=HTMLResponse, name="credit_card_detail")
async def credit_card_detail(card_id: str, request: Request, db: Session = Depends(get_db)):
    card = db.query(CreditCard).filter(CreditCard.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Kart bulunamadı.")

    today = date.today()
    stmt_date, due_date = _billing_dates(card, today)

    # Mevcut döneme ait (ekstreye atanmamış) harcamalar
    open_txns = (
        db.query(CreditCardTxn)
        .filter(
            CreditCardTxn.card_id == card_id,
            CreditCardTxn.statement_id == None,
        )
        .order_by(CreditCardTxn.txn_date.desc())
        .all()
    )

    # Ekstreler
    statements = (
        db.query(CreditCardStatement)
        .filter(CreditCardStatement.card_id == card_id)
        .order_by(CreditCardStatement.statement_date.desc())
        .all()
    )

    open_total = sum(t.amount for t in open_txns if not t.is_refund)

    return templates.TemplateResponse(
        request,
        "credit_cards/detail.html",
        {
            "active": "credit_cards",
            "card": card,
            "open_txns": open_txns,
            "open_total": open_total,
            "statements": statements,
            "next_stmt_date": stmt_date,
            "next_due_date": due_date,
            "today": today,
            "status_labels": CC_STATEMENT_LABELS,
        },
    )


# ---------------------------------------------------------------------------
# Kart düzenle
# ---------------------------------------------------------------------------
@router.get("/{card_id}/edit", response_class=HTMLResponse, name="credit_card_edit")
async def credit_card_edit(card_id: str, request: Request, db: Session = Depends(get_db)):
    card = db.query(CreditCard).filter(CreditCard.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request,
        "credit_cards/form.html",
        {"active": "credit_cards", "card": card},
    )


@router.post("/{card_id}/edit")
async def credit_card_update(
    card_id: str,
    name: str = Form(...),
    bank: str = Form(""),
    last_four: str = Form(""),
    credit_limit: float = Form(0.0),
    billing_day: int = Form(1),
    due_day_offset: int = Form(10),
    is_active: bool = Form(True),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    card = db.query(CreditCard).filter(CreditCard.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404)
    card.name = name
    card.bank = bank or None
    card.last_four = last_four[-4:] if last_four else None
    card.credit_limit = credit_limit
    card.billing_day = billing_day
    card.due_day_offset = due_day_offset
    card.is_active = is_active
    card.notes = notes or None
    db.commit()
    return RedirectResponse(url=f"/credit-cards/{card_id}", status_code=303)


# ---------------------------------------------------------------------------
# Harcama ekle
# ---------------------------------------------------------------------------
@router.post("/{card_id}/txns/add")
async def txn_add(
    card_id: str,
    txn_date: str = Form(...),
    description: str = Form(...),
    amount: float = Form(0.0),
    category: str = Form(""),
    is_refund: bool = Form(False),
    installments: int = Form(1),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    card = db.query(CreditCard).filter(CreditCard.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404)

    if installments > 1:
        # Her taksit için ayrı kayıt
        unit = round(amount / installments, 2)
        for i in range(1, installments + 1):
            txn = CreditCardTxn(
                card_id=card_id,
                txn_date=date.fromisoformat(txn_date),
                description=f"{description} ({i}/{installments}. taksit)",
                amount=unit,
                category=category or None,
                is_refund=is_refund,
                installments=installments,
                installment_no=i,
                notes=notes or None,
            )
            db.add(txn)
    else:
        txn = CreditCardTxn(
            card_id=card_id,
            txn_date=date.fromisoformat(txn_date),
            description=description,
            amount=amount,
            category=category or None,
            is_refund=is_refund,
            notes=notes or None,
        )
        db.add(txn)
    db.commit()
    return RedirectResponse(url=f"/credit-cards/{card_id}", status_code=303)


# ---------------------------------------------------------------------------
# Ekstre oluştur
# ---------------------------------------------------------------------------
@router.post("/{card_id}/statements/create")
async def statement_create(
    card_id: str,
    statement_date: str = Form(...),
    due_date: str = Form(...),
    total_amount: float = Form(0.0),
    minimum_payment: float = Form(0.0),
    db: Session = Depends(get_db),
):
    card = db.query(CreditCard).filter(CreditCard.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404)

    stmt = CreditCardStatement(
        card_id=card_id,
        statement_date=date.fromisoformat(statement_date),
        due_date=date.fromisoformat(due_date),
        total_amount=total_amount,
        minimum_payment=minimum_payment,
    )
    db.add(stmt)
    db.flush()

    # Açık harcamaları bu ekstreye bağla
    open_txns = db.query(CreditCardTxn).filter(
        CreditCardTxn.card_id == card_id,
        CreditCardTxn.statement_id == None,
    ).all()
    for t in open_txns:
        t.statement_id = stmt.id

    if total_amount == 0:
        stmt.total_amount = round(sum(t.amount for t in open_txns if not t.is_refund), 2)

    db.commit()
    return RedirectResponse(url=f"/credit-cards/{card_id}", status_code=303)


# ---------------------------------------------------------------------------
# Ekstre öde
# ---------------------------------------------------------------------------
@router.post("/{card_id}/statements/{stmt_id}/pay")
async def statement_pay(
    card_id: str,
    stmt_id: str,
    paid_amount: float = Form(0.0),
    payment_date: str = Form(""),
    db: Session = Depends(get_db),
):
    stmt = db.query(CreditCardStatement).filter(
        CreditCardStatement.id == stmt_id,
        CreditCardStatement.card_id == card_id,
    ).first()
    if not stmt:
        raise HTTPException(status_code=404)
    stmt.paid_amount += paid_amount
    stmt.payment_date = date.fromisoformat(payment_date) if payment_date else date.today()
    if stmt.paid_amount >= stmt.total_amount:
        stmt.status = "odendi"
    elif stmt.paid_amount > 0:
        stmt.status = "kismi"
    db.commit()
    return RedirectResponse(url=f"/credit-cards/{card_id}", status_code=303)
