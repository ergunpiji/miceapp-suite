"""
micedesk — Ortak HBF muhasebe görünümü
event ile paylaşımlı expense_reports tablosu. Muhasebe `onaylandi` HBF'leri görür,
öder → `kapandi` yapar; GeneralExpense + Kasa/Banka hareketi oluşur (tam muhasebe kaydı).
Kanonik tablo event'te; burası sadece muhasebe ödeme/kapatma adımı.
"""
from datetime import date as _date, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user, get_company_id
from database import get_db
from models import (
    ExpenseReport, ExpenseItem, User, CashBook, BankAccount,
    GeneralExpense, CashEntry, BankMovement,
)
from templates_config import templates
import storage_helper
from routers.hbf import _hbf_expense_category

router = APIRouter(prefix="/hbf-muhasebe", tags=["hbf-muhasebe"])

EXP_STATUS_LABELS = {
    "draft": "Taslak", "submitted": "Müdür Onayında", "mudur_onayladi": "GM Onayında",
    "onaylandi": "Muhasebe Bekliyor", "kapandi": "Kapandı", "rejected": "Reddedildi",
    "approved": "Onaylandı",
}
EXP_STATUS_COLORS = {
    "draft": "secondary", "submitted": "warning", "mudur_onayladi": "info",
    "onaylandi": "primary", "kapandi": "success", "rejected": "danger", "approved": "success",
}


def _can_pay(user: User) -> bool:
    return user.is_admin or user.role in ("muhasebe", "muhasebe_muduru")


def _user_names(db: Session) -> dict:
    return {u.id: u.name for u in db.query(User.id, User.name).all()}


@router.get("", response_class=HTMLResponse, name="hbf_muhasebe_list")
async def hbf_muhasebe_list(
    request: Request,
    status_filter: str = "onaylandi",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: str = Depends(get_company_id),
):
    if not _can_pay(current_user):
        raise HTTPException(403, detail="Bu sayfa muhasebe içindir.")

    q = db.query(ExpenseReport).filter(ExpenseReport.company_id == cid)
    if status_filter and status_filter != "all":
        q = q.filter(ExpenseReport.status == status_filter)
    else:
        # "all" → sadece muhasebeyi ilgilendiren aşamalar (onaylandi + kapandi)
        q = q.filter(ExpenseReport.status.in_(["onaylandi", "kapandi"]))
    reports = q.order_by(ExpenseReport.updated_at.desc()).all()

    pending = db.query(ExpenseReport).filter(
        ExpenseReport.company_id == cid, ExpenseReport.status == "onaylandi"
    ).count()

    return templates.TemplateResponse("hbf_muhasebe/list.html", {
        "request": request,
        "current_user": current_user,
        "reports": reports,
        "status_filter": status_filter,
        "pending": pending,
        "user_names": _user_names(db),
        "STATUS_LABELS": EXP_STATUS_LABELS,
        "STATUS_COLORS": EXP_STATUS_COLORS,
    })


@router.get("/{report_id}", response_class=HTMLResponse, name="hbf_muhasebe_detail")
async def hbf_muhasebe_detail(
    report_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: str = Depends(get_company_id),
):
    if not _can_pay(current_user):
        raise HTTPException(403, detail="Bu sayfa muhasebe içindir.")
    rep = db.query(ExpenseReport).filter(
        ExpenseReport.id == report_id, ExpenseReport.company_id == cid
    ).first()
    if not rep:
        raise HTTPException(404)

    # Belge URL'leri: önce R2 (presigned/public — auth gerektirmez), yoksa event'in
    # belge servisine düş (SSO cookie .miceapp.net ile muhasebe görebilir).
    from auth import EVENT_URL
    doc_urls = {}
    for it in rep.items:
        if not it.document_path:
            continue
        url = None
        try:
            u = storage_helper.get_file_url(it.document_path)
            if u and u.startswith("http"):
                url = u
        except Exception:
            url = None
        doc_urls[it.id] = url or f"{EVENT_URL}/expenses/doc/{it.id}"

    cash_books = db.query(CashBook).filter(CashBook.company_id == cid).all()
    bank_accounts = db.query(BankAccount).filter(BankAccount.company_id == cid).all()

    return templates.TemplateResponse("hbf_muhasebe/detail.html", {
        "request": request,
        "current_user": current_user,
        "rep": rep,
        "doc_urls": doc_urls,
        "cash_books": cash_books,
        "bank_accounts": bank_accounts,
        "user_names": _user_names(db),
        "today": _date.today().isoformat(),
        "can_pay": _can_pay(current_user) and rep.status == "onaylandi",
        "STATUS_LABELS": EXP_STATUS_LABELS,
        "STATUS_COLORS": EXP_STATUS_COLORS,
    })


@router.post("/{report_id}/pay", name="hbf_muhasebe_pay")
async def hbf_muhasebe_pay(
    report_id: str,
    pay_date: str = Form(""),
    payment_method: str = Form("banka"),
    bank_account_id: str = Form(None),
    cash_book_id: str = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: str = Depends(get_company_id),
):
    if not _can_pay(current_user):
        raise HTTPException(403, detail="Bu adım muhasebe tarafından yapılır.")
    rep = db.query(ExpenseReport).filter(
        ExpenseReport.id == report_id, ExpenseReport.company_id == cid
    ).first()
    if not rep or rep.status != "onaylandi":
        raise HTTPException(404, detail="Ödenecek HBF bulunamadı (onaylandı durumunda olmalı).")

    pdate = _date.fromisoformat(pay_date) if pay_date else _date.today()
    total = rep.grand_total
    desc = f"HBF {rep.title or rep.id[:8]}"

    # 1) GeneralExpense kaydı
    cat_id = _hbf_expense_category(db, cid)
    ge = GeneralExpense(
        company_id=cid,
        category_id=cat_id,
        description=f"HBF: {rep.title or rep.id[:8]}",
        amount=total,
        expense_date=pdate,
        source="manual",
        created_by=current_user.id,
    )
    db.add(ge)
    db.flush()
    rep.general_expense_id = ge.id

    # 2) Kasa/Banka çıkış hareketi
    if payment_method == "nakit" and cash_book_id:
        db.add(CashEntry(
            company_id=cid, book_id=cash_book_id, entry_date=pdate,
            entry_type="cikis", amount=total, description=desc,
        ))
    elif payment_method == "banka" and bank_account_id:
        db.add(BankMovement(
            company_id=cid, account_id=bank_account_id, movement_date=pdate,
            movement_type="cikis", amount=total, description=desc,
        ))

    # 3) HBF kapat
    rep.status = "kapandi"
    rep.paid_by = current_user.id
    rep.paid_at = datetime.utcnow()
    rep.payment_method = payment_method
    rep.bank_account_id = bank_account_id if payment_method == "banka" else None
    rep.cash_book_id = cash_book_id if payment_method == "nakit" else None
    rep.updated_at = datetime.utcnow()
    db.commit()

    # 4) Gönderene bildirim
    try:
        from notification_helper import notify
        notify(
            db, rep.submitted_by,
            title=f"HBF kapandı: {rep.title or 'Harcama Formu'}",
            message=f"{current_user.name} harcama formunuzu ödedi ve kapattı.",
            link=f"/hbf-muhasebe/{rep.id}", notif_type="success", ref_id=rep.id,
        )
        db.commit()
    except Exception:
        db.rollback()

    return RedirectResponse(url=f"/hbf-muhasebe/{report_id}", status_code=302)
