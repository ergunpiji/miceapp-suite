"""
Tedarikçi Tip Yönetimi — admin: listele, ekle, sil, sıra güncelle
"""
import re
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import require_admin
from database import get_db
from models import User, VendorType, Vendor
from templates_config import templates

router = APIRouter(prefix="/admin/vendor-types", tags=["admin_vendor_types"])


def _slugify(label: str) -> str:
    s = label.strip().lower()
    s = s.replace("ç", "c").replace("ş", "s").replace("ğ", "g")
    s = s.replace("ü", "u").replace("ö", "o").replace("ı", "i")
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s[:40] or "tip"


@router.get("", response_class=HTMLResponse, name="admin_vendor_types")
async def vendor_types_list(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    types = db.query(VendorType).order_by(VendorType.sort_order, VendorType.label).all()
    return templates.TemplateResponse(
        "admin/vendor_types.html",
        {"request": request, "current_user": current_user,
         "types": types, "page_title": "Tedarikçi Tipleri"},
    )


@router.post("/new", name="admin_vendor_type_new")
async def vendor_type_new(
    label: str = Form(...),
    sort_order: int = Form(0),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    label = label.strip()
    if not label:
        raise HTTPException(status_code=400, detail="Tip adı boş olamaz.")
    slug = _slugify(label)
    # Slug çakışması varsa sonuna sayı ekle
    base = slug
    i = 2
    while db.query(VendorType).filter_by(value=slug).first():
        slug = f"{base}_{i}"
        i += 1
    db.add(VendorType(value=slug, label=label, sort_order=sort_order))
    db.commit()
    return RedirectResponse(url="/admin/vendor-types", status_code=status.HTTP_302_FOUND)


@router.post("/{type_id}/delete", name="admin_vendor_type_delete")
async def vendor_type_delete(
    type_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    vt = db.get(VendorType, type_id)
    if not vt:
        raise HTTPException(status_code=404)
    in_use = db.query(Vendor).filter(Vendor.supplier_type == vt.value).count()
    if in_use:
        raise HTTPException(
            status_code=400,
            detail=f"Bu tip {in_use} tedarikçide kullanılıyor, silinemez.",
        )
    db.delete(vt)
    db.commit()
    return RedirectResponse(url="/admin/vendor-types", status_code=status.HTTP_302_FOUND)


@router.post("/{type_id}/toggle", name="admin_vendor_type_toggle")
async def vendor_type_toggle(
    type_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    vt = db.get(VendorType, type_id)
    if not vt:
        raise HTTPException(status_code=404)
    vt.active = not vt.active
    db.commit()
    return RedirectResponse(url="/admin/vendor-types", status_code=status.HTTP_302_FOUND)
