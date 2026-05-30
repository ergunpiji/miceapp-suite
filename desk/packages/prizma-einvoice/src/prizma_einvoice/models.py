"""
SQLAlchemy modelleri — host app'in declarative_base'ine takılırlar
(register_models pattern). Modüllerin tablo isimleri 'einvoice_' prefix'i
ile host şemasını kirletmez.
"""
from __future__ import annotations

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Date, DateTime, Text, ForeignKey,
)


def register_models(Base):
    """Host app'in Base'ine modülün tablolarını kaydet, sınıfları döndür."""

    class EInvoiceSubmission(Base):
        """Bir Invoice için yapılan e-Fatura/e-Arşiv gönderim girişimi (audit)."""
        __tablename__ = "einvoice_submissions"

        id = Column(Integer, primary_key=True)
        invoice_id = Column(String(36), ForeignKey("invoices.id"), nullable=False)
        doc_type = Column(String(20), nullable=False)  # efatura | earsiv
        uuid = Column(String(64), nullable=True, index=True)
        status = Column(String(20), default="queued", nullable=False)
        # queued | sending | sent | accepted | rejected | cancelled | error
        status_detail = Column(Text, nullable=True)
        provider = Column(String(40), nullable=False)
        submitted_at = Column(DateTime, default=datetime.utcnow, nullable=False)
        responded_at = Column(DateTime, nullable=True)
        pdf_url = Column(Text, nullable=True)
        xml_blob = Column(Text, nullable=True)
        request_payload = Column(Text, nullable=True)
        response_payload = Column(Text, nullable=True)
        attempted_by = Column(String(36), ForeignKey("users.id"), nullable=True)
        attempt_no = Column(Integer, default=1, nullable=False)

    class EInvoiceInboxItem(Base):
        """GİB'den entegratör üzerinden gelen bir e-fatura kalemi (raw kayıt)."""
        __tablename__ = "einvoice_inbox_items"

        id = Column(Integer, primary_key=True)
        external_uuid = Column(String(64), unique=True, nullable=False, index=True)
        provider = Column(String(40), nullable=False)
        sender_tax_no = Column(String(20))
        sender_name = Column(String(200))
        invoice_no = Column(String(50))
        invoice_date = Column(Date)
        total_amount = Column(Float)
        currency = Column(String(3), default="TRY")
        status = Column(String(20), default="received", nullable=False)
        # received | imported | rejected | returned | ignored
        vendor_id = Column(String(36), ForeignKey("vendors.id"), nullable=True)
        imported_invoice_id = Column(String(36), ForeignKey("invoices.id"), nullable=True)
        raw_payload = Column(Text, nullable=True)
        fetched_at = Column(DateTime, default=datetime.utcnow, nullable=False)
        imported_at = Column(DateTime, nullable=True)
        imported_by = Column(String(36), ForeignKey("users.id"), nullable=True)

    return EInvoiceSubmission, EInvoiceInboxItem
