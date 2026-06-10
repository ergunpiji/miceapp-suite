"""
Kanonik rol / yetenek (capability) modeli — miceapp-suite ortak kaynağı.

Bu dosya event/ ve desk/ altına BİREBİR AYNI kopyalanır (repo'daki
utils/funds.py, utils/tcmb.py "perfect-duplication" deseni gibi). İleride
shared-core fazında gerçek paylaşımlı pakete çıkarılacak. İki kopya byte-eşit
olmalı — test/CI bunu doğrular.

Amaç: event ve desk tek `users.role` kolonunu paylaşıyor ama tarihsel olarak iki
farklı rol felsefesi kullanıyordu. Bu dosya ikisini tek kanonik kaynağa bağlar:
  - CANONICAL_ROLES        : birleşik rol listesi + Türkçe label
  - ROLE_RANK              : ValueError-proof hiyerarşi (bilinmeyen rol → 0)
  - ROLE_CAPABILITIES      : rol → yetenek kümesi (uygulamalar-arası kavramlar)
  - ROLE_DEFAULT_DEPARTMENTS : rol → desk departman key'leri (departmansız
                               event kullanıcılarına desk görünürlüğü sağlar)

HİÇBİR model/DB import'u yok — bağımsız kalmalı.
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Kanonik roller (event USER_ROLES ∪ desk ROLE_LABELS)
# ---------------------------------------------------------------------------
# Sıra hiyerarşik DEĞİL; hiyerarşi ROLE_RANK'tedir.
CANONICAL_ROLES: list[dict[str, str]] = [
    {"value": "super_admin",        "label": "Süper Admin"},
    {"value": "admin",              "label": "Sistem Yöneticisi"},
    {"value": "genel_mudur",        "label": "Genel Müdür"},
    {"value": "mudur",              "label": "Müdür"},
    {"value": "yonetici",           "label": "Proje Yöneticisi"},
    {"value": "asistan",            "label": "Proje Asistanı"},
    {"value": "satinalma",          "label": "Satın Alma"},
    {"value": "muhasebe_muduru",    "label": "Muhasebe Müdürü"},
    {"value": "muhasebe",           "label": "Muhasebe Yetkilisi"},
    {"value": "insan_kaynaklari",   "label": "İnsan Kaynakları"},
    {"value": "kullanici",          "label": "Kullanıcı"},
]

ROLE_LABELS: dict[str, str] = {r["value"]: r["label"] for r in CANONICAL_ROLES}

# "ik" → "insan_kaynaklari" eski takma adı normalize etmek için
ROLE_ALIASES: dict[str, str] = {
    "ik": "insan_kaynaklari",
    "project_manager": "yonetici",   # event eski rol adı
}


def normalize_role(role: Any) -> str:
    r = (role or "").strip()
    return ROLE_ALIASES.get(r, r)


def role_label(role: Any) -> str:
    return ROLE_LABELS.get(normalize_role(role), str(role or ""))


# ---------------------------------------------------------------------------
# Hiyerarşi (ValueError-proof) — desk ROLE_ORDER.index yerine
# ---------------------------------------------------------------------------
# Yüksek sayı = daha fazla yetki. Bilinmeyen rol → 0 (en düşük).
ROLE_RANK: dict[str, int] = {
    "kullanici":        1,
    "asistan":          2,
    "yonetici":         3,
    "muhasebe":         3,
    "insan_kaynaklari": 3,
    "satinalma":        3,
    "mudur":            4,
    "muhasebe_muduru":  4,
    "genel_mudur":      5,
    "admin":            6,
    "super_admin":      7,
}

# Desk geriye-dönük uyumluluk: desk auth.py min-rol eşiklerinde "genel_mudur"
# gibi anahtarlar kullanıyor; ROLE_RANK bunları kapsıyor.


def role_rank(role: Any) -> int:
    return ROLE_RANK.get(normalize_role(role), 0)


def has_role_min(role: Any, min_role: str) -> bool:
    """role, min_role veya daha yüksek mi? (ValueError atmaz)"""
    return role_rank(role) >= role_rank(min_role)


# ---------------------------------------------------------------------------
# Yetenekler (capability) — uygulamalar-arası kanonik kavramlar
# ---------------------------------------------------------------------------
# app.event / app.desk : kullanıcının ana çalışma alanı (yönlendirme/erişim)
# finance.view_all      : finans satır-seviyesi filtrelerini bypass (tüm
#                         referans/fatura/müşteri görünür) — desk RBAC v2
# approve.gm            : GM seviyesi nihai onaycı (desk haftalık ödeme vb.)
# admin.manage          : yönetim (kullanıcı/rol/şirket)
CAP_APP_EVENT      = "app.event"
CAP_APP_DESK       = "app.desk"
CAP_FINANCE_VIEW_ALL = "finance.view_all"
CAP_APPROVE_GM     = "approve.gm"
CAP_ADMIN_MANAGE   = "admin.manage"

_ALL_CAPS = {
    CAP_APP_EVENT, CAP_APP_DESK, CAP_FINANCE_VIEW_ALL,
    CAP_APPROVE_GM, CAP_ADMIN_MANAGE,
}

ROLE_CAPABILITIES: dict[str, set[str]] = {
    "super_admin":      set(_ALL_CAPS),
    "admin":            set(_ALL_CAPS),
    "genel_mudur":      {CAP_APP_EVENT, CAP_APP_DESK, CAP_FINANCE_VIEW_ALL, CAP_APPROVE_GM},
    "mudur":            {CAP_APP_EVENT},
    "yonetici":         {CAP_APP_EVENT},
    "asistan":          {CAP_APP_EVENT},
    "satinalma":        {CAP_APP_EVENT},
    # Muhasebe ve İK: desk'te tüm operasyonel finans verisini görür (eski
    # FULL_ACCESS_ROLES davranışı korunur).
    "muhasebe_muduru":  {CAP_APP_DESK, CAP_FINANCE_VIEW_ALL},
    "muhasebe":         {CAP_APP_DESK, CAP_FINANCE_VIEW_ALL},
    "insan_kaynaklari": {CAP_APP_DESK, CAP_FINANCE_VIEW_ALL},
    "kullanici":        {CAP_APP_DESK},
}


def has_capability(role: Any, capability: str) -> bool:
    return capability in ROLE_CAPABILITIES.get(normalize_role(role), set())


# ---------------------------------------------------------------------------
# Rol → desk varsayılan departmanları
# ---------------------------------------------------------------------------
# Event UI'da departman atanamıyor; SSO ile gelen event kullanıcılarının
# user.departments listesi boş olur. Bu eşleme, departmansız kullanıcılara
# desk satır-seviyesi görünürlüğü için "etkili departman" sağlar.
ROLE_DEFAULT_DEPARTMENTS: dict[str, set[str]] = {
    "muhasebe_muduru":  {"accounting"},
    "muhasebe":         {"accounting"},
    "insan_kaynaklari": {"hr"},
    "satinalma":        {"operations"},
    "mudur":            {"sales"},
    "yonetici":         {"sales"},
    "asistan":          {"sales"},
    # admin / genel_mudur / super_admin: zaten bypass; kullanici: yok.
}


def default_department_keys(role: Any) -> set[str]:
    return set(ROLE_DEFAULT_DEPARTMENTS.get(normalize_role(role), set()))


def effective_department_keys(user: Any) -> set[str]:
    """Kullanıcının açık departman key'leri ∪ rolünden gelen varsayılanlar.

    `user`'da `department_keys` (set/iterable) ve `role` bulunması beklenir;
    yoksa güvenli şekilde boş/varsayılana düşer.
    """
    explicit = set()
    dk = getattr(user, "department_keys", None)
    if dk:
        try:
            explicit = set(dk)
        except TypeError:
            explicit = set()
    return explicit | default_department_keys(getattr(user, "role", None))


# ---------------------------------------------------------------------------
# Departman → app erişimi (departman-merkezli model)
# ---------------------------------------------------------------------------
# Hangi departman hangi app'e girer. Departman objesinde access_event/access_desk
# yoksa (eski kayıt) key'e göre bu varsayılan kullanılır.
DEPARTMENT_DEFAULT_APPS: dict[str, set[str]] = {
    "sales":      {"event"},
    "operations": {"event", "desk"},
    "accounting": {"desk"},
    "hr":         {"desk"},
}


def _dept_apps(dept) -> set:
    """Bir departman objesinden app erişim kümesi."""
    ev = getattr(dept, "access_event", None)
    dk = getattr(dept, "access_desk", None)
    if ev is None and dk is None:
        return set(DEPARTMENT_DEFAULT_APPS.get(getattr(dept, "key", ""), set()))
    apps = set()
    if ev:
        apps.add("event")
    if dk:
        apps.add("desk")
    return apps


def user_app_access(user) -> set:
    """Kullanıcının girebileceği app'ler: {"event","desk"} alt kümesi.

    Sıra: 1) yönetim rolleri (super_admin/admin/genel_mudur) → ikisi; 2) açık
    departmanların app erişimi; 3) departmansız → rol-varsayılan departman köprüsü;
    4) son çare ROLE_CAPABILITIES; yine boşsa {"event"} (kimse kilitlenmesin)."""
    role = normalize_role(getattr(user, "role", None))
    if role in ("super_admin", "admin", "genel_mudur"):
        return {"event", "desk"}
    apps = set()
    for d in (getattr(user, "departments", None) or []):
        if getattr(d, "active", True):
            apps |= _dept_apps(d)
    if apps:
        return apps
    for k in default_department_keys(role):
        apps |= DEPARTMENT_DEFAULT_APPS.get(k, set())
    if apps:
        return apps
    if has_capability(role, CAP_APP_EVENT):
        apps.add("event")
    if has_capability(role, CAP_APP_DESK):
        apps.add("desk")
    return apps or {"event"}
