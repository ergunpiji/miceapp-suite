"""
Kredi kartı yönetimi
"""

from datetime import date, datetime, timedelta
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from auth import get_current_user, require_admin, require_module, get_company_id
from database import get_db
from models import CreditCard, CreditCardTxn, CreditCardStatement, User, BankAccount
from templates_config import templates

router = APIRouter(prefix="/credit-cards", tags=["credit_cards"])


def _used_limit(db, card_id):
    """Açık (ödenmemiş) ekstre + ekstre dışı işlemlerden kullanılan limit."""
    unpaid = db.query(func.sum(CreditCardStatement.total_amount)).filter(
        CreditCardStatement.card_id == card_id,
        CreditCardStatement.status == "unpaid",
    ).scalar() or 0
    unassigned = db.query(func.sum(CreditCardTxn.amount)).filter(
        CreditCardTxn.card_id == card_id,
        CreditCardTxn.statement_id == None,  # noqa: E711
        CreditCardTxn.is_refund == False,  # noqa: E712
    ).scalar() or 0
    return unpaid + unassigned


def _next_due_date(card: CreditCard) -> date:
    today = date.today()
    stmt_day = card.statement_day
    if today.day <= stmt_day:
        stmt_month = today.month
    else:
        stmt_month = today.month + 1 if today.month < 12 else 1
    stmt_year = today.year if stmt_month >= today.month else today.year + 1
    try:
        stmt_date = date(stmt_year, stmt_month, stmt_day)
    except ValueError:
        import calendar
        last_day = calendar.monthrange(stmt_year, stmt_month)[1]
        stmt_date = date(stmt_year, stmt_month, last_day)
    return stmt_date + timedelta(days=card.payment_offset_days)


@router.get("", response_class=HTMLResponse, name="credit_cards_list")
async def credit_cards_list(
    request: Request,
    current_user: User = Depends(require_module("credit_cards")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    cards = db.query(CreditCard).filter(CreditCard.company_id == cid).order_by(CreditCard.name).all()
    cards_with_info = [
        {"card": c, "used": _used_limit(db, c.id),
         "available": max(0, c.credit_limit - _used_limit(db, c.id))}
        for c in cards
    ]
    return templates.TemplateResponse(
        "credit_cards/list.html",
        {"request": request, "current_user": current_user,
         "cards_with_info": cards_with_info, "page_title": "Kredi Kartları"},
    )


@router.get("/new", response_class=HTMLResponse, name="credit_card_new_get")
async def credit_card_new_get(
    request: Request,
    current_user: User = Depends(require_module("credit_cards", edit=True)),
):
    return templates.TemplateResponse(
        "credit_cards/form.html",
        {"request": request, "current_user": current_user,
         "card": None, "page_title": "Yeni Kredi Kartı"},
    )


@router.post("/new", name="credit_card_new_post")
async def credit_card_new_post(
    name: str = Form(...),
    bank_name: str = Form(""),
    last4: str = Form(""),
    credit_limit: float = Form(0.0),
    statement_day: int = Form(1),
    payment_offset_days: int = Form(10),
    currency: str = Form("TRY"),
    current_user: User = Depends(require_module("credit_cards", edit=True)),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    c = CreditCard(
        name=name.strip(), bank_name=bank_name.strip(),
        last4=last4.strip()[-4:] if last4 else "",
        credit_limit=credit_limit, statement_day=statement_day,
        payment_offset_days=payment_offset_days, currency=currency,
        company_id=cid,
    )
    db.add(c)
    db.commit()
    return RedirectResponse(url=f"/credit-cards/{c.id}", status_code=status.HTTP_302_FOUND)


@router.get("/{card_id}", response_class=HTMLResponse, name="credit_card_detail")
async def credit_card_detail(
    card_id: str,
    request: Request,
    current_user: User = Depends(require_module("credit_cards")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    card = db.query(CreditCard).filter(CreditCard.id == card_id, CreditCard.company_id == cid).first()
    if not card:
        raise HTTPException(status_code=404)
    statements = db.query(CreditCardStatement).filter(
        CreditCardStatement.card_id == card_id,
        CreditCardStatement.company_id == cid,
    ).order_by(CreditCardStatement.statement_date.desc()).all()
    unassigned_txns = db.query(CreditCardTxn).filter(
        CreditCardTxn.card_id == card_id,
        CreditCardTxn.company_id == cid,
        CreditCardTxn.statement_id == None,  # noqa: E711
    ).order_by(CreditCardTxn.txn_date.desc()).all()
    used = _used_limit(db, card_id)
    bank_accounts = db.query(BankAccount).filter(BankAccount.company_id == cid).order_by(BankAccount.name).all()
    return templates.TemplateResponse(
        "credit_cards/detail.html",
        {
            "request": request, "current_user": current_user,
            "card": card, "statements": statements,
            "unassigned_txns": unassigned_txns,
            "used": used, "available": max(0, card.credit_limit - used),
            "next_due_date": _next_due_date(card),
            "bank_accounts": bank_accounts,
            "page_title": card.name,
        },
    )


@router.post("/{card_id}/txn", name="credit_card_txn_add")
async def credit_card_txn_add(
    card_id: str,
    txn_date: str = Form(...),
    amount: float = Form(...),
    description: str = Form(""),
    is_refund: str = Form("0"),
    current_user: User = Depends(require_module("credit_cards")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    card = db.query(CreditCard).filter(CreditCard.id == card_id, CreditCard.company_id == cid).first()
    if not card:
        raise HTTPException(status_code=404)
    refund = is_refund == "1"
    if not refund:
        used = _used_limit(db, card_id)
        if used + amount > card.credit_limit:
            raise HTTPException(status_code=400,
                                detail=f"Limit yetersiz. Kullanılabilir: ₺{card.credit_limit - used:,.2f}")
    db.add(CreditCardTxn(
        card_id=card_id,
        txn_date=date.fromisoformat(txn_date),
        amount=amount,
        description=description.strip(),
        is_refund=refund,
        company_id=cid,
    ))
    db.commit()
    return RedirectResponse(url=f"/credit-cards/{card_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{card_id}/statement", name="credit_card_statement_close")
async def credit_card_statement_close(
    card_id: str,
    statement_date: str = Form(...),
    due_date: str = Form(...),
    current_user: User = Depends(require_module("credit_cards")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    card = db.query(CreditCard).filter(CreditCard.id == card_id, CreditCard.company_id == cid).first()
    if not card:
        raise HTTPException(status_code=404)
    unassigned = db.query(CreditCardTxn).filter(
        CreditCardTxn.card_id == card_id,
        CreditCardTxn.company_id == cid,
        CreditCardTxn.statement_id == None,  # noqa: E711
    ).all()
    total = sum(t.amount for t in unassigned if not t.is_refund) - sum(t.amount for t in unassigned if t.is_refund)
    stmt = CreditCardStatement(
        card_id=card_id,
        statement_date=date.fromisoformat(statement_date),
        due_date=date.fromisoformat(due_date),
        total_amount=total,
        status="unpaid",
        company_id=cid,
    )
    db.add(stmt)
    db.flush()
    for t in unassigned:
        t.statement_id = stmt.id
    db.commit()
    return RedirectResponse(url=f"/credit-cards/{card_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{card_id}/statement/{stmt_id}/pay", name="credit_card_statement_pay")
async def credit_card_statement_pay(
    card_id: str,
    stmt_id: str,
    payment_method: str = Form("banka"),
    bank_account_id: str = Form(None),
    cash_book_id: str = Form(None),
    pay_date: str = Form(""),
    current_user: User = Depends(require_module("credit_cards")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    """KK ekstresini öder + ödeme kaynağı hesapta yan kayıt oluşturur (bug fix)."""
    from payment_helpers import apply_cc_statement_payment
    stmt = db.query(CreditCardStatement).filter(
        CreditCardStatement.id == stmt_id, CreditCardStatement.company_id == cid
    ).first()
    if not stmt or stmt.card_id != card_id:
        raise HTTPException(status_code=404)
    pdate = date.fromisoformat(pay_date) if pay_date else date.today()
    apply_cc_statement_payment(
        db, stmt,
        payment_method=payment_method, pdate=pdate,
        bank_account_id=bank_account_id, cash_book_id=cash_book_id,
    )
    db.commit()
    return RedirectResponse(url=f"/credit-cards/{card_id}", status_code=status.HTTP_302_FOUND)
