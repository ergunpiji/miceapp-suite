"""
Ortak ödeme helper'ları — hem manuel endpoint'ler hem PaymentInstruction.execute
aynı mantığı kullansın diye.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import (
    Invoice, InvoicePayment, Cheque, CreditCardStatement, CreditCardTxn,
    BankMovement, CashEntry, BankAccount, CashBook, CreditCard,
    Employee, SalaryPayment, GeneralExpense, GeneralExpenseCategory,
    PayrollDecision, User, ManualPaymentLine,
)


# ---------------------------------------------------------------------------
# Invoice ödeme
# ---------------------------------------------------------------------------

def apply_invoice_payment(
    db: Session,
    inv: Invoice,
    *,
    payment_method: str,
    amount: float,
    pdate: date,
    current_user: User,
    cash_book_id: Optional[int] = None,
    bank_account_id: Optional[int] = None,
    credit_card_id: Optional[int] = None,
    cheque_no: str = "",
    cheque_bank: str = "",
    cheque_date_str: str = "",
    cheque_due_date_str: str = "",
    pay_notes: str = "",
    instruction_id: Optional[int] = None,
) -> InvoicePayment:
    """
    Faturaya InvoicePayment + yan kayıt yarat, status güncelle.
    Hedef hesap (cash_book_id / bank_account_id / credit_card_id) zorunlu;
    cek için cheque_no/cheque_bank/due_date opsiyonel.
    """
    if not inv:
        raise HTTPException(400, "Fatura bulunamadı")
    if inv.status == "paid":
        raise HTTPException(400, "Fatura zaten ödendi")

    amount = min(amount, inv.remaining)
    is_income = inv.invoice_type in ("kesilen", "komisyon")
    flow = "giris" if is_income else "cikis"
    desc = f"Fatura {inv.invoice_no or inv.id}" + (f" — {inv.vendor.name}" if inv.vendor else "")

    pmt = InvoicePayment(
        invoice_id=inv.id,
        payment_date=pdate,
        amount=amount,
        payment_method=payment_method,
        notes=(pay_notes or "").strip(),
        created_by=current_user.id,
        instruction_id=instruction_id,
    )

    if payment_method == "nakit":
        if not cash_book_id:
            raise HTTPException(400, "Nakit ödeme için kasa seçilmeli")
        pmt.cash_book_id = cash_book_id
        db.add(CashEntry(
            book_id=cash_book_id, entry_date=pdate, entry_type=flow,
            amount=amount, description=desc, invoice_id=inv.id, ref_id=inv.ref_id,
            instruction_id=instruction_id,
        ))
    elif payment_method == "banka":
        if not bank_account_id:
            raise HTTPException(400, "Banka ödeme için hesap seçilmeli")
        pmt.bank_account_id = bank_account_id
        db.add(BankMovement(
            account_id=bank_account_id, movement_date=pdate, movement_type=flow,
            amount=amount, description=desc, invoice_id=inv.id, ref_id=inv.ref_id,
            instruction_id=instruction_id,
        ))
    elif payment_method == "kredi_karti":
        if not credit_card_id:
            raise HTTPException(400, "Kredi kartı ödeme için kart seçilmeli")
        pmt.credit_card_id = credit_card_id
        db.add(CreditCardTxn(
            card_id=credit_card_id, txn_date=pdate,
            amount=amount, description=desc, invoice_id=inv.id, ref_id=inv.ref_id,
            instruction_id=instruction_id,
        ))
    elif payment_method == "cek":
        cheque = Cheque(
            vendor_id=inv.vendor_id,
            cheque_type="alinan" if is_income else "verilen",
            cheque_no=(cheque_no or "").strip(),
            bank=(cheque_bank or "").strip(),
            amount=amount,
            currency=inv.currency,
            cheque_date=date.fromisoformat(cheque_date_str) if cheque_date_str else pdate,
            due_date=date.fromisoformat(cheque_due_date_str) if cheque_due_date_str else pdate,
            status="beklemede",
            created_by_instruction_id=instruction_id,
        )
        db.add(cheque)
        db.flush()
        pmt.cheque_id = cheque.id
    else:
        raise HTTPException(400, "Geçersiz ödeme yöntemi")

    db.add(pmt)
    db.flush()

    total = inv.total_with_vat
    new_paid = sum(p.amount for p in inv.payments)
    if new_paid >= total - 0.01:
        inv.status = "paid"
        inv.payment_status = "paid"
        inv.paid_at = datetime.utcnow()
        inv.payment_method = payment_method
    else:
        inv.status = "partial"
        inv.payment_status = "partial"

    return pmt


# ---------------------------------------------------------------------------
# Çek (verilen) ödeme — banka/kasa/KK/yeni çek ile
# ---------------------------------------------------------------------------

def apply_cheque_settlement(
    db: Session,
    cheque: Cheque,
    *,
    payment_method: str,
    pdate: date,
    cash_book_id: Optional[int] = None,
    bank_account_id: Optional[int] = None,
    credit_card_id: Optional[int] = None,
    instruction_id: Optional[int] = None,
) -> None:
    """Verilen çek tahsil_edildi durumuna geçer + yan kayıt oluşturur."""
    if cheque.status != "beklemede":
        raise HTTPException(400, "Çek zaten işlem görmüş")
    if cheque.cheque_type != "verilen":
        raise HTTPException(400, "Bu helper yalnızca verilen çekler için")

    desc = f"Çek tahsilat — {cheque.cheque_no or cheque.id}"
    flow = "cikis"  # verilen çek tahsil edildi = paramız bizden çıktı

    if payment_method == "banka":
        if not bank_account_id:
            raise HTTPException(400, "Banka hesabı seçilmeli")
        db.add(BankMovement(
            account_id=bank_account_id, movement_date=pdate, movement_type=flow,
            amount=cheque.amount, description=desc, instruction_id=instruction_id,
        ))
    elif payment_method == "nakit":
        if not cash_book_id:
            raise HTTPException(400, "Kasa seçilmeli")
        db.add(CashEntry(
            book_id=cash_book_id, entry_date=pdate, entry_type=flow,
            amount=cheque.amount, description=desc, instruction_id=instruction_id,
        ))
    elif payment_method == "kredi_karti":
        if not credit_card_id:
            raise HTTPException(400, "Kart seçilmeli")
        db.add(CreditCardTxn(
            card_id=credit_card_id, txn_date=pdate,
            amount=cheque.amount, description=desc, instruction_id=instruction_id,
        ))
    else:
        raise HTTPException(400, "Çek tahsilatı için geçersiz yöntem")

    cheque.status = "tahsil_edildi"


# ---------------------------------------------------------------------------
# KK Ekstre ödeme — bug fix: BankMovement/CashEntry oluşturuyor artık
# ---------------------------------------------------------------------------

def apply_cc_statement_payment(
    db: Session,
    stmt: CreditCardStatement,
    *,
    payment_method: str,
    pdate: date,
    cash_book_id: Optional[int] = None,
    bank_account_id: Optional[int] = None,
    other_credit_card_id: Optional[int] = None,
    instruction_id: Optional[int] = None,
) -> None:
    """KK ekstresini öder + ödeme kaynağına yan kayıt oluşturur."""
    if stmt.status != "unpaid":
        raise HTTPException(400, "Ekstre zaten ödenmiş")

    desc = f"KK ekstre ödemesi — {stmt.card.name if stmt.card else ''} {stmt.statement_date.isoformat()}"

    if payment_method == "banka":
        if not bank_account_id:
            raise HTTPException(400, "Banka hesabı seçilmeli")
        db.add(BankMovement(
            account_id=bank_account_id, movement_date=pdate, movement_type="cikis",
            amount=stmt.total_amount, description=desc, instruction_id=instruction_id,
        ))
    elif payment_method == "nakit":
        if not cash_book_id:
            raise HTTPException(400, "Kasa seçilmeli")
        db.add(CashEntry(
            book_id=cash_book_id, entry_date=pdate, entry_type="cikis",
            amount=stmt.total_amount, description=desc, instruction_id=instruction_id,
        ))
    elif payment_method == "kredi_karti":
        if not other_credit_card_id or other_credit_card_id == stmt.card_id:
            raise HTTPException(400, "Farklı bir KK seçilmeli")
        db.add(CreditCardTxn(
            card_id=other_credit_card_id, txn_date=pdate,
            amount=stmt.total_amount, description=desc, instruction_id=instruction_id,
        ))
    elif payment_method == "cek":
        # KK ekstresini çek ile öderken yeni çek yaratıp instruction'a bağlamak gerekiyor
        # ama bu rotanın UI'da pratik karşılığı zayıf — şimdilik desteklemiyoruz
        raise HTTPException(400, "KK ekstresi çek ile ödenemez")
    else:
        raise HTTPException(400, "Geçersiz ödeme yöntemi")

    stmt.status = "paid"
    stmt.paid_at = datetime.utcnow()


# ---------------------------------------------------------------------------
# Maaş (period) toplu ödeme
# ---------------------------------------------------------------------------

def apply_payroll_payment(
    db: Session,
    period: str,
    *,
    payment_method: str,
    pdate: date,
    current_user: User,
    cash_book_id: Optional[int] = None,
    bank_account_id: Optional[int] = None,
    instruction_id: Optional[int] = None,
) -> dict:
    """
    Period için ödenmemiş aktif çalışanlara SalaryPayment + GeneralExpense yarat,
    toplu BankMovement/CashEntry oluştur.
    """
    paid_ids = {p.employee_id for p in db.query(SalaryPayment).filter(
        SalaryPayment.period == period
    ).all()}
    employees = db.query(Employee).filter(Employee.active == True).all()  # noqa: E712
    unpaid = [e for e in employees if e.id not in paid_ids]
    if not unpaid:
        raise HTTPException(400, f"{period} için ödenecek maaş yok")

    total = sum(e.net_salary or 0 for e in unpaid)
    if total <= 0:
        raise HTTPException(400, "Toplam maaş 0")

    # Personel/Maaş kategorisini bul (yoksa "Diğer/Maaş" gibi en yakın)
    cat = db.query(GeneralExpenseCategory).filter(
        GeneralExpenseCategory.name == "Maaş"
    ).first()
    if not cat:
        cat = db.query(GeneralExpenseCategory).filter(
            GeneralExpenseCategory.name.ilike("%maaş%")
        ).first()

    if payment_method not in ("banka", "nakit"):
        # KK/çek ile maaş ödeme nadiren olur, şimdilik desteklemiyoruz
        raise HTTPException(400, "Maaş için banka veya nakit gerekli")

    desc = f"Maaş ödemesi — {period} ({len(unpaid)} kişi)"
    flow = "cikis"
    if payment_method == "banka":
        if not bank_account_id:
            raise HTTPException(400, "Banka hesabı seçilmeli")
        db.add(BankMovement(
            account_id=bank_account_id, movement_date=pdate, movement_type=flow,
            amount=total, description=desc, instruction_id=instruction_id,
        ))
    else:
        if not cash_book_id:
            raise HTTPException(400, "Kasa seçilmeli")
        db.add(CashEntry(
            book_id=cash_book_id, entry_date=pdate, entry_type=flow,
            amount=total, description=desc, instruction_id=instruction_id,
        ))

    # Her çalışan için SalaryPayment + GeneralExpense
    for e in unpaid:
        amt = e.net_salary or 0
        ge = GeneralExpense(
            category_id=cat.id if cat else None,
            expense_date=pdate,
            amount=amt,
            description=f"Maaş {period} — {e.name}",
            employee_id=e.id,
            source="salary",
        )
        db.add(ge)
        db.flush()
        sp = SalaryPayment(
            employee_id=e.id, period=period,
            gross_amount=e.gross_salary or amt, net_amount=amt,
            payment_method="banka" if payment_method == "banka" else "nakit",
            bank_account_id=bank_account_id if payment_method == "banka" else None,
            paid_at=datetime.combine(pdate, datetime.min.time()),
            general_expense_id=ge.id,
            instruction_id=instruction_id,
        )
        db.add(sp)

    return {"count": len(unpaid), "total": total}


# ---------------------------------------------------------------------------
# ManualPaymentLine ödeme — serbest tanımlı ödeme kalemi
# ---------------------------------------------------------------------------

def apply_manual_payment(
    db: Session,
    line: ManualPaymentLine,
    *,
    payment_method: str,
    amount: float,
    pdate: date,
    cash_book_id: Optional[int] = None,
    bank_account_id: Optional[int] = None,
    credit_card_id: Optional[int] = None,
    instruction_id: Optional[int] = None,
) -> None:
    """Manuel ödeme kalemini öder + yan kayıt oluşturur.
    - line.ref_id varsa: yan kayda ref_id basılır (referansa atanmış harcama)
    - line.ref_id yoksa: ek olarak GeneralExpense (genel giderler) kaydı yaratılır
    """
    if not line:
        raise HTTPException(404, "Manuel kalem bulunamadı")
    if line.status != "open":
        raise HTTPException(400, "Manuel kalem zaten kapatılmış")

    desc = line.description + (f" — {line.party}" if line.party else "")
    line_ref_id = line.ref_id

    if payment_method == "banka":
        if not bank_account_id:
            raise HTTPException(400, "Banka hesabı seçilmeli")
        db.add(BankMovement(
            account_id=bank_account_id, movement_date=pdate, movement_type="cikis",
            amount=amount, description=desc, ref_id=line_ref_id,
            instruction_id=instruction_id,
        ))
    elif payment_method == "nakit":
        if not cash_book_id:
            raise HTTPException(400, "Kasa seçilmeli")
        db.add(CashEntry(
            book_id=cash_book_id, entry_date=pdate, entry_type="cikis",
            amount=amount, description=desc, ref_id=line_ref_id,
            instruction_id=instruction_id,
        ))
    elif payment_method == "kredi_karti":
        if not credit_card_id:
            raise HTTPException(400, "Kart seçilmeli")
        db.add(CreditCardTxn(
            card_id=credit_card_id, txn_date=pdate,
            amount=amount, description=desc, ref_id=line_ref_id,
            instruction_id=instruction_id,
        ))
    elif payment_method == "cek":
        # Manuel kalem için çek = yeni çek yaratıp beklemede bırak
        cheque = Cheque(
            cheque_type="verilen",
            cheque_no="",
            amount=amount,
            currency="TRY",
            cheque_date=pdate,
            due_date=pdate,
            status="beklemede",
            created_by_instruction_id=instruction_id,
        )
        db.add(cheque)
    else:
        raise HTTPException(400, "Geçersiz ödeme yöntemi")

    # Referans bağlanmamışsa genel giderlere düşür
    if not line_ref_id:
        cat = db.query(GeneralExpenseCategory).filter(
            GeneralExpenseCategory.name.ilike("%manuel%")
        ).first()
        if not cat:
            # En yakın "Diğer Giderler" / "Operasyonel Harcamalar" kategorisini kullan
            cat = db.query(GeneralExpenseCategory).filter(
                GeneralExpenseCategory.name.in_(
                    ["Diğer Giderler", "Operasyonel Harcamalar", "Diğer"]
                )
            ).first()
        db.add(GeneralExpense(
            category_id=cat.id if cat else None,
            expense_date=pdate,
            amount=amount,
            description=desc,
            source="manual",
        ))

    line.status = "paid"
    line.paid_at = datetime.utcnow()
