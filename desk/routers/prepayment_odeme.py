"""
micedesk — Ön Ödeme Ödemeleri (event ile paylaşımlı prepayment_requests)
event'te GM onaylı ön ödeme talepleri muhasebeye düşer; muhasebe öder →
Kasa/Banka çıkışı + VendorPrepayment oluşur (nakit akışına yansır), talep 'paid' olur.
event GM onayı kanonik; burası sadece muhasebe ödeme adımı.
"""
from datetime import date as _date, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user, get_company_id
from database import get_db
from models import (
    EventPrepaymentRequest, Vendor, User, CashBook, BankAccount,
    CashEntry, BankMovement, VendorPrepayment, _uuid,
)
from templates_config import templates

router = APIRouter(prefix="/prepayment-odeme", tags=["prepayment-odeme"])

PR_STATUS_LABELS = {
    "pending_gm": "GM Onayında", "approved": "Ödeme Bekliyor",
    "paid": "Ödendi", "rejected": "Reddedildi", "cancelled": "İptal",
}
PR_STATUS_COLORS = {
    "pending_gm": "warning", "approved": "primary",
    "paid": "success", "rejected": "danger", "cancelled": "secondary",
}


def _can_pay(user: User) -> bool:
    return user.is_admin or user.role in ("muhasebe", "muhasebe_muduru")


def _vendor_names(db: Session) -> dict:
    return {v.id: v.name for v in db.query(Vendor.id, Vendor.name).all()}


def _user_names(db: Session) -> dict:
    return {u.id: u.name for u in db.query(User.id, User.name).all()}


@router.get("", response_class=HTMLResponse, name="prepayment_odeme_list")
async def prepayment_odeme_list(
    request: Request,
    status_filter: str = "approved",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: str = Depends(get_company_id),
):
    if not _can_pay(current_user):
        raise HTTPException(403, detail="Bu sayfa muhasebe içindir.")

    q = db.query(EventPrepaymentRequest).filter(EventPrepaymentRequest.company_id == cid)
    if status_filter == "paid":
        q = q.filter(EventPrepaymentRequest.status == "paid")
    elif status_filter == "all":
        q = q.filter(EventPrepaymentRequest.status.in_(["approved", "paid"]))
    else:
        q = q.filter(EventPrepaymentRequest.status == "approved")
    rows = q.order_by(EventPrepaymentRequest.updated_at.desc()).all()

    pending = db.query(EventPrepaymentRequest).filter(
        EventPrepaymentRequest.company_id == cid,
        EventPrepaymentRequest.status == "approved",
    ).count()

    # Ek dosya URL'leri: R2 (auth gerektirmez) yoksa event belge servisi (SSO)
    import storage_helper
    from auth import EVENT_URL
    doc_urls = {}
    for r in rows:
        if not r.document_path:
            continue
        url = None
        try:
            u = storage_helper.get_file_url(r.document_path)
            if u and u.startswith("http"):
                url = u
        except Exception:
            url = None
        doc_urls[r.id] = url or f"{EVENT_URL}/prepayment-requests/{r.id}/doc"

    return templates.TemplateResponse("prepayment_odeme/list.html", {
        "request": request, "current_user": current_user,
        "rows": rows, "status_filter": status_filter, "pending": pending,
        "doc_urls": doc_urls,
        "vendor_names": _vendor_names(db), "user_names": _user_names(db),
        "cash_books": db.query(CashBook).filter(CashBook.company_id == cid).all(),
        "bank_accounts": db.query(BankAccount).filter(BankAccount.company_id == cid).all(),
        "today": _date.today().isoformat(),
        "STATUS_LABELS": PR_STATUS_LABELS, "STATUS_COLORS": PR_STATUS_COLORS,
    })


@router.post("/{pr_id}/pay", name="prepayment_odeme_pay")
async def prepayment_odeme_pay(
    pr_id: str,
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
    pr = db.query(EventPrepaymentRequest).filter(
        EventPrepaymentRequest.id == pr_id, EventPrepaymentRequest.company_id == cid
    ).first()
    if not pr or pr.status != "approved":
        raise HTTPException(404, detail="Ödenecek ön ödeme bulunamadı (onaylı olmalı).")

    pdate = _date.fromisoformat(pay_date) if pay_date else _date.today()
    vendor = db.query(Vendor).filter(Vendor.id == pr.vendor_id).first()
    vname = vendor.name if vendor else "Tedarikçi"
    total = round(pr.amount or 0, 2)
    desc = f"Ön ödeme: {vname}" + (f" — {pr.description}" if pr.description else "")
    pm = payment_method if payment_method in ("nakit", "banka") else "banka"

    # 1) VendorPrepayment kaydı (tedarikçi ön ödemesi — ileride faturadan düşülür)
    vp = VendorPrepayment(
        id=_uuid(), company_id=cid, vendor_id=pr.vendor_id,
        payment_type="prepayment", payment_date=pdate, amount=total,
        payment_method=pm,
        bank_account_id=(bank_account_id if pm == "banka" else None),
        cash_book_id=(cash_book_id if pm == "nakit" else None),
        notes=(pr.description or "")[:300], created_by=current_user.id,
    )
    db.add(vp)
    db.flush()

    # 2) Kasa/Banka çıkış hareketi → nakit akışına yansır
    if pm == "nakit" and cash_book_id:
        db.add(CashEntry(
            company_id=cid, book_id=cash_book_id, entry_date=pdate,
            entry_type="cikis", amount=total, description=desc,
        ))
    elif pm == "banka" and bank_account_id:
        db.add(BankMovement(
            company_id=cid, account_id=bank_account_id, movement_date=pdate,
            movement_type="cikis", amount=total, description=desc,
        ))

    # 3) Ön ödeme talebini kapat
    pr.status = "paid"
    pr.paid_by = current_user.id
    pr.paid_at = pdate.isoformat()
    pr.payment_method = pm
    pr.vendor_prepayment_id = vp.id
    pr.updated_at = datetime.utcnow()
    db.commit()

    # 4) Talep edene bildirim (event)
    try:
        from notification_helper import notify
        from auth import EVENT_URL
        notify(
            db, pr.requested_by,
            title=f"Ön Ödeme Ödendi: {vname}",
            message=f"{current_user.name} ödemeyi gerçekleştirdi — {total:,.2f} ₺",
            link=f"{EVENT_URL}/prepayment-requests/{pr.id}",
            notif_type="success", ref_id=pr.id,
        )
        db.commit()
    except Exception:
        db.rollback()

    return RedirectResponse(url="/prepayment-odeme", status_code=302)
