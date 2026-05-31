"""
Satın Alma — HBF (Harcama Bildirim Formu) & Belgesiz Gelir/Gider
"""
import os
import shutil

from storage import save_upload, serve_upload as _serve_upload
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi import status as http_status
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import (
    ExpenseReport, ExpenseItem, UndocumentedEntry,
    DeskCreditCard, DeskCreditCardTxn,
    Request as ReqModel, User,
    EXPENSE_STATUSES, EXPENSE_STATUS_LABELS, EXPENSE_STATUS_COLORS,
    EXPENSE_PAYMENT_METHODS, EXPENSE_DOC_TYPES,
    _uuid, _now,
)
from templates_config import templates

router = APIRouter(prefix="/expenses", tags=["expenses"])

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "uploads", "expenses")
ALLOWED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def _ensure_upload_dir():
    os.makedirs(UPLOAD_DIR, exist_ok=True)


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


def _is_gm(user: User) -> bool:
    """Genel Müdür yetkisi: admin/super_admin/genel_mudur veya org grade 1."""
    return getattr(user, "is_gm", False) or user.role in ("admin", "super_admin", "genel_mudur")


def _find_gms(db: Session) -> list[User]:
    """Şirketteki GM (genel_mudur/admin/super_admin) kullanıcıları — bildirim için."""
    return db.query(User).filter(
        User.role.in_(["genel_mudur", "admin", "super_admin"]),
        User.active == True,  # noqa: E712
    ).all()


def _find_muhasebe(db: Session) -> list[User]:
    """Muhasebe kullanıcıları — ödeme/kapatma bildirimleri için."""
    return db.query(User).filter(
        User.role.in_(["muhasebe", "muhasebe_muduru"]),
        User.active == True,  # noqa: E712
    ).all()


def _gm_level_users(db: Session, company_id, exclude_id: str | None = None) -> list[User]:
    """AYNI ŞİRKETteki aktif GM seviyesi kullanıcılar (genel_mudur/admin/super_admin).
    Şirket-bazlı: başka şirketin admini bu HBF'yi onaylayamaz sayılır."""
    q = db.query(User).filter(
        User.role.in_(["genel_mudur", "admin", "super_admin"]),
        User.active == True,  # noqa: E712
        User.company_id == company_id,
    )
    if exclude_id:
        q = q.filter(User.id != exclude_id)
    return q.all()


def _other_approver_exists(report: ExpenseReport, user: User, db: Session) -> bool:
    """Bu HBF için (gönderen hariç) onaylayabilecek başka biri var mı?
    submitted: başka GM ya da gönderenin müdürü; mudur_onayladi: başka GM.
    (Aynı şirket kapsamında.)"""
    if _gm_level_users(db, report.company_id, exclude_id=user.id):
        return True
    if report.status == "submitted":
        approver = _find_hbf_approver(report.submitted_by, db)
        return approver is not None and approver.id != user.id
    return False


def _can_approve(report: ExpenseReport, user: User, db: Session) -> bool:
    """HBF onay zinciri — mevcut aşamada bu kullanıcı işlem yapabilir mi?
      submitted       → müdür (gönderenin müdürü) veya GM/admin onaylar
      mudur_onayladi  → sadece GM/admin onaylar
    Kural: kimse kendi HBF'sini onaylayamaz. İSTİSNA: en üst yetkili (GM/admin) ve
    onaylayacak BAŞKA kimse yoksa kendi HBF'sini onaylayabilir (takılma olmasın)."""
    is_self = bool(report.submitted_by and report.submitted_by == user.id)
    if is_self:
        # Yalnızca GM seviyesi + başka onaylayıcı yoksa kendi formunu onaylayabilir
        if report.status in ("submitted", "mudur_onayladi") and _is_gm(user):
            return not _other_approver_exists(report, user, db)
        return False
    if report.status == "submitted":
        # GM/admin her zaman onaylayabilir (müdür adımını atlayarak)
        if _is_gm(user):
            return True
        # Aksi halde gönderenin zincirideki müdür/yönetici
        approver = _find_hbf_approver(report.submitted_by, db)
        return approver is not None and approver.id == user.id
    if report.status == "mudur_onayladi":
        # 2. aşama: yalnızca GM/admin
        return _is_gm(user)
    return False


def hbf_pending_count_for(db: Session, user: User) -> int:
    """Bu kullanıcının onayını bekleyen HBF sayısı (sidebar badge + çan için)."""
    if not user:
        return 0
    cnt = 0
    # Müdür aşaması: doğrudan ekibinin gönderdiği (submitted) formlar
    if user.role in ("mudur", "yonetici", "genel_mudur", "admin", "super_admin"):
        team_ids = [
            r[0] for r in db.query(User.id).filter(
                User.manager_id == user.id, User.active == True  # noqa: E712
            ).all()
        ]
        if team_ids:
            cnt += db.query(ExpenseReport).filter(
                ExpenseReport.status == "submitted",
                ExpenseReport.submitted_by.in_(team_ids),
            ).count()
    # GM aşaması: müdürü onaylamış, GM onayı bekleyen tüm formlar
    if _is_gm(user):
        cnt += db.query(ExpenseReport).filter(
            ExpenseReport.status == "mudur_onayladi"
        ).count()
    return cnt


# ---------------------------------------------------------------------------
# GET /expenses  — Genel HBF Listesi (tüm referanslar)
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse, name="expenses_all_list")
async def expenses_all_list(
    request: Request,
    status_filter: str = "all",  # all | draft | submitted | approved | rejected
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(ExpenseReport)

    # PM sadece kendi referanslarına ait HBF'leri görür
    if current_user.role in ("yonetici", "asistan"):
        query = query.join(ExpenseReport.request).filter(
            ReqModel.created_by == current_user.id
        )
    # satinalma sadece kendi gönderdiği HBF'leri görür
    elif current_user.role == "satinalma":
        query = query.filter(ExpenseReport.submitted_by == current_user.id)

    if status_filter != "all":
        query = query.filter(ExpenseReport.status == status_filter)

    reports = query.order_by(ExpenseReport.created_at.desc()).all()

    # Bu kullanıcının mevcut aşamada onaylayabileceği HBF'ler (her satır için buton)
    approvable_ids = {r.id for r in reports if _can_approve(r, current_user, db)}
    # Onay bekleyen sayısı = bu kullanıcının onayını bekleyenler
    pending_count = hbf_pending_count_for(db, current_user)

    return templates.TemplateResponse("expenses/list_all.html", {
        "request":       request,
        "current_user":  current_user,
        "page_title":    "Harcama Formları (HBF)",
        "reports":       reports,
        "status_filter": status_filter,
        "pending_count": pending_count,
        "approvable_ids": approvable_ids,
        "STATUS_LABELS": EXPENSE_STATUS_LABELS,
        "STATUS_COLORS": EXPENSE_STATUS_COLORS,
        "STATUSES":      EXPENSE_STATUSES,
    })


# ---------------------------------------------------------------------------
# Yeni HBF
# ---------------------------------------------------------------------------

def _all_requests_for_user(db: Session, user):
    """Form dropdown için tüm aktif referansları döndür.
    İptal ve kapanmış referanslar hariç — herkes tüm referanslara harcama yapabilir.
    """
    from models import Request as ReqModel
    q = db.query(ReqModel).filter(ReqModel.status.notin_(["cancelled", "closed"]))
    return q.order_by(ReqModel.created_at.desc()).all()


@router.get("/new", response_class=HTMLResponse, name="expenses_new")
async def expenses_new(
    request: Request,
    request_id: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = None
    if request_id:
        req = db.query(ReqModel).filter(ReqModel.id == request_id).first()
    all_reqs = _all_requests_for_user(db, current_user)
    return templates.TemplateResponse("expenses/form.html", {
        "request": request,
        "current_user": current_user,
        "report": None,
        "req": req,
        "all_requests": all_reqs,
        "page_title": "Yeni Harcama Bildirim Formu",
        "PAYMENT_METHODS": EXPENSE_PAYMENT_METHODS,
        "DOC_TYPES": EXPENSE_DOC_TYPES,
        "credit_cards": db.query(DeskCreditCard).order_by(DeskCreditCard.name).all(),
    })


@router.post("/new", name="expenses_create")
async def expenses_create(
    request: Request,
    request_ids_json: str = Form("[]"),
    title: str = Form(""),
    items_json: str = Form("[]"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
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

    # Kalemleri assigned_request_id'ye göre grupla
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
        req_obj = db.query(ReqModel).filter(ReqModel.id == ref_id).first()
        if not req_obj:
            continue
        ref_no = refs_by_id.get(ref_id, {}).get("request_no", ref_id[:8])
        report_title = (title.strip() or f"HBF — {req_obj.request_no}")
        if len(groups) > 1:
            report_title = f"{report_title} ({ref_no})"
        report = ExpenseReport(
            id=_uuid(),
            company_id=current_user.company_id,
            request_id=ref_id,
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


# ---------------------------------------------------------------------------
# HBF Düzenle
# ---------------------------------------------------------------------------

@router.get("/{report_id}/edit", response_class=HTMLResponse, name="expenses_edit")
async def expenses_edit_get(
    report_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    report = db.query(ExpenseReport).filter(ExpenseReport.id == report_id).first()
    if not report:
        raise HTTPException(404)
    if not _can_edit(report, current_user):
        raise HTTPException(403)
    all_reqs = _all_requests_for_user(db, current_user)
    return templates.TemplateResponse("expenses/form.html", {
        "request": request,
        "current_user": current_user,
        "report": report,
        "req": report.request,
        "all_requests": all_reqs,
        "page_title": report.title or "HBF Düzenle",
        "PAYMENT_METHODS": EXPENSE_PAYMENT_METHODS,
        "DOC_TYPES": EXPENSE_DOC_TYPES,
        "credit_cards": db.query(DeskCreditCard).order_by(DeskCreditCard.name).all(),
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
):
    import json as _json
    report = db.query(ExpenseReport).filter(ExpenseReport.id == report_id).first()
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
    _save_items_from_json(db, report.id, items_json)

    if next_action == "submit":
        report.status = "submitted"

    db.commit()

    if next_action == "submit":
        back_id = report.request_id
        # Bildirim: gönderenin bir üstüne git
        approver = _find_hbf_approver(report.submitted_by, db)
        req_obj = db.query(ReqModel).filter(ReqModel.id == back_id).first() if back_id else None
        if approver:
            from utils.notifications import create_notification
            create_notification(
                db,
                user_id    = approver.id,
                notif_type = "hbf_submitted",
                title      = f"HBF onayı bekleniyor — {report.title or 'Harcama Formu'}",
                message    = f"{req_obj.request_no if req_obj else ''} referansına ait harcama formu onayınızı bekliyor.",
                link       = f"/expenses/{report.id}",
                ref_id     = report.id,
            )
            db.commit()
        return RedirectResponse(url=f"/requests/{back_id}", status_code=302)
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
):
    report = db.query(ExpenseReport).filter(ExpenseReport.id == report_id).first()
    if not report:
        raise HTTPException(404)
    # Hangi kredi kartıyla harcandığını göstermek için: id → "Ad ••1234"
    card_names = {
        c.id: (c.name + (f" ••{c.last4}" if c.last4 else ""))
        for c in db.query(DeskCreditCard).all()
    }
    # HBF'yi kim doldurdu (gönderen)
    submitter_name = None
    if report.submitted_by:
        su = db.query(User).filter(User.id == report.submitted_by).first()
        if su:
            submitter_name = (f"{su.name} {getattr(su, 'surname', '') or ''}").strip()
    return templates.TemplateResponse("expenses/form.html", {
        "request": request,
        "current_user": current_user,
        "report": report,
        "req": report.request,
        "all_requests": [],
        "readonly": True,
        "can_approve": _can_approve(report, current_user, db),
        "card_names": card_names,
        "submitter_name": submitter_name,
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

    from utils.notifications import create_notification
    now = _now()
    report.updated_at = now
    req_obj = db.query(ReqModel).filter(ReqModel.id == report.request_id).first()
    ref_no = req_obj.request_no if req_obj else ""

    to_muhasebe = False
    if report.status == "submitted":
        if _is_gm(current_user):
            # GM/admin doğrudan finalize → muhasebe bekliyor
            report.status = "onaylandi"
            report.approved_by = current_user.id
            report.approved_at = now
            notify_targets, stage_msg, to_muhasebe = _find_muhasebe(db), "ödeme/kapatma", True
        else:
            # Müdür onayı → GM onayına gider
            report.status = "mudur_onayladi"
            report.manager_approved_by = current_user.id
            report.manager_approved_at = now
            notify_targets, stage_msg = _find_gms(db), "GM onayı"
    elif report.status == "mudur_onayladi":
        # GM onayı → muhasebe bekliyor
        report.status = "onaylandi"
        report.approved_by = current_user.id
        report.approved_at = now
        notify_targets, stage_msg, to_muhasebe = _find_muhasebe(db), "ödeme/kapatma", True
    else:
        raise HTTPException(400, detail="Bu HBF bu aşamada onaylanamaz.")

    db.commit()

    # Sıradaki onaycı(lar)a bildirim. Muhasebe desk'te çalışır → desk linki ver.
    from auth import DESK_URL
    notif_link = (f"{DESK_URL}/hbf-muhasebe/{report.id}") if to_muhasebe else f"/expenses/{report.id}"
    for u in notify_targets:
        if u.id == current_user.id:
            continue
        create_notification(
            db,
            user_id    = u.id,
            notif_type = "hbf_submitted",
            title      = f"HBF {stage_msg} bekliyor — {report.title or 'Harcama Formu'}",
            message    = f"{ref_no} referansına ait harcama formu {stage_msg} aşamasında sizi bekliyor.",
            link       = notif_link,
            ref_id     = report.id,
        )
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

    _save_items_from_json(db, report_id, items_json)
    db.commit()
    db.refresh(report)

    return JSONResponse({
        "ok": True,
        "items": [{"idx": i, "id": item.id} for i, item in enumerate(
            sorted(report.items, key=lambda x: x.sort_order)
        )],
    })


@router.post("/new-draft", name="expenses_new_draft")
async def expenses_new_draft(
    request_ids_json: str = Form("[]"),
    title: str = Form(""),
    items_json: str = Form("[]"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Yeni HBF'i taslak olarak AJAX ile oluşturur; report_id döndürür."""
    import json as _json
    try:
        refs = _json.loads(request_ids_json or "[]")
    except Exception:
        refs = []
    if not refs:
        return JSONResponse({"ok": False, "error": "En az bir referans seçmelisiniz."}, status_code=400)

    primary_id = refs[0]["id"]
    req_obj = db.query(ReqModel).filter(ReqModel.id == primary_id).first()
    if not req_obj:
        return JSONResponse({"ok": False, "error": "Referans bulunamadı."}, status_code=404)

    report_title = title.strip() or f"HBF — {req_obj.request_no}"
    report = ExpenseReport(
        id=_uuid(),
        company_id=current_user.company_id,
        request_id=primary_id,
        request_ids_json=_json.dumps(refs, ensure_ascii=False),
        title=report_title,
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

    safe_name = f"{item_id}{ext}"
    try:
        key = save_upload(content, "expenses", safe_name)
    except Exception as exc:
        print(f"[UPLOAD ERROR] expenses/{safe_name}: {exc}", flush=True)
        return JSONResponse({"ok": False, "error": f"Dosya yüklenemedi: {exc}"}, status_code=500)

    item.document_path = key
    item.document_name = file.filename
    db.commit()
    return JSONResponse({"ok": True, "name": file.filename, "path": key})


@router.get("/doc/{item_id}", name="expenses_doc_download")
async def expenses_doc_download(
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = db.query(ExpenseItem).filter(ExpenseItem.id == item_id).first()
    if not item or not item.document_path:
        raise HTTPException(404)
    return _serve_upload(item.document_path, item.document_name or "belge")


# ---------------------------------------------------------------------------
# Belgesiz Gelir/Gider (inline AJAX — request detail'den çağrılır)
# ---------------------------------------------------------------------------

undoc_router = APIRouter(prefix="/undocumented", tags=["undocumented"])


@undoc_router.get("", response_class=HTMLResponse, name="undocumented_list")
async def undocumented_list(
    request: Request,
    type_filter: str = "all",   # all | gelir | gider
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role not in ("admin", "mudur", "muhasebe_muduru", "muhasebe", "yonetici"):
        raise HTTPException(403)

    query = db.query(UndocumentedEntry)
    if type_filter != "all":
        query = query.filter(UndocumentedEntry.entry_type == type_filter)

    # mudur (Etkinlik Süreç Müdürü), GM, admin, muhasebe_muduru: tüm belgesiz kayıtları görür

    entries = query.order_by(UndocumentedEntry.entry_date.desc(), UndocumentedEntry.created_at.desc()).all()

    gelir_total = sum(e.amount for e in entries if e.entry_type == "gelir")
    gider_total = sum(e.amount for e in entries if e.entry_type == "gider")
    can_manage = current_user.role in ("admin", "muhasebe_muduru", "muhasebe")

    # Ekleme formu için aktif referanslar (iptal ve kapalı hariç)
    all_requests = []
    if can_manage:
        all_requests = db.query(ReqModel).filter(
            ReqModel.status.notin_(["cancelled", "closed"])
        ).order_by(ReqModel.created_at.desc()).all()

    from datetime import date as _date
    today = _date.today().isoformat()

    return templates.TemplateResponse("undocumented/list.html", {
        "request":       request,
        "current_user":  current_user,
        "entries":       entries,
        "type_filter":   type_filter,
        "gelir_total":   gelir_total,
        "gider_total":   gider_total,
        "can_manage":    can_manage,
        "all_requests":  all_requests,
        "today":         today,
    })


@undoc_router.post("/add", name="undocumented_add")
async def undocumented_add(
    request: Request,
    request_id: str = Form(...),
    entry_type: str = Form(...),    # gelir | gider
    description: str = Form(""),
    amount: float = Form(0.0),
    entry_date: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role not in ("admin", "muhasebe_muduru", "muhasebe"):
        raise HTTPException(403, detail="Bu işlem için yetkiniz yok.")
    req = db.query(ReqModel).filter(ReqModel.id == request_id).first()
    if not req:
        raise HTTPException(404)
    if entry_type not in ("gelir", "gider"):
        raise HTTPException(400)
    if amount <= 0:
        return JSONResponse({"ok": False, "error": "Tutar 0'dan büyük olmalı."}, status_code=400)

    entry = UndocumentedEntry(
        id=_uuid(),
        request_id=request_id,
        entry_type=entry_type,
        description=description.strip(),
        amount=round(amount, 2),
        entry_date=entry_date.strip(),
        created_by=current_user.id,
        created_at=_now(),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return JSONResponse({
        "ok": True,
        "id": entry.id,
        "entry_type": entry.entry_type,
        "description": entry.description,
        "amount": entry.amount,
        "entry_date": entry.entry_date,
    })


@undoc_router.delete("/{entry_id}", name="undocumented_delete")
async def undocumented_delete(
    entry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entry = db.query(UndocumentedEntry).filter(UndocumentedEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(404)
    # Sadece muhasebe rolü veya admin silebilir
    if current_user.role not in ("admin", "muhasebe_muduru", "muhasebe"):
        raise HTTPException(403, detail="Bu işlem için yetkiniz yok.")
    db.delete(entry)
    db.commit()
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Yardımcı
# ---------------------------------------------------------------------------

def _sync_credit_card_txns(db: Session, report_id: str) -> None:
    """HBF kredi_karti kalemleri → micedesk kredi kartı işlemi (CreditCardTxn) oluşturur.
    Bu, kartın kullanılabilir limitinden düşer. Her kayıtta bu HBF'nin eski txn'leri
    silinip güncel kalemlerden yeniden oluşturulur (idempotent senkron)."""
    from datetime import date as _date2
    db.query(DeskCreditCardTxn).filter(
        DeskCreditCardTxn.expense_report_id == report_id
    ).delete(synchronize_session=False)
    report = db.query(ExpenseReport).filter(ExpenseReport.id == report_id).first()
    title = (report.title if report else "") or "HBF harcaması"
    for item in db.query(ExpenseItem).filter(ExpenseItem.report_id == report_id).all():
        if item.payment_method == "kredi_karti" and item.credit_card_id:
            card = db.query(DeskCreditCard).filter(DeskCreditCard.id == item.credit_card_id).first()
            try:
                tdate = _date2.fromisoformat(item.item_date) if item.item_date else _date2.today()
            except Exception:
                tdate = _date2.today()
            db.add(DeskCreditCardTxn(
                id=_uuid(),
                company_id=(card.company_id if card else None),
                card_id=item.credit_card_id,
                amount=round(item.total_amount or 0, 2),
                txn_date=tdate,
                description=(f"{title} — {item.description or ''}").strip(" —")[:300],
                is_refund=False,
                expense_report_id=report_id,
            ))
    db.flush()


def _save_items_from_json(db: Session, report_id: str, items_json: str) -> None:
    """
    Kalemleri JSON'dan günceller.
    Mevcut ID ile eşleşen satırlarda belge eki (document_path) korunur;
    JSON'da path gönderilmemişse DB değeri bozulmaz.
    """
    import json
    try:
        new_items = json.loads(items_json or "[]")
    except Exception:
        new_items = []

    # Mevcut kalemleri ID'ye göre indeksle (belge yollarını korumak için)
    existing: dict = {
        item.id: item
        for item in db.query(ExpenseItem).filter(ExpenseItem.report_id == report_id).all()
    }

    seen_ids: set = set()

    for idx, it in enumerate(new_items):
        doc_type = it.get("document_type", "fis")
        if "total_amount" in it:
            total_amount = float(it.get("total_amount", 0) or 0)
            vat_amount   = 0.0 if doc_type == "belgesiz" else float(it.get("vat_amount", 0) or 0)
            amount       = round(total_amount - vat_amount, 2)
            vat_rate     = round(vat_amount / amount * 100, 2) if amount > 0 else 0.0
        else:
            amount       = float(it.get("amount", 0) or 0)
            vat_rate     = float(it.get("vat_rate", 0) or 0)
            vat_amount   = round(amount * vat_rate / 100, 2)
            total_amount = round(amount + vat_amount, 2)

        json_id   = (it.get("id") or "").strip()
        json_path = it.get("document_path") or None
        json_name = it.get("document_name") or None

        if json_id and json_id in existing:
            # Mevcut kalemi yerinde güncelle
            item = existing[json_id]
            item.assigned_request_id = it.get("assigned_request_id") or None
            item.item_date           = it.get("item_date", "") or ""
            item.description         = it.get("description", "") or ""
            item.payment_method      = it.get("payment_method", "nakit")
            item.credit_card_id      = (it.get("credit_card_id") or None) if it.get("payment_method") == "kredi_karti" else None
            item.document_type       = doc_type
            item.amount              = round(amount, 2)
            item.vat_rate            = round(vat_rate, 2)
            item.vat_amount          = round(vat_amount, 2)
            item.total_amount        = round(total_amount, 2)
            item.sort_order          = idx
            # Belge yolu: JSON'da varsa güncelle, yoksa DB değerini koru
            if json_path:
                item.document_path = json_path
                item.document_name = json_name
            seen_ids.add(json_id)
        else:
            # Yeni kalem oluştur
            item = ExpenseItem(
                id=_uuid(),
                report_id=report_id,
                assigned_request_id=it.get("assigned_request_id") or None,
                item_date=it.get("item_date", "") or "",
                description=it.get("description", "") or "",
                payment_method=it.get("payment_method", "nakit"),
                credit_card_id=(it.get("credit_card_id") or None) if it.get("payment_method") == "kredi_karti" else None,
                document_type=doc_type,
                amount=round(amount, 2),
                vat_rate=round(vat_rate, 2),
                vat_amount=round(vat_amount, 2),
                total_amount=round(total_amount, 2),
                sort_order=idx,
                document_path=json_path,
                document_name=json_name,
                created_at=_now(),
            )
            db.add(item)

    # Kullanıcının sildiği kalemleri DB'den de temizle
    for item_id, item in existing.items():
        if item_id not in seen_ids:
            db.delete(item)

    db.flush()

    # miceapp suite: kredi kartı harcamalarını kartın limitinden düş (CreditCardTxn senkron)
    _sync_credit_card_txns(db, report_id)
