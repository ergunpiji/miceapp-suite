# E-dem — Etkinlik Talep Yönetim Sistemi
## Python Yeniden Yazım Kılavuzu (Claude Code için)

Bu dosya, mevcut single-page HTML uygulamasının Python tabanlı bir web uygulamasına
dönüştürülmesi için kapsamlı teknik spesifikasyon içerir.
Referans uygulama: `reference/edem.html` (~5000 satır, sıfır dış bağımlılık, localStorage tabanlı)

---

## 1. Projeye Genel Bakış

E-dem, etkinlik organizasyon şirketleri için tasarlanmış bir **teklif & bütçe yönetim sistemidir**.
Üç farklı rol arasındaki iş akışını yönetir:

- **Proje Yöneticisi**: Müşteri adına etkinlik talebi oluşturur; tedarikçi seçer; hazırlanan bütçeyi görüntüler.
- **E-dem (Satın Alma)**: Gelen talepleri alır; tedarikçilere RFQ e-postası gönderir; bütçe hazırlar.
- **Admin**: Kullanıcı, tedarikçi, hizmet kataloğu ve müşteri yönetimini yapar.

---

## 2. Önerilen Teknoloji Yığını

```
backend/
  app.py              # FastAPI veya Flask ana giriş noktası
  models.py           # SQLAlchemy modelleri
  database.py         # DB bağlantısı (SQLite başlangıç için yeterli)
  routers/
    auth.py
    users.py
    venues.py
    requests.py
    budgets.py
    services.py
    customers.py
  static/
    (CSS, JS)
  templates/
    (Jinja2 HTML şablonları) — veya tamamen API + SPA

requirements.txt
CLAUDE.md             # Bu dosya
reference/
  edem.html           # Orijinal çalışan referans uygulama
```

**Önerilen paketler:**
- `fastapi` + `uvicorn` — REST API
- `sqlalchemy` — ORM
- `alembic` — DB migrations
- `python-jose` + `passlib` — JWT auth + şifre hash
- `pydantic` v2 — veri validasyonu
- ya da sadece `flask` + `flask-login` + `flask-sqlalchemy` daha basit yaklaşım için

---

## 3. Veri Modelleri

Mevcut uygulama localStorage'da JSON olarak saklıyor. Python'da SQLite/PostgreSQL tablosuna dönüşecek.

### 3.1 User (Kullanıcı)
```python
class User:
    id: str          # uid() → Python: str(uuid4())
    email: str       # unique
    password: str    # hash'lenmiş olmalı (bcrypt)
    role: str        # 'admin' | 'project_manager' | 'e_dem'
    name: str
    surname: str
    title: str
    phone: str
    active: bool     # False = giriş yapamaz
    created_at: datetime

# Varsayılan kullanıcılar (seed):
# admin@edem.com / Admin123 / role=admin
# manager@edem.com / Manager123 / role=project_manager
# edem@edem.com / Edem123 / role=e_dem
```

### 3.2 Venue (Tedarikçi / Mekan)
```python
class Venue:
    id: str
    name: str
    city: str              # birincil şehir
    cities: list[str]      # birden fazla şehir (tag tabanlı)
    supplier_type: str     # bkz. SUPPLIER_TYPES
    address: str
    stars: int | None      # sadece otel için (1-5)
    total_rooms: int       # sadece otel için
    website: str
    notes: str
    halls: list[Hall]      # salon listesi (sadece otel/etkinlik mekanı için)
    contacts: list[Contact]  # EN AZ 1 kişi zorunlu
    active: bool
    created_at: datetime

class Hall:
    name: str
    capacity: int
    area: float   # m²

class Contact:
    name: str
    title: str
    email: str
    phone: str

# SUPPLIER_TYPES sabiti:
SUPPLIER_TYPES = [
    {'value': 'otel',      'label': 'Otel'},
    {'value': 'etkinlik',  'label': 'Etkinlik Mekanı'},
    {'value': 'restaurant','label': 'Restoran'},
    {'value': 'teknik',    'label': 'Teknik Ekipman'},
    {'value': 'dekor',     'label': 'Dekor / Süsleme'},
    {'value': 'transfer',  'label': 'Transfer / Ulaşım'},
    {'value': 'tasarim',   'label': 'Tasarım & Baskı'},
    {'value': 'susleme',   'label': 'Süsleme'},
    {'value': 'ik',        'label': 'İnsan Kaynakları'},
    {'value': 'diger',     'label': 'Diğer'},
]
```

### 3.3 Customer (Müşteri)
```python
class Customer:
    id: str
    name: str         # firma/müşteri adı
    code: str         # 3 harfli kod (küçük harf) — ref no için kullanılır
    sector: str
    address: str
    tax_office: str
    tax_number: str
    email: str
    phone: str
    notes: str
    created_at: datetime
```

### 3.4 Request (Talep / Referans)
```python
class Request:
    id: str
    request_no: str     # Format: "TIP-MUS-YYMM-001" bkz. generateRefNo
    client_name: str
    customer_id: str | None   # Customer.id ile bağlantı
    event_name: str
    event_type: str     # 'toplanti' | 'konferans' | 'gala' | 'egitim' | 'lansman' | 'diger'
    city: str           # virgülle ayrılmış şehirler (eski compat)
    cities: list[str]   # tercih edilen şehirler (tag tabanlı)
    attendee_count: int
    check_in: date
    check_out: date
    accom_check_in: date | None    # konaklama giriş (farklı olabilir)
    accom_check_out: date | None   # konaklama çıkış
    status: str         # bkz. REQUEST_STATUSES
    items: dict         # section_key → list[RequestItem]
    description: str
    notes: str
    preferred_venues: list[str]   # Venue.id listesi
    selected_venues: list[str]    # E-dem tarafından seçilen
    created_by: str     # User.id
    created_at: datetime
    updated_at: datetime

# REQUEST_STATUSES:
# 'draft'            → Taslak (PM kaydetti ama göndermedi)
# 'pending'          → Beklemede (PM gönderdi, E-dem almadı)
# 'in_progress'      → İşlemde (E-dem üstlendi)
# 'venues_contacted' → Mekanlarla iletişime geçildi
# 'budget_ready'     → Bütçe hazır
# 'completed'        → Tamamlandı
# 'cancelled'        → İptal edildi

class RequestItem:
    id: str
    description: str
    unit: str
    qty: float
    notes: str
    detail: str
    # Konaklama için: check_in/check_out yok (accom date block'tan gelir)
    # Diğer servisler için:
    date_from: date | None
    date_to: date | None
    # Toplantı için:
    daily_attendees: list[DailyAttendee] | None
    seating_layout: str | None

class DailyAttendee:
    date: date
    qty: int
    seating_layout: str   # 'tiyatro' | 'sinif' | 'u-seklinde' | 'toplanti' | 'adatr' | 'kokteyl' | 'gala'
```

**Referans No Formatı:**
```python
def generate_ref_no(event_type: str, customer_code: str, check_in: date) -> str:
    # event_type map:
    TYPE_CODES = {
        'toplanti': 'TOP', 'konferans': 'KON', 'gala': 'GAL',
        'egitim': 'EGT', 'lansman': 'LAN', 'diger': 'ETK'
    }
    tip = TYPE_CODES.get(event_type, 'ETK')
    mus = (customer_code or 'xxx').upper()[:3]
    yymm = check_in.strftime('%y%m')
    # Sıradaki numara: o yıl/ay içindeki REQ sayısı + 1
    seq = count_existing_refs_for_month(yymm) + 1
    return f"{tip}-{mus}-{yymm}-{seq:03d}"
    # Örnek: TOP-ABC-2504-001
```

### 3.5 Budget (Bütçe)
```python
class Budget:
    id: str
    request_id: str      # Request.id
    venue_name: str      # Mekan adı (serbest metin)
    rows: list[BudgetRow]
    created_by: str      # User.id (E-dem)
    created_at: datetime
    updated_at: datetime

class BudgetRow:
    id: str
    section: str          # kategori: 'accommodation' | 'meeting' | 'fb' | ...
    description: str
    unit: str
    qty: float
    nights: int           # konaklama için gece sayısı
    cost_price: float     # tedarikçi fiyatı (KDV hariç)
    sale_price: float     # müşteriye satış fiyatı (KDV hariç)
    vat_rate: float       # KDV oranı (0.20 = %20)
    notes: str
    is_service_fee: bool  # Hizmet Bedeli satırı (sadece satış, maliyet yok)

# Hesaplamalar (frontend'de de var, backend'de de doğrulanmalı):
# cost_total = cost_price * qty * nights (nights=1 if not accommodation)
# sale_total = sale_price * qty * nights
# cost_vat = cost_total * vat_rate
# sale_vat = sale_total * vat_rate
# grand_cost = sum(cost_total + cost_vat)
# grand_sale = sum(sale_total + sale_vat)
```

### 3.6 Service (Hizmet Kataloğu)
```python
class Service:
    id: str
    category: str    # 'accommodation' | 'meeting' | 'fb' | 'teknik' | 'dekor' | 'transfer' | 'tasarim' | 'other' | <custom_cat_id>
    name: str
    unit: str
    active: bool

# Varsayılan servisler (seed):
# Konaklama: Standart Oda SGL/DBL, Superior, Suite, Ekstra Yatak
# Toplantı: Salon Kirası, Proyeksiyon, Ses, Simultane, LED, Kayıt
# F&B: Kahvaltı, Öğle, Akşam, Gala, Coffee Break, Kokteyl, Set Menu
# Diğer: Transfer, Aktivite, Dekorasyon, Fotoğraf, Hostess
```

### 3.7 CustomCategory (Özel Kategori)
```python
class CustomCategory:
    id: str
    name: str
    icon: str       # emoji
    bg_color: str   # hex renk (#e0f2fe)
    txt_color: str  # hex renk (#0c4a6e)
```

---

## 4. Kullanıcı Rolleri ve İzinler

| Sayfa / İşlev               | Admin | Proje Yöneticisi | E-dem |
|-----------------------------|-------|-----------------|-------|
| Dashboard                   | ✅    | ✅              | ✅    |
| Yeni Talep Oluştur          | ❌    | ✅              | ❌    |
| Tüm Referanslar             | ✅    | ❌              | ❌    |
| Referanslarım               | ❌    | ✅              | ❌    |
| Gelen Referanslar           | ❌    | ❌              | ✅    |
| Bütçe Yönetimi (düzenle)    | ❌    | ❌              | ✅    |
| Bütçe Görüntüle (sadece)    | ❌    | ✅              | ❌    |
| Tedarikçi Havuzu            | ✅    | ✅ (görüntüle)  | ✅    |
| Tedarikçi Ekle/Düzenle      | ✅    | ❌              | ✅    |
| Hizmet Kataloğu             | ✅    | ❌              | ❌    |
| Müşteri Yönetimi            | ✅    | ❌              | ❌    |
| Kullanıcı Yönetimi          | ✅    | ❌              | ❌    |

---

## 5. Navigasyon / Sayfa Yapısı

```
Sidebar navigasyonu (role'e göre filtrelenir):

ADMIN:
  - Dashboard
  - Referanslar > Tüm Referanslar
  - Tedarikçi Havuzu
  - Hizmet Kataloğu
  - Müşteri Yönetimi
  - Kullanıcı Yönetimi

PROJECT_MANAGER:
  - Dashboard
  - Yeni Talep Oluştur
  - Referanslar > Referanslarım
  - Tedarikçi Havuzu (salt görüntüleme)
  - Bütçeler

E_DEM:
  - Dashboard
  - Gelen Referanslar
  - Bütçe Yönetimi
  - Tedarikçi Havuzu
```

---

## 6. İş Akışı (Workflow)

```
1. PM → Yeni Talep Oluştur
        - Müşteri seç (veya serbest metin)
        - Etkinlik bilgileri (ad, tip, şehir(ler), tarih, katılımcı)
        - Hizmet kalemleri tab tab (Otel/Mekan, Teknik, Dekor, Transfer, Tasarım, Diğer)
        - Her tab'da tedarikçi seçimi (checkbox, tag tabanlı)
        - "Taslak Kaydet" veya "E-dem'e Gönder"

2. E-dem ← Gelen Referanslar sayfasında "pending" durumdaki talepler
        - Talep detayını görüntüle
        - "İşleme Al" → status: in_progress
        - Seçilen tedarikçilere RFQ e-postası gönder (mailto: ile)
        - Bütçe oluştur → Bütçe Editörü açılır

3. E-dem → Bütçe Editörü
        - Mekan adı gir
        - Satırları kategoriye göre grupla
        - Her satır: açıklama, birim, miktar, gece, maliyet fiyatı, satış fiyatı, KDV
        - "Katalogdan Ekle" butonu ile hizmet kataloğundan satır ekle
        - Ara toplamlar (section bazlı) + genel toplam
        - Hizmet Bedeli satırı (sadece satış, maliyet yok)
        - Kaydet

4. PM ← Bütçeler sayfasında hazırlanan bütçeyi görüntüler
        - salt görüntüleme
        - İlerde: PDF export, müşteriye gönder
```

---

## 7. RFQ E-posta Sistemi

Tedarikçilere gönderilecek teklif talebi e-postası:

- Her tedarikçi için ayrı e-posta kartı oluşturulur
- Alıcı seçimi: tedarikçi kontakları checkbox listesi (hepsi başta seçili)
- Konu formatı: `{etkinlik_adı} - {tarih} - {referans_no}` (tire ile ayrılır)
- E-posta içeriği (hem zengin HTML hem düz metin):
  - Etkinlik özeti tablosu (müşteri, tarih, katılımcı, şehir)
  - Konaklama detayları (SADECE konaklama kalemi varsa göster)
  - Talep edilen hizmet kalemleri
  - Teklif son tarihi (bugün + 3 gün)
- Açılış yöntemi: `mailto:` linki ile mail uygulaması açılır
- Zengin metin kopyala: HTML içeriği clipboard'a kopyalanır (Outlook/Gmail paste)

**E-posta renk şeması:**
```python
CS = {
    'main':  'background:#1a3a5c;color:#ffffff;font-weight:bold;',   # ana başlık (lacivert)
    'sec':   'background:#1e5f8c;color:#ffffff;font-weight:bold;',   # alt başlık
    'lbl':   'background:#f0f4f8;color:#1e293b;font-weight:600;',    # etiket hücresi
    'val':   'background:#ffffff;color:#1e293b;',                     # değer hücresi
    'night': 'background:#f8fafc;color:#374151;',                    # gece satırı
    'bullet':'background:#ffffff;color:#1e293b;',                    # madde listesi
}
```

---

## 8. Bütçe Editörü Detayları

```
Bütçe editörü (E-dem kullanır):

Üst kısım:
  - Mekan adı (serbest metin input)
  - Referans no göster (sadece görüntüleme)

Satır tablosu sütunları:
  Konaklama tablosu:
    Hizmet | Birim | Miktar | Gece | Maliyet (KDV hariç) | Satış (KDV hariç) | KDV % | Sil

  Diğer tablolar:
    Hizmet | Birim | Miktar | Maliyet (KDV hariç) | Satış (KDV hariç) | KDV % | Sil

Her kategorinin altında:
  - "Katalogdan Ekle" butonu → hizmet listesinden seç
  - Yeni satır ekle butonu
  - Ara toplam satırı (section subtotal)

En altta:
  - Hizmet Bedeli (servis fee) satırı — sadece satış fiyatı, maliyet yok
  - KDV dahil genel toplam (maliyet + satış ayrı ayrı)

Konaklama satırında "Gece" sütunu:
  - Düzenlenebilir (readonly değil!)
  - calcNights(checkIn, checkOut) ile otomatik doldurulur ama değiştirilebilir

KDV oranları: %0, %1, %8, %10, %18, %20
```

---

## 9. Talep Formu Detayları

### 9.1 Genel Bilgiler
- Müşteri / Firma: autocomplete dropdown (DB'den) + serbest metin fallback
- Etkinlik Adı
- Şehir(ler): tag tabanlı çoklu seçim — 81 Türkiye ili
- Etkinlik Tipi: toplanti | konferans | gala | egitim | lansman | diger
- Katılımcı Sayısı
- Etkinlik Tarihleri: başlangıç / bitiş (aynı gün olabilir)
- Açıklama, Notlar

### 9.2 Hizmet Sekmeleri (REQUEST_TABS)
```python
REQUEST_TABS = [
    {
        'id': 'venue',
        'label': '🏨 Otel / Mekan',
        'supplier_types': ['otel', 'etkinlik'],
        'sections': ['accommodation', 'meeting', 'fb']
    },
    {
        'id': 'teknik',
        'label': '🔧 Teknik Ekipman',
        'supplier_types': ['teknik'],
        'sections': ['teknik']
    },
    {
        'id': 'dekor',
        'label': '🎨 Dekor',
        'supplier_types': ['dekor'],
        'sections': ['dekor']
    },
    {
        'id': 'transfer',
        'label': '🚌 Ulaşım & Transferler',
        'supplier_types': ['transfer'],
        'sections': ['transfer']
    },
    {
        'id': 'tasarim',
        'label': '🖨 Tasarım & Basılı',
        'supplier_types': ['tasarim'],
        'sections': ['tasarim']
    },
    {
        'id': 'diger',
        'label': '📦 Diğer Servisler',
        'supplier_types': ['restaurant', 'susleme', 'ik', 'diger'],
        'sections': ['other']
    },
    # + Admin tarafından oluşturulan özel kategoriler (CustomCategory) burada eklenir
]
```

Her tab'da:
- Tedarikçi seçme bloğu (standart tablar için): tag input + dropdown (şehre göre filtreli)
- Hizmet kalemleri tablosu (o sekmeye ait section'lar)
- "Katalogdan Ekle" + "Boş Satır Ekle"

### 9.3 Konaklama Özel Durumu
- Konaklama sekmeye dahil ama zorunlu değil
- Ayrı giriş/çıkış tarihi bloğu var (etkinlik tarihinden farklı olabilir)
- RFQ e-postasında sadece konaklama kalemi varsa "KONAKLAMA DETAYLARI" bölümü gösterilir
- `calcNights(check_in, check_out)`: aynı gün → 0 gece döner

### 9.4 Toplantı Hizmetleri Günlük Detay
- Toplantı kaleminde "katılımcı sayısı" günlük bazda girilebilir
- check_in → check_out arası her gün için bir satır oluşur
- Her gün için: tarih, katılımcı, oturma düzeni

### 9.5 Oturma Düzeni Seçenekleri
```python
SEATING_LAYOUTS = [
    {'value': 'tiyatro',   'label': 'Tiyatro Düzeni'},
    {'value': 'sinif',     'label': 'Sınıf Düzeni'},
    {'value': 'u-seklinde','label': 'U Şeklinde'},
    {'value': 'toplanti',  'label': 'Toplantı Düzeni'},
    {'value': 'adatr',     'label': 'Ada / Roundtable'},
    {'value': 'kokteyl',   'label': 'Kokteyl'},
    {'value': 'gala',      'label': 'Gala Oturma'},
]
```

---

## 10. Hizmet Kataloğu (Admin)

- Sekme tabanlı görünüm (her kategori bir sekme)
- Admin özel kategori ekleyebilir (isim, ikon emoji, arka plan rengi, metin rengi)
- Her kategoride: hizmet adı, birim, aktif/pasif toggle, düzenle/sil
- Özel kategoriler talep formunda da sekmeli olarak görünür
- Renk seçimi: color picker ile bg + txt renk seçimi

---

## 11. 81 Türkiye İli

```python
TR_CITIES = [
    "Adana","Adıyaman","Afyonkarahisar","Ağrı","Amasya","Ankara","Antalya","Artvin",
    "Aydın","Balıkesir","Bilecik","Bingöl","Bitlis","Bolu","Burdur","Bursa","Çanakkale",
    "Çankırı","Çorum","Denizli","Diyarbakır","Edirne","Elazığ","Erzincan","Erzurum",
    "Eskişehir","Gaziantep","Giresun","Gümüşhane","Hakkari","Hatay","Isparta","Mersin",
    "İstanbul","İzmir","Kars","Kastamonu","Kayseri","Kırklareli","Kırşehir","Kocaeli",
    "Konya","Kütahya","Malatya","Manisa","Kahramanmaraş","Mardin","Muğla","Muş",
    "Nevşehir","Niğde","Ordu","Rize","Sakarya","Samsun","Siirt","Sinop","Sivas",
    "Tekirdağ","Tokat","Trabzon","Tunceli","Şanlıurfa","Uşak","Van","Yozgat","Zonguldak",
    "Aksaray","Bayburt","Karaman","Kırıkkale","Batman","Şırnak","Bartın","Ardahan",
    "Iğdır","Yalova","Karabük","Kilis","Osmaniye","Düzce"
]
```

---

## 12. API Endpoint Planı (FastAPI)

```
AUTH:
  POST /auth/login         → {email, password} → JWT token
  POST /auth/logout
  GET  /auth/me

USERS:
  GET    /users            → Admin only
  POST   /users            → Admin only
  PUT    /users/{id}       → Admin only
  DELETE /users/{id}       → Admin only

VENUES:
  GET    /venues           → All roles (filtreli)
  POST   /venues           → Admin + E-dem
  PUT    /venues/{id}      → Admin + E-dem
  DELETE /venues/{id}      → Admin + E-dem

REQUESTS:
  GET    /requests         → Role bazlı filtreleme (admin=all, pm=mine, edem=pending+)
  POST   /requests         → PM only
  PUT    /requests/{id}    → PM (draft), E-dem (status update)
  DELETE /requests/{id}    → PM (draft only)

BUDGETS:
  GET    /budgets          → E-dem (all), PM (mine)
  POST   /budgets          → E-dem only
  PUT    /budgets/{id}     → E-dem only
  DELETE /budgets/{id}     → E-dem only

SERVICES:
  GET    /services         → All roles
  POST   /services         → Admin only
  PUT    /services/{id}    → Admin only
  DELETE /services/{id}    → Admin only

CUSTOM_CATS:
  GET    /custom-cats      → All roles
  POST   /custom-cats      → Admin only
  PUT    /custom-cats/{id} → Admin only
  DELETE /custom-cats/{id} → Admin only

CUSTOMERS:
  GET    /customers        → Admin + PM (autocomplete)
  POST   /customers        → Admin only
  PUT    /customers/{id}   → Admin only
  DELETE /customers/{id}   → Admin only
```

---

## 13. Frontend Tercihi

**Seçenek A (Tavsiye edilen başlangıç):**
Jinja2 şablon tabanlı, server-side rendered HTML + minimal JavaScript
- Mevcut HTML'i parçalara bölerek şablon haline getir
- Form submit → redirect (POST/PRG pattern)
- AJAX sadece dropdown/autocomplete için

**Seçenek B:**
FastAPI backend + React/Vue SPA frontend
- API-first yaklaşım
- Daha modern ama daha fazla iş

**Öneri:** Seçenek A ile başla, sonra kademeli olarak AJAX/SPA'ya geç.

---

## 14. Önemli Davranışlar ve Edge Case'ler

1. **Aynı günlük etkinlik**: checkIn == checkOut → calcNights = 0 (hata değil)
2. **Konaklama zorunlu değil**: Talep konaklama kalemi içermeyebilir; RFQ e-postasında o bölüm atlanır
3. **Referans no**: Yıl/ay bazlı sıralı numara, düzenlemede değişmez
4. **Taslak**: PM taslak kaydedebilir (status='draft'), E-dem'e göründüğünde 'pending' olmalı
5. **Özel kategoriler**: Admin eklediğinde hem hizmet kataloğunda hem talep formunun sekmelerinde görünür
6. **Tedarikçi şehir filtresi**: Talep formunda seçilen şehirlere göre tedarikçi dropdown'ı güncellenir
7. **Müşteri kodu**: 3 harfli, küçük harf, ref no'da kullanılır

---

## 15. Mevcut Referans Uygulamadan Notlar

- `reference/edem.html` tamamen çalışan versiyondur — tarayıcıda açarak inceleyebilirsin
- localStorage kullanır → veri kaybolmaması için önce import/export ekle
- ~5000 satır tek dosya JavaScript — Python'da aynı mantık backend'e taşınacak
- Tüm UI Türkçe
- Para birimi: Türk Lirası (₺)
- Tarih formatı: `tr-TR` locale (GG.AA.YYYY)

---

## 16. Başlangıç Sırası (Öneri)

1. `database.py` + `models.py` → tüm tabloları oluştur + seed data
2. `auth.py` → login/logout/session
3. Dashboard + navigation skeleton
4. Users CRUD (Admin)
5. Venues CRUD
6. Customers CRUD
7. Services + CustomCategories (Admin)
8. New Request form (PM) — en karmaşık sayfa
9. Request list views (tüm roller)
10. Budget editor (E-dem)
11. RFQ email modal
12. Budget view (PM)
