# prizma-einvoice

Türkiye e-Fatura/e-Arşiv için pluggable entegrasyon modülü. Giden + gelen e-fatura desteği; İzibiz/Paraşüt/Faturaport gibi özel entegratör API'leriyle çalışır. Mali mühür/entegrator anlaşması olmadan **fake** provider ile sandbox geliştirme yapılabilir.

## Tasarım

- **Pluggable adapter**: `providers/base.py` ABC, `providers/{izibiz,parasut,faturaport,fake}.py` implementations
- **Host-base modeller**: `register_models(host_base)` host app'in SQLAlchemy `Base` registry'sine modelleri kaydeder; ayrı bir Base/engine yönetimi yok
- **FastAPI sub-router**: `EInvoiceModule(host_base, engine, config).install(app)` ile mount
- **Feature flag**: host app modülü kurarken kullanır; UI tarafı kendi flag'ını yönetir

## Kullanım (host app)

```python
from prizma_einvoice import EInvoiceModule
from models import Base
from database import engine

einvoice = EInvoiceModule(
    host_base=Base,
    engine=engine,
    config={
        "provider": "fake",        # 'izibiz' | 'parasut' | 'faturaport' | 'fake'
        "api_url": "...",
        "api_username": "...",
        "api_password": "...",
        "company_tax_no": "1234567890",
        "webhook_secret": "...",
    },
)
einvoice.install(app)  # FastAPI uygulamasına /einvoice/* router'ını mount eder
```

## Lisans

Proprietary — Prizmatik iç kullanım için.
