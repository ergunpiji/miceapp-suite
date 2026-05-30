"""E-Fatura entegratör provider'ları."""
from .base import (
    BaseProvider, ProviderConfig, SubmitResult, InboxItem, EFaturaUserInfo,
    InvoicePayload, InvoiceLine,
)
from .fake import FakeProvider

__all__ = [
    "BaseProvider", "ProviderConfig",
    "SubmitResult", "InboxItem", "EFaturaUserInfo",
    "InvoicePayload", "InvoiceLine",
    "FakeProvider",
    "get_provider",
]


def get_provider(name: str, config: "ProviderConfig") -> "BaseProvider":
    """Provider factory — name'e göre uygun adapter döner."""
    name = (name or "fake").lower()
    if name == "fake":
        return FakeProvider(config)
    if name == "izibiz":
        from .izibiz import IzibizProvider
        return IzibizProvider(config)
    if name == "parasut":
        from .parasut import ParasutProvider
        return ParasutProvider(config)
    if name == "faturaport":
        from .faturaport import FaturaportProvider
        return FaturaportProvider(config)
    raise ValueError(f"Bilinmeyen entegratör: {name}")
