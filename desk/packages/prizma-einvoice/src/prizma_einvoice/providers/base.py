"""
BaseProvider — entegratör adapter ABC.

Her gerçek entegratör (İzibiz/Paraşüt/Faturaport) bu sınıfı implement eder.
Helper'lar yalnızca bu interface üzerinden çağrı yapar — vendor-specific
detay paketin dış yüzeyine sızmaz.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Veri tipleri (provider yanıtları için)
# ---------------------------------------------------------------------------

@dataclass
class ProviderConfig:
    """Provider'ın çalışması için gereken konfigürasyon."""
    api_url: str = ""
    api_username: str = ""
    api_password: str = ""
    api_key: str = ""
    company_tax_no: str = ""
    webhook_secret: str = ""
    sandbox: bool = True
    extra: dict = field(default_factory=dict)


@dataclass
class EFaturaUserInfo:
    """E-Fatura mükellef sorgu sonucu."""
    is_user: bool
    alias: Optional[str] = None        # urn:mail:defaultpk@... gibi
    title: Optional[str] = None        # mükellefin unvanı
    raw: Optional[dict] = None


@dataclass
class InvoiceLine:
    description: str
    quantity: float
    unit: str = "ADET"                 # ADET, KG, LT, ...
    unit_price: float = 0.0            # KDV hariç birim
    vat_rate: float = 0.20             # 0.20 = %20
    discount_amount: float = 0.0


@dataclass
class InvoicePayload:
    """Provider'a gönderilen fatura verisi (provider-agnostik)."""
    invoice_no: str
    invoice_date: date
    currency: str = "TRY"
    # Müşteri / alıcı
    customer_name: str = ""
    customer_tax_no: str = ""
    customer_tax_office: str = ""
    customer_address: str = ""
    customer_email: str = ""
    customer_phone: str = ""
    customer_alias: Optional[str] = None  # e-Fatura PK varsa
    is_efatura: bool = False              # True → e-Fatura, False → e-Arşiv
    # Kalemler
    lines: list[InvoiceLine] = field(default_factory=list)
    notes: str = ""


@dataclass
class SubmitResult:
    """Provider'ın gönderim cevabı."""
    success: bool
    uuid: Optional[str] = None         # entegratör/GİB UUID/ETTN
    status: str = "queued"             # queued|sent|accepted|rejected|error
    detail: Optional[str] = None
    pdf_url: Optional[str] = None
    raw: Optional[dict] = None


@dataclass
class InboxItem:
    """Inbox'tan listelenen gelen e-fatura kalemi."""
    external_uuid: str
    sender_tax_no: str
    sender_name: str
    invoice_no: str
    invoice_date: date
    total_amount: float
    currency: str = "TRY"
    raw: Optional[dict] = None


# ---------------------------------------------------------------------------
# ABC
# ---------------------------------------------------------------------------

class BaseProvider(ABC):
    """E-Fatura entegratör adapter contract.

    Her metod provider-spesifik HTTP/SOAP isteğini yapar ve normalleştirilmiş
    veri tipi döner. Hata durumunda exception fırlatır (helper layer yakalar)."""

    name: str = "base"

    def __init__(self, config: ProviderConfig):
        self.config = config

    # --- Kontrol ---

    @abstractmethod
    def check_connection(self) -> bool:
        """API'ye bağlanıp credential'ı doğrula."""
        ...

    @abstractmethod
    def check_efatura_user(self, tax_no: str) -> EFaturaUserInfo:
        """Vergi numarası e-Fatura mükellefi mi sorgula."""
        ...

    # --- Giden ---

    @abstractmethod
    def send_invoice(self, payload: InvoicePayload) -> SubmitResult:
        """Faturayı entegratöre gönder; UUID + status döner."""
        ...

    @abstractmethod
    def get_status(self, uuid: str) -> SubmitResult:
        """Gönderilmiş bir faturanın güncel durumunu sorgula."""
        ...

    @abstractmethod
    def cancel_invoice(self, uuid: str, reason: str) -> SubmitResult:
        """Faturayı iptal et (e-Fatura ~8 gün, e-Arşiv 7 gün penceresinde)."""
        ...

    # --- Gelen ---

    @abstractmethod
    def list_inbox(self, since: datetime, until: Optional[datetime] = None) -> list[InboxItem]:
        """Gelen kutusunu çek (kullanıcıya gelen e-faturaların özet listesi)."""
        ...

    @abstractmethod
    def fetch_inbox_item(self, external_uuid: str) -> dict:
        """Tek bir gelen faturanın tam detayını ham olarak getir (kalemler, vergi vb.)."""
        ...

    # --- Webhook (opsiyonel) ---

    def verify_webhook(self, headers: dict, body: bytes) -> bool:  # noqa: ARG002
        """HMAC veya benzeri ile webhook payload'ını doğrula. Default: kapalı."""
        return True
