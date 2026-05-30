"""
PaymentInstruction router — GM onayı sonrası operatör infazı.
- GET  /payment-instructions/inbox            — bekleyen talimatlar listesi
- POST /payment-instructions/{id}/execute     — operatör infaz (yan kayıt + status)
- POST /payment-instructions/{id}/cancel      — pending talimat iptal
- POST /payment-instructions/bulk-execute     — çoklu infaz
"""
from __future__ import annotations

from datetime import date, datetime
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user, get_company_id, require_admin, require_module, safe_redirect
from database import get_db
from models import (
    User, PaymentInstruction, Invoice, Cheque, CreditCardStatement,
    PayrollDecision, BankAccount, CashBook, CreditCard, ManualPaymentLine,
)
from payment_helpers import (
    apply_invoice_payment, apply_cheque_settlement,
    apply_cc_statement_payment, apply_payroll_payment,
    apply_manual_payment,
)
from templates_config import templates


router = APIRouter(prefix="/payment-instructions", tags=["payment_instructions"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _instruction_party_label(instr: PaymentInstruction, db: Session) -> str:
    """Talimat satırında görüntülenecek karşı taraf etiketi."""
    if instr.source_type == "invoice" and instr.source_id:
        inv = db.query(Invoice).get(instr.source_id)
        if inv:
            return inv.vendor.name if inv.vendor else f"Fatura #{inv.id}"
    elif instr.source_type == "cheque" and instr.source_id:
        c = db.query(Cheque).get(instr.source_id)
        if c:
            return (c.vendor.name if c.vendor else None) or f"Çek {c.cheque_no or c.id}"
    elif instr.source_type == "cc_statement" and instr.source_id:
        s = db.query(CreditCardStatement).get(instr.source_id)
        if s:
            return s.card.name if s.card else "KK"
    elif instr.source_type == "payroll":
        return f"Personel maaşı ({instr.source_period})"
    elif instr.source_type == "manual" and instr.source_id:
        line = db.query(ManualPaymentLine).get(instr.source_id)
        if line:
            return (line.party or line.description or "Manuel")[:80]
    return "—"


def _source_label(source_type: str) -> str:
    return {
        "invoice": "Fatura", "cheque": "Çek",
        "cc_statement": "KK Ekstre", "payroll": "Maaş",
        "manual": "Manuel",
    }.get(source_type, source_type)


# ---------------------------------------------------------------------------
# Inbox
# ---------------------------------------------------------------------------

@router.get("/inbox", response_class=HTMLResponse, name="payment_instructions_inbox")
async def inbox(
    request: Request,
    current_user: User = Depends(require_module("payment_instructions")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    """Bekleyen ödeme talimatları."""
    pending = db.query(PaymentInstruction).filter(
        PaymentInstruction.company_id == cid,
        PaymentInstruction.status == "pending"
    ).order_by(PaymentInstruction.created_at.asc()).all()

    rows = []
    for instr in pending:
        rows.append({
            "id": instr.id,
            "source_type": instr.source_type,
            "source_label": _source_label(instr.source_type),
            "party": _instruction_party_label(instr, db),
            "amount": instr.amount,
            "method": instr.payment_method,
            "note": instr.note,
            "created_at": instr.created_at,
            "creator": instr.creator.name if instr.creator else "—",
        })

    bank_accounts = db.query(BankAccount).filter(BankAccount.company_id == cid).order_by(BankAccount.name).all()
    cash_books = db.query(CashBook).filter(CashBook.company_id == cid).order_by(CashBook.name).all()
    credit_cards = db.query(CreditCard).filter(CreditCard.company_id == cid).order_by(CreditCard.name).all()

    return templates.TemplateResponse(
        "payment_instructions/inbox.html",
        {
            "request": request, "current_user": current_user,
            "page_title": "Bekleyen Ödeme Talimatları",
            "rows": rows,
            "bank_accounts": bank_accounts,
            "cash_books": cash_books,
            "credit_cards": credit_cards,
        },
    )


# ---------------------------------------------------------------------------
# Execute (operatör infaz)
# ---------------------------------------------------------------------------

@router.post("/{instruction_id}/execute", name="payment_instruction_execute")
async def execute_instruction(
    instruction_id: str,
    pay_date: str = Form(""),
    bank_account_id: str = Form(None),
    cash_book_id: str = Form(None),
    credit_card_id: str = Form(None),
    cheque_no: str = Form(""),
    cheque_bank: str = Form(""),
    cheque_due_date: str = Form(""),
    pay_notes: str = Form(""),
    redirect_url: str = Form("/payment-instructions/inbox"),
    current_user: User = Depends(require_module("payment_instructions")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    instr = db.query(PaymentInstruction).filter(
        PaymentInstruction.id == instruction_id,
        PaymentInstruction.company_id == cid,
    ).first()
    if not instr:
        raise HTTPException(404, "Talimat bulunamadı")
    if instr.status != "pending":
        raise HTTPException(400, f"Talimat zaten {instr.status}")

    pdate = date.fromisoformat(pay_date) if pay_date else date.today()

    if instr.source_type == "invoice":
        inv = db.query(Invoice).get(instr.source_id)
        if not inv:
            raise HTTPException(404, "Fatura bulunamadı")
        apply_invoice_payment(
            db, inv,
            payment_method=instr.payment_method, amount=instr.amount, pdate=pdate,
            current_user=current_user,
            cash_book_id=cash_book_id, bank_account_id=bank_account_id,
            credit_card_id=credit_card_id,
            cheque_no=cheque_no, cheque_bank=cheque_bank,
            cheque_due_date_str=cheque_due_date,
            pay_notes=pay_notes,
            instruction_id=instr.id,
        )
    elif instr.source_type == "cheque":
        c = db.query(Cheque).get(instr.source_id)
        if not c:
            raise HTTPException(404, "Çek bulunamadı")
        apply_cheque_settlement(
            db, c,
            payment_method=instr.payment_method, pdate=pdate,
            cash_book_id=cash_book_id, bank_account_id=bank_account_id,
            credit_card_id=credit_card_id,
            instruction_id=instr.id,
        )
    elif instr.source_type == "cc_statement":
        s = db.query(CreditCardStatement).get(instr.source_id)
        if not s:
            raise HTTPException(404, "KK ekstre bulunamadı")
        apply_cc_statement_payment(
            db, s,
            payment_method=instr.payment_method, pdate=pdate,
            bank_account_id=bank_account_id, cash_book_id=cash_book_id,
            other_credit_card_id=credit_card_id,
            instruction_id=instr.id,
        )
    elif instr.source_type == "payroll":
        if not instr.source_period:
            raise HTTPException(400, "Maaş periyodu eksik")
        apply_payroll_payment(
            db, instr.source_period,
            payment_method=instr.payment_method, pdate=pdate,
            current_user=current_user,
            cash_book_id=cash_book_id, bank_account_id=bank_account_id,
            instruction_id=instr.id,
        )
        # PayrollDecision'ı executed olarak işaretle
        pd = db.query(PayrollDecision).filter(
            PayrollDecision.period == instr.source_period
        ).first()
        if pd:
            pd.gm_decision = "approved"  # zaten 'approved' olmalı, garanti
    elif instr.source_type == "manual":
        line = db.query(ManualPaymentLine).get(instr.source_id)
        if not line:
            raise HTTPException(404, "Manuel kalem bulunamadı")
        apply_manual_payment(
            db, line,
            payment_method=instr.payment_method, amount=instr.amount, pdate=pdate,
            cash_book_id=cash_book_id, bank_account_id=bank_account_id,
            credit_card_id=credit_card_id,
            instruction_id=instr.id,
        )
    else:
        raise HTTPException(400, "Geçersiz kaynak tipi")

    # Talimatı executed işaretle ve hedef hesabı sakla
    instr.status = "executed"
    instr.executed_at = datetime.utcnow()
    instr.executed_by = current_user.id
    if bank_account_id:
        instr.target_bank_account_id = bank_account_id
    if cash_book_id:
        instr.target_cash_book_id = cash_book_id
    if credit_card_id:
        instr.target_credit_card_id = credit_card_id

    db.commit()
    return RedirectResponse(url=safe_redirect(redirect_url, "/payment-instructions/inbox"), status_code=303)


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

@router.post("/{instruction_id}/cancel", name="payment_instruction_cancel")
async def cancel_instruction(
    instruction_id: str,
    cancel_reason: str = Form(...),
    redirect_url: str = Form("/payment-instructions/inbox"),
    current_user: User = Depends(require_module("payment_instructions", edit=True)),
    db: Session = Depends(get_db),
):
    """Pending talimatı iptal et (admin yetkili)."""
    instr = db.query(PaymentInstruction).filter(
        PaymentInstruction.id == instruction_id,
        PaymentInstruction.company_id == current_user.company_id,
    ).first()
    if not instr:
        raise HTTPException(404, "Talimat bulunamadı")
    if instr.status != "pending":
        raise HTTPException(400, f"Sadece pending talimat iptal edilebilir (mevcut: {instr.status})")
    if not (cancel_reason or "").strip():
        raise HTTPException(400, "İptal nedeni gerekli")
    instr.status = "cancelled"
    instr.cancelled_at = datetime.utcnow()
    instr.cancelled_by = current_user.id
    instr.cancel_reason = cancel_reason.strip()
    db.commit()
    return RedirectResponse(url=safe_redirect(redirect_url, "/payment-instructions/inbox"), status_code=303)


# ---------------------------------------------------------------------------
# Pending instruction yardımcısı — payments.py decide endpoint'i çağıracak
# ---------------------------------------------------------------------------

def get_pending_for_source(db: Session, source_type: str, source_id_or_period) -> PaymentInstruction:
    """Aynı kaynak için aktif pending talimatı döndür (varsa)."""
    q = db.query(PaymentInstruction).filter(
        PaymentInstruction.source_type == source_type,
        PaymentInstruction.status == "pending",
    )
    if source_type == "payroll":
        q = q.filter(PaymentInstruction.source_period == str(source_id_or_period))
    else:
        q = q.filter(PaymentInstruction.source_id == int(source_id_or_period))
    return q.first()


def create_instruction(
    db: Session, *, source_type: str, source_id_or_period,
    amount: float, payment_method: str, note: str, current_user: User,
    company_id: str = None,
) -> PaymentInstruction:
    """Yeni pending talimat oluştur. Aynı kaynak için pending varsa hata."""
    if get_pending_for_source(db, source_type, source_id_or_period):
        raise HTTPException(
            409, "Bu kalem için zaten bekleyen bir ödeme talimatı var (önce iptal edin)"
        )
    if source_type == "payroll":
        instr = PaymentInstruction(
            source_type="payroll", source_id=None, source_period=str(source_id_or_period),
            amount=amount, payment_method=payment_method, note=note,
            status="pending", created_by=current_user.id,
            company_id=company_id,
        )
    else:
        instr = PaymentInstruction(
            source_type=source_type, source_id=int(source_id_or_period),
            source_period=None,
            amount=amount, payment_method=payment_method, note=note,
            status="pending", created_by=current_user.id,
            company_id=company_id,
        )
    db.add(instr)
    db.flush()
    return instr


def cancel_pending_for_source(db: Session, source_type: str, source_id_or_period, user_id: str, reason: str) -> None:
    """Kaynak için pending talimat varsa iptal et (GM red/onay-geri-çekme akışı için)."""
    instr = get_pending_for_source(db, source_type, source_id_or_period)
    if instr:
        instr.status = "cancelled"
        instr.cancelled_at = datetime.utcnow()
        instr.cancelled_by = user_id
        instr.cancel_reason = reason
