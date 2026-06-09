"""
Çok-kiracılı (multi-tenant) kapsam yardımcıları — event app.

Event aslen tek-şirket varsayımıyla yazıldı; GM/admin "her şeyi görür" mantığı
şirketler arası veri sızdırıyordu. Bu modül, sorguları kullanıcının şirketine
(company_id) göre kapsamlandırır. Yalnızca super_admin tüm şirketleri görür.

Kullanım:
    from tenant import scope, effective_company_id
    q = scope(db.query(Request), Request, current_user)
    cid = effective_company_id(current_user)   # None ise super_admin (hepsi)
"""
from __future__ import annotations

from typing import Any, Optional


def effective_company_id(user: Any) -> Optional[str]:
    """Kullanıcının görebileceği TEK company_id. super_admin → None (tüm şirketler).
    Diğerleri için user.company_id, yoksa kanonik EVENT_COMPANY_ID fallback."""
    if user is None:
        return None   # kullanıcı yoksa filtre uygulama (çağıran sorumlu)
    if getattr(user, "role", None) == "super_admin":
        return None
    cid = getattr(user, "company_id", None)
    if cid:
        return cid
    from database import EVENT_COMPANY_ID
    return EVENT_COMPANY_ID


def assert_tenant(user, obj_company_id) -> None:
    """ID ile erişilen detayda sahiplik guard'ı: nesne kullanıcının şirketinde
    değilse 404. super_admin (cid None) her şeye erişir. obj_company_id None ise
    (eski/atanmamış veri) engellenmez — backfill bunları kanonik şirkete bağlar."""
    cid = effective_company_id(user)
    if cid is None or obj_company_id is None:
        return
    if str(obj_company_id) != str(cid):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Kayıt bulunamadı.")


def scope(query, model, user):
    """query'yi kullanıcının şirketine göre filtreler.
    super_admin → dokunma; model'de company_id yoksa → dokunma."""
    cid = effective_company_id(user)
    if cid is None:
        return query
    if hasattr(model, "company_id"):
        return query.filter(model.company_id == cid)
    return query
