"""
FakeProvider — gerçek entegratör seçilmeden önce sandbox geliştirme için.
Her gönderimi başarıyla "accepted" işaretler, in-memory inbox simülasyonu sağlar.
"""
from __future__ import annotations

import uuid as uuid_lib
from datetime import date, datetime, timedelta
from typing import Optional

from .base import (
    BaseProvider, ProviderConfig, SubmitResult,
    InboxItem, EFaturaUserInfo, InvoicePayload,
)


# Bellekte tutulan dummy data (process içinde kalıcı; restart'ta sıfırlanır)
_FAKE_INBOX: list[InboxItem] = []
_FAKE_SENT: dict[str, dict] = {}


def _seed_inbox():
    """Geliştirme için 2 adet sahte gelen e-fatura."""
    if _FAKE_INBOX:
        return
    today = date.today()
    _FAKE_INBOX.append(InboxItem(
        external_uuid="FAKE-IN-" + uuid_lib.uuid4().hex[:8],
        sender_tax_no="1234567890",
        sender_name="Demo Tedarikçi A.Ş.",
        invoice_no="DMO2026000001",
        invoice_date=today - timedelta(days=2),
        total_amount=4720.00,
        currency="TRY",
        raw={"note": "fake seed item 1"},
    ))
    _FAKE_INBOX.append(InboxItem(
        external_uuid="FAKE-IN-" + uuid_lib.uuid4().hex[:8],
        sender_tax_no="9876543210",
        sender_name="Test Hizmet Ltd.",
        invoice_no="THZ20260042",
        invoice_date=today - timedelta(days=5),
        total_amount=11800.00,
        currency="TRY",
        raw={"note": "fake seed item 2"},
    ))


class FakeProvider(BaseProvider):
    name = "fake"

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        _seed_inbox()

    # --- Kontrol ---

    def check_connection(self) -> bool:
        return True

    def check_efatura_user(self, tax_no: str) -> EFaturaUserInfo:
        # Çift sayı ile bitenler "e-Fatura mükellefi" sayılır (deterministik test için)
        is_user = bool(tax_no and tax_no[-1].isdigit() and int(tax_no[-1]) % 2 == 0)
        return EFaturaUserInfo(
            is_user=is_user,
            alias=f"urn:mail:defaultpk@fake-{tax_no}.com.tr" if is_user else None,
            title=f"Fake Şirket {tax_no[-3:]}" if is_user else None,
            raw={"tax_no": tax_no, "fake": True},
        )

    # --- Giden ---

    def send_invoice(self, payload: InvoicePayload) -> SubmitResult:
        u = "FAKE-OUT-" + uuid_lib.uuid4().hex[:12]
        _FAKE_SENT[u] = {
            "submitted_at": datetime.utcnow().isoformat(),
            "invoice_no": payload.invoice_no,
            "customer_name": payload.customer_name,
            "doc_type": "efatura" if payload.is_efatura else "earsiv",
            "status": "accepted",
        }
        return SubmitResult(
            success=True, uuid=u, status="accepted",
            detail="Fake provider — gönderildi",
            pdf_url=f"https://fake-einvoice.local/pdf/{u}.pdf",
            raw=_FAKE_SENT[u],
        )

    def get_status(self, uuid: str) -> SubmitResult:
        rec = _FAKE_SENT.get(uuid)
        if not rec:
            return SubmitResult(success=False, status="error", detail="UUID bulunamadı")
        return SubmitResult(
            success=True, uuid=uuid, status=rec["status"],
            pdf_url=f"https://fake-einvoice.local/pdf/{uuid}.pdf",
            raw=rec,
        )

    def cancel_invoice(self, uuid: str, reason: str) -> SubmitResult:
        rec = _FAKE_SENT.get(uuid)
        if not rec:
            return SubmitResult(success=False, status="error", detail="UUID bulunamadı")
        rec["status"] = "cancelled"
        rec["cancel_reason"] = reason
        rec["cancelled_at"] = datetime.utcnow().isoformat()
        return SubmitResult(success=True, uuid=uuid, status="cancelled", raw=rec)

    # --- Gelen ---

    def list_inbox(self, since: datetime, until: Optional[datetime] = None) -> list[InboxItem]:
        _seed_inbox()
        # since filtresi pratik amaçlı uygulanır
        items = []
        since_d = since.date() if isinstance(since, datetime) else since
        for it in _FAKE_INBOX:
            if it.invoice_date >= since_d:
                items.append(it)
        return items

    def fetch_inbox_item(self, external_uuid: str) -> dict:
        for it in _FAKE_INBOX:
            if it.external_uuid == external_uuid:
                # Demo amaçlı 2-3 kalem üret
                base = it.total_amount / 1.20  # KDV %20 varsayımı
                if it.total_amount > 5000:
                    lines = [
                        {"description": "Hizmet bedeli — Ana iş", "qty": 1,
                         "unit": "ADET", "unit_price": base * 0.7,
                         "vat_rate": 0.20, "vat_amount": base * 0.7 * 0.20,
                         "total": base * 0.7 * 1.20},
                        {"description": "Ek hizmet — Destek", "qty": 2,
                         "unit": "SAAT", "unit_price": base * 0.15,
                         "vat_rate": 0.20, "vat_amount": base * 0.30 * 0.20,
                         "total": base * 0.30 * 1.20},
                    ]
                else:
                    lines = [
                        {"description": "Tek kalem hizmet bedeli", "qty": 1,
                         "unit": "ADET", "unit_price": base,
                         "vat_rate": 0.20, "vat_amount": base * 0.20,
                         "total": it.total_amount},
                    ]
                return {
                    "external_uuid": it.external_uuid,
                    "sender_tax_no": it.sender_tax_no,
                    "sender_name": it.sender_name,
                    "sender_address": "İstanbul / Türkiye (demo adres)",
                    "sender_email": f"info@{it.sender_tax_no}.com.tr",
                    "invoice_no": it.invoice_no,
                    "invoice_date": it.invoice_date.isoformat(),
                    "due_date": it.invoice_date.isoformat(),
                    "total_amount": it.total_amount,
                    "subtotal": round(base, 2),
                    "vat_total": round(it.total_amount - base, 2),
                    "currency": it.currency,
                    "lines": lines,
                    "pdf_url": f"https://fake-einvoice.local/pdf/{it.external_uuid}.pdf",
                    "xml_preview": f"<Invoice><ID>{it.invoice_no}</ID><IssueDate>{it.invoice_date.isoformat()}</IssueDate><LegalMonetaryTotal>{it.total_amount}</LegalMonetaryTotal></Invoice>",
                    "raw": it.raw,
                }
        return {}
