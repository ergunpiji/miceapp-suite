"""
FastAPI sub-router builder.
build_router(module) host app'in EInvoiceModule instance'ından bir
APIRouter üretir; host'un get_db / require_admin dependency'lerini kullanır.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from .helpers import sync_inbox


def build_router(module) -> APIRouter:
    router = APIRouter()

    Submission = module.Submission
    InboxItem = module.InboxItem

    # Host'un dependency'leri
    get_db = module.get_db or (lambda: None)  # zorunlu — host vermeli
    require_admin = module.require_admin or (lambda: None)
    get_current_user = module.get_current_user or (lambda: None)

    # ----------------------------- Status / Health -----------------------------

    @router.get("/health", name="einvoice_health")
    async def health(current_user=Depends(get_current_user)):
        ok = False
        try:
            ok = module.provider.check_connection()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "provider": module.provider.name, "error": str(exc)}
        return {"ok": ok, "provider": module.provider.name, "sandbox": module.provider.config.sandbox}

    # ----------------------------- Mükellef sorgu -----------------------------

    @router.post("/check-efatura-user", name="einvoice_check_user")
    async def check_user(
        tax_no: str = Form(...),
        current_user=Depends(get_current_user),
    ):
        info = module.provider.check_efatura_user(tax_no.strip())
        return {
            "tax_no": tax_no, "is_user": info.is_user,
            "alias": info.alias, "title": info.title,
        }

    # ----------------------------- Submissions -----------------------------

    @router.get("/submissions/{invoice_id}", name="einvoice_submissions_for_invoice")
    async def list_submissions_for_invoice(
        invoice_id: str,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
    ):
        rows = db.query(Submission).filter(
            Submission.invoice_id == invoice_id
        ).order_by(Submission.submitted_at.desc()).all()
        return [
            {"id": r.id, "uuid": r.uuid, "doc_type": r.doc_type,
             "status": r.status, "status_detail": r.status_detail,
             "provider": r.provider, "submitted_at": r.submitted_at,
             "responded_at": r.responded_at, "pdf_url": r.pdf_url}
            for r in rows
        ]

    @router.post("/submissions/{submission_id}/refresh-status", name="einvoice_refresh_status")
    async def refresh_status(
        submission_id: int,
        db: Session = Depends(get_db),
        current_user=Depends(require_admin),
    ):
        s = db.query(Submission).get(submission_id)
        if not s or not s.uuid:
            raise HTTPException(404)
        result = module.provider.get_status(s.uuid)
        s.status = result.status
        s.status_detail = result.detail
        if result.pdf_url:
            s.pdf_url = result.pdf_url
        s.responded_at = datetime.utcnow()
        db.commit()
        return {"ok": True, "status": s.status}

    @router.post("/submissions/{submission_id}/cancel", name="einvoice_cancel")
    async def cancel(
        submission_id: int,
        reason: str = Form(""),
        db: Session = Depends(get_db),
        current_user=Depends(require_admin),
    ):
        s = db.query(Submission).get(submission_id)
        if not s or not s.uuid:
            raise HTTPException(404)
        result = module.provider.cancel_invoice(s.uuid, reason or "—")
        s.status = result.status
        s.status_detail = result.detail
        db.commit()
        return {"ok": result.success, "status": s.status, "detail": result.detail}

    # ----------------------------- Inbox -----------------------------

    @router.get("/inbox", name="einvoice_inbox_list")
    async def inbox_list(
        status: Optional[str] = None,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
    ):
        q = db.query(InboxItem).order_by(InboxItem.fetched_at.desc())
        if status:
            q = q.filter(InboxItem.status == status)
        rows = q.limit(500).all()
        return [
            {"id": r.id, "external_uuid": r.external_uuid,
             "sender_tax_no": r.sender_tax_no, "sender_name": r.sender_name,
             "invoice_no": r.invoice_no, "invoice_date": r.invoice_date,
             "total_amount": r.total_amount, "status": r.status,
             "fetched_at": r.fetched_at}
            for r in rows
        ]

    @router.post("/inbox/sync", name="einvoice_inbox_sync")
    async def inbox_sync_endpoint(
        days: int = Form(30),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
    ):
        since = datetime.utcnow() - timedelta(days=max(1, min(days, 365)))
        n = sync_inbox(db, inbox_model=InboxItem, provider=module.provider, since=since)
        return {"ok": True, "new": n}

    @router.post("/inbox/{item_id}/ignore", name="einvoice_inbox_ignore")
    async def inbox_ignore(
        item_id: int,
        db: Session = Depends(get_db),
        current_user=Depends(require_admin),
    ):
        item = db.query(InboxItem).get(item_id)
        if not item:
            raise HTTPException(404)
        item.status = "ignored"
        db.commit()
        return {"ok": True}

    # ----------------------------- Webhook -----------------------------

    @router.post("/webhook", name="einvoice_webhook")
    async def webhook(request: Request, db: Session = Depends(get_db)):
        body = await request.body()
        headers = dict(request.headers)
        if not module.provider.verify_webhook(headers, body):
            raise HTTPException(401, "Webhook imzası doğrulanamadı")
        # Default: yalnızca log; provider-spesifik handling host adapter'da
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            payload = {"raw": body.decode("utf-8", errors="replace")}
        # UUID üzerinden submission güncelleme
        u = payload.get("uuid") or payload.get("ettn")
        if u:
            s = db.query(Submission).filter(Submission.uuid == u).first()
            if s:
                s.status = payload.get("status", s.status)
                s.status_detail = payload.get("detail")
                s.responded_at = datetime.utcnow()
                db.commit()
        return JSONResponse({"ok": True})

    return router
