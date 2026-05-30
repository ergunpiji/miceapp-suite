"""
E-Fatura host adapter — Invoice modeli ile prizma-einvoice paketi arasında köprü.

UI sayfaları (admin için):
  GET  /einvoice-ui                — modül paneli (overview, quick actions)
  GET  /einvoice-ui/inbox          — gelen e-fatura kalemleri tablosu
  POST /einvoice-ui/inbox/sync     — şimdi çek
  POST /einvoice-ui/inbox/{id}/import   — kalemden Invoice (gelen) yarat
  POST /einvoice-ui/inbox/{id}/ignore   — yok say

Invoice gönderim:
  POST /invoices/{invoice_id}/einvoice/send  — Invoice'tan InvoicePayload üret + paket helper'ı
"""
from datetime import datetime, timedelta
import json

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user, require_admin, require_mudur, require_module, get_company_id
from database import get_db
from models import (
    User, Invoice, InvoicePayment, Customer, Vendor, Reference,
    SystemSetting,
)
from templates_config import templates


router = APIRouter(tags=["einvoice_ui"])


# ---------------------------------------------------------------------------
# Modül aktif değilse 404
# ---------------------------------------------------------------------------

def _require_module_active(db: Session):
    s = db.query(SystemSetting).filter(SystemSetting.key == "module_einvoice_enabled").first()
    if not (s and s.value == "1"):
        raise HTTPException(404, "E-Fatura modülü aktif değil")


def _get_einvoice_module(request: Request):
    """app.py'da init edilmiş EInvoiceModule instance'ını döner."""
    mod = getattr(request.app.state, "einvoice_module", None)
    if mod is None:
        # app.py module-level einvoice_module değişkenini import edelim
        try:
            from app import einvoice_module as mod
        except Exception:  # noqa: BLE001
            mod = None
    if mod is None:
        raise HTTPException(503, "E-Fatura modülü yüklenmemiş")
    return mod


# ---------------------------------------------------------------------------
# Landing / Panel
# ---------------------------------------------------------------------------

@router.get("/einvoice-ui", response_class=HTMLResponse, name="einvoice_panel")
async def einvoice_panel(
    request: Request,
    current_user: User = Depends(require_module("einvoice")),
    db: Session = Depends(get_db),
):
    _require_module_active(db)
    mod = _get_einvoice_module(request)

    Submission = mod.Submission
    InboxItem = mod.InboxItem

    # Özet sayılar
    total_sent = db.query(Submission).filter(Submission.status.in_(["sent", "accepted"])).count()
    total_rejected = db.query(Submission).filter(Submission.status == "rejected").count()
    inbox_pending = db.query(InboxItem).filter(InboxItem.status == "received").count()

    # Son 5 gönderim
    recent = db.query(Submission).order_by(Submission.submitted_at.desc()).limit(5).all()

    return templates.TemplateResponse(
        "einvoice/panel.html",
        {
            "request": request,
            "current_user": current_user,
            "page_title": "E-Fatura Paneli",
            "provider_name": mod.provider.name,
            "is_sandbox": mod.provider.config.sandbox,
            "total_sent": total_sent,
            "total_rejected": total_rejected,
            "inbox_pending": inbox_pending,
            "recent": recent,
        },
    )


# ---------------------------------------------------------------------------
# Inbox
# ---------------------------------------------------------------------------

@router.get("/einvoice-ui/inbox", response_class=HTMLResponse, name="einvoice_inbox_ui")
async def einvoice_inbox(
    request: Request,
    status: str = "received",
    current_user: User = Depends(require_module("einvoice")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    _require_module_active(db)
    mod = _get_einvoice_module(request)
    InboxItem = mod.InboxItem

    q = db.query(InboxItem).order_by(InboxItem.fetched_at.desc())
    if status:
        q = q.filter(InboxItem.status == status)
    items = q.limit(500).all()

    vendors = db.query(Vendor).filter(
        Vendor.active == True,  # noqa: E712
        Vendor.company_id == cid,
    ).order_by(Vendor.name).all()
    references = db.query(Reference).filter(
        Reference.status == "aktif",
        Reference.company_id == cid,
    ).order_by(Reference.created_at.desc()).all()

    return templates.TemplateResponse(
        "einvoice/inbox.html",
        {
            "request": request,
            "current_user": current_user,
            "page_title": "Gelen E-Faturalar",
            "items": items,
            "selected_status": status,
            "vendors": vendors,
            "references": references,
        },
    )


@router.post("/einvoice-ui/inbox/sync", name="einvoice_inbox_sync_ui")
async def inbox_sync_ui(
    request: Request,
    days: int = Form(30),
    current_user: User = Depends(require_module("einvoice")),
    db: Session = Depends(get_db),
):
    _require_module_active(db)
    mod = _get_einvoice_module(request)
    from prizma_einvoice import sync_inbox
    since = datetime.utcnow() - timedelta(days=max(1, min(days, 365)))
    n = sync_inbox(db, inbox_model=mod.InboxItem, provider=mod.provider, since=since)
    return RedirectResponse(url=f"/einvoice-ui/inbox?synced={n}", status_code=303)


@router.get("/einvoice-ui/invoice/{invoice_id}/pdf", name="einvoice_invoice_pdf")
async def invoice_pdf(
    invoice_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """E-fatura PDF görüntüleme. Gerçek entegratör URL'i varsa oraya
    redirect; yoksa (örn. FakeProvider) yerel HTML preview döner."""
    _require_module_active(db)
    inv = db.query(Invoice).get(invoice_id)
    if not inv:
        raise HTTPException(404, "Fatura bulunamadı")
    pdf_url = inv.einvoice_pdf_url or ""
    # Gerçek (https) URL varsa ve fake değilse redirect
    if pdf_url.startswith("https://") and "fake-einvoice.local" not in pdf_url:
        return RedirectResponse(url=pdf_url, status_code=302)
    # Aksi → yerel HTML preview render et
    customer = inv.reference.customer if (inv.reference and inv.reference.customer) else None
    items = []
    if inv.items_json:
        try:
            items = json.loads(inv.items_json)
        except Exception:  # noqa: BLE001
            items = []
    return templates.TemplateResponse(
        "einvoice/invoice_html.html",
        {
            "request": request,
            "current_user": current_user,
            "page_title": f"E-Fatura {inv.invoice_no or inv.id}",
            "invoice": inv,
            "customer": customer,
            "items": items,
            "is_fake": "fake-einvoice.local" in pdf_url or not pdf_url,
        },
    )


@router.get("/einvoice-ui/inbox/{item_id}/preview", name="einvoice_inbox_preview")
async def inbox_preview(
    item_id: str,
    request: Request,
    current_user: User = Depends(require_module("einvoice")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    """Inbox kaleminin detayını fragment olarak döner — modal AJAX için."""
    _require_module_active(db)
    mod = _get_einvoice_module(request)
    item = db.query(mod.InboxItem).get(item_id)
    if not item:
        raise HTTPException(404)
    detail = mod.provider.fetch_inbox_item(item.external_uuid)
    vendors = db.query(Vendor).filter(
        Vendor.active == True,  # noqa: E712
        Vendor.company_id == cid,
    ).order_by(Vendor.name).all()
    references = db.query(Reference).filter(
        Reference.status == "aktif",
        Reference.company_id == cid,
    ).order_by(Reference.created_at.desc()).all()
    return templates.TemplateResponse(
        "einvoice/_preview_modal.html",
        {
            "request": request,
            "current_user": current_user,
            "item": item,
            "detail": detail,
            "vendors": vendors,
            "references": references,
        },
    )


@router.post("/einvoice-ui/inbox/{item_id}/return", name="einvoice_inbox_return_ui")
async def inbox_return(
    item_id: str,
    request: Request,
    reason: str = Form(""),
    current_user: User = Depends(require_module("einvoice")),
    db: Session = Depends(get_db),
):
    """Faturayı reddet (iade) — GİB'e olumsuz uygulama yanıtı gider."""
    _require_module_active(db)
    mod = _get_einvoice_module(request)
    item = db.query(mod.InboxItem).get(item_id)
    if not item:
        raise HTTPException(404)
    if item.status != "received":
        raise HTTPException(400, f"Kalem zaten işlenmiş ({item.status})")
    # Provider'a iade yanıtını gönder (FakeProvider'da no-op)
    try:
        result = mod.provider.cancel_invoice(item.external_uuid, reason or "Alıcı tarafından reddedildi")
        if not result.success:
            raise HTTPException(502, f"Provider iade hatası: {result.detail}")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        # Provider iade'yi desteklemiyor olabilir; yine de local'de işaretle
        print(f"[einvoice] iade provider hatası: {exc}", flush=True)
    item.status = "returned"
    item.imported_at = datetime.utcnow()
    item.imported_by = current_user.id
    db.commit()
    return RedirectResponse(url="/einvoice-ui/inbox", status_code=303)


@router.post("/einvoice-ui/inbox/{item_id}/ignore", name="einvoice_inbox_ignore_ui")
async def inbox_ignore_ui(
    item_id: str,
    request: Request,
    current_user: User = Depends(require_module("einvoice")),
    db: Session = Depends(get_db),
):
    _require_module_active(db)
    mod = _get_einvoice_module(request)
    item = db.query(mod.InboxItem).get(item_id)
    if not item:
        raise HTTPException(404)
    item.status = "ignored"
    db.commit()
    return RedirectResponse(url="/einvoice-ui/inbox", status_code=303)


@router.post("/einvoice-ui/inbox/{item_id}/import", name="einvoice_inbox_import_ui")
async def inbox_import_ui(
    item_id: str,
    request: Request,
    vendor_id: str = Form(None),
    new_vendor_name: str = Form(""),
    ref_id: str = Form(None),
    current_user: User = Depends(require_module("einvoice")),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    """Inbox kaleminden Invoice (gelen) kaydı yaratır."""
    _require_module_active(db)
    mod = _get_einvoice_module(request)
    item = db.query(mod.InboxItem).get(item_id)
    if not item:
        raise HTTPException(404)
    if item.status != "received":
        raise HTTPException(400, f"Kalem zaten işlenmiş ({item.status})")

    # Tedarikçi: önce vendor_id verildiyse onu, sonra vergi no eşleşmesi, sonra yeni yarat
    vendor = None
    if vendor_id:
        vendor = db.query(Vendor).filter(
            Vendor.id == vendor_id,
            Vendor.company_id == cid,
        ).first()
    if not vendor and item.sender_tax_no:
        vendor = db.query(Vendor).filter(
            Vendor.tax_no == item.sender_tax_no,
            Vendor.company_id == cid,
        ).first()
    if not vendor:
        name = (new_vendor_name or item.sender_name or "").strip() or f"Tedarikçi #{item.id}"
        vendor = Vendor(
            name=name,
            tax_no=item.sender_tax_no or "",
            active=True,
            company_id=cid,
        )
        db.add(vendor)
        db.flush()

    # Invoice (gelen) yarat
    from datetime import date as _date
    inv = Invoice(
        company_id=cid,
        invoice_type="gelen",
        invoice_no=item.invoice_no or "",
        invoice_date=item.invoice_date or _date.today(),
        amount=float(item.total_amount or 0) / 1.20 if item.total_amount else 0,  # KDV hariç tahmini
        vat_rate=0.20,
        currency=item.currency or "TRY",
        status="approved",
        vendor_id=vendor.id,
        ref_id=ref_id if ref_id else None,
        notes=f"E-Fatura inbox'tan içe aktarıldı (UUID: {item.external_uuid})",
        created_by=current_user.id,
        einvoice_external_uuid=item.external_uuid,
        einvoice_inbox_id=item.id,
        einvoice_status="received",
    )
    db.add(inv)
    db.flush()

    item.status = "imported"
    item.vendor_id = vendor.id
    item.imported_invoice_id = inv.id
    item.imported_by = current_user.id
    item.imported_at = datetime.utcnow()
    db.commit()

    return RedirectResponse(url=f"/invoices/{inv.id}", status_code=303)


# ---------------------------------------------------------------------------
# Invoice'tan e-Fatura gönder
# ---------------------------------------------------------------------------

@router.post("/invoices/{invoice_id}/einvoice/send", name="einvoice_send_for_invoice")
async def einvoice_send_for_invoice(
    invoice_id: str,
    request: Request,
    current_user: User = Depends(require_module("einvoice")),
    db: Session = Depends(get_db),
):
    _require_module_active(db)
    mod = _get_einvoice_module(request)

    inv = db.query(Invoice).get(invoice_id)
    if not inv:
        raise HTTPException(404, "Fatura bulunamadı")
    if inv.invoice_type not in ("kesilen", "komisyon"):
        raise HTTPException(400, "Sadece kesilen/komisyon faturaları gönderilebilir")
    if inv.einvoice_status in ("accepted", "sent"):
        raise HTTPException(409, "Fatura zaten gönderilmiş")

    # Müşteri bilgisi (Reference üzerinden)
    customer = None
    if inv.reference and inv.reference.customer:
        customer = inv.reference.customer

    # E-Fatura mükellefi mi (cache veya provider check)
    is_efatura = False
    cust_alias = None
    if customer and customer.tax_no:
        if customer.is_efatura_user is None:
            info = mod.provider.check_efatura_user(customer.tax_no)
            customer.is_efatura_user = info.is_user
            customer.efatura_alias = info.alias
            customer.efatura_checked_at = datetime.utcnow()
            db.flush()
        is_efatura = bool(customer.is_efatura_user)
        cust_alias = customer.efatura_alias

    # Items_json'dan kalemler
    lines = []
    if inv.items_json:
        try:
            raw = json.loads(inv.items_json)
            for li in raw:
                lines.append({
                    "description": li.get("description") or li.get("aciklama") or "Hizmet",
                    "quantity": float(li.get("qty") or li.get("quantity") or 1),
                    "unit": li.get("unit") or "ADET",
                    "unit_price": float(li.get("price") or li.get("unit_price") or 0),
                    "vat_rate": float(li.get("vat_rate") or inv.vat_rate or 0.20),
                    "discount": float(li.get("discount") or 0),
                })
        except Exception:  # noqa: BLE001
            pass
    if not lines:
        # tek kalem fallback
        lines = [{
            "description": inv.invoice_no or "Hizmet bedeli",
            "quantity": 1,
            "unit": "ADET",
            "unit_price": float(inv.amount or 0),
            "vat_rate": float(inv.vat_rate or 0.20),
            "discount": 0,
        }]

    payload_dict = {
        "invoice_no": inv.invoice_no or f"INV-{inv.id}",
        "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
        "currency": inv.currency or "TRY",
        "is_efatura": is_efatura,
        "customer": {
            "name": customer.name if customer else "—",
            "tax_no": customer.tax_no if customer else "",
            "tax_office": customer.tax_office if customer else "",
            "address": customer.address if customer else "",
            "email": customer.email if customer else "",
            "phone": customer.phone if customer else "",
            "alias": cust_alias,
        },
        "lines": lines,
        "notes": inv.notes or "",
    }

    from prizma_einvoice import build_invoice_payload_from_dict, submit_payload
    payload = build_invoice_payload_from_dict(payload_dict)
    sub = submit_payload(
        db,
        invoice_id=inv.id,
        payload=payload,
        submission_model=mod.Submission,
        provider=mod.provider,
        user_id=current_user.id,
    )

    # Invoice denormalize
    inv.einvoice_status = sub.status
    inv.einvoice_uuid = sub.uuid
    inv.einvoice_pdf_url = sub.pdf_url
    inv.einvoice_sent_at = sub.submitted_at
    db.commit()

    return RedirectResponse(url=f"/invoices/{inv.id}", status_code=303)
