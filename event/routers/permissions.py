"""
E-dem — Rol İzin Yönetimi (Admin only)
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse

from auth import require_admin
from database import get_db
from models import RolePermission, PERMISSIONS, DEFAULT_ROLE_PERMISSIONS, USER_ROLES, User, _uuid
from sqlalchemy.orm import Session

router = APIRouter(prefix="/admin/permissions", tags=["permissions"])
from templates_config import templates


@router.get("", response_class=HTMLResponse, name="permissions_list")
async def permissions_list(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    # Tüm izinleri çek: {role: {perm_key: allowed}}
    rows = db.query(RolePermission).all()
    perm_map: dict[str, dict[str, bool]] = {}
    for rp in rows:
        perm_map.setdefault(rp.role, {})[rp.permission] = rp.allowed

    # Admin olmayan roller
    roles = [r for r in USER_ROLES if r["value"] != "admin"]

    return templates.TemplateResponse(
        "admin/permissions.html",
        {
            "request":      request,
            "current_user": current_user,
            "page_title":   "Rol İzinleri",
            "permissions":  PERMISSIONS,
            "roles":        roles,
            "perm_map":     perm_map,
        },
    )


@router.post("/toggle", name="permissions_toggle")
async def permissions_toggle(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """AJAX: {"role": "mudur", "permission": "request_create", "allowed": true}"""
    body = await request.json()
    role       = body.get("role", "")
    permission = body.get("permission", "")
    allowed    = bool(body.get("allowed", False))

    rp = db.query(RolePermission).filter(
        RolePermission.role == role,
        RolePermission.permission == permission,
    ).first()

    if rp:
        rp.allowed = allowed
    else:
        rp = RolePermission(id=_uuid(), role=role, permission=permission, allowed=allowed)
        db.add(rp)

    db.commit()
    return JSONResponse({"ok": True})
