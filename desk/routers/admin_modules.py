"""
Admin Modüller — sistem modüllerinin durumunu/aktivasyonunu yönetir.
v1: Modül kataloğu + detay + aktivasyon (simülasyon modunda)
SystemSetting key formatı: 'module_<key>_enabled' = '1' | '0'
"""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import require_admin
from database import get_db
from models import User, SystemSetting
from templates_config import templates


router = APIRouter(prefix="/admin/modules", tags=["admin_modules"])


# ---------------------------------------------------------------------------
# Modül kataloğu
# ---------------------------------------------------------------------------

MODULES_CATALOG = [
    {
        "key": "einvoice",
        "name": "E-Fatura / E-Arşiv",
        "icon": "bi-receipt-cutoff",
        "color": "#1A3A5C",
        "description": (
            "Türkiye e-Fatura/e-Arşiv entegrasyonu — webapp üzerinden direkt "
            "GİB'e fatura kesme ve gelen e-faturaları otomatik sisteme çekme."
        ),
        "blocked_reason": (
            "Gerçek GİB gönderimi için mali mühür ve özel entegratör gereklidir; "
            "şu an sandbox/simülasyon modunda çalışır (FakeProvider)."
        ),
        "next_steps": [
            "KamuSM'den mali mühür başvurusu (5–10 iş günü, ~1.500–3.500 TL)",
            "İzibiz ve Paraşüt'ten teklif alın (Logo müşterisi olduğunuz için İzibiz öncelikli)",
            "Seçilen entegratörle GİB e-Fatura mükellefiyet başvurusu",
            "Sertifika + entegratör onayı gelince provider 'fake' yerine gerçek seçilir",
        ],
        "scope": [
            "Giden: kesilen faturalar e-Fatura (B2B) veya e-Arşiv (B2C) olarak gönderilir",
            "Gelen: tedarikçilerin kestiği e-faturalar otomatik webapp'e düşer (inbox)",
            "Status takibi + iptal akışı + PDF görüntüleme",
            "Müşteri/tedarikçi e-Fatura mükellefi otomatik kontrol",
        ],
        "simulation_note": "FakeProvider ile UI ve akış %100 çalışır. Gerçek gönderim yerine sahte UUID döner; ekibe demo yapılabilir.",
    },
    {
        "key": "edefter",
        "name": "E-Defter",
        "icon": "bi-journal-text",
        "color": "#1E5F8C",
        "description": "Aylık/yıllık yevmiye + büyük defter elektronik gönderimi.",
        "blocked_reason": "Gönderim için mali mühür gerekir; veri hazırlama ve görüntüleme şu an simülasyonda çalışır.",
        "next_steps": [
            "Mali mühür alındığında 'GİB'e Gönder' butonu açılır",
            "Veri hazırlığı + görüntüleme + Excel export şu an kullanılabilir",
        ],
        "scope": [
            "Yevmiye Defteri (her ay için, Invoice + GeneralExpense + hareketlerden)",
            "Büyük Defter (hesap bazlı muavin)",
            "XBRL/Excel export — mali müşavir kontrol için",
        ],
        "simulation_note": "Defter verisi tamamen üretilir, ekrana çıkar, Excel'e indirilir. Sadece resmi gönderim mali mühür sonrası.",
    },
    {
        "key": "tax_reports",
        "name": "Vergi Raporları (KDV / BA-BS)",
        "icon": "bi-file-earmark-bar-graph",
        "color": "#16a34a",
        "description": (
            "KDV1/KDV2 özet raporu, BA/BS otomatik üretimi, geçici vergi tahmini, "
            "yıllık kâr/zarar projeksiyonu."
        ),
        "blocked_reason": None,  # Mali mühür gerek yok — production-ready
        "next_steps": [],
        "scope": [
            "Aylık KDV1 (giden) / KDV2 (gelen) özet",
            "BA/BS formu (5.000 TL üzeri alımlar/satışlar)",
            "Geçici vergi tahmini (çeyreklik kâr × kurumlar vergisi oranı)",
            "Excel export — mali müşavire teslim için",
        ],
        "simulation_note": None,  # Production-ready
    },
    {
        "key": "bordro",
        "name": "Bordro & Maaş Yönetimi",
        "icon": "bi-people-fill",
        "color": "#7c3aed",
        "description": (
            "SGK (%14+%1), gelir vergisi (kümülatif dilimli), damga vergisi hesaplama. "
            "Emekli SGDP desteği, ücretsiz izin entegrasyonu, kıdem/ihbar hesaplama, "
            "toplu ödeme — nakit akışı ve banka hareketlerine otomatik yansıma."
        ),
        "blocked_reason": None,
        "next_steps": [],
        "scope": [
            "Aylık taslak oluştur → düzenle → onayla → toplu öde akışı",
            "Türkiye 2026 vergi sabitleri (her yıl güncellenebilir)",
            "Emekli çalışan SGDP oranları (%7,5 çalışan / %22,5 işveren)",
            "Ücretsiz izin → otomatik eksik gün kesintisi",
            "Kıdem ve ihbar tazminatı hesaplama aracı",
        ],
        "simulation_note": None,
    },
]


# ---------------------------------------------------------------------------
# Settings helper'ları
# ---------------------------------------------------------------------------

def _setting_key(module_key: str) -> str:
    return f"module_{module_key}_enabled"


def is_module_enabled(db: Session, module_key: str) -> bool:
    s = db.query(SystemSetting).filter(
        SystemSetting.key == _setting_key(module_key)
    ).first()
    return bool(s and s.value == "1")


def set_module_enabled(db: Session, module_key: str, enabled: bool) -> None:
    key = _setting_key(module_key)
    s = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    val = "1" if enabled else "0"
    if s:
        s.value = val
    else:
        db.add(SystemSetting(key=key, value=val))


def _enriched_modules(db: Session) -> list:
    """Katalogdaki modüllere mevcut durumlarını ekle."""
    result = []
    for m in MODULES_CATALOG:
        item = dict(m)
        item["enabled"] = is_module_enabled(db, m["key"])
        if item["enabled"]:
            item["status"] = "active"
            item["status_label"] = "Aktif"
        else:
            item["status"] = "inactive"
            item["status_label"] = "Pasif"
        result.append(item)
    return result


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse, name="admin_modules_list")
async def modules_list(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(
        "admin_modules/list.html",
        {
            "request": request,
            "current_user": current_user,
            "page_title": "Modüller",
            "modules": _enriched_modules(db),
        },
    )


@router.get("/{module_key}", response_class=HTMLResponse, name="admin_module_detail")
async def module_detail(
    module_key: str,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    cat = next((m for m in MODULES_CATALOG if m["key"] == module_key), None)
    if not cat:
        return templates.TemplateResponse(
            "admin_modules/list.html",
            {
                "request": request,
                "current_user": current_user,
                "page_title": "Modüller",
                "modules": _enriched_modules(db),
                "error": f"Modül bulunamadı: {module_key}",
            },
        )
    mod = dict(cat)
    mod["enabled"] = is_module_enabled(db, module_key)
    mod["status"] = "active" if mod["enabled"] else "inactive"
    mod["status_label"] = "Aktif" if mod["enabled"] else "Pasif"
    return templates.TemplateResponse(
        "admin_modules/detail.html",
        {
            "request": request,
            "current_user": current_user,
            "page_title": mod["name"],
            "module": mod,
        },
    )


@router.post("/{module_key}/activate", name="admin_module_activate")
async def module_activate(
    module_key: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    cat = next((m for m in MODULES_CATALOG if m["key"] == module_key), None)
    if not cat:
        return RedirectResponse(url="/admin/modules", status_code=303)
    set_module_enabled(db, module_key, True)
    db.commit()
    return RedirectResponse(url=f"/admin/modules/{module_key}", status_code=303)


@router.post("/{module_key}/deactivate", name="admin_module_deactivate")
async def module_deactivate(
    module_key: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    set_module_enabled(db, module_key, False)
    db.commit()
    return RedirectResponse(url=f"/admin/modules/{module_key}", status_code=303)
