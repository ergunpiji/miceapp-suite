"""
Satın Alma — HBF (Harcama Bildirim Formu) & Belgesiz Gelir/Gider
"""
import os
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.responses import FileResponse
from fastapi import status as http_status
from sqlalchemy.orm import Session

import storage_helper
from auth import get_current_user, get_company_id, EVENT_URL
from database import get_db
from models import (
    ExpenseReport, ExpenseItem,
    User, Reference, DeskRequest,
    CreditCard, CreditCardTxn,
    _uuid, _now,
)
from templates_config import templates
# Ortak HBF (expense_reports) — desk referans → backing request + kredi kartı limit senkronu
# hbf_muhasebe ile aynı yardımcılar + durum etiketleri; tek kaynak.
from routers.hbf_muhasebe import (
    _active_references, _request_for_reference, _sync_cc,
    EXP_STATUS_LABELS as EXPENSE_STATUS_LABELS,
    EXP_STATUS_COLORS as EXPENSE_STATUS_COLORS,
)

# Form sabitleri — event ile AYNI şekil (list-of-dict): form JS p.value/p.label, d.value/d.label bekler
EXPENSE_PAYMENT_METHODS = [
    {"value": "kredi_karti", "label": "Kredi Kartı"},
    {"value": "nakit", "label": "Nakit"},
]
EXPENSE_DOC_TYPES = [
    {"value": "fatura", "label": "Fatura"},
    {"value": "fis", "label": "Fiş"},
    {"value": "belgesiz", "label": "Belgesiz"},
]
EXPENSE_STATUSES = ["draft", "owner_onayi", "submitted", "mudur_onayladi", "onaylandi", "kapandi", "rejected"]

router = APIRouter(prefix="/expenses", tags=["expenses"])

ALLOWED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def _can_edit(report: ExpenseReport, user: User) -> bool:
    """Taslak ve reddedilen HBF'ler sahibi veya admin tarafından düzenlenebilir."""
    if user.role == "admin":
        return True
    return report.submitted_by == user.id and report.status in ("draft", "rejected")


def _find_hbf_approver(submitted_by: str | None, db: Session) -> User | None:
    """HBF onaylayıcısı: gönderenin manager zincirindeki ilk mudur veya yonetici."""
    if not submitted_by:
        return db.query(User).filter(User.role == "mudur", User.active == True).first()
    submitter = db.query(User).filter(User.id == submitted_by).first()
    if not submitter:
        return None
    visited: set = {submitter.id}
    current = submitter
    while current.manager_id and current.manager_id not in visited:
        visited.add(current.manager_id)
        mgr = db.query(User).filter(User.id == current.manager_id, User.active == True).first()
        if not mgr:
            break
        if mgr.role in ("mudur", "admin", "yonetici"):
            return mgr
        current = mgr
    # Fallback: herhangi bir aktif mudur
    return db.query(User).filter(User.role == "mudur", User.active == True).first()


def _reference_owner(report: ExpenseReport, db: Session) -> "User | None":
    """HBF'nin (birincil) referans/dosya sahibini döndürür (desk Reference.owner_id).
    Sahip yoksa None → eski davranış (zincir gönderene göre)."""
    import json as _json
    try:
        refs = _json.loads(report.request_ids_json or "[]")
    except Exception:
        refs = []
    ref_no = refs[0].get("request_no") if refs else None
    if not ref_no:
        return None
    ref = db.query(Reference).filter(Reference.ref_no == ref_no).first()
    if ref and ref.owner_id:
        return db.query(User).filter(
            User.id == ref.owner_id, User.active == True  # noqa: E712
        ).first()
    return None


def _chain_anchor_id(report: ExpenseReport, db: Session):
    """Onay zincirinin demir attığı kişi: dosya sahibi varsa O, yoksa gönderen."""
    owner = _reference_owner(report, db)
    return owner.id if owner else report.submitted_by


def _can_approve(report: ExpenseReport, user: User, db: Session) -> bool:
    """HBF gönderenin üstündeki mudur/yonetici veya admin onaylayabilir."""
    if user.role in ("admin", "mudur"):
        return True
    # yonetici: kendi direktifi altındaki birinin gönderdiği formu onaylayabilir
    if user.role == "yonetici":
        approver = _find_hbf_approver(report.submitted_by, db)
        return approver is not None and approver.id == user.id
    return False


# ---------------------------------------------------------------------------
# GET /expenses  — Genel HBF Listesi (tüm referanslar)
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse, name="expenses_all_list")
async def expenses_all_list(
    request: Request,
    status_filter: str = "all",  # all | draft | submitted | approved | rejected
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: str = Depends(get_company_id),
):
    # Tenant izolasyonu: sadece kendi firmasının HBF'leri
    query = db.query(ExpenseReport).filter(ExpenseReport.company_id == cid)

    # Onay yetkisi olmayan kullanıcı yalnızca kendi gönderdiği HBF'leri görür
    privileged = current_user.is_admin or current_user.role in ("mudur", "yonetici", "genel_mudur")
    if not privileged:
        query = query.filter(ExpenseReport.submitted_by == current_user.id)

    if status_filter != "all":
        query = query.filter(ExpenseReport.status == status_filter)

    reports = query.order_by(ExpenseReport.created_at.desc()).all()

    # Onay bekleyen sayısı
    pending_q = db.query(ExpenseReport).filter(
        ExpenseReport.company_id == cid,
        ExpenseReport.status == "submitted",
    )
    if not privileged:
        pending_q = pending_q.filter(ExpenseReport.submitted_by == current_user.id)
    pending_count = pending_q.count()

    # Gönderen isimleri (submitted_by → "Ad Soyad")
    user_names = {
        u.id: (f"{u.name} {u.surname or ''}").strip()
        for u in db.query(User).filter(User.company_id == cid).all()
    }

    return templates.TemplateResponse("expenses/list_all.html", {
        "request":       request,
        "current_user":  current_user,
        "page_title":    "Harcama Formları (HBF)",
        "reports":       reports,
        "status_filter": status_filter,
        "pending_count": pending_count,
        "user_names":    user_names,
        "STATUS_LABELS": EXPENSE_STATUS_LABELS,
        "STATUS_COLORS": EXPENSE_STATUS_COLORS,
        "STATUSES":      EXPENSE_STATUSES,
    })


# ---------------------------------------------------------------------------
# Yeni HBF
# ---------------------------------------------------------------------------

def _ref_options(db: Session, cid: str):
    """HBF formu dropdown'ı için aktif desk Referansları → form alanlarıyla uyumlu dict.
    Form JS request_no/event_name/client_name bekliyor → ref_no/title eşlenir."""
    out = []
    for r in _active_references(db, cid):
        out.append({
            "id": r.id,
            "request_no": r.ref_no,
            "event_name": (r.title or ""),
            "client_name": "",
        })
    return out


def _credit_cards(db: Session, cid: str):
    return (db.query(CreditCard)
            .filter(CreditCard.company_id == cid)
            .order_by(CreditCard.name).all())


@router.get("/new", response_class=HTMLResponse, name="expenses_new")
async def expenses_new(
    request: Request,
    request_id: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: str = Depends(get_company_id),
):
    req = None
    if request_id:
        ref = db.query(Reference).filter(
            Reference.id == request_id, Reference.company_id == cid
        ).first()
        if ref:
            req = {"id": ref.id, "request_no": ref.ref_no,
                   "event_name": (ref.title or ""), "client_name": ""}
    return templates.TemplateResponse("expenses/form.html", {
        "request": request,
        "current_user": current_user,
        "report": None,
        "req": req,
        "all_requests": _ref_options(db, cid),
        "credit_cards": _credit_cards(db, cid),
        "page_title": "Yeni Harcama Bildirim Formu",
        "PAYMENT_METHODS": EXPENSE_PAYMENT_METHODS,
        "DOC_TYPES": EXPENSE_DOC_TYPES,
    })


@router.post("/new", name="expenses_create")
async def expenses_create(
    request: Request,
    request_ids_json: str = Form("[]"),
    title: str = Form(""),
    items_json: str = Form("[]"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: str = Depends(get_company_id),
):
    import json
    try:
        refs = json.loads(request_ids_json or "[]")
    except Exception:
        refs = []
    if not refs:
        raise HTTPException(400, detail="En az bir referans seçmelisiniz.")

    try:
        items = json.loads(items_json or "[]")
    except Exception:
        items = []

    primary_id = refs[0]["id"]
    refs_by_id = {r["id"]: r for r in refs}

    # Kalemleri assigned_request_id'ye göre grupla (referans = desk Reference.id)
    # Atanmamış kalemler birincil referansa gider
    groups: dict[str, list] = {}
    for item in items:
        rid = item.get("assigned_request_id") or primary_id
        if rid not in refs_by_id:
            rid = primary_id   # geçersiz ref → birincile düş
        groups.setdefault(rid, []).append(item)

    if not groups:
        groups[primary_id] = []

    first_report_id = None
    for ref_id, group_items in groups.items():
        ref = db.query(Reference).filter(
            Reference.id == ref_id, Reference.company_id == cid
        ).first()
        if not ref:
            continue
        # expense_reports.request_id FK'sı için referansa karşılık gelen backing request
        backing_req_id = _request_for_reference(db, ref, current_user)
        ref_no = refs_by_id.get(ref_id, {}).get("request_no", ref.ref_no)
        report_title = (title.strip() or f"HBF — {ref.ref_no}")
        if len(groups) > 1:
            report_title = f"{report_title} ({ref_no})"
        report = ExpenseReport(
            id=_uuid(),
            company_id=cid,
            request_id=backing_req_id,
            request_ids_json=json.dumps(refs, ensure_ascii=False),
            title=report_title,
            status="draft",
            submitted_by=current_user.id,
            created_at=_now(),
            updated_at=_now(),
        )
        db.add(report)
        db.flush()
        _save_items_from_json(db, report.id, json.dumps(group_items))
        if first_report_id is None:
            first_report_id = report.id

    db.commit()
    return RedirectResponse(url=f"/expenses/{first_report_id}/edit", status_code=302)


@router.post("/new-draft", name="expenses_new_draft")
async def expenses_new_draft(
    request_ids_json: str = Form("[]"),
    title: str = Form(""),
    items_json: str = Form("[]"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: str = Depends(get_company_id),
):
    """Belge ekinden önce HBF'yi taslak olarak AJAX ile oluşturur; report_id döndürür."""
    import json as _json
    try:
        refs = _json.loads(request_ids_json or "[]")
    except Exception:
        refs = []
    if not refs:
        return JSONResponse({"ok": False, "error": "En az bir referans seçmelisiniz."}, status_code=400)

    primary_id = refs[0]["id"]
    ref = db.query(Reference).filter(
        Reference.id == primary_id, Reference.company_id == cid
    ).first()
    if not ref:
        return JSONResponse({"ok": False, "error": "Referans bulunamadı."}, status_code=404)

    backing_req_id = _request_for_reference(db, ref, current_user)
    report = ExpenseReport(
        id=_uuid(),
        company_id=cid,
        request_id=backing_req_id,
        request_ids_json=_json.dumps(refs, ensure_ascii=False),
        title=(title.strip() or f"HBF — {ref.ref_no}"),
        status="draft",
        submitted_by=current_user.id,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(report)
    db.flush()
    _save_items_from_json(db, report.id, items_json)
    db.commit()
    return JSONResponse({"ok": True, "report_id": report.id})


# ---------------------------------------------------------------------------
# HBF Düzenle
# ---------------------------------------------------------------------------

@router.get("/{report_id}/edit", response_class=HTMLResponse, name="expenses_edit")
async def expenses_edit_get(
    report_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: str = Depends(get_company_id),
):
    report = db.query(ExpenseReport).filter(
        ExpenseReport.id == report_id, ExpenseReport.company_id == cid
    ).first()
    if not report:
        raise HTTPException(404)
    if not _can_edit(report, current_user):
        raise HTTPException(403)
    card_names = {c.id: (c.name + (f" ••{c.last4}" if c.last4 else ""))
                  for c in _credit_cards(db, cid)}
    return templates.TemplateResponse("expenses/form.html", {
        "request": request,
        "current_user": current_user,
        "report": report,
        "req": None,  # desk: referanslar request_ids_json'dan yüklenir
        "all_requests": _ref_options(db, cid),
        "credit_cards": _credit_cards(db, cid),
        "card_names": card_names,
        "page_title": report.title or "HBF Düzenle",
        "PAYMENT_METHODS": EXPENSE_PAYMENT_METHODS,
        "DOC_TYPES": EXPENSE_DOC_TYPES,
    })


@router.post("/{report_id}/edit", name="expenses_edit_post")
async def expenses_edit_post(
    report_id: str,
    request: Request,
    title: str = Form(""),
    request_ids_json: str = Form("[]"),
    items_json: str = Form("[]"),
    next_action: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: str = Depends(get_company_id),
):
    import json as _json
    report = db.query(ExpenseReport).filter(
        ExpenseReport.id == report_id, ExpenseReport.company_id == cid
    ).first()
    if not report:
        raise HTTPException(404)
    if not _can_edit(report, current_user):
        raise HTTPException(403)

    report.title = title.strip() or report.title
    report.updated_at = _now()

    try:
        refs = _json.loads(request_ids_json or "[]")
    except Exception:
        refs = []
    if refs:
        report.request_ids_json = _json.dumps(refs, ensure_ascii=False)

    # Edit modunda sadece bu raporun kalemlerini güncelle (split yok)
    for item in list(report.items):
        db.delete(item)
    db.flush()
    _save_items_from_json(db, report.id, items_json)

    first_approver = None
    if next_action == "submit":
        # Sahip-onayı kuralı: gönderen ≠ referans sahibi ise önce SAHİP onaylar
        owner = _reference_owner(report, db)
        if owner and owner.id != report.submitted_by:
            report.status = "owner_onayi"
            first_approver = owner
        else:
            report.status = "submitted"
            first_approver = _find_hbf_approver(_chain_anchor_id(report, db), db)

    db.commit()

    if next_action == "submit":
        # Onay event tarafında yapılır (birleşik akış) → bildirim EVENT linkiyle
        refs = []
        try:
            refs = _json.loads(report.request_ids_json or "[]")
        except Exception:
            refs = []
        ref_no = refs[0].get("request_no") if refs else ""
        if first_approver:
            stage = "dosya sahibi onayı" if report.status == "owner_onayi" else "onayı"
            try:
                from utils.notifications import create_notification
                create_notification(
                    db,
                    user_id    = first_approver.id,
                    notif_type = "hbf_submitted",
                    title      = f"HBF {stage} bekleniyor — {report.title or 'Harcama Formu'}",
                    message    = f"{ref_no} referansına ait harcama formu {stage} aşamasında sizi bekliyor.",
                    link       = f"{EVENT_URL}/expenses/{report.id}",
                    ref_id     = report.id,
                )
                db.commit()
            except Exception:
                db.rollback()
        return RedirectResponse(url="/expenses", status_code=302)
    return RedirectResponse(url=f"/expenses/{report_id}/edit", status_code=302)


# ---------------------------------------------------------------------------
# HBF Görüntüle (onay sayfası)
# ---------------------------------------------------------------------------

@router.get("/{report_id}", response_class=HTMLResponse, name="expenses_view")
async def expenses_view(
    report_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: str = Depends(get_company_id),
):
    report = db.query(ExpenseReport).filter(
        ExpenseReport.id == report_id, ExpenseReport.company_id == cid
    ).first()
    if not report:
        raise HTTPException(404)
    card_names = {c.id: (c.name + (f" ••{c.last4}" if c.last4 else ""))
                  for c in _credit_cards(db, cid)}
    # HBF'yi kim doldurdu (gönderen)
    submitter_name = None
    if report.submitted_by:
        su = db.query(User).filter(User.id == report.submitted_by).first()
        if su:
            submitter_name = (f"{su.name} {getattr(su, 'surname', '') or ''}").strip()
    # Şu an kimin onayında (durum çubuğu için)
    def _uname(u):
        return (f"{u.name} {getattr(u, 'surname', '') or ''}").strip() if u else None
    current_approver_name = None
    if report.status == "owner_onayi":
        current_approver_name = _uname(_reference_owner(report, db)) or "Dosya sahibi"
    elif report.status == "submitted":
        current_approver_name = _uname(_find_hbf_approver(_chain_anchor_id(report, db), db)) or "Müdür"
    elif report.status == "mudur_onayladi":
        current_approver_name = "Genel Müdür"
    elif report.status == "onaylandi":
        current_approver_name = "Muhasebe"
    # Başlık için referans bilgisi (request_ids_json'dan)
    import json as _json
    req = None
    try:
        _refs = _json.loads(report.request_ids_json or "[]")
        if _refs:
            req = {"id": _refs[0].get("id"), "request_no": _refs[0].get("request_no"),
                   "event_name": _refs[0].get("event_name", ""),
                   "client_name": _refs[0].get("client_name", "")}
    except Exception:
        req = None
    return templates.TemplateResponse("expenses/form.html", {
        "request": request,
        "current_user": current_user,
        "report": report,
        "req": req,
        "all_requests": [],
        "readonly": True,
        # Onay/red birleşik akışta EVENT tarafında yapılır → desk'te salt görüntüleme
        "can_approve": False,
        "card_names": card_names,
        "submitter_name": submitter_name,
        "current_approver_name": current_approver_name,
        "page_title": report.title or "HBF Detay",
        "PAYMENT_METHODS": EXPENSE_PAYMENT_METHODS,
        "DOC_TYPES": EXPENSE_DOC_TYPES,
        "STATUS_LABELS": EXPENSE_STATUS_LABELS,
        "STATUS_COLORS": EXPENSE_STATUS_COLORS,
    })


# ---------------------------------------------------------------------------
# Onay / Red
# ---------------------------------------------------------------------------

@router.post("/{report_id}/approve", name="expenses_approve")
async def expenses_approve(
    report_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    report = db.query(ExpenseReport).filter(ExpenseReport.id == report_id).first()
    if not report:
        raise HTTPException(404)
    if not _can_approve(report, current_user, db):
        raise HTTPException(403)
    report.status = "approved"
    report.approved_by = current_user.id
    report.approved_at = _now()
    report.updated_at = _now()
    db.commit()
    return RedirectResponse(url=f"/requests/{report.request_id}", status_code=302)


@router.post("/{report_id}/reject", name="expenses_reject")
async def expenses_reject(
    report_id: str,
    request: Request,
    rejection_note: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    report = db.query(ExpenseReport).filter(ExpenseReport.id == report_id).first()
    if not report:
        raise HTTPException(404)
    if not _can_approve(report, current_user, db):
        raise HTTPException(403)
    report.status = "rejected"
    report.rejection_note = rejection_note.strip()
    report.updated_at = _now()
    db.commit()
    return RedirectResponse(url=f"/requests/{report.request_id}", status_code=302)


# ---------------------------------------------------------------------------
# Kalem belge yükleme
# ---------------------------------------------------------------------------

@router.post("/{report_id}/sync-rows", name="expenses_sync_rows")
async def expenses_sync_rows(
    report_id: str,
    items_json: str = Form("[]"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Satırları kaydet ve item ID'lerini döndür (belge yükleme öncesi auto-save)."""
    report = db.query(ExpenseReport).filter(ExpenseReport.id == report_id).first()
    if not report:
        raise HTTPException(404)
    if not _can_edit(report, current_user):
        raise HTTPException(403)

    for item in list(report.items):
        db.delete(item)
    db.flush()
    _save_items_from_json(db, report_id, items_json)
    db.commit()
    db.refresh(report)

    return JSONResponse({
        "ok": True,
        "items": [{"idx": i, "id": item.id} for i, item in enumerate(
            sorted(report.items, key=lambda x: x.sort_order)
        )],
    })


@router.post("/{report_id}/upload/{item_id}", name="expenses_upload_doc")
async def expenses_upload_doc(
    report_id: str,
    item_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    report = db.query(ExpenseReport).filter(ExpenseReport.id == report_id).first()
    if not report:
        raise HTTPException(404)
    if not _can_edit(report, current_user):
        raise HTTPException(403)
    item = db.query(ExpenseItem).filter(
        ExpenseItem.id == item_id, ExpenseItem.report_id == report_id
    ).first()
    if not item:
        raise HTTPException(404)

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTS:
        return JSONResponse({"ok": False, "error": "Desteklenmeyen dosya türü."}, status_code=400)

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        return JSONResponse({"ok": False, "error": "Dosya 10 MB sınırını aşıyor."}, status_code=400)

    key = storage_helper.company_key(current_user.company_id, "expenses", item_id, ext)
    storage_helper.upload_file(content, key)
    item.document_path = key
    item.document_name = file.filename
    db.commit()
    return JSONResponse({"ok": True, "name": file.filename, "path": item.document_path})


@router.get("/doc/{item_id}", name="expenses_doc_download")
async def expenses_doc_download(
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from fastapi.responses import RedirectResponse as _Redirect
    item = db.query(ExpenseItem).filter(ExpenseItem.id == item_id).first()
    if not item or not item.document_path:
        raise HTTPException(404)
    if storage_helper.R2_ENABLED:
        return _Redirect(url=storage_helper.get_file_url_secure(item.document_path, current_user), status_code=302)
    # Yerel fallback: eski format "expenses/..." veya yeni "uploads/expenses/..."
    key = item.document_path
    local = os.path.join("static", key)
    if not os.path.exists(local):
        local = os.path.join("static", "uploads", key)
    if not os.path.exists(local):
        raise HTTPException(404)
    return FileResponse(local, filename=item.document_name or "belge")


# ---------------------------------------------------------------------------
# Yardımcı
# ---------------------------------------------------------------------------

def _save_items_from_json(db: Session, report_id: str, items_json: str):
    import json
    try:
        items = json.loads(items_json or "[]")
    except Exception:
        items = []
    for idx, it in enumerate(items):
        doc_type = it.get("document_type", "fis")
        # Yeni format: kullanıcı KDV dahil tutar + KDV tutarı giriyor
        # Eski format (geriye uyumluluk): amount (KDV hariç) + vat_rate → dönüştür
        if "total_amount" in it:
            total_amount = float(it.get("total_amount", 0) or 0)
            vat_amount   = 0.0 if doc_type == "belgesiz" else float(it.get("vat_amount", 0) or 0)
            amount       = round(total_amount - vat_amount, 2)
            vat_rate     = round(vat_amount / amount * 100, 2) if amount > 0 else 0.0
        else:
            # Eski format geriye uyumluluk
            amount     = float(it.get("amount", 0) or 0)
            vat_rate   = float(it.get("vat_rate", 0) or 0)
            vat_amount = round(amount * vat_rate / 100, 2)
            total_amount = round(amount + vat_amount, 2)

        pay_method = it.get("payment_method", "nakit")
        item = ExpenseItem(
            id=_uuid(),
            report_id=report_id,
            assigned_request_id=it.get("assigned_request_id") or None,
            item_date=it.get("item_date", "") or "",
            description=it.get("description", "") or "",
            payment_method=pay_method,
            credit_card_id=((it.get("credit_card_id") or None)
                            if pay_method == "kredi_karti" else None),
            document_type=doc_type,
            amount=round(amount, 2),
            vat_rate=round(vat_rate, 2),
            vat_amount=round(vat_amount, 2),
            total_amount=round(total_amount, 2),
            sort_order=idx,
            # Daha önce yüklenen belgeyi koru
            document_path=it.get("document_path") or None,
            document_name=it.get("document_name") or None,
            created_at=_now(),
        )
        db.add(item)

    db.flush()
    # Kredi kartı kalemlerini kartın limitinden düş (CreditCardTxn senkron)
    _sync_cc(db, report_id)
