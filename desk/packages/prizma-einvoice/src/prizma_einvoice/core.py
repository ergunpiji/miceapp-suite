"""
EInvoiceModule — host app entegrasyon entry point.

Kullanım:
    from prizma_einvoice import EInvoiceModule
    einvoice = EInvoiceModule(host_base=Base, engine=engine, config={...})
    einvoice.install(app)
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from fastapi import FastAPI
from sqlalchemy.orm import Session

from .providers import BaseProvider, ProviderConfig, get_provider
from .models import register_models


class EInvoiceModule:
    """Pluggable e-Fatura modülü — host app'e takılır."""

    def __init__(
        self,
        host_base,
        engine,
        config: Optional[dict] = None,
        get_db_dependency: Optional[Callable] = None,
        require_admin_dependency: Optional[Callable] = None,
        get_current_user_dependency: Optional[Callable] = None,
        url_prefix: str = "/einvoice",
    ):
        """
        host_base: host app'in SQLAlchemy declarative_base()'i (Base)
        engine: host app'in DB engine'i (modeller bu engine ile yaratılır)
        config: provider/credential config dict
        get_db_dependency: host app'in get_db() FastAPI dependency'si
        require_admin_dependency: admin yetkisi için dependency
        get_current_user_dependency: current_user için dependency
        url_prefix: router prefix (default /einvoice)
        """
        self.host_base = host_base
        self.engine = engine
        self.config_dict = config or {}
        self.url_prefix = url_prefix

        # Host'tan gelen FastAPI dependency'leri
        self.get_db = get_db_dependency
        self.require_admin = require_admin_dependency
        self.get_current_user = get_current_user_dependency

        # Modelleri host_base'e kaydet
        self.Submission, self.InboxItem = register_models(host_base)

        # Provider'ı yapılandır
        self._provider: Optional[BaseProvider] = None

    @property
    def provider(self) -> BaseProvider:
        """Lazy provider — config çağırma anında okunur, env override'ı çalışır."""
        if self._provider is None:
            self._provider = self._build_provider()
        return self._provider

    def reload_provider(self) -> None:
        """Config DB'den/wizard'dan değiştirildiğinde provider'ı yeniden oluştur."""
        self._provider = None

    def _build_provider(self) -> BaseProvider:
        cfg = self.config_dict or {}
        # Env override (host her şeyi env ile geçebilir)
        provider_name = (
            os.environ.get("EINVOICE_PROVIDER")
            or cfg.get("provider")
            or "fake"
        )
        pc = ProviderConfig(
            api_url=os.environ.get("EINVOICE_API_URL", cfg.get("api_url", "")),
            api_username=os.environ.get("EINVOICE_API_USERNAME", cfg.get("api_username", "")),
            api_password=os.environ.get("EINVOICE_API_PASSWORD", cfg.get("api_password", "")),
            api_key=os.environ.get("EINVOICE_API_KEY", cfg.get("api_key", "")),
            company_tax_no=os.environ.get("EINVOICE_COMPANY_TAX_NO", cfg.get("company_tax_no", "")),
            webhook_secret=os.environ.get("EINVOICE_WEBHOOK_SECRET", cfg.get("webhook_secret", "")),
            sandbox=str(os.environ.get("EINVOICE_SANDBOX", "1")).lower() in ("1", "true", "yes"),
            extra=cfg.get("extra", {}),
        )
        return get_provider(provider_name, pc)

    def install(self, app: FastAPI) -> None:
        """FastAPI uygulamasına router'ı mount et."""
        from .router import build_router
        router = build_router(self)
        app.include_router(router, prefix=self.url_prefix, tags=["einvoice"])

    # --- Convenience helpers ---

    def session(self) -> Session:
        """Helper: paket dışından doğrudan kullanılmak istenirse."""
        from sqlalchemy.orm import sessionmaker
        SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        return SessionLocal()
