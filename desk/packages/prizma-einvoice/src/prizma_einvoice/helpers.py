"""
Submit + sync + import helper'ları. Host app modellerini doğrudan import etmez,
modülün kendi tablolarına yazar; host app'in Invoice/Customer/Vendor modellerini
**callback** veya **dynamic getattr** ile günceller (loose coupling).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Optional, Callable

from sqlalchemy.orm import Session

from .providers import (
    BaseProvider, InvoicePayload, InvoiceLine,
    SubmitResult, EFaturaUserInfo,
)


# ---------------------------------------------------------------------------
# Giden (kesilen Invoice → e-Fatura/e-Arşiv)
# ---------------------------------------------------------------------------

def submit_einvoice(
    db: Session,
    invoice,
    *,
    submission_model,
    provider: BaseProvider,
    user_id: Optional[int] = None,
):
    """Bir Invoice için e-Fatura/e-Arşiv gönderimi yapar.

    Args:
        invoice: host app Invoice instance (vendor, items, customer ile)
        submission_model: EInvoiceSubmission model class (host_base'e kayıtlı)
        provider: BaseProvider instance
        user_id: gönderimi tetikleyen kullanıcının id'si (audit)

    Returns: yaratılan submission objesi
    """
    # Müşteri e-Fatura mükellefi mi (cache veya provider sorgusu)
    customer = getattr(invoice, "reference", None)  # host'a göre değişebilir
    # Pratik: vendor/customer ilişkisi host'a göre değişir.
    # Host integration tarafında bu fonksiyon sarılır ve doğru alanlar geçirilir.

    # Bu helper raw bir interface sağlar; host adapter (host app içindeki einvoice_helper.py)
    # invoice'tan payload çıkarmayı bilir. İlerideki entegrasyonda host_adapter kullanılır.
    raise NotImplementedError(
        "submit_einvoice host-spesifik wrapper içinde kullanılmalı; build_payload ile çağırın"
    )


def build_invoice_payload_from_dict(data: dict) -> InvoicePayload:
    """Host app'in çıkardığı sözlükten InvoicePayload oluştur.
    Host adapter şu şekildeki dict'i hazırlar:

    {
      'invoice_no': '...', 'invoice_date': date, 'currency': 'TRY',
      'is_efatura': True/False,
      'customer': {'name', 'tax_no', 'tax_office', 'address', 'email', 'phone', 'alias'},
      'lines': [{'description', 'quantity', 'unit', 'unit_price', 'vat_rate', 'discount'}, ...],
      'notes': '...',
    }
    """
    c = data.get("customer", {})
    lines = [
        InvoiceLine(
            description=l.get("description", ""),
            quantity=float(l.get("quantity", 1)),
            unit=l.get("unit", "ADET"),
            unit_price=float(l.get("unit_price", 0)),
            vat_rate=float(l.get("vat_rate", 0.20)),
            discount_amount=float(l.get("discount", 0)),
        )
        for l in data.get("lines", [])
    ]
    inv_date = data.get("invoice_date")
    if isinstance(inv_date, str):
        inv_date = date.fromisoformat(inv_date)
    return InvoicePayload(
        invoice_no=data.get("invoice_no", ""),
        invoice_date=inv_date or date.today(),
        currency=data.get("currency", "TRY"),
        customer_name=c.get("name", ""),
        customer_tax_no=c.get("tax_no", ""),
        customer_tax_office=c.get("tax_office", ""),
        customer_address=c.get("address", ""),
        customer_email=c.get("email", ""),
        customer_phone=c.get("phone", ""),
        customer_alias=c.get("alias"),
        is_efatura=bool(data.get("is_efatura", False)),
        lines=lines,
        notes=data.get("notes", ""),
    )


def submit_payload(
    db: Session,
    *,
    invoice_id: str,
    payload: InvoicePayload,
    submission_model,
    provider: BaseProvider,
    user_id: Optional[str] = None,
):
    """Hazırlanmış payload'ı entegratöre gönder + Submission kaydı yarat."""
    sub = submission_model(
        invoice_id=invoice_id,
        doc_type="efatura" if payload.is_efatura else "earsiv",
        status="sending",
        provider=provider.name,
        attempted_by=user_id,
        request_payload=json.dumps(_payload_to_jsonable(payload), ensure_ascii=False),
    )
    db.add(sub)
    db.flush()

    try:
        result: SubmitResult = provider.send_invoice(payload)
    except Exception as exc:  # noqa: BLE001
        sub.status = "error"
        sub.status_detail = f"{type(exc).__name__}: {exc}"
        sub.responded_at = datetime.utcnow()
        db.commit()
        return sub

    sub.uuid = result.uuid
    sub.status = result.status
    sub.status_detail = result.detail
    sub.pdf_url = result.pdf_url
    sub.response_payload = json.dumps(result.raw or {}, ensure_ascii=False)
    sub.responded_at = datetime.utcnow()
    db.commit()
    return sub


def _payload_to_jsonable(p: InvoicePayload) -> dict:
    return {
        "invoice_no": p.invoice_no,
        "invoice_date": p.invoice_date.isoformat() if p.invoice_date else None,
        "currency": p.currency,
        "is_efatura": p.is_efatura,
        "customer": {
            "name": p.customer_name, "tax_no": p.customer_tax_no,
            "tax_office": p.customer_tax_office, "address": p.customer_address,
            "email": p.customer_email, "phone": p.customer_phone,
            "alias": p.customer_alias,
        },
        "lines": [
            {"description": l.description, "quantity": l.quantity, "unit": l.unit,
             "unit_price": l.unit_price, "vat_rate": l.vat_rate,
             "discount": l.discount_amount}
            for l in p.lines
        ],
        "notes": p.notes,
    }


# ---------------------------------------------------------------------------
# Gelen (inbox)
# ---------------------------------------------------------------------------

def sync_inbox(
    db: Session,
    *,
    inbox_model,
    provider: BaseProvider,
    since: Optional[datetime] = None,
) -> int:
    """Entegratör inbox'ından yeni kalemleri çekip DB'ye kaydet.
    Mevcut external_uuid'ler atlanır (UNIQUE constraint güvencesi)."""
    if since is None:
        since = datetime.utcnow() - timedelta(days=30)

    items = provider.list_inbox(since=since)
    new_count = 0
    for it in items:
        existing = db.query(inbox_model).filter(
            inbox_model.external_uuid == it.external_uuid
        ).first()
        if existing:
            continue
        rec = inbox_model(
            external_uuid=it.external_uuid,
            provider=provider.name,
            sender_tax_no=it.sender_tax_no,
            sender_name=it.sender_name,
            invoice_no=it.invoice_no,
            invoice_date=it.invoice_date,
            total_amount=it.total_amount,
            currency=it.currency,
            status="received",
            raw_payload=json.dumps(it.raw or {}, ensure_ascii=False),
        )
        db.add(rec)
        new_count += 1
    db.commit()
    return new_count


# ---------------------------------------------------------------------------
# Mükellef sorgu cache
# ---------------------------------------------------------------------------

def check_efatura_user_cached(
    provider: BaseProvider,
    tax_no: str,
    *,
    cache_lookup: Callable[[str], Optional[EFaturaUserInfo]] = None,
    cache_save: Callable[[str, EFaturaUserInfo], None] = None,
) -> EFaturaUserInfo:
    """Cache callback'leri ile e-Fatura mükellef sorgusu yap.
    Host app cache'i (Customer/Vendor tablo kolonları) kendi yönetir."""
    if cache_lookup:
        cached = cache_lookup(tax_no)
        if cached is not None:
            return cached
    info = provider.check_efatura_user(tax_no)
    if cache_save:
        cache_save(tax_no, info)
    return info
