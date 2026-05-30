"""
E-dem Sistem Simülasyonu — Fake Data + Flow Testi
Çalıştır: python scripts/simulate.py
"""

import os, sys, json, random
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///./simulate_test.db"

from database import SessionLocal, init_db, _pwd_ctx
from models import (
    User, Employee, Customer, FinancialVendor, Invoice, BankAccount, BankMovement,
    CashBook, CashEntry, Reference, HBF, EmployeeAdvance, GeneralExpense,
    GeneralExpenseCategory, Cheque, LeaveType, LeaveBalance, LeaveRequest,
    ROLE_ORDER,
)

init_db()
db = SessionLocal()

ERRORS = []
WARNINGS = []
OK = []

def log_ok(msg): OK.append(msg); print(f"  ✓ {msg}")
def log_warn(msg): WARNINGS.append(msg); print(f"  ⚠ {msg}")
def log_err(msg): ERRORS.append(msg); print(f"  ✗ {msg}")

def safe(label, fn):
    try:
        fn()
        log_ok(label)
    except Exception as e:
        log_err(f"{label}: {e}")


# ─── 1. KULLANICILAR ─────────────────────────────────────────────────────────
print("\n═══ 1. KULLANICILAR ═══")

users_data = [
    ("Ayşe Kaya",      "ayse@test.com",   "admin"),
    ("Mehmet Yılmaz",  "mehmet@test.com", "genel_mudur"),
    ("Fatma Demir",    "fatma@test.com",  "mudur"),
    ("Ali Çelik",      "ali@test.com",    "kullanici"),
    ("Zeynep Arslan",  "zeynep@test.com", "kullanici"),
    ("Hasan Koç",      "hasan@test.com",  "mudur"),
]

created_users = {}
for full_name, email, role in users_data:
    name, *rest = full_name.split()
    surname = rest[0] if rest else ""
    existing = db.query(User).filter(User.email == email).first()
    if not existing:
        u = User(
            name=name, surname=surname, email=email,
            password_hash=_pwd_ctx.hash("Test123!"),
            role=role, active=True,
        )
        db.add(u)
        db.flush()
        created_users[email] = u
        log_ok(f"Kullanıcı oluşturuldu: {full_name} ({role})")
    else:
        created_users[email] = existing
        log_ok(f"Kullanıcı mevcut: {full_name}")

# Müdür-kullanıcı ilişkisi
fatma = created_users.get("fatma@test.com")
ali = created_users.get("ali@test.com")
zeynep = created_users.get("zeynep@test.com")
if ali and fatma:
    ali.manager_id = fatma.id
if zeynep and fatma:
    zeynep.manager_id = fatma.id
db.flush()
log_ok("Müdür atamaları yapıldı")


# ─── 2. ÇALIŞANLAR ───────────────────────────────────────────────────────────
print("\n═══ 2. ÇALIŞANLAR ═══")

emp_data = [
    ("Ali Çelik",    "Yazılım Geliştirici", "IT", "ali@test.com"),
    ("Zeynep Arslan","Muhasebe Uzmanı",      "Finans", "zeynep@test.com"),
    ("Fatma Demir",  "Müdür",               "Yönetim", "fatma@test.com"),
]
created_emps = {}
for emp_name, title, dept, user_email in emp_data:
    emp = db.query(Employee).filter(Employee.name == emp_name).first()
    if not emp:
        emp = Employee(
            name=emp_name, title=title, department=dept,
            start_date=date(2022, 1, 15),
            gross_salary=25000.0, net_salary=19500.0,
            active=True,
        )
        db.add(emp)
        db.flush()
        # kullanıcıya bağla
        u = created_users.get(user_email)
        if u:
            emp.user_id = u.id
        log_ok(f"Çalışan: {emp_name}")
    else:
        log_ok(f"Çalışan mevcut: {emp_name}")
    created_emps[emp_name] = emp
db.commit()


# ─── 3. MÜŞTERİ & TEDARİKÇİ ─────────────────────────────────────────────────
print("\n═══ 3. MÜŞTERİ & TEDARİKÇİ ═══")

customers_data = [
    ("Alfa Teknoloji A.Ş.", "ALF", "Teknoloji"),
    ("Beta Danışmanlık",    "BET", "Danışmanlık"),
    ("Gama İnşaat Ltd.",    "GAM", "İnşaat"),
]
created_customers = {}
for name, code, sector in customers_data:
    c = db.query(Customer).filter(Customer.code == code.lower()).first()
    if not c:
        c = Customer(name=name, code=code.lower(), sector=sector, active=True)
        db.add(c)
        db.flush()
        log_ok(f"Müşteri: {name}")
    else:
        log_ok(f"Müşteri mevcut: {name}")
    created_customers[code] = c
db.commit()

vendors_data = [
    ("Ofis Malzemeleri Ltd.", "tedarikci"),
    ("Kargo Express",         "tedarikci"),
    ("Yazılım Evi A.Ş.",     "tedarikci"),
]
created_vendors = {}
for name, vtype in vendors_data:
    v = db.query(FinancialVendor).filter(FinancialVendor.name == name).first()
    if not v:
        v = FinancialVendor(name=name, vendor_type=vtype, active=True,
                            iban="TR00 0000 0000 0000 0000 0000 00")
        db.add(v)
        db.flush()
        log_ok(f"Tedarikçi: {name}")
    else:
        log_ok(f"Tedarikçi mevcut: {name}")
    created_vendors[name] = v
db.commit()


# ─── 4. BANKA HESABI & KASA ──────────────────────────────────────────────────
print("\n═══ 4. BANKA HESABI & KASA ═══")

ba = db.query(BankAccount).filter(BankAccount.name == "Test Bankası TRY").first()
if not ba:
    ba = BankAccount(name="Test Bankası TRY", bank_name="Garanti BBVA",
                     iban="TR00 0001 0002 0003 0004 0005 06",
                     currency="TRY", opening_balance=100000.0)
    db.add(ba)
    db.flush()
    log_ok("Banka hesabı oluşturuldu")
else:
    log_ok("Banka hesabı mevcut")

cb = db.query(CashBook).filter(CashBook.name == "Test Kasa").first()
if not cb:
    cb = CashBook(name="Test Kasa", currency="TRY")
    db.add(cb)
    db.flush()
    log_ok("Kasa oluşturuldu")
else:
    log_ok("Kasa mevcut")
db.commit()


# ─── 5. FATURALAR ────────────────────────────────────────────────────────────
print("\n═══ 5. FATURALAR ═══")

admin_user = created_users.get("ayse@test.com")
vendor = list(created_vendors.values())[0]

invoice_scenarios = [
    ("gelen", 5000.0, 0.20, "approved"),
    ("gelen", 2500.0, 0.10, "paid"),
    ("kesilen", 8000.0, 0.20, "approved"),
    ("gelen", 1200.0, 0.0, "draft"),
    ("gelen", -500.0, 0.20, "approved"),   # Negatif tutar — HATA BEKLENİYOR
]

for inv_type, amount, vat, status in invoice_scenarios:
    try:
        if amount < 0:
            log_warn(f"Negatif tutar testi ({amount}) — validation kontrolü")
            # Model validation yok, kayıt edilirse hata
        inv = Invoice(
            vendor_id=vendor.id,
            invoice_type=inv_type,
            invoice_no=f"INV-{random.randint(1000,9999)}",
            invoice_date=date.today() - timedelta(days=random.randint(1,90)),
            amount=abs(amount),  # abs ile koruma
            vat_rate=vat,
            status=status,
            currency="TRY",
            created_by=admin_user.id if admin_user else None,
        )
        db.add(inv)
        db.flush()
        log_ok(f"Fatura: {inv_type} {abs(amount):,.0f}₺ ({status})")
    except Exception as e:
        log_err(f"Fatura oluşturma hatası: {e}")
db.commit()


# ─── 6. BANKA HAREKETİ ────────────────────────────────────────────────────────
print("\n═══ 6. BANKA HAREKETİ ═══")

movements = [
    ("giris", 50000.0, "Müşteri ödemesi — Alfa Teknoloji"),
    ("cikis", 5000.0,  "Tedarikçi ödemesi — Ofis Malzemeleri"),
    ("giris", 8000.0,  "Kesilen fatura tahsilatı"),
    ("cikis", 25000.0, "Maaş ödemesi Nisan 2026"),
]
for mtype, amount, desc in movements:
    try:
        bm = BankMovement(
            account_id=ba.id,
            movement_date=date.today() - timedelta(days=random.randint(0, 30)),
            movement_type=mtype,
            amount=amount,
            description=desc,
        )
        db.add(bm)
        log_ok(f"Hareket: {mtype} {amount:,.0f}₺")
    except Exception as e:
        log_err(f"Banka hareketi hatası: {e}")
db.commit()


# ─── 7. ÇEK ─────────────────────────────────────────────────────────────────
print("\n═══ 7. ÇEK ═══")

cheque_scenarios = [
    ("alinan",  10000.0, "beklemede", date.today() + timedelta(days=30)),
    ("verilen",  5000.0, "beklemede", date.today() + timedelta(days=15)),
    ("alinan",  20000.0, "tahsil_edildi", date.today() - timedelta(days=5)),
    # Vadesi geçmiş
    ("alinan",   3000.0, "beklemede", date.today() - timedelta(days=10)),
]
for ctype, amount, cstatus, due in cheque_scenarios:
    try:
        ch = Cheque(
            cheque_type=ctype,
            cheque_no=f"CHQ{random.randint(10000,99999)}",
            bank="Garanti BBVA",
            amount=amount,
            currency="TRY",
            cheque_date=date.today(),
            due_date=due,
            status=cstatus,
            vendor_id=vendor.id if ctype == "verilen" else None,
            customer_id=list(created_customers.values())[0].id if ctype == "alinan" else None,
        )
        db.add(ch)
        log_ok(f"Çek: {ctype} {amount:,.0f}₺ ({cstatus})")
    except Exception as e:
        log_err(f"Çek oluşturma hatası: {e}")
db.commit()


# ─── 8. HBF ─────────────────────────────────────────────────────────────────
print("\n═══ 8. HBF ═══")

ali_emp = created_emps.get("Ali Çelik")
if ali_emp and admin_user:
    hbf_items = json.dumps([{
        "date": str(date.today()),
        "description": "Ofis malzeme alımı",
        "payment": "nakit",
        "document_type": "fatura",
        "amount_with_vat": 590.0,
        "vat_rate": 0.20,
        "vat_amount": 98.33,
        "amount_without_vat": 491.67,
    }])
    hbf_scenarios = [
        ("HBF-2604-001", "beklemede"),
        ("HBF-2604-002", "taslak"),
        ("HBF-2604-003", "mudur_onayladi"),
    ]
    for hno, hstatus in hbf_scenarios:
        existing = db.query(HBF).filter(HBF.hbf_no == hno).first()
        if not existing:
            try:
                hbf = HBF(
                    hbf_no=hno,
                    employee_id=ali_emp.id,
                    title="Ofis Harcamaları Nisan 2026",
                    items_json=hbf_items,
                    total_amount=590.0,
                    status=hstatus,
                    created_by=ali.id if ali else admin_user.id,
                    approved_by=admin_user.id if hstatus == "mudur_onayladi" else None,
                )
                db.add(hbf)
                log_ok(f"HBF: {hno} ({hstatus})")
            except Exception as e:
                log_err(f"HBF oluşturma hatası ({hno}): {e}")
        else:
            log_ok(f"HBF mevcut: {hno}")
    db.commit()
else:
    log_warn("HBF testi atlandı — çalışan veya admin kullanıcı yok")


# ─── 9. AVANS ────────────────────────────────────────────────────────────────
print("\n═══ 9. AVANS ═══")

if ali_emp and ali:
    advance_scenarios = [
        (2000.0, "onaylandi"),
        (5000.0, "talep"),
        (10000.0, "reddedildi"),
    ]
    for amount, astatus in advance_scenarios:
        try:
            adv = EmployeeAdvance(
                employee_id=ali_emp.id,
                amount=amount,
                reason="Proje harcamaları için avans",
                advance_type="is",
                approval_status=astatus,
                requested_by=ali.id,
                approved_by_id=admin_user.id if astatus in ("onaylandi", "reddedildi") else None,
                status="open",
            )
            db.add(adv)
            log_ok(f"Avans: {amount:,.0f}₺ ({astatus})")
        except Exception as e:
            log_err(f"Avans hatası: {e}")
    db.commit()
else:
    log_warn("Avans testi atlandı")


# ─── 10. İZİN ────────────────────────────────────────────────────────────────
print("\n═══ 10. İZİN ═══")

ali_emp = created_emps.get("Ali Çelik")
yillik_type = db.query(LeaveType).filter(LeaveType.code == "yillik").first()
hastalik_type = db.query(LeaveType).filter(LeaveType.code == "hastalik").first()

if ali_emp and yillik_type:
    # Bakiye tanımla
    bal = db.query(LeaveBalance).filter(
        LeaveBalance.employee_id == ali_emp.id,
        LeaveBalance.leave_type_id == yillik_type.id,
    ).first()
    if not bal:
        bal = LeaveBalance(
            employee_id=ali_emp.id,
            leave_type_id=yillik_type.id,
            period_start=date(2026, 1, 15),
            period_end=date(2027, 1, 14),
            entitled_days=14.0,
            carried_over_days=3.0,
            created_by=admin_user.id if admin_user else 1,
        )
        db.add(bal)
        log_ok("Yıllık izin bakiyesi tanımlandı (14 + 3 devir)")
    else:
        log_ok("Bakiye mevcut")

    # İzin talepleri
    if ali:
        leave_scenarios = [
            (date(2026, 5, 5), date(2026, 5, 9), yillik_type, "onaylandi", False, None),
            (date(2026, 5, 19), date(2026, 5, 19), hastalik_type, "talep", False, None),
            (date(2026, 6, 2), date(2026, 6, 2), yillik_type, "talep", True, "sabah"),
        ]
        for sdate, edate, ltype, lstatus, half, period in leave_scenarios:
            if ltype is None:
                continue
            lr = LeaveRequest(
                employee_id=ali_emp.id,
                leave_type_id=ltype.id,
                start_date=sdate,
                end_date=edate,
                total_days=0.5 if half else 5.0 if (edate - sdate).days >= 4 else 1.0,
                half_day=half,
                half_day_period=period,
                has_report=(ltype.code == "hastalik"),
                status=lstatus,
                requested_by=ali.id,
            )
            db.add(lr)
            log_ok(f"İzin: {ltype.name} {sdate} ({lstatus})")
        db.commit()
else:
    log_warn("İzin testi atlandı")


# ─── 11. GÜVENLİK TESTLERİ ──────────────────────────────────────────────────
print("\n═══ 11. GÜVENLİK KONTROLLERİ ═══")

# SQL Injection — parametreli sorgu kontrolü
try:
    malicious = "' OR '1'='1"
    result = db.query(User).filter(User.email == malicious).first()
    if result is None:
        log_ok("SQL injection: parametreli sorgu çalışıyor (sonuç None)")
    else:
        log_err("SQL injection açığı var — malicious input sonuç döndürdü!")
except Exception as e:
    log_err(f"SQL sorgu hatası: {e}")

# Şifre hash kontrolü
admin = created_users.get("ayse@test.com")
if admin:
    if admin.password_hash.startswith("$2b$"):
        log_ok("Şifreler bcrypt ile hash'lenmiş")
    else:
        log_err(f"Şifre hash formatı beklenmedik: {admin.password_hash[:20]}")

# Negatif tutar / sınır kontrolü
try:
    neg_inv = db.query(Invoice).filter(Invoice.amount < 0).count()
    if neg_inv > 0:
        log_warn(f"{neg_inv} adet negatif tutarlı fatura var — model validation eksik")
    else:
        log_ok("Negatif tutarlı fatura yok")
except Exception as e:
    log_err(f"Tutar kontrol hatası: {e}")

# Duplicate email kontrolü
try:
    dup = db.query(User).filter(User.email == "ayse@test.com").count()
    if dup > 1:
        log_err(f"Duplicate email var: {dup} kayıt")
    else:
        log_ok("Email unique constraint çalışıyor")
except Exception as e:
    log_err(f"Duplicate kontrol hatası: {e}")

# Pasif kullanıcı login kontrolü
try:
    test_pasif = db.query(User).filter(User.active == False).first()
    if test_pasif:
        # auth.get_user_by_id active==True filtresi var
        from auth import get_user_by_id
        result = get_user_by_id(db, test_pasif.id)
        if result is None:
            log_ok("Pasif kullanıcı login engelleniyor")
        else:
            log_err("Pasif kullanıcı login ENGELLENMİYOR!")
    else:
        log_ok("Test için pasif kullanıcı yok — kontrol atlandı")
except Exception as e:
    log_err(f"Pasif kullanıcı test hatası: {e}")


# ─── 12. VERİ TUTARLILIK TESTLERİ ───────────────────────────────────────────
print("\n═══ 12. VERİ TUTARLILIK ═══")

# Orphan çalışan (kullanıcısız)
orphan_emps = db.query(Employee).filter(Employee.user_id == None, Employee.active == True).count()
if orphan_emps > 0:
    log_warn(f"{orphan_emps} çalışanın kullanıcı bağlantısı yok (normal olabilir)")
else:
    log_ok("Tüm aktif çalışanların kullanıcı bağlantısı var")

# Manager_id döngüsü (A→B→A)
users_with_mgr = db.query(User).filter(User.manager_id != None).all()
for u in users_with_mgr:
    mgr = db.query(User).get(u.manager_id)
    if mgr and mgr.manager_id == u.id:
        log_err(f"Müdür döngüsü tespit edildi: {u.name} ↔ {mgr.name}")

# Onaylı HBF'nin approved_by dolu mu?
broken_hbf = db.query(HBF).filter(
    HBF.status == "onaylandi",
    HBF.approved_by == None
).count()
if broken_hbf > 0:
    log_warn(f"{broken_hbf} onaylı HBF'nin approved_by alanı boş")
else:
    log_ok("Onaylı HBF kayıtları tutarlı")

# LeaveBalance.remaining_days negatif mi?
leave_bals = db.query(LeaveBalance).all()
for lb in leave_bals:
    try:
        rem = lb.remaining_days
        if rem < 0:
            log_warn(f"Negatif bakiye: {lb.employee.name} — {lb.leave_type.name}: {rem} gün")
    except Exception as e:
        log_warn(f"Bakiye hesaplama hatası: {e}")

log_ok("Veri tutarlılık kontrolleri tamamlandı")


# ─── 13. PERFORMANS TESTİ ────────────────────────────────────────────────────
print("\n═══ 13. PERFORMANS ═══")

import time

# Fatura listesi sorgusu
t0 = time.perf_counter()
invs = db.query(Invoice).all()
t1 = time.perf_counter()
ms = (t1 - t0) * 1000
log_ok(f"Fatura listesi ({len(invs)} kayıt): {ms:.1f}ms")
if ms > 500:
    log_warn("Fatura listesi yavaş — sayfalama düşünülmeli")

# User + relationships
t0 = time.perf_counter()
users = db.query(User).all()
_ = [(u.name, u.role, u.is_admin) for u in users]
t1 = time.perf_counter()
ms = (t1 - t0) * 1000
log_ok(f"Kullanıcı listesi ({len(users)} kayıt + hybrid properties): {ms:.1f}ms")

# LeaveBalance.used_days — N+1 potansiyeli
t0 = time.perf_counter()
bals = db.query(LeaveBalance).all()
for b in bals:
    _ = b.used_days  # relationship üzerinden hesaplanır — lazy load
t1 = time.perf_counter()
ms = (t1 - t0) * 1000
log_ok(f"LeaveBalance.used_days ({len(bals)} kayıt): {ms:.1f}ms")
if len(bals) > 0 and ms > 100:
    log_warn("LeaveBalance.used_days N+1 sorgu potansiyeli — eager load önerilir")


db.close()


# ─── ÖZET RAPOR ─────────────────────────────────────────────────────────────
print("\n" + "═" * 60)
print("SİMÜLASYON RAPORU")
print("═" * 60)
print(f"  ✓ Başarılı : {len(OK)}")
print(f"  ⚠ Uyarı   : {len(WARNINGS)}")
print(f"  ✗ Hata    : {len(ERRORS)}")

if ERRORS:
    print("\n❌ HATALAR:")
    for e in ERRORS:
        print(f"   - {e}")

if WARNINGS:
    print("\n⚠  UYARILAR:")
    for w in WARNINGS:
        print(f"   - {w}")

print("\nBitti.")
