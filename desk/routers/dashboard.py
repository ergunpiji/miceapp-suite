"""
Dashboard — GET /dashboard
"""

from datetime import date
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, extract

from auth import get_current_user, get_company_id
from access_policy import (
    visible_invoices_query, visible_references_query, visible_customers_query,
)
from database import get_db
from models import (
    User, Reference, Invoice, CashBook, CashEntry,
    BankAccount, BankMovement, GeneralExpense,
    CreditCard, CreditCardStatement, CreditCardTxn,
    PaymentInstruction, Customer,
)
from templates_config import templates

router = APIRouter()


def _cash_balance(db, book_id):
    ins = db.query(func.sum(CashEntry.amount)).filter(
        CashEntry.book_id == book_id, CashEntry.entry_type == "giris"
    ).scalar() or 0
    outs = db.query(func.sum(CashEntry.amount)).filter(
        CashEntry.book_id == book_id, CashEntry.entry_type == "cikis"
    ).scalar() or 0
    return ins - outs


def _bank_balance(db, account_id):
    account = db.query(BankAccount).get(account_id)
    opening = account.opening_balance if account else 0
    ins = db.query(func.sum(BankMovement.amount)).filter(
        BankMovement.account_id == account_id, BankMovement.movement_type == "giris"
    ).scalar() or 0
    outs = db.query(func.sum(BankMovement.amount)).filter(
        BankMovement.account_id == account_id, BankMovement.movement_type == "cikis"
    ).scalar() or 0
    return opening + ins - outs


def _cc_outstanding(db, card_id):
    """Ödenmemiş ekstreler + ekstreye atanmamış (refund hariç) işlemler."""
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


@router.get("/dashboard", response_class=HTMLResponse, name="dashboard")
async def dashboard(
    request: Request,
    date_from: str = None,
    date_to: str = None,
    customer_id: str = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    today = date.today()
    cust_id = int(customer_id) if customer_id and customer_id.strip().lstrip("-").isdigit() else None

    # Tarih aralığı — default: yılın başından bugüne
    try:
        d_from = date.fromisoformat(date_from) if date_from else date(today.year, 1, 1)
    except ValueError:
        d_from = date(today.year, 1, 1)
    try:
        d_to = date.fromisoformat(date_to) if date_to else today
    except ValueError:
        d_to = today

    # Müşteri listesi (filtre için) — sadece görme yetkisi olanlar
    customers = (
        visible_customers_query(db, current_user)
        .filter(Customer.active == True)  # noqa: E712
        .order_by(Customer.name)
        .all()
    )

    # RBAC v2: Sales user yalnızca kendi müşterilerine ait faturaları görür
    inv_q = visible_invoices_query(db, current_user).filter(
        Invoice.status.in_(["approved", "partial", "paid"]),
        Invoice.invoice_date >= d_from,
        Invoice.invoice_date <= d_to,
        Invoice.deleted_at == None,  # noqa: E711
    )
    if cust_id:
        # Müşteriye ait referans ID'leri
        cust_ref_ids = [
            r.id for r in db.query(Reference)
            .filter(Reference.customer_id == cust_id, Reference.company_id == cid)
            .all()
        ]
        from sqlalchemy import or_
        inv_q = inv_q.filter(
            or_(
                Invoice.customer_id == cust_id,
                Invoice.ref_id.in_(cust_ref_ids) if cust_ref_ids else False,
            )
        )
    try:
        period_invoices = inv_q.all()
    except Exception:
        period_invoices = []

    # Ciro = sadece kesilen tipi (komisyon/iade dahil değil)
    ciro     = sum(i.amount for i in period_invoices if i.invoice_type == "kesilen")
    gelen    = sum(i.amount for i in period_invoices if i.invoice_type == "gelen")

    # Genel giderler: sadece muhasebe/GM/admin'in görmesi gereken finansal veri.
    # Sales user için 0 (kendi müşterilerinin proje gideri ayrı bir konu).
    _can_finance = (
        current_user.is_approver or current_user.is_admin
        or current_user.has_department_key("accounting")
        or current_user.role in ("muhasebe", "muhasebe_muduru")
    )
    hbf_gider = 0
    if _can_finance:
        # HBF kapanışından gelen GeneralExpense'leri hariç tut (HBF'yi ayrıca ekliyoruz → çift sayım olmasın)
        period_expenses = db.query(GeneralExpense).filter(
            GeneralExpense.company_id == cid,
            GeneralExpense.expense_date >= d_from,
            GeneralExpense.expense_date <= d_to,
            ~GeneralExpense.description.like("HBF:%"),
        ).all()
        toplam_gider = sum(e.amount for e in period_expenses)

        # Harcama Bildirimleri (HBF) — GM onayından geçenler gider sayılır (KDV dahil)
        from models import ExpenseReport
        hbf_reports = db.query(ExpenseReport).filter(
            ExpenseReport.company_id == cid,
            ExpenseReport.status.in_(["onaylandi", "kapandi", "approved"]),
            func.date(ExpenseReport.created_at) >= d_from,
            func.date(ExpenseReport.created_at) <= d_to,
        ).all()
        hbf_gider = round(sum((r.grand_total or 0) for r in hbf_reports), 2)
    else:
        toplam_gider = 0

    ytd_kar = ciro - gelen - toplam_gider - hbf_gider
    # Kârlılık oranı (%) — ciro yoksa None
    karlilik = round(ytd_kar / ciro * 100, 1) if ciro else None

    # Tahsilat beklenen — sadece kendi müşterilerinin tahsilatları (RBAC v2)
    try:
        receivable_invs = visible_invoices_query(db, current_user).filter(
            Invoice.invoice_type.in_(["kesilen", "komisyon"]),
            Invoice.status.in_(["approved", "partial"]),
            Invoice.deleted_at == None,  # noqa: E711
        ).all()
        tahsilat_beklenen = sum(i.remaining for i in receivable_invs)
    except Exception:
        receivable_invs = []
        tahsilat_beklenen = 0.0

    try:
        payable_invs = visible_invoices_query(db, current_user).filter(
            Invoice.invoice_type == "gelen",
            Invoice.status.in_(["approved", "partial"]),
            Invoice.deleted_at == None,  # noqa: E711
        ).all()
        fatura_odeme = sum(i.remaining for i in payable_invs)
    except Exception:
        payable_invs = []
        fatura_odeme = 0.0

    cards = db.query(CreditCard).filter(CreditCard.company_id == cid).all()
    kk_bakiye = sum(_cc_outstanding(db, c.id) for c in cards)

    odeme_yapilacak = fatura_odeme + kk_bakiye

    # Kasa & banka bakiyeleri
    cash_books = db.query(CashBook).filter(CashBook.company_id == cid).all()
    cash_total = sum(_cash_balance(db, b.id) for b in cash_books)
    bank_accounts = db.query(BankAccount).filter(BankAccount.company_id == cid).all()
    bank_total = sum(_bank_balance(db, a.id) for a in bank_accounts)

    # Bekleyen ödeme talimatları (GM onaylı, operatör infaz bekliyor)
    pending_instructions = db.query(PaymentInstruction).filter(
        PaymentInstruction.company_id == cid,
        PaymentInstruction.status == "pending"
    ).all()
    pending_instr_count = len(pending_instructions)
    pending_instr_total = sum(i.amount or 0 for i in pending_instructions)

    # Son referanslar & faturalar — RBAC v2 ile filter
    try:
        son_referanslar = (
            visible_references_query(db, current_user)
            .order_by(Reference.created_at.desc()).limit(5).all()
        )
    except Exception:
        son_referanslar = []
    try:
        from sqlalchemy.orm.attributes import set_committed_value
        son_faturalar = (
            visible_invoices_query(db, current_user)
            .filter(Invoice.deleted_at == None)  # noqa: E711
            .order_by(Invoice.created_at.desc()).limit(5).all()
        )
        for _inv in son_faturalar:
            try:
                set_committed_value(_inv, 'vendor', None)
            except Exception:
                pass
    except Exception:
        son_faturalar = []

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "current_user": current_user,
            "page_title": "Dashboard",
            "ytd_kar": ytd_kar,
            "karlilik": karlilik,
            "hbf_gider": hbf_gider,
            "tahsilat_beklenen": tahsilat_beklenen,
            "odeme_yapilacak": odeme_yapilacak,
            "kk_bakiye": kk_bakiye,
            "ciro": ciro,
            "gelen_yil": gelen,
            "cash_total": cash_total,
            "bank_total": bank_total,
            "son_referanslar": son_referanslar,
            "son_faturalar": son_faturalar,
            "d_from": d_from.isoformat(),
            "d_to": d_to.isoformat(),
            "d_from_tr": d_from.strftime("%d.%m.%Y"),
            "d_to_tr": d_to.strftime("%d.%m.%Y"),
            "customers": customers,
            "selected_customer_id": cust_id,
            "pending_instr_count": pending_instr_count,
            "pending_instr_total": pending_instr_total,
        },
    )
