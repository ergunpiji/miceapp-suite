# micedesk — Finans & İK Yönetim Sistemi

Bu repo (`prizmafinans`) **micedesk** adlı kapsamlı bir kurumsal yönetim sistemini barındırır.
Kökeni `Satın Alma` (etkinlik/RFQ yönetimi) projesi olmasına rağmen evrim sonucu artık ana odak
**finans + İK + onay akışı + Türkiye e-fatura entegrasyonu**'dur. Satın Alma ürünü ayrı bir
repo'ya (`ergunpiji/Satın Alma`) ayrılmıştır; bu repo sadece **micedesk** içindir.

> **Önemli:** Eski etkinlik yönetimi kodları (Reference, Venue, event_types, budgets RFQ kısmı)
> hâlâ duruyor — silmeyin, çünkü `Reference` model'i fatura/HBF/avans gibi finans modüllerinde
> "iş/proje" referansı olarak kullanılıyor.

---

## 1. Teknoloji yığını

- **Web:** FastAPI 0.111, Starlette 0.37, Uvicorn
- **ORM:** SQLAlchemy 2.0+ (Pydantic 2 ile)
- **Auth:** python-jose (JWT) + passlib (bcrypt). HttpOnly cookie `access_token`.
- **DB:** PostgreSQL (Railway'de canlı), yerelde fallback olarak SQLite (`satinalma.db`).
- **Şablonlama:** Jinja2 (server-side rendered HTML, SPA değil)
- **Asenkron:** `httpx` (e-fatura provider çağrıları için)
- **Excel:** `openpyxl` (rapor export)
- **Deployment:** Railway (NIXPACKS builder, GitHub'a push → otomatik deploy)

`requirements.txt` tek kaynak; ek paket eklerken oraya eklenmeli.

---

## 2. Klasör yapısı (kök)

```
app.py                    # Ana FastAPI girişi — tüm router'ları register eder
auth.py                   # JWT + role/permission sistemi
database.py               # Engine, SessionLocal, init_db, _migrate, seed_data
models.py                 # 40+ SQLAlchemy modeli (tek dosya)
templates_config.py       # Jinja2 ortak filtreler + company cache
email_helper.py           # SMTP wrapper (config yoksa sessizce log düşer)
payment_helpers.py        # apply_invoice_payment, apply_cheque_payment vb.
migrate_invoices.py       # Tek seferlik veri taşıma scriptleri
migrate_vendors.py
migrate_references.py

routers/                  # ~40 modüler router (her biri APIRouter)
templates/                # Jinja2 şablonları (modül başına bir alt klasör)
static/                   # CSS, JS, uploads/, logo
packages/prizma-einvoice/ # İç Python paketi (e-fatura modülü)
agents/                   # Ayrı FastAPI alt-uygulamaları (operasyon, finans, ik)

Procfile                  # Railway: web: uvicorn app:app --host 0.0.0.0 --port $PORT
railway.json              # NIXPACKS, ON_FAILURE restart
.env / .env.example       # Ortam değişkenleri (.env gitignore'lı)
```

---

## 3. Domain modülleri (router prefix → işlev)

### Finans çekirdeği
| Prefix | Sorumluluk |
|---|---|
| `/invoices` | Gelen/kesilen/komisyon/iade fatura yönetimi, ödeme, e-fatura |
| `/cheques` | Çek (verilen/alınan) — beklemede, tahsil_edildi, iade, karşılıksız, iptal |
| `/cash` | Kasa giriş/çıkış, günlük bakiye, gün sonu kapatma (`CashDayClose`) |
| `/bank-accounts` | Banka hesabı + hareketleri |
| `/credit-cards` | Kart, ekstre, işlem mutabakatı |
| `/vendors` | Tedarikçiler (tax_no, IBAN, vade, ön ödemeler) |
| `/customers` | Müşteri master |
| `/payment-instructions` | GM onayı ile oluşan ödeme talimatları (operatör execute eder) |
| `/payments` | Haftalık GM ödeme listesi (invoice/cheque/payroll/cc_statement birleşik) |

### İK / personel
| Prefix | Sorumluluk |
|---|---|
| `/employees` | Personel master, User account ile bağlanabilir (`Employee.user_id`) |
| `/advances` | Maaş avansı (`maas`) ve iş avansı (`is`) — talep/onay/kapatma |
| `/hbf` | Harcama Bildirim Formu — çoklu ref, dosya ek, çift onay |
| `/leaves` | İzin: yıllık/hastalık/mazeret/ücretsiz/doğum günü, takvim, bakiye |
| `/admin/leaves` | Admin izin türü/bakiye yönetimi |

### Bütçe & raporlama
| Prefix | Sorumluluk |
|---|---|
| `/fund-pools` | Fon havuzu (KDV dahil bütçe) — müşteri başına |
| `/budgets` | Yıllık bütçe satırları + sabit giderler |
| `/general-expenses` | İşletme giderleri (hiyerarşik kategori ağacı) |
| `/reports` | Tüm finans raporları + Excel export |
| `/tax-reports`, `/edefter` | Vergi/E-defter export |

### Yönetim & sistem
| Prefix | Sorumluluk |
|---|---|
| `/auth` | Login/logout |
| `/dashboard` | Bekleyen işlerin badge sayıları |
| `/profile` | Kullanıcı kendi profilini düzenler |
| `/users` | User CRUD (admin) |
| `/admin/roles`, `/admin/permissions` | Rol & izin matrisi |
| `/admin/modules` | Modül feature flag toggle |
| `/admin/company-profile` | Firma bilgileri (logo, IBAN, vergi) |
| `/notifications`, `/settings`, `/teams`, `/exchange-rates`, `/email-templates` | Yardımcı |

### Satın Alma mirası (silinmedi, kullanımda)
`/references`, `/venues`, `/event-types`, `/requests`, `/services` — etkinlik/proje referansı
yapısı, finans modülleri tarafından "iş/proje" linki olarak kullanılıyor.

> Yeni modül eklerken: `routers/yeni_modul.py` oluştur → `app.py` içinde `app.include_router(yeni_modul.router)` ile register et → `templates/yeni_modul/` altında Jinja şablonlarını koy.

---

## 4. Modeller (özet — detay için `models.py`)

40+ SQLAlchemy class tek dosyada, mantıksal gruplar:

**Auth/erişim:** `User`, `RolePermission`, `SystemSetting`
**Müşteri/tedarikçi:** `Customer`, `FinancialVendor` (e-fatura cache alanları içerir)
**Kasa/banka/kart:** `CashBook`, `CashDayClose`, `CashEntry`, `BankAccount`, `BankMovement`, `CreditCard`, `CreditCardStatement`, `CreditCardTxn`
**Çek:** `Cheque`
**Fatura:** `Reference` (proje/iş ref'i), `Invoice`, `InvoicePayment`, `VendorPrepayment`
**Personel:** `Employee`, `SalaryPayment`, `EmployeeBenefit`, `EmployeeAdvance`
**İzin:** `LeaveType`, `LeaveBalance`, `LeaveRequest`, `PublicHoliday`
**Bütçe/fon:** `AnnualBudget`, `BudgetLine`, `FixedExpense`, `FundPool`, `FundTransfer`
**Gider:** `GeneralExpenseCategory`, `GeneralExpense`
**Onay/ödeme:** `HBF`, `PaymentInstruction`, `ManualPaymentLine`, `PayrollDecision`

**Sabitler/enum'lar (string olarak, DB enum değil — migration kolaylığı için):**
```python
ROLE_ORDER       = ["kullanici", "mudur", "genel_mudur", "admin", "super_admin"]
INVOICE_TYPES    = ["gelen", "kesilen", "komisyon", "iade_gelen", "iade_kesilen"]
PAYMENT_METHODS  = ["nakit", "banka", "kredi_karti", "cek", "acik_hesap"]
VAT_RATES        = [0.0, 0.01, 0.08, 0.10, 0.18, 0.20]
```

---

## 5. Rol & izin sistemi (`auth.py`)

**Hiyerarşi (düşükten yükseğe):**
```
kullanici < mudur < genel_mudur < admin < super_admin
```

**User'da hybrid property'ler:**
- `is_admin` → role ∈ {admin, super_admin}
- `is_approver` → role ∈ {genel_mudur, admin, super_admin} ← **Genel Müdür rolünün bayrağı**

> Yani admin **rolü** olan biri otomatik onay yetkilidir. "Sadece müdür" kullanıcı `is_approver=False`.

**İzinler iki katmanlı:**
1. `auth.py::DEFAULT_PERMISSIONS` — kod içinde varsayılan eşikler (örn. `payment_list_approve=genel_mudur`)
2. `RolePermission` tablosu — admin UI'dan rol başına override edilebilir

`check_permission(user, perm)` önce `RolePermission`'a bakar, kayıt yoksa `DEFAULT_PERMISSIONS`'a düşer.

**Önemli izin kodları:**
- `advance_create` / `advance_approve_first` (mudur) / `advance_approve_final` (genel_mudur)
- `hbf_create` / `hbf_approve_first` / `hbf_approve_final`
- `payment_list_prepare` (kullanici) / `payment_list_approve` (genel_mudur — haftalık ödeme onayı)
- `invoice_delete`, `customer_manage`, `employee_manage`, `vendor_manage`
- `report_view` / `report_view_financial` / `report_view_all`
- `module_config`, `user_manage`, `role_permission_manage`, `super_admin_panel`

**Takım yapısı:** `User.manager_id` (FK to User.id) raporlama zincirini tanımlar. Müdür kendi ekibinin
talep/avans/HBF/izinlerini görür (app.py middleware bu sayıları hesaplar).

---

## 6. Onay akışları (iki kademeli)

`Avans`, `HBF`, `Leave` aynı pattern'i izler:
```
talep            (kullanıcı oluşturur)
   ↓
mudur_onayladi   (manager_approved_by, manager_approved_at)
   ↓
onaylandi        (approved_by_id, approved_at — Genel Müdür)
   ↓
odendi / kapandi
```

`Reddedildi` ve `iptal` her aşamada mümkün, `rejection_note` zorunlu.

**GM haftalık ödeme listesi (farklı pattern):**
`Invoice`, `Cheque`, `CreditCardStatement`, `PayrollDecision`, `ManualPaymentLine` modellerinin
hepsinde tek tip GM karar alanları:
- `gm_decision` (onay/erteleme/red), `gm_decision_at`, `gm_decision_by`
- `gm_postpone_until`, `gm_method_override`, `gm_approved_amount`, `gm_decision_note`

GM "onayla" derse → `PaymentInstruction` oluşur → operatör `/payment-instructions/{id}/execute`
ile gerçek ödemeyi posta eder. `payment_helpers.py` tek kaynak — manuel endpoint ve instruction
execute aynı fonksiyonu çağırır.

---

## 7. Database & migration yaklaşımı

**Alembic kullanılmıyor.** `database.py::_migrate()` startup'ta çalışır:
- Idempotent raw SQL: `ALTER TABLE … ADD COLUMN IF NOT EXISTS …`
- PostgreSQL enum eklemeleri AUTOCOMMIT ile (transaction dışı)
- SQLite + PostgreSQL aynı listede çalışır

**Yeni kolon eklerken sıra:**
1. `models.py`'da Column tanımına ekle
2. `database.py::_migrate()`'in `migrations` listesine `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...` satırı ekle
3. `Base.metadata.create_all()` zaten yeni tablolar için yeterli — sadece `ALTER TABLE` mevcut tablolar için

**Asla `DROP COLUMN` yazmayın** — eski instance'ların bozulmaması için. Eğer kolon kullanım dışıysa
sadece kod kullanımını kaldır, kolon DB'de kalsın.

**Seed (`seed_data` + `_seed_extra_categories` + `_seed_leave_types` + `_seed_public_holidays_2026`):**
- Boş DB'de admin user (`admin@miceapp.net / Admin123`) ve "Ana Kasa" oluşur
- Gider kategorileri, izin türleri, 2026 resmi tatilleri seed edilir
- Hepsi idempotent — tekrar çalıştırınca duplicate üretmez

**Reference no formatı:**
- `Reference.ref_no` → `TIP-MUS-YYMM-NNN` (örn. `TOP-ABC-2601-001`)
- `HBF.hbf_no` → `HBF-YYMM-NNN`
- Üretim: `database.py::generate_ref_no()` ve `generate_hbf_no()`

**`RESET_DB=1` env var:** startup'ta `Base.metadata.drop_all()` çalıştırır → **DİKKAT, veriyi siler**.
Sadece sıfırlama gerekiyorsa kullanılmalı, asla production'da değil.

---

## 8. `agents/` alt uygulamaları (3 ayrı FastAPI app)

`agents/operasyon`, `agents/finans`, `agents/insan_kaynaklari` — her biri **kendi DB'si, kendi
modelleri, kendi router'ları olan ayrı FastAPI uygulamaları**. Ana app'le aynı process'te
çalışmıyorlar; mount edilmiyorlar; ayrı port/host ile deploy edilebilirler.

> Ana micedesk app'i kanonik. Agent'lar ileride microservice'leşmek üzere ayrılmış prototip
> niteliğinde. Yeni özellik geliştirirken **ana app'e** ekle, agent'a değil — aksi belirtilmedikçe.

`agents/operasyon` özellikle Satın Alma'in eski etkinlik kodunun daha derin halini içeriyor; bu kod
artık `ergunpiji/Satın Alma` repo'sunda da var ve ileride buradan tamamen ayrılacak.

---

## 9. `prizma-einvoice` paketi

`packages/prizma-einvoice/src/prizma_einvoice/` — Türkiye e-fatura entegrasyonu için iç paket.

**Entegrasyon (`app.py`):**
1. Pip editable install yerine `sys.path` enjeksiyonu — paket development hızını için
2. `EInvoiceModule(host_base, engine, config, get_db_dependency, ...)` ile init
3. `module.install(app)` ile `/einvoice/*` route'larını mount eder
4. `Invoice` tablosuna ek kolonlar (`einvoice_status`, `einvoice_uuid`, `einvoice_pdf_url`, ...) database.py migration ile

**Provider seçimi:** Şu an `{"provider": "fake"}` (mock). Gerçek provider eklerken
`packages/prizma-einvoice/src/prizma_einvoice/providers/` altında yeni implementasyon ekle,
`config["provider"]` değerini değiştir.

**Customer/Vendor e-fatura cache'i:**
`is_efatura_user`, `efatura_alias`, `efatura_checked_at` — provider'dan gelen mükellef sorgusu
sonucu. Stale ise re-check edilir.

**Module feature flag:** `SystemSetting.module_einvoice_enabled` — admin UI'dan toggle.

---

## 10. Deployment (Railway)

- **Repo:** `git@github.com:ergunpiji/prizmafinans.git`
- **Live URL:** https://prizmafinans-production.up.railway.app
- **Postgres:** Railway-managed, public proxy URL `mainline.proxy.rlwy.net:45486`
  (internal: `postgres.railway.internal:5432` — sadece Railway içinden erişilebilir)
- **Build:** NIXPACKS (Procfile auto-detect)
- **Auto-deploy:** GitHub `main` branch'e push → otomatik build & deploy (~1-2 dk)

**Railway env vars (production'da set edilmiş olmalı):**
- `DATABASE_URL` (Railway Postgres referans değişkeni: `${{Postgres.DATABASE_URL}}`)
- `SECRET_KEY` (32+ karakter random)
- `ENVIRONMENT=production` (cookie secure=True olur)
- `SMTP_*` — gerçek SMTP varsa
- `APP_URL=https://prizmafinans-production.up.railway.app`

---

## 11. Yerel geliştirme

```bash
cd ~/Desktop/CLAUDE/Prizma\ Finans
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # değerleri doldur (zaten yapılmışsa atla)
uvicorn app:app --reload --port 8000
# http://localhost:8000  →  admin@miceapp.net / Admin123
```

**`.env` örneği:**
```
SECRET_KEY=<32+ karakter random — `python3 -c "import secrets; print(secrets.token_hex(32))"`>
ENVIRONMENT=development
DATABASE_URL=postgresql://...   # boş bırakılırsa satinalma.db (SQLite) kullanılır
APP_URL=http://localhost:8000
```

---

## 12. Konvansiyonlar / dikkat edilecekler

- **Tüm UI Türkçe**, kod yorumları da Türkçe — devam et.
- **Para birimi varsayılan TRY** (`₺`), tarih formatı `tr-TR` (GG.AA.YYYY).
- **JSON kolonlar** esnek veri için kullanılıyor — `items_json`, `refs_json`, `bank_accounts_json`,
  `expense_items_json`. Şema değiştirirken validate eden bir helper yaz, frontend'e güven.
- **`SystemSetting` key-value tablosu** runtime config için — feature flag, firma bilgisi, haftalık
  ödeme günü vs. Cache'i `templates_config.py::invalidate_company_cache()` invalidate eder.
- **Middleware `nav_counts_middleware`** her request'te bekleyen item sayılarını hesaplar
  (`request.state.nav_counts`) — base.html sidebar'ında kullanılır. Ağır query atmayın oraya.
- **`payment_helpers.py` tek kaynak** — yeni ödeme yolu eklerken mevcut fonksiyonları kullan,
  yan etkileri (`CashEntry`, `BankMovement`, `CreditCardTxn`, `Cheque`) tutarlı tut.
- **Onay akışları üç durumlu state machine** (talep → mudur_onayladi → onaylandi). Yeni onay
  modülü eklerken aynı pattern'i izle.
- **Static `uploads/`** — dosya yüklemeleri (HBF eki, çek görseli) buraya gider. Production'da
  Railway disk'i geçici, S3'e taşınmadan büyük dosya saklamayın.
- **Excel export** `openpyxl` ile, `excel_export/` modülünde — yeni rapor eklerken oradaki
  pattern'i izle (StreamingResponse + `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`).
- **`reference/` klasörü gitignore'lı** — tarihsel HTML referansı (eski `satinalma.html`), commit edilmez.

---

## 13. Bilinen modüller arası ilişkiler

```
Reference (proje)
  ├─→ Invoice.ref_id          (proje faturası)
  ├─→ HBF.ref_id / refs_json  (proje gideri formu)
  ├─→ EmployeeAdvance.ref_id  (proje avansı)
  ├─→ GeneralExpense.ref_id   (proje gideri)
  ├─→ FundPool.customer_id   (proje fonu — dolaylı, customer üzerinden)
  └─→ ManualPaymentLine.ref_id

Invoice
  ├─→ InvoicePayment (n)        (kısmi/tam ödeme)
  ├─→ Cheque (verilen)          (çekle ödeme)
  ├─→ CreditCardTxn             (kartla ödeme)
  └─→ einvoice_* alanları       (e-fatura state)

PaymentInstruction
  ├─ source_type: invoice | cheque | cc_statement | payroll | manual
  └─ executed_by: operatör — payment_helpers ile gerçek ödemeyi posta eder

Employee
  ├─→ User.manager_id           (raporlama zinciri)
  ├─→ SalaryPayment             (maaş)
  ├─→ EmployeeAdvance           (avans)
  ├─→ EmployeeBenefit           (yan haklar)
  ├─→ LeaveBalance + LeaveRequest
  └─→ HBF.employee_id           (kendi gider formu)
```

---

## 14. Hızlı navigasyon

- **Login akışı:** [auth.py](auth.py) → `routers/auth.py` → `templates/login.html`
- **Yeni router pattern:** [routers/invoices.py](routers/invoices.py) (tipik, hem GET liste hem POST create)
- **GM onay akışı pattern:** [routers/payments.py](routers/payments.py)
- **Onay state machine:** [routers/advances.py](routers/advances.py) veya [routers/hbf.py](routers/hbf.py)
- **Excel rapor:** `routers/reports.py` + `excel_export/`
- **E-fatura:** `packages/prizma-einvoice/src/prizma_einvoice/router.py`
- **Migration ekleme:** [database.py](database.py) `_migrate()` fonksiyonu

---

## 15. Eskiden ne vardı, ne kaldı

`reference/satinalma.html` — orijinal single-page HTML referans uygulaması (~5000 satır). Bu Python
sürümünün ilk taslağı için kullanıldı, **artık güncel değil**. Repo'da bulunsa bile gitignore'lı.
Yeni özellik için referans almayın — kod kendi başına kanonik.
