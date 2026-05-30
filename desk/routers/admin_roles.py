"""
Rol & İzin Yönetimi — Admin paneli
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user, require_admin, DEFAULT_PERMISSIONS
from database import get_db
from models import RolePermission, User, ROLE_ORDER, ROLE_LABELS
from templates_config import templates

router = APIRouter(prefix="/admin/roles", tags=["admin_roles"])

# İzin grupları ve açıklamaları
PERMISSION_GROUPS = [
    ("Onay Akışları", [
        ("advance_create",        "Avans talebi oluşturabilir"),
        ("advance_approve_first", "Avansı müdür kademesinde onaylar"),
        ("advance_approve_final", "Avansı nihai olarak onaylar (GM)"),
        ("hbf_create",            "HBF oluşturabilir"),
        ("hbf_approve_first",     "HBF'i müdür kademesinde onaylar"),
        ("hbf_approve_final",     "HBF'i nihai olarak onaylar (GM)"),
    ]),
    ("Finansal İşlemler", [
        ("invoice_create",        "Fatura oluşturabilir / düzenleyebilir"),
        ("invoice_delete",        "Fatura silebilir"),
        ("payment_list_prepare",  "Haftalık ödeme listesi hazırlayabilir"),
        ("payment_list_approve",  "Haftalık ödeme listesini onaylayabilir"),
        ("fund_pool_manage",      "Fon havuzu oluşturabilir / düzenleyebilir"),
        ("cash_close",            "Gün sonu kasa kapatabilir"),
    ]),
    ("Raporlar", [
        ("report_view",           "Temel raporları görüntüleyebilir"),
        ("report_view_financial", "Finansal raporları görüntüleyebilir"),
        ("report_view_all",       "Tüm çalışan verilerini raporlarda görür"),
    ]),
    ("Veri Yönetimi", [
        ("customer_manage",  "Müşteri ekler / düzenler / siler"),
        ("employee_manage",  "Çalışan ekler / düzenler / siler"),
        ("vendor_manage",    "Tedarikçi ekler / düzenler / siler"),
    ]),
    ("Sistem Yönetimi", [
        ("user_manage",             "Kullanıcı ekler / düzenler, rol atar"),
        ("role_permission_manage",  "İzin matrisini düzenleyebilir"),
        ("module_config",           "Sistem modüllerini aktif/pasif yapabilir"),
        ("super_admin_panel",       "Süper Admin paneline erişebilir"),
    ]),
]

def _build_matrix(db: Session) -> dict[str, dict[str, bool]]:
    """role → permission → bool matrisi döner."""
    overrides = {
        (r.role, r.permission): r.enabled
        for r in db.query(RolePermission).all()
    }
    matrix: dict[str, dict[str, bool]] = {}
    for role in ROLE_ORDER:
        matrix[role] = {}
        for _, perms in PERMISSION_GROUPS:
            for perm_key, _ in perms:
                if (role, perm_key) in overrides:
                    matrix[role][perm_key] = overrides[(role, perm_key)]
                else:
                    min_role = DEFAULT_PERMISSIONS.get(perm_key, "super_admin")
                    try:
                        matrix[role][perm_key] = ROLE_ORDER.index(role) >= ROLE_ORDER.index(min_role)
                    except ValueError:
                        matrix[role][perm_key] = False
    return matrix


@router.get("", response_class=HTMLResponse, name="admin_roles_get")
async def admin_roles_get(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    matrix = _build_matrix(db)
    return templates.TemplateResponse(
        "admin/roles.html",
        {
            "request": request, "current_user": current_user,
            "page_title": "Rol & İzin Yönetimi",
            "roles": ROLE_ORDER,
            "role_labels": ROLE_LABELS,
            "permission_groups": PERMISSION_GROUPS,
            "matrix": matrix,
        },
    )


@router.post("", name="admin_roles_post")
async def admin_roles_post(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    form = await request.form()
    # Tüm geçerli (role, permission) çiftleri için güncelle
    for role in ROLE_ORDER:
        if role == "super_admin":
            continue  # süper admin her şeyi yapabilir, kilitle
        for _, perms in PERMISSION_GROUPS:
            for perm_key, _ in perms:
                if perm_key == "super_admin_panel" and role != "super_admin":
                    continue  # sadece super_admin erişir
                field = f"{role}__{perm_key}"
                enabled = field in form
                row = db.query(RolePermission).filter_by(
                    role=role, permission=perm_key
                ).first()
                if row:
                    row.enabled = enabled
                    row.updated_by = current_user.id
                else:
                    db.add(RolePermission(
                        role=role,
                        permission=perm_key,
                        enabled=enabled,
                        updated_by=current_user.id,
                    ))
    db.commit()
    return RedirectResponse(url="/admin/roles?saved=1", status_code=303)
