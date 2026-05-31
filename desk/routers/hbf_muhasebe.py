"""
micedesk — Ortak HBF muhasebe görünümü
event ile paylaşımlı expense_reports tablosu. Muhasebe `onaylandi` HBF'leri görür,
öder → `kapandi` yapar; GeneralExpense + Kasa/Banka hareketi oluşur (tam muhasebe kaydı).
Kanonik tablo event'te; burası sadece muhasebe ödeme/kapatma adımı.
"""
import json
import os
from datetime import date as _date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user, get_company_id
from database import get_db
from models import (
    ExpenseReport, ExpenseItem, DeskRequest, User, CashBook, BankAccount,
    GeneralExpense, CashEntry, BankMovement, CreditCard, CreditCardTxn,
    _uuid,
)
from templates_config import templates
import storage_helper
from routers.hbf import _hbf_expense_category

ALLOWED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

EXP_PAYMENT_METHODS = [("nakit", "Nakit"), ("kredi_karti", "Kredi Kartı")]
EXP_DOC_TYPES = [("fatura", "Fatura"), ("fis", "Fiş"), ("belgesiz", "Belgesiz")]

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
    if status_filter == "mine":
        # Kullanıcının kendi doldurduğu HBF'ler (her aşama) — taslağını bulup düzenlesin
        q = q.filter(ExpenseReport.submitted_by == current_user.id)
    elif status_filter and status_filter != "all":
        q = q.filter(ExpenseReport.status == status_filter)
    else:
        # "all" → muhasebeyi ilgilendiren aşamalar (onaylandi + kapandi)
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


# ---------------------------------------------------------------------------
# HBF DOLDURMA (muhasebe/İK desk'ten HBF oluşturur) — ortak expense_reports'a yazar
# ---------------------------------------------------------------------------

def _can_edit(report: ExpenseReport, user: User) -> bool:
    if user.is_admin:
        return True
    return report.submitted_by == user.id and report.status in ("draft", "rejected")


def _active_requests(db: Session):
    return (db.query(DeskRequest)
            .filter(DeskRequest.status.notin_(["cancelled", "closed"]))
            .order_by(DeskRequest.request_no.desc()).all())


def _sync_cc(db: Session, report_id: str) -> None:
    db.query(CreditCardTxn).filter(
        CreditCardTxn.expense_report_id == report_id
    ).delete(synchronize_session=False)
    rep = db.query(ExpenseReport).filter(ExpenseReport.id == report_id).first()
    title = (rep.title if rep else "") or "HBF harcaması"
    for item in db.query(ExpenseItem).filter(ExpenseItem.report_id == report_id).all():
        if item.payment_method == "kredi_karti" and item.credit_card_id:
            card = db.query(CreditCard).filter(CreditCard.id == item.credit_card_id).first()
            try:
                tdate = _date.fromisoformat(item.item_date) if item.item_date else _date.today()
            except Exception:
                tdate = _date.today()
            db.add(CreditCardTxn(
                id=_uuid(), company_id=(card.company_id if card else None),
                card_id=item.credit_card_id, txn_date=tdate,
                amount=round(item.total_amount or 0, 2),
                description=(f"{title} — {item.description or ''}").strip(" —")[:300],
                is_refund=False, expense_report_id=report_id,
            ))
    db.flush()


def _save_items(db: Session, report_id: str, items_json: str) -> None:
    try:
        new_items = json.loads(items_json or "[]")
    except Exception:
        new_items = []
    existing = {it.id: it for it in db.query(ExpenseItem).filter(ExpenseItem.report_id == report_id).all()}
    seen = set()
    for idx, it in enumerate(new_items):
        doc_type = it.get("document_type", "fis")
        total = float(it.get("total_amount", 0) or 0)
        vat = 0.0 if doc_type == "belgesiz" else float(it.get("vat_amount", 0) or 0)
        amount = round(total - vat, 2)
        vat_rate = round(vat / amount * 100, 2) if amount > 0 else 0.0
        pm = it.get("payment_method", "nakit")
        ccid = (it.get("credit_card_id") or None) if pm == "kredi_karti" else None
        jid = (it.get("id") or "").strip()
        if jid and jid in existing:
            item = existing[jid]
            item.assigned_request_id = it.get("assigned_request_id") or None
            item.item_date = it.get("item_date", "") or ""
            item.description = it.get("description", "") or ""
            item.payment_method = pm
            item.credit_card_id = ccid
            item.document_type = doc_type
            item.amount = amount
            item.vat_rate = vat_rate
            item.vat_amount = round(vat, 2)
            item.total_amount = round(total, 2)
            item.sort_order = idx
            seen.add(jid)
        else:
            db.add(ExpenseItem(
                id=_uuid(), report_id=report_id,
                assigned_request_id=it.get("assigned_request_id") or None,
                item_date=it.get("item_date", "") or "", description=it.get("description", "") or "",
                payment_method=pm, credit_card_id=ccid, document_type=doc_type,
                amount=amount, vat_rate=vat_rate, vat_amount=round(vat, 2),
                total_amount=round(total, 2), sort_order=idx, created_at=datetime.utcnow(),
            ))
    for iid, item in existing.items():
        if iid not in seen:
            db.delete(item)
    db.flush()
    _sync_cc(db, report_id)


def _form_ctx(request, current_user, db, cid, report):
    return {
        "request": request, "current_user": current_user, "report": report,
        "requests": _active_requests(db),
        "credit_cards": db.query(CreditCard).filter(CreditCard.company_id == cid).order_by(CreditCard.name).all(),
        "PAYMENT_METHODS": EXP_PAYMENT_METHODS, "DOC_TYPES": EXP_DOC_TYPES,
    }


@router.get("/new", response_class=HTMLResponse, name="hbf_muhasebe_new")
async def hbf_muhasebe_new(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: str = Depends(get_company_id),
):
    return templates.TemplateResponse("hbf_muhasebe/form.html", _form_ctx(request, current_user, db, cid, None))


@router.post("/new", name="hbf_muhasebe_create")
async def hbf_muhasebe_create(
    request_id: str = Form(""),
    title: str = Form(""),
    items_json: str = Form("[]"),
    next_action: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: str = Depends(get_company_id),
):
    req = db.query(DeskRequest).filter(DeskRequest.id == request_id).first() if request_id else None
    if not req:
        raise HTTPException(400, detail="Geçerli bir referans seçmelisiniz.")
    now = datetime.utcnow()
    report = ExpenseReport(
        id=_uuid(), company_id=cid, request_id=req.id,
        request_ids_json=json.dumps([{"id": req.id, "request_no": req.request_no}], ensure_ascii=False),
        title=(title.strip() or f"HBF — {req.request_no}"),
        status="draft", submitted_by=current_user.id, created_at=now, updated_at=now,
    )
    db.add(report)
    db.flush()
    _save_items(db, report.id, items_json)
    if next_action == "submit":
        report.status = "submitted"
    db.commit()
    if next_action == "submit":
        return RedirectResponse(url="/hbf-muhasebe?status_filter=all", status_code=302)
    return RedirectResponse(url=f"/hbf-muhasebe/{report.id}/edit", status_code=302)


@router.get("/{report_id}/edit", response_class=HTMLResponse, name="hbf_muhasebe_edit")
async def hbf_muhasebe_edit_get(
    report_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: str = Depends(get_company_id),
):
    report = db.query(ExpenseReport).filter(ExpenseReport.id == report_id, ExpenseReport.company_id == cid).first()
    if not report:
        raise HTTPException(404)
    if not _can_edit(report, current_user):
        raise HTTPException(403, detail="Bu HBF düzenlenemez (yalnızca taslak/reddedilen, sahibi).")
    return templates.TemplateResponse("hbf_muhasebe/form.html", _form_ctx(request, current_user, db, cid, report))


@router.post("/{report_id}/edit", name="hbf_muhasebe_edit_post")
async def hbf_muhasebe_edit_post(
    report_id: str,
    title: str = Form(""),
    items_json: str = Form("[]"),
    next_action: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: str = Depends(get_company_id),
):
    report = db.query(ExpenseReport).filter(ExpenseReport.id == report_id, ExpenseReport.company_id == cid).first()
    if not report:
        raise HTTPException(404)
    if not _can_edit(report, current_user):
        raise HTTPException(403)
    report.title = title.strip() or report.title
    report.updated_at = datetime.utcnow()
    _save_items(db, report.id, items_json)
    if next_action == "submit":
        report.status = "submitted"
    db.commit()
    if next_action == "submit":
        return RedirectResponse(url="/hbf-muhasebe?status_filter=all", status_code=302)
    return RedirectResponse(url=f"/hbf-muhasebe/{report_id}/edit", status_code=302)


@router.post("/{report_id}/upload/{item_id}", name="hbf_muhasebe_upload")
async def hbf_muhasebe_upload(
    report_id: str,
    item_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: str = Depends(get_company_id),
):
    report = db.query(ExpenseReport).filter(ExpenseReport.id == report_id, ExpenseReport.company_id == cid).first()
    if not report or not _can_edit(report, current_user):
        raise HTTPException(403)
    item = db.query(ExpenseItem).filter(ExpenseItem.id == item_id, ExpenseItem.report_id == report_id).first()
    if not item:
        raise HTTPException(404)
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTS:
        return JSONResponse({"ok": False, "error": "Desteklenmeyen dosya türü."}, status_code=400)
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        return JSONResponse({"ok": False, "error": "Dosya 10 MB sınırını aşıyor."}, status_code=400)
    key = f"expenses/{item_id}{ext}"
    try:
        storage_helper.upload_file(content, key)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": f"Dosya yüklenemedi: {exc}"}, status_code=500)
    item.document_path = key
    item.document_name = file.filename
    db.commit()
    return JSONResponse({"ok": True, "name": file.filename})


@router.post("/{report_id}/sync-rows", name="hbf_muhasebe_sync_rows")
async def hbf_muhasebe_sync_rows(
    report_id: str,
    items_json: str = Form("[]"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: str = Depends(get_company_id),
):
    report = db.query(ExpenseReport).filter(ExpenseReport.id == report_id, ExpenseReport.company_id == cid).first()
    if not report or not _can_edit(report, current_user):
        raise HTTPException(403)
    _save_items(db, report_id, items_json)
    db.commit()
    return JSONResponse({"ok": True, "items": [
        {"idx": i, "id": it.id} for i, it in enumerate(
            sorted(report.items, key=lambda x: x.sort_order or 0))
    ]})


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
