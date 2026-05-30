# miceapp Suite — Claude Code Başlangıç Promptu

> **Bu dosyayı projenin kök klasörüne `CLAUDE.md` olarak kopyala.**
> Sıfırdan inşa edilecek yeni bir proje; mevcut hiçbir koda bağımlılık yoktur.
> İki bağımsız FastAPI uygulaması, tek PostgreSQL veritabanı, tek Railway projesi.

---

## 0. Proje Kimliği

```
Ürün ailesi  : miceapp Suite
Repo         : github.com/ergunpiji/miceapp-suite   (tek mono-repo, iki uygulama)
Railway proje: miceapp-suite
Servisler    :
  miceapp   → miceapp.net          (etkinlik yönetimi — front office)
  micedesk  → desk.miceapp.net     (finans + İK — back office)
DB           : Railway PostgreSQL (her iki servis aynı DB'ye bağlanır)
```

**MICE** = Meetings, Incentives, Conferences, Exhibitions.
Etkinlik sektörü hedef kitlesi; kısaltma ilk duyuşta anlam ifade eder.

---

## 1. Vizyon

| Uygulama | URL | Hedef Kullanıcı | Odak |
|----------|-----|----------------|------|
| **miceapp** | miceapp.net | Koordinatör, satış müdürü, proje yöneticisi | Talep → RFQ → Bütçe → Mekan |
| **micedesk** | desk.miceapp.net | Muhasebe, İK, Genel Müdür | Fatura → Kasa → Banka → Personel |

İki uygulama **ayrı servis, ortak PostgreSQL** mimarisini kullanır.
Veri transferi yoktur — ikisi de aynı tablolara doğrudan yazar/okur.
Ortak tablolar köprü görevi görür; çapraz FK bağlantısı kurulmaz.

---

## 2. Mono-Repo Klasör Yapısı

```
miceapp-suite/                   ← tek git repo
│
├── miceapp/                     ← FastAPI uygulaması 1
│   ├── app.py
│   ├── auth.py
│   ├── database.py
│   ├── models.py
│   ├── templates_config.py
│   ├── storage_helper.py
│   ├── email_helper.py
│   ├── routers/
│   │   ├── auth.py
│   │   ├── dashboard.py
│   │   ├── references.py
│   │   ├── requests.py
│   │   ├── budgets.py
│   │   ├── vendors.py
│   │   ├── customers.py
│   │   ├── coordinator.py      ← micedesk faturalarını onayla/reddet
│   │   ├── users.py
│   │   ├── teams.py
│   │   ├── profile.py
│   │   ├── notifications.py
│   │   └── admin_branding.py
│   ├── templates/
│   │   ├── base.html
│   │   ├── login.html
│   │   ├── dashboard/
│   │   ├── references/
│   │   ├── requests/
│   │   ├── budgets/
│   │   ├── vendors/
│   │   ├── customers/
│   │   ├── coordinator/
│   │   ├── users/
│   │   └── admin/
│   ├── static/
│   │   ├── design-tokens.css
│   │   ├── css/
│   │   ├── js/
│   │   └── logo/
│   ├── requirements.txt
│   ├── Procfile
│   ├── railway.json
│   └── .env.example
│
├── micedesk/                    ← FastAPI uygulaması 2
│   ├── app.py
│   ├── auth.py
│   ├── database.py
│   ├── models.py
│   ├── templates_config.py
│   ├── storage_helper.py
│   ├── email_helper.py
│   ├── payment_helpers.py      ← ödeme yan etkileri tek kaynak
│   ├── routers/
│   │   ├── auth.py
│   │   ├── dashboard.py
│   │   ├── invoices.py
│   │   ├── cheques.py
│   │   ├── cash.py
│   │   ├── bank_accounts.py
│   │   ├── credit_cards.py
│   │   ├── payments.py
│   │   ├── payment_instructions.py
│   │   ├── vendors.py
│   │   ├── customers.py
│   │   ├── employees.py
│   │   ├── advances.py
│   │   ├── hbf.py
│   │   ├── leaves.py
│   │   ├── reports.py
│   │   ├── users.py
│   │   ├── profile.py
│   │   ├── notifications.py
│   │   ├── admin_branding.py
│   │   └── admin_modules.py
│   ├── templates/
│   │   ├── base.html
│   │   ├── login.html
│   │   ├── dashboard/
│   │   ├── invoices/
│   │   ├── ...
│   │   └── admin/
│   ├── static/
│   │   ├── design-tokens.css
│   │   ├── css/
│   │   ├── js/
│   │   └── logo/
│   ├── requirements.txt
│   ├── Procfile
│   ├── railway.json
│   └── .env.example
│
└── shared/                      ← opsiyonel: iki uygulama arasında paylaşılan yardımcılar
    └── (boş başla, gerekirse ekle)
```

> Her uygulama kendi `requirements.txt`, `Procfile`, `railway.json` ve `.env.example`
> dosyalarına sahiptir. Railway'de **iki ayrı servis**, her birinin root dizini
> `miceapp/` veya `micedesk/` olarak ayarlanır.

---

## 3. Teknoloji Yığını

### Backend (her iki uygulama için özdeş)

| Paket | Sürüm | Kullanım |
|-------|-------|---------|
| `fastapi` | ≥0.111 | Web framework |
| `uvicorn[standard]` | ≥0.29 | ASGI sunucu |
| `sqlalchemy` | ≥2.0 | ORM |
| `psycopg2-binary` | ≥2.9 | PostgreSQL sürücüsü |
| `python-jose[cryptography]` | ≥3.3 | JWT üretimi |
| `passlib[bcrypt]` | ≥1.7 | Şifre hash |
| `python-multipart` | ≥0.0.9 | Form & dosya yükleme |
| `jinja2` | ≥3.1 | HTML şablonlama |
| `httpx` | ≥0.27 | Async HTTP (webhook, e-fatura) |
| `openpyxl` | ≥3.1 | Excel export |
| `python-dotenv` | ≥1.0 | .env yükleme |
| `boto3` | ≥1.34 | R2/S3 (opsiyonel, dosya depolama) |
| `Pillow` | ≥10.0 | Logo/resim boyutlandırma |

`requirements.txt` tek kaynak — paket eklerken buraya ekle.

### Veritabanı
- **PostgreSQL 16** — Railway managed, production
- **SQLite** — yerel geliştirme fallback (`app.db`)
- Alembic **kullanılmaz** — `database.py::_migrate()` idempotent startup fonksiyonu

### Frontend
- **Bootstrap 5.3** (CDN) — layout, form, modal, tablo
- **Bootstrap Icons** (CDN) — ikon seti
- **Vanilla JS** — minimum; sadece modal, AJAX, renk seçici için
- SPA yok — klasik server-side render + POST/Redirect/GET

### Deployment
- **Railway** — NIXPACKS builder, GitHub push → auto-deploy
- Her uygulama ayrı Railway servisi, `rootDirectory` ayarı ile ayrılır
- Ortak Railway projesi → tek PostgreSQL servisi → iki uygulama aynı `DATABASE_URL`

---

## 4. Tasarım Sistemi

### Tipografi

```
Primary font  : Inter (Google Fonts, 300/400/500/600/700/800)
Mono font     : JetBrains Mono (sayı blokları, kod)
Fallback      : 'Segoe UI', system-ui, -apple-system, sans-serif
```

HTML `<head>`:
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
```

### design-tokens.css (her iki uygulamanın `static/` klasörüne kopyalanır)

```css
/* ─────────────────────────────────────────────────────────
   miceapp Suite — Global Design Tokens
   Tenant marka renkleri base.html'de runtime <style> ile
   bu token'ların üzerine yazılır.
───────────────────────────────────────────────────────── */
:root {
  /* Renk — Sidebar */
  --mice-sidebar-bg:        #0f172a;
  --mice-sidebar-hover:     #1e3a8a;
  --mice-sidebar-active:    #2563eb;
  --mice-sidebar-text:      #cbd5e1;
  --mice-sidebar-muted:     #64748b;
  --mice-sidebar-border:    rgba(255,255,255,.07);

  /* Renk — Primary */
  --mice-primary:           #2563eb;
  --mice-primary-dark:      #1d4ed8;
  --mice-primary-light:     #dbeafe;
  --mice-primary-rgb:       37, 99, 235;   /* rgba() için */

  /* Renk — Durum */
  --mice-success:           #16a34a;
  --mice-success-light:     #dcfce7;
  --mice-warning:           #d97706;
  --mice-warning-light:     #fef3c7;
  --mice-danger:            #dc2626;
  --mice-danger-light:      #fee2e2;
  --mice-info:              #0891b2;
  --mice-info-light:        #cffafe;

  /* Renk — Yüzey */
  --mice-surface:           #ffffff;
  --mice-bg:                #f8fafc;
  --mice-bg-dark:           #f1f5f9;
  --mice-border:            #e2e8f0;
  --mice-border-dark:       #cbd5e1;

  /* Renk — Metin */
  --mice-text:              #1e293b;
  --mice-text-secondary:    #475569;
  --mice-muted:             #94a3b8;

  /* Tipografi */
  --mice-font:              'Inter', 'Segoe UI', system-ui, sans-serif;
  --mice-font-mono:         'JetBrains Mono', 'Fira Code', monospace;
  --mice-font-size-base:    14px;
  --mice-font-size-sm:      12px;
  --mice-line-height:       1.6;

  /* Layout */
  --mice-sidebar-width:     260px;
  --mice-sidebar-collapsed: 64px;
  --mice-topbar-height:     56px;
  --mice-content-padding:   28px;

  /* Border radius */
  --mice-radius-sm:         6px;
  --mice-radius-md:         10px;
  --mice-radius-lg:         14px;
  --mice-radius-xl:         20px;
  --mice-radius-pill:       999px;

  /* Gölge */
  --mice-shadow-xs:  0 1px 2px rgba(0,0,0,.06);
  --mice-shadow-sm:  0 1px 4px rgba(0,0,0,.08);
  --mice-shadow-md:  0 4px 12px rgba(0,0,0,.10);
  --mice-shadow-lg:  0 10px 30px rgba(0,0,0,.12);
  --mice-shadow-xl:  0 20px 60px rgba(0,0,0,.15);

  /* Geçiş */
  --mice-transition: .15s ease;
}
```

### miceapp vs micedesk Varsayılan Renk Farkı

miceapp `static/css/app.css`:
```css
:root {
  --mice-sidebar-active: #2563eb;   /* canlı mavi — front office */
}
```

micedesk `static/css/app.css`:
```css
:root {
  --mice-sidebar-active: #1e40af;   /* koyu mavi — kurumsal back office */
}
```

### Komponent Standartları
- **Kart:** `border-radius: var(--mice-radius-lg)`, `box-shadow: var(--mice-shadow-sm)`, beyaz bg
- **Tablo:** başlık `var(--mice-bg)`, hover `var(--mice-bg-dark)`, 1px border
- **Badge:** `border-radius: var(--mice-radius-pill)`, 11px bold, durum rengiyle eşleşir
- **Buton:** `border-radius: var(--mice-radius-md)`, 3 boyut: sm/md/lg
- **Form input:** `border-radius: var(--mice-radius-md)`, focus ring `var(--mice-primary)`
- **Modal:** `border-radius: var(--mice-radius-xl)`, backdrop `rgba(0,0,0,.45)`
- **Empty state:** ortalı, büyük ikon (48px), başlık, açıklama metni

---

## 5. Tenant Markası (White-Label)

Her şirket kendi logosunu ve renklerini kullanabilir.
Varsayılan platform markası hiçbir zaman dayatılmaz.

### TenantBranding Modeli

```python
class TenantBranding(Base):
    __tablename__ = "tenant_brandings"

    id                   = Column(String(36), primary_key=True, default=_uuid)
    tenant_id            = Column(String(36), ForeignKey("tenants.id"),
                                  unique=True, nullable=False)

    # ── Kimlik ──────────────────────────────────────────────────────────────
    brand_name           = Column(String(100), nullable=True)
    # None → "miceapp" veya "micedesk" gösterilir

    # ── Logo dosya yolları (storage_helper key formatı) ────────────────────
    # Yol: {tenant_id}/branding/logo.png  vb.
    logo_path            = Column(String(500), nullable=True)   # açık arka plan
    logo_dark_path       = Column(String(500), nullable=True)   # sidebar (koyu arka plan)
    favicon_path         = Column(String(500), nullable=True)   # ICO/PNG

    # ── Renk override'ları (HEX, örn. "#2563eb") ───────────────────────────
    # None → design-tokens.css varsayılanı kullanılır
    color_primary        = Column(String(7), nullable=True)
    color_sidebar_bg     = Column(String(7), nullable=True)
    color_sidebar_active = Column(String(7), nullable=True)

    updated_at           = Column(DateTime, default=_now, onupdate=_now)
    updated_by           = Column(String(36), nullable=True)
```

### base.html — Dinamik Marka Enjeksiyonu

`</head>` kapanmadan önce (design-tokens.css'den **sonra**):

```jinja2
{# ── Tenant marka renkleri (yalnızca override varsa yazılır) ── #}
{% set br = request.state.branding %}
{% if br and (br.color_primary or br.color_sidebar_bg or br.color_sidebar_active) %}
<style>
:root {
  {% if br.color_primary %}
  --mice-primary:       {{ br.color_primary }};
  --mice-primary-dark:  {{ br.color_primary }};
  --mice-primary-light: {{ br.color_primary }}22;
  {% endif %}
  {% if br.color_sidebar_bg %}
  --mice-sidebar-bg:    {{ br.color_sidebar_bg }};
  {% endif %}
  {% if br.color_sidebar_active %}
  --mice-sidebar-active: {{ br.color_sidebar_active }};
  --mice-sidebar-hover:  {{ br.color_sidebar_active }}cc;
  {% endif %}
}
</style>
{% endif %}
```

### base.html — Logo Bloğu

```jinja2
{% set br = request.state.branding %}
<a href="/dashboard" class="sidebar-brand">
  {% if br and br.logo_dark_path %}
    <img src="{{ br.logo_dark_path | file_url }}"
         alt="{{ br.brand_name or app_name }}"
         style="height:34px; max-width:176px; object-fit:contain;">
  {% elif br and br.logo_path %}
    <img src="{{ br.logo_path | file_url }}"
         alt="{{ br.brand_name or app_name }}"
         style="height:34px; max-width:176px; object-fit:contain;">
  {% else %}
    <img src="/static/logo/{{ app_logo }}"
         alt="{{ app_name }}"
         style="height:34px;">
  {% endif %}
</a>
```

`app_name` ve `app_logo` değişkenleri `templates_config.py`'deki Jinja2 ortamı globals'ından gelir:

```python
# templates_config.py
templates.env.globals["app_name"]  = "miceapp"   # veya "micedesk"
templates.env.globals["app_logo"]  = "miceapp-logo-white.png"
```

### Middleware Entegrasyonu

`nav_counts_middleware` içinde, token decode edildikten sonra:

```python
branding = None
if tenant_id:
    branding_row = db.query(TenantBranding).filter(
        TenantBranding.tenant_id == tenant_id
    ).first()
    if branding_row:
        db.expunge(branding_row)   # session kapandıktan sonra da erişilebilir
    branding = branding_row
request.state.branding = branding
```

### Admin Branding Sayfası (`/admin/branding`)
- Logo yükle (maks 2 MB, PNG/SVG/JPG) — preview anlık
- Sidebar (koyu) logo yükle (maks 2 MB)
- Favicon yükle (maks 512 KB, ICO/PNG)
- Marka adı text input
- Ana renk color picker (HEX + preview)
- Sidebar arka plan rengi color picker
- Sidebar aktif rengi color picker
- **Önizle** — aynı sayfada anlık CSS değişkeni güncellemesi
- **Sıfırla** — tüm override'ları NULL yap

---

## 6. Dosya Depolama (Tenant İzolasyonlu)

### Temel Kural

Her dosya yolu `{tenant_id}/` prefix'iyle başlar.
Hiçbir kullanıcı başka bir tenant'ın dosyasına erişemez.

```
Yol şeması: {tenant_id}/{modül}/{yıl}/{ay}/{uuid}.{ext}

Örnekler:
  abc123/hbf/2026/05/f47ac10b.pdf          → HBF belgesi
  abc123/invoices/2026/05/8d3f9a12.pdf     → Fatura PDF
  abc123/cheques/2026/05/cc9f1234.jpg      → Çek görseli
  abc123/avatars/{user_uuid}.jpg           → Kullanıcı fotoğrafı
  abc123/branding/logo.png                 → Firma logosu
  abc123/branding/logo-dark.png            → Sidebar logosu
  abc123/branding/favicon.png              → Favicon
```

### storage_helper.py (her iki uygulamada özdeş)

```python
import os, uuid
from datetime import datetime
from pathlib import Path
from fastapi import HTTPException, UploadFile

R2_ENABLED  = bool(os.getenv("R2_ENDPOINT"))
LOCAL_BASE  = Path("static")

ALLOWED = {
    "document": {".pdf", ".doc", ".docx", ".xls", ".xlsx"},
    "image":    {".jpg", ".jpeg", ".png", ".gif", ".webp"},
    "logo":     {".jpg", ".jpeg", ".png", ".svg"},
    "favicon":  {".ico", ".png"},
}
MAX_SIZE = {
    "document": 10 * 1024 * 1024,    # 10 MB
    "image":    5  * 1024 * 1024,    # 5 MB
    "logo":     2  * 1024 * 1024,    # 2 MB
    "favicon":  512 * 1024,           # 512 KB
}


def _key(tenant_id: str, module: str, filename: str, dated=True) -> str:
    ext = Path(filename).suffix.lower() or ".bin"
    uid = str(uuid.uuid4())
    if dated:
        d = datetime.utcnow()
        return f"{tenant_id}/{module}/{d.year}/{d.month:02d}/{uid}{ext}"
    return f"{tenant_id}/{module}/{uid}{ext}"


def save_file(
    upload: UploadFile,
    tenant_id: str,          # ZORUNLU — atlanırsa tenant izolasyonu bozulur
    module: str,             # "hbf" | "invoices" | "cheques" | "branding" | "avatars"
    file_type: str = "document",
    dated: bool = True,
) -> str:
    """Dosyayı kaydeder, storage key döner."""
    ext = Path(upload.filename or "").suffix.lower()
    allowed = ALLOWED.get(file_type, set())
    if allowed and ext not in allowed:
        raise HTTPException(400, f"İzin verilmeyen dosya türü: {ext}")

    content = upload.file.read()
    if len(content) > MAX_SIZE.get(file_type, MAX_SIZE["document"]):
        raise HTTPException(400, "Dosya çok büyük.")
    upload.file.seek(0)

    key = _key(tenant_id, module, upload.filename or "file", dated=dated)

    if R2_ENABLED:
        import boto3
        s3 = boto3.client(
            "s3",
            endpoint_url=os.getenv("R2_ENDPOINT"),
            aws_access_key_id=os.getenv("R2_KEY_ID"),
            aws_secret_access_key=os.getenv("R2_SECRET"),
        )
        s3.put_object(
            Bucket=os.getenv("R2_BUCKET"),
            Key=key,
            Body=content,
            ContentType=upload.content_type or "application/octet-stream",
        )
    else:
        dest = LOCAL_BASE / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)

    return key


def delete_file(key: str):
    if not key:
        return
    if R2_ENABLED:
        import boto3
        s3 = boto3.client(
            "s3",
            endpoint_url=os.getenv("R2_ENDPOINT"),
            aws_access_key_id=os.getenv("R2_KEY_ID"),
            aws_secret_access_key=os.getenv("R2_SECRET"),
        )
        s3.delete_object(Bucket=os.getenv("R2_BUCKET"), Key=key)
    else:
        (LOCAL_BASE / key).unlink(missing_ok=True)


def get_file_url(key: str, expires: int = 3600) -> str:
    """
    R2: presigned URL (expires saniye cinsinden; logo için 86400 kullan)
    Yerel: /files/{key}  (app.py güvenli endpoint)
    """
    if not key:
        return ""
    if R2_ENABLED:
        import boto3
        s3 = boto3.client(
            "s3",
            endpoint_url=os.getenv("R2_ENDPOINT"),
            aws_access_key_id=os.getenv("R2_KEY_ID"),
            aws_secret_access_key=os.getenv("R2_SECRET"),
        )
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": os.getenv("R2_BUCKET"), "Key": key},
            ExpiresIn=expires,
        )
    return f"/files/{key}"
```

### Güvenli Dosya Endpoint'i (`app.py`)

```python
from fastapi.responses import FileResponse

@app.get("/files/{key:path}", name="serve_file")
async def serve_file(key: str, current_user=Depends(get_current_user)):
    # 1. Path traversal koruması
    if ".." in key or key.startswith("/"):
        raise HTTPException(403)

    # 2. Tenant izolasyonu — key'in ilk segmenti tenant_id olmalı
    if current_user.role != "super_admin":
        user_tid = str(current_user.tenant_id or current_user.company_id or "")
        key_tid  = key.split("/")[0]
        if not user_tid or user_tid != key_tid:
            raise HTTPException(403, "Bu dosyaya erişim yetkiniz yok.")

    # 3. R2 → presigned redirect
    if R2_ENABLED:
        return RedirectResponse(get_file_url(key), status_code=302)

    # 4. Yerel dosya
    base = Path("static").resolve()
    candidate = (base / key).resolve()
    if not str(candidate).startswith(str(base)):
        raise HTTPException(403)
    if not candidate.is_file():
        raise HTTPException(404, "Dosya bulunamadı.")
    return FileResponse(candidate)
```

### Jinja2 Filtresi

`templates_config.py` içinde:
```python
from storage_helper import get_file_url
templates.env.filters["file_url"] = lambda k: get_file_url(k or "", expires=86400)
```

Şablonda: `{{ vendor.logo_path | file_url }}`

---

## 7. Paylaşılan Veritabanı Mimarisi

```
Railway PostgreSQL (tek DB)
│
├── ORTAK TABLOLAR (her iki uygulama okur/yazar)
│   ├── tenants              → ajans/kiracı, plan, trial
│   ├── tenant_brandings     → beyaz etiket marka ayarları
│   ├── companies            → firma bilgisi (micedesk sahipli ama FK paylaşılır)
│   ├── users                → tek hesap, ortak JWT secret ile her iki uygulamaya giriş
│   ├── vendors              → tedarikçi master (venue + finansal alan birleşik)
│   ├── customers            → müşteri master
│   ├── references           → proje/etkinlik köprüsü (miceapp yazar, micedesk okur)
│   └── notifications        → target_app alanıyla ayrılan çapraz bildirimler
│
├── miceapp TABLOLARI
│   ├── requests, request_items
│   ├── budgets, budget_rows
│   ├── rfq_emails
│   ├── services, custom_categories, event_types
│   ├── org_titles, teams, team_members
│   ├── fund_requests, fund_transfers
│   └── invoice_logs         (coordinator işlem kaydı)
│
└── micedesk TABLOLARI
    ├── invoices              (+ coordinator_status köprü alanı)
    ├── invoice_payments
    ├── cash_books, cash_entries, cash_day_closes
    ├── bank_accounts, bank_movements
    ├── cheques
    ├── credit_cards, credit_card_statements, credit_card_txns
    ├── payment_instructions, manual_payment_lines
    ├── employees, salary_payments, employee_benefits
    ├── employee_advances
    ├── leave_types, leave_balances, leave_requests, public_holidays
    ├── hbf
    ├── annual_budgets, budget_lines, fixed_expenses
    ├── fund_pools
    ├── general_expense_categories, general_expenses
    ├── payroll_decisions
    ├── vendor_prepayments
    ├── role_permissions, system_settings
    └── departments, department_module_access
```

### Paylaşım Kuralları

1. **`invoices` micedesk'e aittir** — miceapp sadece `coordinator_status` + `coordinator_note` yazar.
2. **`vendors` ortaktır** — miceapp `company_id=NULL` vendor oluşturur; micedesk `OR company_id IS NULL` filtresiyle her ikisini görür.
3. **`users` ortaktır** — aynı JWT secret, aynı tablo; her iki uygulamaya aynı hesapla girilir.
4. **`references` miceapp'e aittir** — micedesk faturalarında `ref_id` olarak kullanılır.
5. **Çapraz FK yok** — başka uygulamanın tablosuna FK bağlanmaz; ortak alanlar `VARCHAR(36)` ID olarak tutulur.
6. **Tenant izolasyonu** — her tabloda `tenant_id VARCHAR(36)` zorunlu. Tüm sorgulara `WHERE tenant_id = ?` eklenir; middleware bunu `request.state.tenant_id` olarak sağlar.

---

## 8. Kullanıcı Rolleri & İzin Sistemi

### micedesk Rol Hiyerarşisi

```
kullanici → mudur → genel_mudur → admin → super_admin
```

| Rol | Yetki Özeti |
|-----|-------------|
| `kullanici` | Kendi kayıtları, talep oluşturma |
| `mudur` | Ekibinin avans/HBF/izin 1. kademe onayı |
| `genel_mudur` | Şirket geneli görüntüleme, haftalık ödeme onayı (2. kademe) |
| `admin` | Firma ayarları + kullanıcı yönetimi + tüm yetkilere sahip |
| `super_admin` | Tüm tenant'lara erişim, platform yönetimi |

Hybrid property'ler:
- `is_admin` → role ∈ {admin, super_admin}
- `is_approver` → role ∈ {genel_mudur, admin, super_admin}

### miceapp Rol Hiyerarşisi

```
asistan → yonetici → mudur → genel_mudur → admin
```

| Rol | Yetki Özeti |
|-----|-------------|
| `asistan` | Talep görüntüleme, taslak oluşturma |
| `yonetici` | Talep oluşturma, RFQ gönderme, fatura onaylama |
| `mudur` | Ekibinin referanslarını görme, 1. kademe onay |
| `genel_mudur` | Tüm referanslar, kapama onayı |
| `admin` | Kullanıcı + tedarikçi + müşteri yönetimi |

Hybrid property'ler:
- `is_gm` → role ∈ {genel_mudur, admin} VEYA org_title.grade == 1
- `is_pm_side` → role ∈ {yonetici, asistan, mudur}

### İzin Sistemi (micedesk — iki katmanlı)

1. `auth.py::DEFAULT_PERMISSIONS` — kod içinde varsayılan eşikler
2. `RolePermission` tablosu — admin UI'dan rol başına override

`check_permission(user, perm)` önce DB'ye bakar, kayıt yoksa DEFAULT'a düşer.

**Kritik izin kodları:**
```python
# Avans
"advance_create"         → kullanici
"advance_approve_first"  → mudur
"advance_approve_final"  → genel_mudur

# HBF
"hbf_create"             → kullanici
"hbf_approve_first"      → mudur
"hbf_approve_final"      → genel_mudur

# Ödeme
"payment_list_prepare"   → kullanici
"payment_list_approve"   → genel_mudur

# Yönetim
"invoice_delete"         → admin
"customer_manage"        → admin
"employee_manage"        → admin
"vendor_manage"          → admin
"report_view_financial"  → mudur
"report_view_all"        → genel_mudur
"module_config"          → admin
"user_manage"            → admin
"super_admin_panel"      → super_admin
```

---

## 9. Takım & Organizasyon Yapısı

```python
class OrgTitle(Base):
    __tablename__ = "org_titles"
    id         = Column(String(36), PK)
    tenant_id  = Column(String(36), nullable=False)
    title      = Column(String(100))     # "Genel Müdür", "Koordinatör" vs.
    grade      = Column(Integer)         # 1 = GM seviye (is_gm True yapar)

class Team(Base):
    __tablename__ = "teams"
    id         = Column(String(36), PK)
    tenant_id  = Column(String(36), nullable=False)
    name       = Column(String(100))
    color      = Column(String(7))       # #hex
    leader_id  = Column(String(36), FK→users, nullable=True)

class TeamMember(Base):
    __tablename__ = "team_members"
    team_id    = Column(String(36), FK→teams)
    user_id    = Column(String(36), FK→users)
    role       = Column(String(20))      # "leader" | "member"
```

`User.manager_id → User.id` raporlama zincirini oluşturur.
Müdür, `WHERE manager_id = {mudur_id}` olan kullanıcıların talep/avans/HBF/izinlerini görür.

### Kullanıcı Limitleri (Plan Bazlı)

```python
PLAN_LIMITS = {
    "starter": {
        "max_users":          5,
        "max_miceapp_users":  5,
        "max_micedesk_users": 0,   # micedesk bu planda yok
        "max_references":     100,
        "max_vendors":        50,
    },
    "pro": {
        "max_users":          25,
        "max_miceapp_users":  15,
        "max_micedesk_users": 10,
        "max_references":     1000,
        "max_vendors":        500,
    },
    "enterprise": {
        "max_users":          -1,   # -1 = sınırsız
        "max_miceapp_users":  -1,
        "max_micedesk_users": -1,
        "max_references":     -1,
        "max_vendors":        -1,
    },
}
```

Kullanıcı eklerken limit kontrolü:
```python
def check_user_limit(db, tenant_id, app: str = "miceapp"):
    plan   = get_tenant_plan(db, tenant_id)
    limit  = PLAN_LIMITS[plan][f"max_{app}_users"]
    if limit == -1:
        return
    count  = db.query(func.count(User.id)).filter(
        User.tenant_id == tenant_id,
        User.app_access.in_([app, "both"]),
        User.active == True
    ).scalar()
    if count >= limit:
        raise HTTPException(400, f"Kullanıcı limitine ulaşıldı ({limit}).")
```

---

## 10. Onay Silsilesi

### A. HBF / Avans / İzin — İki Kademeli

```
talep  →  mudur_onayladi  →  onaylandi  →  odendi / kapandi
  ↓              ↓                ↓
reddedildi   reddedildi     reddedildi   (her aşamada mümkün, rejection_note zorunlu)
```

Her modelde standart alanlar:
```python
status                  = Column(String(30), default="talep")
manager_approved_by     = Column(String(36), nullable=True)
manager_approved_at     = Column(DateTime,   nullable=True)
approved_by_id          = Column(String(36), nullable=True)
approved_at             = Column(DateTime,   nullable=True)
rejected_by             = Column(String(36), nullable=True)
rejected_at             = Column(DateTime,   nullable=True)
rejection_note          = Column(Text,       nullable=True)   # zorunlu reddedince
```

### B. Fatura Çok Kademeli Onay (micedesk — RBAC v2)

```python
approval_status         = Column(String(30), nullable=True)
# NULL = eski kayıt (onay yok)
# "onay_bekliyor" = sıradaki onaylayıcıya yönlendirildi
# "approved"      = tüm zincir tamamlandı
# "reddedildi"    = herhangi bir kademede reddedildi

current_approver_id     = Column(String(36), FK→users, nullable=True)
approval_history        = Column(Text, nullable=True)   # JSON list
approval_rejection_note = Column(Text, nullable=True)
```

### C. GM Haftalık Ödeme Listesi (micedesk)

Tüm ödemeye hazır kayıtlarda standart GM karar alanları:
```python
gm_decision         = Column(String(20), nullable=True)
# NULL="henüz listelenmedi", "approved", "rejected", "postponed"
gm_decision_at      = Column(DateTime, nullable=True)
gm_decision_by      = Column(String(36), FK→users, nullable=True)
gm_postpone_until   = Column(Date,     nullable=True)
gm_method_override  = Column(String(20), nullable=True)   # ödeme yöntemi değişikliği
gm_approved_amount  = Column(Float,    nullable=True)     # kısmi onay
gm_decision_note    = Column(Text,     nullable=True)
preparer_note       = Column(Text,     nullable=True)     # listecinin GM'e notu
```

GM "approved" → `PaymentInstruction` otomatik oluşur → operatör execute eder.

### D. Koordinatör Fatura Onayı (miceapp ↔ micedesk köprüsü)

```
micedesk                  invoices tablosu               miceapp
────────                  ────────────────               ───────
Kesilen fatura gir
+ ref_id bağla      ──▶  coordinator_status='beklemede'
                                                    ──▶  Onay Bekleyenler listesi
                         coordinator_status='onaylandi'  ◀── Koordinatör: Onayla
                         coordinator_status='reddedildi' ◀── Koordinatör: Reddet + not
Ödeme akışına girer ◀──  WHERE coordinator_status='onaylandi'
```

`invoices` tablosuna eklenen alanlar:
```python
coordinator_status      = Column(String(20), nullable=True)
coordinator_note        = Column(Text,       nullable=True)
coordinator_reviewed_at = Column(DateTime,   nullable=True)
coordinator_reviewed_by = Column(String(36), nullable=True)  # FK değil (çapraz uygulama)
```

---

## 11. Tüm Veri Modelleri

### Ortak Modeller

```python
def _uuid(): return str(uuid4())
def _now():  return datetime.utcnow()

class Tenant(Base):
    __tablename__ = "tenants"
    id         = Column(String(36), primary_key=True, default=_uuid)
    name       = Column(String(200), nullable=False)
    slug       = Column(String(50),  unique=True, nullable=False)
    plan       = Column(String(20),  default="starter")  # starter|pro|enterprise
    trial_ends = Column(Date,        nullable=True)
    is_active  = Column(Boolean,     default=True)
    created_at = Column(DateTime,    default=_now)
    branding   = relationship("TenantBranding", uselist=False, back_populates="tenant")

class TenantBranding(Base):
    __tablename__ = "tenant_brandings"
    id                   = Column(String(36), primary_key=True, default=_uuid)
    tenant_id            = Column(String(36), ForeignKey("tenants.id"), unique=True)
    brand_name           = Column(String(100), nullable=True)
    logo_path            = Column(String(500), nullable=True)
    logo_dark_path       = Column(String(500), nullable=True)
    favicon_path         = Column(String(500), nullable=True)
    color_primary        = Column(String(7),   nullable=True)
    color_sidebar_bg     = Column(String(7),   nullable=True)
    color_sidebar_active = Column(String(7),   nullable=True)
    updated_at           = Column(DateTime, default=_now, onupdate=_now)
    updated_by           = Column(String(36), nullable=True)
    tenant               = relationship("Tenant", back_populates="branding")

class User(Base):
    __tablename__ = "users"
    id           = Column(String(36), primary_key=True, default=_uuid)
    tenant_id    = Column(String(36), ForeignKey("tenants.id"), nullable=True, index=True)
    company_id   = Column(String(36), nullable=True, index=True)  # micedesk uyumu
    email        = Column(String(200), unique=True, nullable=False)
    password     = Column(String(200), nullable=False)    # bcrypt
    name         = Column(String(100), nullable=False)
    surname      = Column(String(100), nullable=False)
    role         = Column(String(30),  default="kullanici")
    app_access   = Column(String(20),  default="miceapp") # miceapp|micedesk|both
    manager_id   = Column(String(36),  ForeignKey("users.id"), nullable=True)
    org_title_id = Column(String(36),  ForeignKey("org_titles.id"), nullable=True)
    active       = Column(Boolean,     default=True)
    phone        = Column(String(20),  nullable=True)
    avatar_path  = Column(String(500), nullable=True)    # {tenant_id}/avatars/{user_id}.jpg
    created_at   = Column(DateTime,    default=_now)

    @property
    def is_admin(self):
        return self.role in ("admin", "super_admin")

    @property
    def is_approver(self):  # micedesk: GM+
        return self.role in ("genel_mudur", "admin", "super_admin")

    @property
    def is_gm(self):        # miceapp
        return self.role in ("genel_mudur", "admin") or (
            self.org_title is not None and self.org_title.grade == 1
        )

class Vendor(Base):
    __tablename__ = "vendors"
    id               = Column(String(36), primary_key=True, default=_uuid)
    tenant_id        = Column(String(36), nullable=True, index=True)
    company_id       = Column(String(36), nullable=True, index=True)  # NULL=miceapp oluşturdu
    name             = Column(String(200), nullable=False)
    active           = Column(Boolean, default=True)
    # ── miceapp alanları ──
    supplier_type    = Column(String(30), nullable=True)
    # otel|etkinlik|restaurant|teknik|dekor|transfer|tasarım|süsleme|ik|diğer
    city             = Column(String(100), nullable=True)
    cities_json      = Column(Text, default="[]")    # ["İstanbul","Ankara"]
    stars            = Column(Integer, nullable=True)
    total_rooms      = Column(Integer, nullable=True)
    halls_json       = Column(Text, default="[]")    # [{name,capacity,area}]
    contacts_json    = Column(Text, default="[]")    # [{name,title,email,phone}]
    website          = Column(String(300), nullable=True)
    notes            = Column(Text, nullable=True)
    # ── micedesk alanları ──
    tax_no           = Column(String(20), nullable=True)
    tax_office       = Column(String(100), nullable=True)
    iban             = Column(String(50), nullable=True)
    bank_name        = Column(String(100), nullable=True)
    payment_terms    = Column(Integer, default=30)    # vade (gün)
    prepayment_limit = Column(Float, default=0.0)
    vendor_type_id   = Column(String(36), nullable=True)
    # ── E-fatura cache ──
    is_efatura_user    = Column(Boolean, nullable=True)
    efatura_alias      = Column(String(200), nullable=True)
    efatura_checked_at = Column(DateTime, nullable=True)
    # ── Meta ──
    created_by  = Column(String(36), nullable=True)  # FK değil
    created_at  = Column(DateTime, default=_now)

class Customer(Base):
    __tablename__ = "customers"
    id         = Column(String(36), primary_key=True, default=_uuid)
    tenant_id  = Column(String(36), nullable=True, index=True)
    company_id = Column(String(36), nullable=True, index=True)
    name       = Column(String(200), nullable=False)
    code       = Column(String(10), nullable=True)     # 3 harf, ref_no içinde kullanılır
    sector     = Column(String(100), nullable=True)
    tax_no     = Column(String(20), nullable=True)
    tax_office = Column(String(100), nullable=True)
    email      = Column(String(200), nullable=True)
    phone      = Column(String(30), nullable=True)
    address    = Column(Text, nullable=True)
    notes      = Column(Text, nullable=True)
    team_id    = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=_now)
```

### miceapp Modelleri

```python
class Reference(Base):
    __tablename__ = "references"
    id             = Column(String(36), primary_key=True, default=_uuid)
    ref_no         = Column(String(30), unique=True)     # TOP-ABC-2601-001
    tenant_id      = Column(String(36), nullable=True, index=True)
    company_id     = Column(String(36), nullable=True)
    customer_id    = Column(String(36), ForeignKey("customers.id"), nullable=True)
    title          = Column(String(200), nullable=False)
    event_type     = Column(String(30))                  # toplanti|konferans|gala|egitim|lansman|diger
    city           = Column(String(100), nullable=True)
    cities_json    = Column(Text, default="[]")
    check_in       = Column(Date, nullable=True)
    check_out      = Column(Date, nullable=True)
    attendee_count = Column(Integer, default=0)
    status         = Column(String(30), default="draft")
    # draft|pending|in_progress|venues_contacted|budget_ready|completed|cancelled
    description    = Column(Text, nullable=True)
    notes          = Column(Text, nullable=True)
    team_id        = Column(String(36), ForeignKey("teams.id"), nullable=True)
    created_by     = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at     = Column(DateTime, default=_now)
    updated_at     = Column(DateTime, default=_now, onupdate=_now)

class Budget(Base):
    __tablename__ = "budgets"
    id          = Column(String(36), primary_key=True, default=_uuid)
    tenant_id   = Column(String(36), nullable=True, index=True)
    request_id  = Column(String(36), ForeignKey("requests.id"), nullable=False)
    venue_name  = Column(String(200))
    rows_json   = Column(Text, default="[]")
    # BudgetRow: {id, section, description, unit, qty, nights,
    #             cost_price, sale_price, vat_rate, is_service_fee}
    created_by  = Column(String(36), ForeignKey("users.id"))
    created_at  = Column(DateTime, default=_now)
    updated_at  = Column(DateTime, default=_now, onupdate=_now)
```

### micedesk Modelleri

```python
class Invoice(Base):
    __tablename__ = "invoices"
    id               = Column(String(36), primary_key=True, default=_uuid)
    tenant_id        = Column(String(36), nullable=True, index=True)
    company_id       = Column(String(36), ForeignKey("companies.id"), nullable=True)
    ref_id           = Column(String(36), ForeignKey("references.id"), nullable=True)
    vendor_id        = Column(String(36), ForeignKey("vendors.id"), nullable=True)
    customer_id      = Column(String(36), ForeignKey("customers.id"), nullable=True)
    invoice_type     = Column(String(20), nullable=False)
    # gelen|kesilen|komisyon|iade_gelen|iade_kesilen
    invoice_no       = Column(String(100))
    invoice_date     = Column(Date, nullable=False)
    due_date         = Column(Date, nullable=True)
    amount           = Column(Float, nullable=False)    # KDV hariç
    vat_rate         = Column(Float, default=0.20)     # ondalık: 0.20 = %20
    total_amount     = Column(Float)                   # KDV dahil (= amount * (1 + vat_rate))
    currency         = Column(String(3), default="TRY")
    status           = Column(String(20), default="approved")
    # draft|approved|partial|paid|cancelled
    payment_method   = Column(String(20), nullable=True)
    notes            = Column(Text, nullable=True)
    items_json       = Column(Text, default="[]")
    attachment_path  = Column(String(500), nullable=True)   # {tenant_id}/invoices/...
    # ── Onay zinciri ──
    approval_status      = Column(String(30), nullable=True)
    current_approver_id  = Column(String(36), ForeignKey("users.id"), nullable=True)
    approval_history     = Column(Text, nullable=True)
    approval_rejection_note = Column(Text, nullable=True)
    # ── GM ödeme kararı ──
    gm_decision          = Column(String(20), nullable=True)
    gm_decision_at       = Column(DateTime, nullable=True)
    gm_decision_by       = Column(String(36), ForeignKey("users.id"), nullable=True)
    gm_postpone_until    = Column(Date, nullable=True)
    gm_method_override   = Column(String(20), nullable=True)
    gm_approved_amount   = Column(Float, nullable=True)
    gm_decision_note     = Column(Text, nullable=True)
    preparer_note        = Column(Text, nullable=True)
    # ── Koordinatör köprüsü ──
    coordinator_status      = Column(String(20), nullable=True)
    coordinator_note        = Column(Text, nullable=True)
    coordinator_reviewed_at = Column(DateTime, nullable=True)
    coordinator_reviewed_by = Column(String(36), nullable=True)  # FK değil
    # ── E-Fatura ──
    einvoice_status  = Column(String(20), nullable=True)
    einvoice_uuid    = Column(String(64), nullable=True)
    einvoice_pdf_url = Column(Text, nullable=True)
    einvoice_sent_at = Column(DateTime, nullable=True)
    # ── Fatura bölme ──
    is_split_parent  = Column(Boolean, default=False)
    split_parent_id  = Column(String(36), ForeignKey("invoices.id"), nullable=True)
    # ── Soft delete ──
    deleted_at  = Column(DateTime, nullable=True)
    deleted_by  = Column(String(36), nullable=True)
    # ── Meta ──
    created_by  = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at  = Column(DateTime, default=_now)

    @property
    def remaining(self) -> float:
        paid = sum(p.amount for p in self.payments)
        return max(0.0, (self.total_amount or self.amount) - paid)

class Employee(Base):
    __tablename__ = "employees"
    id              = Column(String(36), primary_key=True, default=_uuid)
    tenant_id       = Column(String(36), nullable=True, index=True)
    company_id      = Column(String(36), ForeignKey("companies.id"), nullable=True)
    user_id         = Column(String(36), ForeignKey("users.id"), nullable=True)
    name            = Column(String(100), nullable=False)
    surname         = Column(String(100), nullable=False)
    tc_no           = Column(String(11), nullable=True)
    birth_date      = Column(Date, nullable=True)
    start_date      = Column(Date, nullable=False)
    end_date        = Column(Date, nullable=True)
    position        = Column(String(100), nullable=True)
    department      = Column(String(100), nullable=True)
    salary          = Column(Float, default=0.0)
    salary_currency = Column(String(3), default="TRY")
    iban            = Column(String(50), nullable=True)
    email           = Column(String(200), nullable=True)
    phone           = Column(String(30), nullable=True)
    active          = Column(Boolean, default=True)

class HBF(Base):
    __tablename__ = "hbf"
    id              = Column(String(36), primary_key=True, default=_uuid)
    hbf_no          = Column(String(30), unique=True)    # HBF-YYMM-NNN
    tenant_id       = Column(String(36), nullable=True, index=True)
    company_id      = Column(String(36), nullable=True)
    employee_id     = Column(String(36), ForeignKey("employees.id"), nullable=False)
    ref_id          = Column(String(36), nullable=True)  # birincil referans
    refs_json       = Column(Text, default="[]")          # çoklu referans
    description     = Column(Text, nullable=False)
    amount          = Column(Float, nullable=False)
    expense_date    = Column(Date, nullable=False)
    expense_items_json = Column(Text, default="[]")
    document_path   = Column(String(500), nullable=True)  # {tenant_id}/hbf/...
    status          = Column(String(30), default="talep")
    # talep|mudur_onayladi|onaylandi|reddedildi|iptal
    manager_approved_by = Column(String(36), nullable=True)
    manager_approved_at = Column(DateTime, nullable=True)
    approved_by_id      = Column(String(36), nullable=True)
    approved_at         = Column(DateTime, nullable=True)
    rejected_by         = Column(String(36), nullable=True)
    rejection_note      = Column(Text, nullable=True)
    created_by      = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at      = Column(DateTime, default=_now)
```

---

## 12. Auth Sistemi

### JWT Token

```python
# auth.py
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
ALGORITHM  = "HS256"
EXPIRE_H   = 8
COOKIE_NAME = "access_token"

def create_token(user: User) -> str:
    payload = {
        "sub":       str(user.id),
        "email":     user.email,
        "role":      user.role,
        "is_admin":  user.is_admin,
        "tenant_id": str(user.tenant_id or ""),
        "company_id": str(user.company_id or ""),
        "exp":       datetime.utcnow() + timedelta(hours=EXPIRE_H),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except Exception:
        return None
```

### FastAPI Bağımlılıkları

```python
async def get_current_user(request: Request, db=Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401)
    payload = decode_token(token)
    if not payload:
        raise HTTPException(401)
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user or not user.active:
        raise HTTPException(401)
    return user

def require_admin(user=Depends(get_current_user)):
    if not user.is_admin:
        raise HTTPException(403)
    return user

def require_approver(user=Depends(get_current_user)):  # GM+ micedesk
    if not user.is_approver:
        raise HTTPException(403)
    return user

def get_tenant_id(user=Depends(get_current_user)) -> str:
    tid = str(user.tenant_id or user.company_id or "")
    if not tid:
        raise HTTPException(400, "Tenant atanmamış.")
    return tid
```

### Cookie Güvenliği
- `ENVIRONMENT=production` → `secure=True, httponly=True, samesite="lax"`
- Development → `secure=False`

---

## 13. Middleware: Nav Counts + Branding

`app.py`'de her HTTP isteğinde çalışır:

```python
@app.middleware("http")
async def app_middleware(request: Request, call_next):
    # Statik dosyalar ve favicon'u atla
    path = request.url.path
    if path.startswith("/static") or path.startswith("/files") or "." in path.split("/")[-1]:
        request.state.nav_counts = {}
        request.state.branding   = None
        request.state.current_user = None
        request.state.tenant_id    = None
        return await call_next(request)

    token = request.cookies.get(COOKIE_NAME)
    if not token:
        request.state.nav_counts   = {}
        request.state.branding     = None
        request.state.current_user = None
        request.state.tenant_id    = None
        return await call_next(request)

    payload = decode_token(token)
    if not payload:
        return await call_next(request)

    db = SessionLocal()
    try:
        user_id   = payload.get("sub")
        tenant_id = payload.get("tenant_id") or payload.get("company_id") or ""

        # Kullanıcıyı yükle (eager load: departments, org_title)
        current_user = db.query(User).filter(User.id == user_id).first()
        if current_user:
            db.expunge(current_user)

        # Tenant branding
        branding = None
        if tenant_id:
            b = db.query(TenantBranding).filter(
                TenantBranding.tenant_id == tenant_id
            ).first()
            if b:
                db.expunge(b)
            branding = b

        # Nav badge sayıları (rol bazlı, hafif sorgular)
        counts = _compute_nav_counts(db, current_user, tenant_id)

    except Exception:
        counts, branding, current_user = {}, None, None
    finally:
        db.close()

    request.state.nav_counts   = counts
    request.state.branding     = branding
    request.state.current_user = current_user
    request.state.tenant_id    = tenant_id
    return await call_next(request)
```

`base.html`'de badge filtresi:
```jinja2
{# nb() filtresi: 0 → "", 1+ → badge HTML #}
{{ nb(request.state.nav_counts.get("pending_leaves", 0)) }}
```

---

## 14. Veritabanı Migration Yaklaşımı

**Alembic kullanılmaz.** `database.py::_migrate()` her startup'ta çalışır.

```python
def _migrate(engine):
    with engine.begin() as conn:
        for sql in _MIGRATIONS:
            try:
                conn.execute(text(sql))
            except Exception:
                pass   # SQLite uyumsuzlukları için silent

_MIGRATIONS = [
    # tenants & branding
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS slug VARCHAR(50)",
    "ALTER TABLE tenant_brandings ADD COLUMN IF NOT EXISTS logo_dark_path VARCHAR(500)",
    "ALTER TABLE tenant_brandings ADD COLUMN IF NOT EXISTS favicon_path VARCHAR(500)",
    "ALTER TABLE tenant_brandings ADD COLUMN IF NOT EXISTS color_sidebar_active VARCHAR(7)",
    # users
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(36)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS app_access VARCHAR(20) DEFAULT 'miceapp'",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_path VARCHAR(500)",
    # vendors & customers
    "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(36)",
    "ALTER TABLE customers ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(36)",
    # invoices
    "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(36)",
    "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS coordinator_status VARCHAR(20)",
    "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS coordinator_note TEXT",
    "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS coordinator_reviewed_at TIMESTAMP",
    "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS coordinator_reviewed_by VARCHAR(36)",
    "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS total_amount FLOAT",
    "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS attachment_path VARCHAR(500)",
    # hbf
    "ALTER TABLE hbf ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(36)",
    "ALTER TABLE hbf ADD COLUMN IF NOT EXISTS document_path VARCHAR(500)",
    # ... her yeni kolon buraya eklenir
]
```

**Kurallar:**
- `ADD COLUMN IF NOT EXISTS` — her zaman idempotent
- `DROP COLUMN` **asla yazılmaz** — eski sürümler bozulur
- PostgreSQL ENUM değer ekleme → `AUTOCOMMIT` bağlantısı gerekir (transaction dışı)
- Yeni tablo için `create_all(checkfirst=True)` yeterli

**Numara formatları:**
- `Reference.ref_no` → `TIP-MUS-YYMM-NNN` (örn. `TOP-ABC-2601-001`)
- `HBF.hbf_no` → `HBF-YYMM-NNN`
- Üretim: `database.py::generate_ref_no(tenant_id, event_type, customer_code, date)`

---

## 15. miceapp — Modül Detayları

### Rotalar & İşlevler

```
/              → /dashboard yönlendirme
/login         → Giriş (hem miceapp hem micedesk için aynı sayfa)
/dashboard     → Aktif referans sayısı, RFQ bekleyenler, koordinatör onayları

/references         Proje/etkinlik listesi, arama, filtre
/references/new     Yeni referans oluştur
/references/{id}    Detay (bütçe, notlar, giderler)

/requests           Talep formu (PM kullanır, sekmeli yapı)
/requests/{id}/rfq  RFQ e-posta oluşturucu

/budgets/{id}       Bütçe editörü (e_dem kullanır)

/coordinator/invoices          Koordinatör fatura onay listesi
/coordinator/invoices/{id}/approve  POST — onayla
/coordinator/invoices/{id}/reject   POST — reddet + not

/vendors       Tedarikçi havuzu (şehir + tip filtresi)
/vendors/new   Yeni tedarikçi
/vendors/{id}  Düzenle / Salon yönetimi / Kontaklar

/customers     Müşteri listesi
/users         Kullanıcı yönetimi (admin)
/teams         Takım yönetimi
/users/org-titles  Unvan + org seviye

/admin/branding    Tenant marka ayarları (logo, renk)
/admin/permissions Rol izin matrisi

/profile       Kendi profilini düzenle (şifre, avatar, iletişim)
/notifications Bildirim merkezi
```

### Sidebar Yapısı (rol bazlı)

```
[Herkes]
  Dashboard

[yonetici | mudur | is_gm]
  Referanslarım
  Koordinatör Onayları  ← badge: coordinator_pending

[mudur | is_gm]
  Tüm Referanslar

[e_dem]
  Gelen Referanslar
  Bütçe Yönetimi

[yonetici+]
  Tedarikçi Havuzu (salt görüntüleme)

[admin | is_gm]
  ── Yönetim ──
    Tedarikçi Yönetimi
    Müşteri Yönetimi
    Hizmet Kataloğu
    Kullanıcılar
    Org Yapısı
    Takımlar
    Rol İzinleri
    Marka Ayarları
```

### Talep Formu Sekmeleri

```python
REQUEST_TABS = [
    {"id": "venue",   "label": "🏨 Otel / Mekan",    "supplier_types": ["otel", "etkinlik"]},
    {"id": "teknik",  "label": "🔧 Teknik Ekipman",  "supplier_types": ["teknik"]},
    {"id": "dekor",   "label": "🎨 Dekor",           "supplier_types": ["dekor"]},
    {"id": "transfer","label": "🚌 Transfer",         "supplier_types": ["transfer"]},
    {"id": "tasarim", "label": "🖨 Tasarım & Basılı", "supplier_types": ["tasarim"]},
    {"id": "diger",   "label": "📦 Diğer",           "supplier_types": ["restaurant","susleme","ik","diger"]},
]
```

KDV oranları: `%0, %1, %8, %10, %18, %20`
Türkiye illeri: 81 il (TR_CITIES sabit listesi)

---

## 16. micedesk — Modül Detayları

### Rotalar & İşlevler

```
/              → /dashboard yönlendirme
/login         → Giriş

/dashboard     → Bekleyen fatura, ödeme talimatları, avans/HBF/izin sayıları,
                 son 5 fatura, dönem özeti

/invoices           Fatura listesi (gelen/kesilen/komisyon/iade + filtreler)
/invoices/new       Yeni fatura girişi
/invoices/{id}      Detay (ödeme, e-fatura, onay geçmişi)
/invoices/{id}/approve   Onay zinciri aksiyonu
/invoices/{id}/split     Fatura bölme

/cheques            Çek listesi + durum
/cash               Kasa özeti, giriş/çıkış, gün sonu kapatma
/bank-accounts      Banka hesapları + hareketler
/credit-cards       Kart + ekstre + txn mutabakatı
/payments           GM haftalık ödeme listesi
/payment-instructions   Ödeme talimatı kuyruğu (operatör execute)

/vendors       Tedarikçi listesi (miceapp oluşturdukları dahil)
/customers     Müşteri master

/employees          Personel listesi
/employees/new      Yeni personel
/employees/{id}     Detay (maaş, yan haklar, izinler, avanslar)

/advances           Avans talepleri (2 kademeli onay)
/hbf                HBF listesi (2 kademeli onay)
/leaves             İzin talepleri + takvim

/reports            Tüm finans raporları + Excel export
/tax-reports        Vergi raporu
/edefter            E-defter export

/users              Kullanıcı yönetimi
/admin/branding     Tenant marka ayarları
/admin/modules      Modül feature flag toggle
/admin/departments  Departman + modül erişimi
/admin/approval-limits  Onay limit eşikleri
/admin/roles        Rol izin matrisi
/admin/company-profile  Firma bilgileri (logo, IBAN, vergi)
/admin/backup       DB yedek indirme

/profile       Kendi profilini düzenle
/notifications Bildirim merkezi
```

### Sidebar Yapısı (rol bazlı)

```
[Herkes]
  Dashboard

[kullanici+]
  ── Finans ──
    Faturalarım      (kendi girdiği)

[mudur+ | is_approver]
  ── Finans ──
    Tüm Faturalar
    Ödeme Listesi (GM)
    Ödeme Talimatları

[admin]
  ── Kasa & Banka ──
    Kasalar
    Banka Hesapları
    Kredi Kartları
    Çekler

[Herkes]
  ── İK & Personel ──
    İzinlerim
    Avanslarım
    HBF'lerim

[mudur+]
  ── İK & Personel ──
    Ekip İzinleri
    Ekip Avansları
    Ekip HBF

[admin]
  Personel (tüm çalışanlar)

[mudur+]
  ── Raporlar ──
    Finans Raporu
    Excel Export

[admin | is_approver]
  ── Yönetim ──
    Kullanıcılar
    Departmanlar
    Modüller
    Rol İzinleri
    Firma Profili
    Marka Ayarları
    Yedekleme
```

### payment_helpers.py — Tek Kaynak

Tüm ödeme yan etkileri (CashEntry, BankMovement, CreditCardTxn) bu dosyadan çağrılır.
Manuel endpoint ve PaymentInstruction execute aynı fonksiyonu çağırır.

```python
def apply_invoice_payment(db, invoice, amount, method, **kwargs):
    """Faturaya ödeme uygular, yan etki kaydeder, PaymentInstruction kapatır."""
    ...

def apply_cheque_payment(db, cheque, **kwargs):
    ...
```

---

## 17. Deployment

### Mono-Repo'da İki Servis

Railway, her servise farklı bir `rootDirectory` tanımlanmasına izin verir:

```
Servis 1: miceapp
  rootDirectory: miceapp
  startCommand:  uvicorn app:app --host 0.0.0.0 --port $PORT

Servis 2: micedesk
  rootDirectory: micedesk
  startCommand:  uvicorn app:app --host 0.0.0.0 --port $PORT

Servis 3: PostgreSQL (Railway managed)
  → DATABASE_URL referans değişkeni her iki servise de bağlanır
```

### Her Uygulama İçin Procfile

```
web: uvicorn app:app --host 0.0.0.0 --port $PORT
```

### Her Uygulama İçin railway.json

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": { "builder": "NIXPACKS" },
  "deploy": {
    "startCommand": "uvicorn app:app --host 0.0.0.0 --port $PORT",
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 3
  }
}
```

### Environment Variables (her iki servis)

```bash
# Zorunlu
SECRET_KEY=<python3 -c "import secrets; print(secrets.token_hex(32))">
ENVIRONMENT=production
DATABASE_URL=${{Postgres.DATABASE_URL}}
APP_URL=https://miceapp.net          # veya https://desk.miceapp.net

# E-posta (opsiyonel)
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=
SMTP_FROM=noreply@miceapp.net

# Cloudflare R2 (opsiyonel — yoksa static/ dizinine kaydeder)
R2_ENDPOINT=https://<account_id>.r2.cloudflarestorage.com
R2_BUCKET=miceapp-files
R2_KEY_ID=
R2_SECRET=
```

### Domain Yapılandırması (Railway Custom Domain)

```
miceapp  servisi → miceapp.net   +  www.miceapp.net
micedesk servisi → desk.miceapp.net
```

DNS CNAME kayıtları Railway'in verdiği `.up.railway.app` adresine yönlendirilir.
Railway'de her servis için "Custom Domain" alanına ilgili domain girilir.
SSL sertifikası Railway tarafından otomatik Let's Encrypt ile sağlanır.

### Sıfırlama (Sadece Dev/Test)

```bash
railway variables set RESET_DB=1 --service miceapp
# Logda "Tablolar hazır" görününce:
railway variables delete RESET_DB --service miceapp
```

---

## 18. Yerel Geliştirme

```bash
# Her uygulama için ayrı venv:
cd miceapp-suite/miceapp
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app:app --reload --port 8001
# → http://localhost:8001  (miceapp)

cd ../micedesk
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app:app --reload --port 8002
# → http://localhost:8002  (micedesk)
```

Her iki uygulama aynı `.env` içindeki `DATABASE_URL`'e bağlanır.
`DATABASE_URL` boş bırakılırsa her uygulama kendi `app.db` SQLite dosyasını kullanır
(paylaşım yok — sadece lokal test için yeterli).

`.env.example` (her iki uygulama için aynı şablon):
```
SECRET_KEY=dev-secret-minimum-32-characters-long
ENVIRONMENT=development
# DATABASE_URL boşsa SQLite fallback
# DATABASE_URL=postgresql://user:pass@localhost:5432/miceapp_suite
APP_URL=http://localhost:8001
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=
SMTP_FROM=noreply@miceapp.net
R2_ENDPOINT=
R2_BUCKET=
R2_KEY_ID=
R2_SECRET=
```

---

## 19. Seed Verisi

`database.py::seed_data(db)` — her startup'ta idempotent çalışır:

```python
def seed_data(db):
    # Demo tenant
    if not db.query(Tenant).filter(Tenant.slug == "demo").first():
        tenant = Tenant(name="Demo Ajans A.Ş.", slug="demo", plan="pro")
        db.add(tenant)
        db.flush()

    # Admin kullanıcı
    if not db.query(User).filter(User.email == "admin@miceapp.net").first():
        db.add(User(
            tenant_id=tenant.id,
            email="admin@miceapp.net",
            password=hash_password("Admin123"),
            name="Sistem", surname="Yöneticisi",
            role="admin", app_access="both", active=True,
        ))

    # Sistem ayarları (feature flag'ler)
    for key, val in [
        ("module_einvoice_enabled", "0"),
        ("module_hbf_enabled", "1"),
        ("module_leaves_enabled", "1"),
        ("payment_day", "5"),         # haftalık ödeme günü (Pazartesi=1)
    ]:
        if not db.query(SystemSetting).filter(SystemSetting.key == key).first():
            db.add(SystemSetting(key=key, value=val))

    # Gider kategorileri, izin türleri, Türkiye 2026 resmi tatilleri...
    db.commit()
```

**Test kullanıcıları (seed ile oluşturulanlar):**

| Email | Şifre | Rol | Uygulama |
|-------|-------|-----|----------|
| admin@miceapp.net | Admin123 | admin | her ikisi |
| gm@miceapp.net | Gm123456 | genel_mudur | micedesk |
| muhasebe@miceapp.net | Muh12345 | kullanici | micedesk |
| koordinator@miceapp.net | Kor12345 | yonetici | miceapp |
| satis@miceapp.net | Sat12345 | mudur | miceapp |

---

## 20. Konvansiyonlar

- **Dil:** Tüm UI Türkçe. Değişken adları İngilizce, yorum/log Türkçe.
- **Para birimi:** TRY (₺) varsayılan. `vat_rate` ondalık (0.20 = %20). KDV dahil = `amount * (1 + vat_rate)`.
- **Tarih:** DB'de `Date` / `DateTime`. Gösterimde `GG.AA.YYYY` (tr-TR).
- **PK:** `String(36)` UUID, `default=_uuid`. Integer PK kullanılmaz.
- **Tenant izolasyonu:** Tüm sorgularda `WHERE tenant_id = ?`. Asla atlanmaz.
- **Dosya yolu:** `{tenant_id}/{modül}/{tarih}/{uuid}.{ext}`. `save_file()` çağrısında `tenant_id` zorunlu.
- **`payment_helpers.py` tek kaynak:** Ödeme yan etkileri tek noktadan.
- **`DROP COLUMN` asla yazılmaz** — kolon koddan çıkar, DB'de kalır.
- **Feature flag:** `SystemSetting.module_X_enabled = "1"`.
- **Çapraz FK yok:** Ortak alanlar `VARCHAR(36)` string olarak tutulur.
- **Enum'lar:** DB ENUM değil Python sabiti — migration kolaylığı.
- **JSON kolonlar:** `items_json`, `halls_json`, `contacts_json` — esnek şema.
- **SQLAlchemy lazy-load + detached instance:** Template'e geçmeden önce `db.expunge()` + gerekli ilişkileri yükle; yoksa `DetachedInstanceError`.

---

## 21. Bilinen Tuzaklar

1. **Tenant izolasyonu — dosya:** `/files/{key}` endpoint'inde `key.split("/")[0]` = `tenant_id` doğrulaması zorunludur. `super_admin` bu kontrolü atlar.

2. **Logo URL'si `None` olabilir:** `br.logo_path | file_url` filtresi `""` dönmeli. Template'de `{% if br and br.logo_path %}` guard şarttır; yoksa `<img src="">` broken icon gösterir.

3. **Branding `expunge`:** Middleware'de `db.expunge(branding)` yapılmazsa session kapandıktan sonra template'de `DetachedInstanceError` alınır.

4. **`vat_rate` formatı:** micedesk ondalık (0.20), miceapp yüzde (20.0) tutabilir. Paylaşımlı `invoices` tablosunda ondalık kullan. Koordinatör template'i `(1 + inv.vat_rate)` ile çarpıyor — micedesk kaynaklı faturalarda doğru.

5. **`company_id` tipi:** UUID string. `get_tenant_id()` her zaman `str()` döner. Integer karşılaştırması `character varying = integer` hatasına yol açar.

6. **Vendor NULL tenant_id:** miceapp vendor'ları `tenant_id` veya `company_id` olmadan oluşturabilir. micedesk `OR tenant_id IS NULL` filtresiyle görür.

7. **Railway disk geçicidir:** `static/uploads/` production'da pod restart'ta kaybolur. R2 zorunludur veya Railway Volume kullanılmalıdır.

8. **R2 presigned URL süresi:** Logo/favicon için `expires=86400` (1 gün). Hassas belgeler için `expires=3600` (1 saat).

9. **RESET_DB=1 env var:** `Base.metadata.drop_all()` çalıştırır. SADECE dev/test. Production'da asla.

10. **PostgreSQL ENUM migration:** `ALTER TYPE ... ADD VALUE` transaction dışında çalışması gerekir → `AUTOCOMMIT` bağlantı zorunlu.

11. **Mono-repo iki venv:** Her uygulamanın kendi `.venv` ve `requirements.txt` dosyası var. `pip install -r` yanlış dizinde çalıştırılmamalı.

12. **Ortak JWT secret:** Her iki uygulama aynı `SECRET_KEY` ile token imzalar. Ayrı `.env` dosyalarında aynı değer girilmelidir — yoksa miceapp tokenı micedesk'te geçersiz olur.
