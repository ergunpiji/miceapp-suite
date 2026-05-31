"""
Referanslar — iş/proje takibi
"""

from datetime import date, datetime
import json
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user, get_company_id, require_admin, require_module
from access_policy import visible_references_query, can_access_reference
from database import get_db, generate_ref_no
from models import Reference, Customer, Invoice, User, Company, EVENT_TYPES, SALES_EVENT_TYPES
from notification_helper import notify
from templates_config import templates

router = APIRouter(prefix="/references", tags=["references"])


def _ref_total(ref_id: str, db: Session, cid: int) -> float:
    """Referansın kesilen+komisyon fatura toplamı (KDV hariç) — limit karşılaştırması için."""
    invoices = db.query(Invoice).filter(
        Invoice.ref_id == ref_id,
        Invoice.company_id == cid,
        Invoice.invoice_type.in_(["kesilen", "komisyon"]),
        Invoice.status.in_(["approved", "partial", "paid"]),
    ).all()
    return sum(i.amount for i in invoices)


def _get_limits(db: Session, cid: int):
    """Şirket onay limitlerini döner. None = limit yok (kendi başına kapatamaz)."""
    c = db.query(Company).filter(Company.id == cid).first()
    if not c:
        return None, None
    return c.ref_close_limit_kullanici, c.ref_close_limit_mudur


@router.get("", response_class=HTMLResponse, name="references_list")
async def references_list(
    request: Request,
    q: str = "",
    status_filter: str = "",
    approval_status: str = "",
    archived: str = "",
    current_user: User = Depends(require_module("references")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    show_archived = archived == "1"
    query = visible_references_query(db, current_user)
    if show_archived:
        query = query.filter(Reference.status == "arsiv")
    elif approval_status == "pending":
        query = query.filter(Reference.approval_status.in_([
            "kapanış_talep", "mudur_onayladi", "reaktivasyon_talep"
        ])).filter(Reference.status != "arsiv")
    elif status_filter:
        query = query.filter(Reference.status == status_filter)
    else:
        query = query.filter(Reference.status != "arsiv")
    if q:
        query = query.filter(
            Reference.title.ilike(f"%{q}%") |
            Reference.ref_no.ilike(f"%{q}%")
        )
    refs = query.order_by(Reference.created_at.desc()).all()
    # Müşteri dropdown'u — yetkili olduğu müşteriler
    from access_policy import visible_customers_query
    customers = visible_customers_query(db, current_user).order_by(Customer.name).all()
    # Arşiv sayacı — yetkili olduğu referansların arşivi
    archived_count = (
        visible_references_query(db, current_user)
        .filter(Reference.status == "arsiv")
        .count()
    )
    return templates.TemplateResponse(
        "references/list.html",
        {
            "request": request,
            "current_user": current_user,
            "refs": refs,
            "customers": customers,
            "q": q,
            "status_filter": status_filter,
            "show_archived": show_archived,
            "archived_count": archived_count,
            "page_title": "Referanslar",
        },
    )


@router.get("/new", response_class=HTMLResponse, name="reference_new_get")
async def reference_new_get(
    request: Request,
    current_user: User = Depends(require_module("references", edit=True)),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    # miceapp suite: Referans yaratma SADECE event (miceapp/satış) tarafında yapılır.
    # micedesk referans OLUŞTURMAZ — yalnızca görüntüler. Bu yüzden form devre dışı.
    return RedirectResponse(url="/references", status_code=303)


@router.post("/new", name="reference_new_post")
async def reference_new_post(
    request: Request,
    customer_id: str = Form(None),
    title: str = Form(...),
    event_type: str = Form("yi"),
    check_in: str = Form(""),
    check_out: str = Form(""),
    notes: str = Form(""),
    current_user: User = Depends(require_module("references", edit=True)),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    # miceapp suite: micedesk referans OLUŞTURMAZ — referanslar event (satış) tarafında açılır.
    # Doğrudan POST denense bile engellenir.
    return RedirectResponse(url="/references", status_code=303)


@router.get("/{ref_id}", response_class=HTMLResponse, name="reference_detail")
async def reference_detail(
    ref_id: str,
    request: Request,
    current_user: User = Depends(require_module("references")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    if not can_access_reference(db, current_user, ref_id):
        raise HTTPException(status_code=404)
    ref = db.query(Reference).filter(Reference.id == ref_id, Reference.company_id == cid).first()
    if not ref:
        raise HTTPException(status_code=404)
    invoices = db.query(Invoice).filter(Invoice.ref_id == ref_id, Invoice.company_id == cid).order_by(Invoice.invoice_date.desc()).all()

    total_kesilen = (
        sum(i.amount for i in invoices if i.invoice_type in ("kesilen", "komisyon"))
        + sum(i.amount for i in invoices if i.invoice_type == "iade_kesilen")
    )
    total_gelen = (
        sum(i.amount for i in invoices if i.invoice_type == "gelen")
        + sum(i.amount for i in invoices if i.invoice_type == "iade_gelen")
    )
    kar = total_kesilen - total_gelen
    kar_orani = round(kar / total_kesilen * 100, 1) if total_kesilen else None

    return templates.TemplateResponse(
        "references/detail.html",
        {
            "request": request,
            "current_user": current_user,
            "ref": ref,
            "invoices": invoices,
            "total_kesilen": total_kesilen,
            "total_gelen": total_gelen,
            "kar": kar,
            "kar_orani": kar_orani,
            "ref_total": total_kesilen,
            "limit_kullanici": _get_limits(db, cid)[0],
            "limit_mudur": _get_limits(db, cid)[1],
            "page_title": f"Referans — {ref.ref_no}",
        },
    )


@router.get("/{ref_id}/edit", response_class=HTMLResponse, name="reference_edit_get")
async def reference_edit_get(
    ref_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    # miceapp suite: micedesk referansı DÜZENLEYEMEZ — referanslar event (satış) tarafında açılır/yönetilir.
    return RedirectResponse(url=f"/references/{ref_id}", status_code=303)


@router.post("/{ref_id}/edit", name="reference_edit_post")
async def reference_edit_post(
    request: Request,
    ref_id: str,
    ref_no: str = Form(...),
    customer_id: str = Form(None),
    title: str = Form(...),
    event_type: str = Form("diger"),
    check_in: str = Form(""),
    check_out: str = Form(""),
    notes: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    # miceapp suite: micedesk referansı DÜZENLEYEMEZ — doğrudan POST denense bile engellenir.
    return RedirectResponse(url=f"/references/{ref_id}", status_code=303)


@router.post("/{ref_id}/status", name="reference_status")
async def reference_status(
    ref_id: str,
    new_status: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    ref = db.query(Reference).filter(Reference.id == ref_id, Reference.company_id == cid).first()
    if not ref:
        raise HTTPException(status_code=404)
    # Kilitli referansta sadece admin durum değiştirebilir
    if ref.is_locked and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Onaylanmış referans kilitlidir.")
    # "tamamlandi" doğrudan ayarlanamaz — onay akışından geçmeli (GM/admin hariç)
    if new_status == "tamamlandi" and not current_user.is_approver:
        raise HTTPException(status_code=403, detail="Tamamlandı için GM onayı gereklidir.")
    if new_status in ("aktif", "iptal"):
        ref.status = new_status
        # Aktife alınırsa onay sıfırla
        if new_status == "aktif" and ref.approval_status not in (None, "gm_onayladi"):
            ref.approval_status = None
            ref.approval_requested_by = None
            ref.approval_requested_at = None
            ref.mudur_approved_by = None
            ref.mudur_approved_at = None
        db.commit()
    return RedirectResponse(url=f"/references/{ref_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{ref_id}/request-close", name="reference_request_close")
async def reference_request_close(
    ref_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    """Kullanıcı kapanış talep eder. Kendi limiti yeterliyse direkt kapanır."""
    ref = db.query(Reference).filter(Reference.id == ref_id, Reference.company_id == cid).first()
    if not ref:
        raise HTTPException(status_code=404)
    if ref.is_locked:
        raise HTTPException(status_code=403, detail="Referans zaten kilitli.")
    if ref.status == "iptal":
        raise HTTPException(status_code=400, detail="İptal edilmiş referans kapatılamaz.")

    ref.approval_requested_by = ref.approval_requested_by or current_user.id
    ref.approval_requested_at = ref.approval_requested_at or datetime.utcnow()

    # GM / admin → direkt kapanır
    if current_user.is_approver:
        ref.approval_status = "gm_onayladi"
        ref.gm_approved_by = current_user.id
        ref.gm_approved_at = datetime.utcnow()
        ref.status = "tamamlandi"
        db.commit()
        return RedirectResponse(url=f"/references/{ref_id}", status_code=status.HTTP_302_FOUND)

    # Limit kontrolü
    total = _ref_total(ref_id, db, cid)
    limit_kullanici, limit_mudur = _get_limits(db, cid)

    if current_user.role == "mudur":
        # Müdür: kendi limitine bakılır
        if limit_mudur is not None and total <= limit_mudur:
            ref.approval_status = "gm_onayladi"
            ref.mudur_approved_by = current_user.id
            ref.mudur_approved_at = datetime.utcnow()
            ref.gm_approved_by = current_user.id
            ref.gm_approved_at = datetime.utcnow()
            ref.status = "tamamlandi"
        else:
            ref.approval_status = "mudur_onayladi"
            ref.mudur_approved_by = current_user.id
            ref.mudur_approved_at = datetime.utcnow()
    else:
        # Normal kullanıcı
        if limit_kullanici is not None and total <= limit_kullanici:
            ref.approval_status = "gm_onayladi"
            ref.mudur_approved_by = current_user.id
            ref.mudur_approved_at = datetime.utcnow()
            ref.gm_approved_by = current_user.id
            ref.gm_approved_at = datetime.utcnow()
            ref.status = "tamamlandi"
        else:
            ref.approval_status = "kapanış_talep"
            ref.approval_requested_by = current_user.id
            ref.approval_requested_at = datetime.utcnow()

    db.commit()
    return RedirectResponse(url=f"/references/{ref_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{ref_id}/approve", name="reference_approve")
async def reference_approve(
    ref_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    """Müdür veya GM onaylar."""
    ref = db.query(Reference).filter(Reference.id == ref_id, Reference.company_id == cid).first()
    if not ref:
        raise HTTPException(status_code=404)
    if ref.is_locked:
        raise HTTPException(status_code=403, detail="Referans zaten onaylanmış.")
    if ref.approval_status not in ("kapanış_talep", "mudur_onayladi"):
        raise HTTPException(status_code=400, detail="Onaylanacak bir talep yok.")

    is_gm = current_user.is_approver  # genel_mudur, admin, super_admin

    if is_gm:
        # GM direkt son onayı verir
        ref.approval_status = "gm_onayladi"
        ref.gm_approved_by = current_user.id
        ref.gm_approved_at = datetime.utcnow()
        if not ref.mudur_approved_by:
            ref.mudur_approved_by = current_user.id
            ref.mudur_approved_at = datetime.utcnow()
        ref.status = "tamamlandi"
        notify(db, ref.approval_requested_by,
               title=f"Referans kapatıldı: {ref.ref_no}",
               message=f"{current_user.name} onayladı ve referans tamamlandı olarak kapatıldı.",
               link=f"/references/{ref_id}", notif_type="success", ref_id=ref_id)
    elif current_user.role == "mudur":
        # Müdür onayı — limit yeterliyse direkt kapat
        total = _ref_total(ref_id, db, cid)
        _, limit_mudur = _get_limits(db, cid)
        if limit_mudur is not None and total <= limit_mudur:
            ref.approval_status = "gm_onayladi"
            ref.gm_approved_by = current_user.id
            ref.gm_approved_at = datetime.utcnow()
            ref.mudur_approved_by = current_user.id
            ref.mudur_approved_at = datetime.utcnow()
            ref.status = "tamamlandi"
            notify(db, ref.approval_requested_by,
                   title=f"Referans kapatıldı: {ref.ref_no}",
                   message=f"{current_user.name} onayladı ve referans tamamlandı olarak kapatıldı.",
                   link=f"/references/{ref_id}", notif_type="success", ref_id=ref_id)
        else:
            ref.approval_status = "mudur_onayladi"
            ref.mudur_approved_by = current_user.id
            ref.mudur_approved_at = datetime.utcnow()
            notify(db, ref.approval_requested_by,
                   title=f"Müdür onayı verildi: {ref.ref_no}",
                   message=f"{current_user.name} onayladı. GM onayı bekleniyor.",
                   link=f"/references/{ref_id}", notif_type="info", ref_id=ref_id)
    else:
        raise HTTPException(status_code=403, detail="Onay yetkiniz yok.")

    db.commit()
    return RedirectResponse(url=f"/references/{ref_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{ref_id}/reject-close", name="reference_reject_close")
async def reference_reject_close(
    ref_id: str,
    rejection_note: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    """Müdür veya GM kapanış talebini reddeder."""
    ref = db.query(Reference).filter(Reference.id == ref_id, Reference.company_id == cid).first()
    if not ref:
        raise HTTPException(status_code=404)
    if ref.approval_status not in ("kapanış_talep", "mudur_onayladi"):
        raise HTTPException(status_code=400, detail="Reddedilecek aktif talep yok.")
    if not (current_user.role in ["mudur", "genel_mudur", "admin", "super_admin"]):
        raise HTTPException(status_code=403)

    ref.approval_status = "reddedildi"
    ref.approval_rejection_note = rejection_note.strip() or None
    notify(db, ref.approval_requested_by,
           title=f"Kapanış talebi reddedildi: {ref.ref_no}",
           message=f"{current_user.name} reddetti." + (f" Neden: {rejection_note.strip()}" if rejection_note.strip() else ""),
           link=f"/references/{ref_id}", notif_type="danger", ref_id=ref_id)
    db.commit()
    return RedirectResponse(url=f"/references/{ref_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{ref_id}/request-reactivate", name="reference_request_reactivate")
async def reference_request_reactivate(
    ref_id: str,
    reactivation_note: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    """Kilitli referans için GM'den aktifleştirme talebi."""
    ref = db.query(Reference).filter(Reference.id == ref_id, Reference.company_id == cid).first()
    if not ref:
        raise HTTPException(status_code=404)
    if not ref.is_locked:
        raise HTTPException(status_code=400, detail="Referans kilitli değil.")
    if current_user.is_approver:
        raise HTTPException(status_code=400, detail="GM zaten doğrudan aktife alabilir.")

    ref.approval_status = "reaktivasyon_talep"
    ref.reactivation_requested_by = current_user.id
    ref.reactivation_requested_at = datetime.utcnow()
    ref.reactivation_note = reactivation_note.strip() or None
    db.commit()
    return RedirectResponse(url=f"/references/{ref_id}", status_code=status.HTTP_302_FOUND)


@router.post("/{ref_id}/approve-reactivate", name="reference_approve_reactivate")
async def reference_approve_reactivate(
    ref_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    """GM aktifleştirme talebini onaylar."""
    ref = db.query(Reference).filter(Reference.id == ref_id, Reference.company_id == cid).first()
    if not ref:
        raise HTTPException(status_code=404)
    if not current_user.is_approver:
        raise HTTPException(status_code=403, detail="GM yetkisi gerekli.")

    requester_id = ref.reactivation_requested_by
    ref.status = "aktif"
    ref.approval_status = None
    ref.approval_requested_by = None
    ref.approval_requested_at = None
    ref.mudur_approved_by = None
    ref.mudur_approved_at = None
    ref.gm_approved_by = None
    ref.gm_approved_at = None
    ref.reactivation_requested_by = None
    ref.reactivation_requested_at = None
    ref.reactivation_note = None
    ref.approval_rejection_note = None
    notify(db, requester_id,
           title=f"Referans aktife alındı: {ref.ref_no}",
           message=f"{current_user.name} aktifleştirme talebinizi onayladı.",
           link=f"/references/{ref_id}", notif_type="success", ref_id=ref_id)
    db.commit()
    return RedirectResponse(url=f"/references/{ref_id}", status_code=status.HTTP_302_FOUND)


@router.post("/bulk-archive", name="reference_bulk_archive")
async def reference_bulk_archive(
    ids_json: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    if not current_user.has_role_min("mudur"):
        return JSONResponse({"ok": False, "error": "Yetersiz yetki"}, status_code=403)
    try:
        ids = json.loads(ids_json)
        if not isinstance(ids, list):
            raise ValueError
    except Exception:
        return JSONResponse({"ok": False, "error": "Geçersiz veri"}, status_code=400)

    updated = 0
    skipped = 0
    for rid in ids:
        ref = db.query(Reference).filter(Reference.id == int(rid), Reference.company_id == cid).first()
        if not ref or ref.status == "arsiv":
            continue
        if ref.status != "tamamlandi":
            skipped += 1
            continue
        ref.status = "arsiv"
        updated += 1
    db.commit()
    msg = None
    if skipped:
        msg = f"{skipped} referans 'tamamlandı' olmadığı için arşivlenmedi."
    return JSONResponse({"ok": True, "archived": updated, "skipped": skipped, "msg": msg})


@router.post("/{ref_id}/unarchive", name="reference_unarchive")
async def reference_unarchive(
    ref_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    if not current_user.has_role_min("mudur"):
        raise HTTPException(status_code=403)
    ref = db.query(Reference).filter(Reference.id == ref_id, Reference.company_id == cid).first()
    if not ref:
        raise HTTPException(status_code=404)
    ref.status = "tamamlandi"
    db.commit()
    return RedirectResponse(url="/references?archived=1", status_code=status.HTTP_302_FOUND)


@router.post("/{ref_id}/delete", name="reference_delete")
async def reference_delete(
    ref_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    ref = db.query(Reference).filter(Reference.id == ref_id, Reference.company_id == current_user.company_id).first()
    if ref:
        db.delete(ref)
        db.commit()
    return RedirectResponse(url="/references", status_code=status.HTTP_302_FOUND)
