"""
Ortak rol/kimlik modeli doğrulama testleri (shared-core 1. adım).
Çalıştır: python3 tests_roles_unification.py
Bağımsız — pytest gerektirmez; DB bağlantısı yapmaz.
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
EVENT_ROLES = os.path.join(ROOT, "event", "roles.py")
DESK_ROLES = os.path.join(ROOT, "desk", "roles.py")

_fail = 0


def check(name, cond):
    global _fail
    if cond:
        print(f"  ✓ {name}")
    else:
        _fail += 1
        print(f"  ✗ FAIL: {name}")


def load(path, mod_name):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


print("1) event/roles.py ve desk/roles.py byte-eşit")
with open(EVENT_ROLES, "rb") as a, open(DESK_ROLES, "rb") as b:
    check("byte-eşit", a.read() == b.read())

roles = load(EVENT_ROLES, "roles_canonical")

print("2) ROLE_RANK ValueError-proof (event rolleri dahil)")
for r in ["yonetici", "asistan", "satinalma", "muhasebe_muduru", "muhasebe", "bilinmeyen_rol"]:
    roles.role_rank(r)  # exception atmamalı
check("role_rank tüm rollerde çalışıyor (exception yok)", True)
check("bilinmeyen rol → 0", roles.role_rank("zzz") == 0)

print("3) is_gm seti korunuyor: {genel_mudur, admin, super_admin}")
gm = {r["value"] for r in roles.CANONICAL_ROLES if roles.has_role_min(r["value"], "genel_mudur")}
check("is_gm seti doğru", gm == {"genel_mudur", "admin", "super_admin"})

print("4) Sibel senaryosu: muhasebe_muduru departmansız → accounting görünürlüğü")
class FakeFinance:
    role = "muhasebe_muduru"
    department_keys = set()
check("effective dept = {accounting}", roles.effective_department_keys(FakeFinance()) == {"accounting"})
check("finance.view_all = True", roles.has_capability("muhasebe_muduru", "finance.view_all"))

print("5) Açık departman + rol-varsayılan birleşir")
class FakeMixed:
    role = "muhasebe_muduru"
    department_keys = {"sales"}
check("effective = {sales, accounting}", roles.effective_department_keys(FakeMixed()) == {"sales", "accounting"})

print("6) Yetki ayrımı korunuyor")
check("muhasebe_muduru finance.view_all var", roles.has_capability("muhasebe_muduru", "finance.view_all"))
check("yonetici finance.view_all YOK", not roles.has_capability("yonetici", "finance.view_all"))
check("kullanici finance.view_all YOK", not roles.has_capability("kullanici", "finance.view_all"))
check("muhasebe_muduru GM değil (payment_approve)", not roles.has_role_min("muhasebe_muduru", "genel_mudur"))
check("muhasebe_muduru invoice_create yapabilir (≥kullanici)", roles.has_role_min("muhasebe_muduru", "kullanici"))

print("7) Alias normalize: ik → insan_kaynaklari → hr departmanı")
check("ik default dept = {hr}", roles.default_department_keys("ik") == {"hr"})
check("normalize project_manager → yonetici", roles.normalize_role("project_manager") == "yonetici")

print("8) desk _bypass: muhasebe_muduru bypass eder (finance.view_all)")
sys.path.insert(0, os.path.join(ROOT, "desk"))
# access_policy import'u: roles'u desk/roles.py'den çekecek (sys.path[0]=desk)
import access_policy as ap  # noqa: E402
class FakeUser:
    role = "muhasebe_muduru"
    is_admin = False
    is_approver = False
check("_bypass(muhasebe_muduru) = True", ap._bypass(FakeUser()) is True)
class FakeSales:
    role = "yonetici"
    is_admin = False
    is_approver = False
check("_bypass(yonetici) = False", ap._bypass(FakeSales()) is False)

print()
if _fail:
    print(f"SONUÇ: {_fail} test BAŞARISIZ")
    sys.exit(1)
print("SONUÇ: tüm testler GEÇTİ ✓")
