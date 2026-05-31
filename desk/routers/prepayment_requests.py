"""
Satın Alma — Ön Ödeme Talep Sistemi

Akış:
  PM / Müdür  → oluştur  (status: pending_gm)
  GM          → onayla / reddet
  Muhasebe    → ödemeyi işle → VendorPrepayment oluştur + bildirim gönder
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import (
    Vendor,
    PrepaymentRequest,
    PrepaymentRequestLog,
    VendorPrepayment,
    PREPAYMENT_REQUEST_STATUSES,
    PREPAYMENT_REQUEST_LOG_ACTIONS,
    Request as ReqModel,
    User,
    _uuid,
    _now,
)
from templates_config import templates
from utils.notifications import create_notification

router = APIRouter(prefix="/prepayment-requests", tags=["prepayment_requests"])

# Talep oluşturabilecek roller
REQUESTER_ROLES = {"admin", "mudur", "yonetici", "asistan"}
# GM onay rolü → is_gm kontrolü yapılıyor
# Ödeme yapabilecek roller
FINANCE_ROLES = {"admin", "muhasebe_muduru", "muhasebe"}


def _is_gm(user: User) -> bool:
    return user.is_gm


def _require_can_request(user: User):
    if user.role not in REQUESTER_ROLES and not _is_gm(user):
        raise HTTPException(403, "Bu işlem için yetkiniz yok.")


def _require_finance(user: User):
    if user.role not in FINANCE_ROLES:
        raise HTTPException(403, "Bu işlem için yetkiniz yok.")


def _add_log(db: Session, pr_id: str, action: str, actor_id: str, note: str = ""):
    db.add(PrepaymentRequestLog(
        id=_uuid(), prepayment_request_id=pr_id,
        action=action, actor_id=actor_id, note=note, created_at=_now(),
    ))


def _get_gm_users(db: Session) -> list[User]:
    return [u for u in db.query(User).filter(User.active == True).all() if u.is_gm]


def _get_finance_users(db: Session) -> list[User]:
    return db.query(User).filter(
        User.active == True,
        User.role.in_(["muhasebe_muduru", "muhasebe"]),
    ).all()


# ---------------------------------------------------------------------------
# GET /prepayment-requests/new  — Talep oluşturma formu
# ---------------------------------------------------------------------------

@router.get("/new", name="prepayment_requests_new")
async def prepayment_requests_new_form(
    request: Request,
    vendor_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_can_request(current_user)

    vendors = (
        db.query(Vendor)
        .filter(Vendor.active == True)  # noqa: E712
        .order_by(Vendor.name)
        .all()
    )

    # Referans listesi — talep edenin erişebildiği referanslar
    if current_user.role == "admin" or _is_gm(current_user):
        req_query = db.query(ReqModel).filter(
            ReqModel.status.notin_(["cancelled"])
        )
    elif current_user.team_id:
        req_query = db.query(ReqModel).filter(
            ReqModel.team_id == current_user.team_id,
            ReqModel.status.notin_(["cancelled"]),
        )
    else:
        req_query = db.query(ReqModel).filter(
            ReqModel.created_by == current_user.id,
            ReqModel.status.notin_(["cancelled"]),
        )

    requests_list = req_query.order_by(ReqModel.created_at.desc()).limit(200).all()

    selected_vendor = None
    if vendor_id:
        selected_vendor = db.query(Vendor).filter(
            Vendor.id == vendor_id
        ).first()

    return templates.TemplateResponse("prepayment_requests/new.html", {
        "request":         request,
        "current_user":    current_user,
        "vendors":         vendors,
        "requests_list":   requests_list,
        "selected_vendor": selected_vendor,
        "today_str":       date.today().isoformat(),
        "page_title":      "Ön Ödeme Talebi Oluştur",
    })


# ---------------------------------------------------------------------------
# POST /prepayment-requests/new  — Talebi kaydet
# ---------------------------------------------------------------------------

@router.post("/new", name="prepayment_requests_create")
async def prepayment_requests_create(
    request: Request,
    vendor_id:   str           = Form(...),
    request_id:  Optional[str] = Form(None),
    amount:      float         = Form(...),
    description: str           = Form(""),
    notes:       str           = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_can_request(current_user)

    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(404, "Tedarikçi bulunamadı.")

    pr = PrepaymentRequest(
        id           = _uuid(),
        vendor_id    = vendor_id,
        request_id   = request_id or None,
        amount       = amount,
        description  = description.strip(),
        notes        = notes.strip(),
        status       = "pending_gm",
        requested_by = current_user.id,
        requested_at = _now(),
        created_at   = _now(),
        updated_at   = _now(),
    )
    db.add(pr)
    db.flush()
    _add_log(db, pr.id, "created", current_user.id,
             f"₺{amount:,.0f} — {vendor.name}")

    # GM kullanıcılarına bildirim
    for gm in _get_gm_users(db):
        create_notification(
            db,
            user_id    = gm.id,
            notif_type = "prepayment_request_pending",
            title      = f"Ön Ödeme Talebi: {vendor.name}",
            message    = f"{current_user.name} {current_user.surname} — ₺{amount:,.0f}",
            link       = f"/prepayment-requests/{pr.id}",
            ref_id     = pr.id,
        )

    db.commit()
    return RedirectResponse(f"/prepayment-requests/{pr.id}?created=1", status_code=303)


# ---------------------------------------------------------------------------
# GET /prepayment-requests  — Liste
# ---------------------------------------------------------------------------

@router.get("", name="prepayment_requests_list")
async def prepayment_requests_list(
    request: Request,
    status:  Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    can_request = current_user.role in REQUESTER_ROLES or _is_gm(current_user)
    can_finance = current_user.role in FINANCE_ROLES
    is_gm       = _is_gm(current_user)

    if not (can_request or can_finance or is_gm):
        raise HTTPException(403)

    query = db.query(PrepaymentRequest)

    # Rol bazlı filtreleme: muhasebe/GM hepsini görür, diğerleri sadece kendileri
    if current_user.role in FINANCE_ROLES or is_gm:
        pass  # hepsini gör
    elif current_user.team_id:
        # Aynı takımdaki talepleri gör
        team_member_ids = [
            u.id for u in db.query(User).filter(User.team_id == current_user.team_id).all()
        ]
        query = query.filter(PrepaymentRequest.requested_by.in_(team_member_ids))
    else:
        query = query.filter(PrepaymentRequest.requested_by == current_user.id)

    if status:
        query = query.filter(PrepaymentRequest.status == status)

    prepayments = query.order_by(PrepaymentRequest.created_at.desc()).all()

    # Badge sayıları
    pending_gm_count = db.query(PrepaymentRequest).filter(
        PrepaymentRequest.status == "pending_gm"
    ).count() if is_gm else 0

    approved_count = db.query(PrepaymentRequest).filter(
        PrepaymentRequest.status == "approved"
    ).count() if can_finance else 0

    return templates.TemplateResponse("prepayment_requests/list.html", {
        "request":          request,
        "current_user":     current_user,
        "prepayments":      prepayments,
        "status_filter":    status or "all",
        "statuses":         PREPAYMENT_REQUEST_STATUSES,
        "pending_gm_count": pending_gm_count,
        "approved_count":   approved_count,
        "can_request":      can_request,
        "can_finance":      can_finance,
        "is_gm":            is_gm,
        "page_title":       "Ön Ödeme Talepleri",
        "today_str":        date.today().isoformat(),
    })


# ---------------------------------------------------------------------------
# GET /prepayment-requests/{id}  — Detay
# ---------------------------------------------------------------------------

@router.get("/{pr_id}", name="prepayment_requests_detail")
async def prepayment_requests_detail(
    pr_id: str,
    request: Request,
    created: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pr = db.query(PrepaymentRequest).filter(PrepaymentRequest.id == pr_id).first()
    if not pr:
        raise HTTPException(404, "Talep bulunamadı.")

    can_finance = current_user.role in FINANCE_ROLES
    is_gm       = _is_gm(current_user)
    is_requester = current_user.id == pr.requested_by

    if not (can_finance or is_gm or is_requester or
            current_user.role in REQUESTER_ROLES):
        raise HTTPException(403)

    # Log kayıtları
    logs = (
        db.query(PrepaymentRequestLog)
        .filter(PrepaymentRequestLog.prepayment_request_id == pr_id)
        .order_by(PrepaymentRequestLog.created_at)
        .all()
    )

    return templates.TemplateResponse("prepayment_requests/detail.html", {
        "request":       request,
        "current_user":  current_user,
        "pr":            pr,
        "logs":          logs,
        "log_actions":   PREPAYMENT_REQUEST_LOG_ACTIONS,
        "statuses":      PREPAYMENT_REQUEST_STATUSES,
        "can_finance":   can_finance,
        "is_gm":         is_gm,
        "is_requester":  is_requester,
        "just_created":  created == "1",
        "today_str":     date.today().isoformat(),
        "page_title":    f"Ön Ödeme Talebi — {pr.vendor.name if pr.vendor else ''}",
    })


# ---------------------------------------------------------------------------
# POST /prepayment-requests/{id}/approve  — GM onaylar
# ---------------------------------------------------------------------------

@router.post("/{pr_id}/approve", name="prepayment_requests_approve")
async def prepayment_requests_approve(
    pr_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not _is_gm(current_user):
        raise HTTPException(403, "Sadece Genel Müdür onaylayabilir.")

    pr = db.query(PrepaymentRequest).filter(PrepaymentRequest.id == pr_id).first()
    if not pr or pr.status != "pending_gm":
        raise HTTPException(400, "Bu talep onaylanamaz.")

    pr.status      = "approved"
    pr.approved_by = current_user.id
    pr.approved_at = _now()
    pr.updated_at  = _now()
    _add_log(db, pr.id, "approved", current_user.id)

    # Muhasebe ekibine bildirim
    for fu in _get_finance_users(db):
        create_notification(
            db,
            user_id    = fu.id,
            notif_type = "prepayment_request_approved",
            title      = f"Ön Ödeme Onaylandı: {pr.vendor.name if pr.vendor else ''}",
            message    = f"GM onayladı — ₺{pr.amount:,.0f} ödenmesi bekleniyor.",
            link       = f"/prepayment-requests/{pr.id}",
            ref_id     = pr.id,
        )

    # Talep edene bildirim
    create_notification(
        db,
        user_id    = pr.requested_by,
        notif_type = "prepayment_request_approved_requester",
        title      = f"Ön Ödeme Talebiniz Onaylandı",
        message    = f"{pr.vendor.name if pr.vendor else ''} — ₺{pr.amount:,.0f}",
        link       = f"/prepayment-requests/{pr.id}",
        ref_id     = pr.id,
    )

    db.commit()
    return RedirectResponse(f"/prepayment-requests/{pr.id}", status_code=303)


# ---------------------------------------------------------------------------
# POST /prepayment-requests/{id}/reject  — GM reddeder
# ---------------------------------------------------------------------------

@router.post("/{pr_id}/reject", name="prepayment_requests_reject")
async def prepayment_requests_reject(
    pr_id:          str,
    rejection_note: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not _is_gm(current_user):
        raise HTTPException(403, "Sadece Genel Müdür reddedebilir.")

    pr = db.query(PrepaymentRequest).filter(PrepaymentRequest.id == pr_id).first()
    if not pr or pr.status != "pending_gm":
        raise HTTPException(400, "Bu talep reddedilemez.")

    pr.status         = "rejected"
    pr.rejection_note = rejection_note.strip()
    pr.approved_by    = current_user.id
    pr.approved_at    = _now()
    pr.updated_at     = _now()
    _add_log(db, pr.id, "rejected", current_user.id, rejection_note)

    # Talep edene bildirim
    create_notification(
        db,
        user_id    = pr.requested_by,
        notif_type = "prepayment_request_rejected",
        title      = "Ön Ödeme Talebiniz Reddedildi",
        message    = rejection_note or f"{pr.vendor.name if pr.vendor else ''} — ₺{pr.amount:,.0f}",
        link       = f"/prepayment-requests/{pr.id}",
        ref_id     = pr.id,
    )

    db.commit()
    return RedirectResponse(f"/prepayment-requests/{pr.id}", status_code=303)


# ---------------------------------------------------------------------------
# POST /prepayment-requests/{id}/pay  — Muhasebe öder
# ---------------------------------------------------------------------------

@router.post("/{pr_id}/pay", name="prepayment_requests_pay")
async def prepayment_requests_pay(
    pr_id:          str,
    paid_at:        str           = Form(...),
    payment_method: str           = Form("banka"),
    cc_due_date:    Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(current_user)

    pr = db.query(PrepaymentRequest).filter(PrepaymentRequest.id == pr_id).first()
    if not pr or pr.status != "approved":
        raise HTTPException(400, "Bu talep ödenemez (henüz GM onayı yok veya zaten işlendi).")

    # VendorPrepayment kaydı oluştur
    vp = VendorPrepayment(
        id             = _uuid(),
        vendor_id      = pr.vendor_id,
        request_id     = pr.request_id,
        amount         = pr.amount,
        applied_amount = 0.0,
        payment_date   = paid_at,
        payment_method = payment_method,
        notes          = pr.description or pr.notes or "",
        status         = "open",
        created_by     = current_user.id,
        created_at     = _now(),
        updated_at     = _now(),
    )
    db.add(vp)
    db.flush()

    # Talebi kapat
    pr.status                = "paid"
    pr.paid_by               = current_user.id
    pr.paid_at               = paid_at
    pr.payment_method        = payment_method
    pr.cc_due_date           = cc_due_date or None
    pr.vendor_prepayment_id  = vp.id
    pr.updated_at            = _now()
    _add_log(db, pr.id, "paid", current_user.id,
             f"₺{pr.amount:,.0f} — {payment_method} — {paid_at}")

    # Talep edene bildirim
    create_notification(
        db,
        user_id    = pr.requested_by,
        notif_type = "prepayment_request_paid",
        title      = "Ön Ödeme Yapıldı",
        message    = (
            f"{pr.vendor.name if pr.vendor else ''} — ₺{pr.amount:,.0f} — "
            f"{paid_at} tarihinde ödendi."
        ),
        link       = f"/prepayment-requests/{pr.id}",
        ref_id     = pr.id,
    )

    # GM'e bilgi
    for gm in _get_gm_users(db):
        create_notification(
            db,
            user_id    = gm.id,
            notif_type = "prepayment_request_paid_gm",
            title      = f"Ön Ödeme Yapıldı: {pr.vendor.name if pr.vendor else ''}",
            message    = f"₺{pr.amount:,.0f} — {paid_at}",
            link       = f"/prepayment-requests/{pr.id}",
            ref_id     = pr.id,
        )

    db.commit()
    return RedirectResponse(f"/prepayment-requests/{pr.id}", status_code=303)


# ---------------------------------------------------------------------------
# POST /prepayment-requests/{id}/cancel  — Talep iptal
# ---------------------------------------------------------------------------

@router.post("/{pr_id}/cancel", name="prepayment_requests_cancel")
async def prepayment_requests_cancel(
    pr_id:  str,
    note:   str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pr = db.query(PrepaymentRequest).filter(PrepaymentRequest.id == pr_id).first()
    if not pr:
        raise HTTPException(404)

    can_cancel = (
        current_user.id == pr.requested_by
        or current_user.role in FINANCE_ROLES
        or _is_gm(current_user)
    )
    if not can_cancel:
        raise HTTPException(403)
    if pr.status in ("paid", "cancelled", "rejected"):
        raise HTTPException(400, "Bu talep iptal edilemez.")

    pr.status     = "cancelled"
    pr.updated_at = _now()
    _add_log(db, pr.id, "cancelled", current_user.id, note)

    db.commit()
    return RedirectResponse(f"/prepayment-requests/{pr.id}", status_code=303)
