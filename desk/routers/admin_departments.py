"""
RBAC v2 — Departman & Modül Erişim Yönetimi (Admin paneli)

Endpoints:
  GET  /admin/departments              → liste
  GET  /admin/departments/new          → yeni departman formu
  POST /admin/departments/create
  GET  /admin/departments/{id}/edit
  POST /admin/departments/{id}/update
  POST /admin/departments/{id}/delete  → soft delete (active=False)
  GET  /admin/departments/{id}/access  → modül erişim matrisi
  POST /admin/departments/{id}/access  → matris kaydet
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user, require_admin
from database import get_db
from models import Department, ModuleAccess, User, UserDepartment
from templates_config import templates
from access_policy import MODULES

router = APIRouter(prefix="/admin/departments", tags=["admin_departments"])


def _slugify(name: str) -> str:
    """Türkçe karakterleri normalize edip slug üret."""
    tr_map = str.maketrans("ığşöüçİĞŞÖÜÇ", "igsoucIGSOUC")
    s = name.translate(tr_map).lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "departman"


def _unique_key(db: Session, company_id: str, base: str, ignore_id: str | None = None) -> str:
    """Aynı company içinde key benzersiz olsun — gerekiyorsa _2, _3 ekle."""
    candidate = base
    n = 1
    while True:
        q = db.query(Department).filter_by(company_id=company_id, key=candidate)
        if ignore_id:
            q = q.filter(Department.id != ignore_id)
        if not q.first():
            return candidate
        n += 1
        candidate = f"{base}_{n}"


# ---------------------------------------------------------------------------
# Liste
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse, name="admin_departments_list")
async def list_departments(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not current_user.company_id:
        raise HTTPException(400, "Şirket atanmamış.")
    depts = (
        db.query(Department)
        .filter(Department.company_id == current_user.company_id)
        .order_by(Department.active.desc(), Department.name)
        .all()
    )
    # Her departman için kullanıcı sayısı
    user_counts = {}
    for d in depts:
        user_counts[d.id] = (
            db.query(UserDepartment)
            .filter_by(department_id=d.id)
            .count()
        )
    return templates.TemplateResponse(
        "admin/departments/list.html",
        {
            "request": request, "current_user": current_user,
            "page_title": "Departmanlar",
            "departments": depts,
            "user_counts": user_counts,
        },
    )


# ---------------------------------------------------------------------------
# Yeni / düzenle form
# ---------------------------------------------------------------------------

@router.get("/new", response_class=HTMLResponse, name="admin_department_new")
async def department_new(
    request: Request,
    current_user: User = Depends(require_admin),
):
    return templates.TemplateResponse(
        "admin/departments/form.html",
        {
            "request": request, "current_user": current_user,
            "page_title": "Yeni Departman",
            "dept": None,
            "mode": "new",
        },
    )


@router.post("/create", name="admin_department_create")
async def department_create(
    request: Request,
    name: str = Form(...),
    color: str = Form("#1A3A5C"),
    icon: str = Form("bi-people"),
    access_event: str = Form(""),
    access_desk: str = Form(""),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not current_user.company_id:
        raise HTTPException(400, "Şirket atanmamış.")
    name = name.strip()
    if not name:
        raise HTTPException(400, "Departman adı zorunlu.")
    key = _unique_key(db, current_user.company_id, _slugify(name))
    dept = Department(
        company_id=current_user.company_id,
        key=key,
        name=name,
        color=color or "#1A3A5C",
        icon=icon or "bi-people",
        active=True,
        access_event=bool(access_event),
        access_desk=bool(access_desk),
    )
    db.add(dept)
    db.commit()
    return RedirectResponse(url=f"/admin/departments/{dept.id}/access?created=1", status_code=303)


@router.get("/{dept_id}/edit", response_class=HTMLResponse, name="admin_department_edit")
async def department_edit(
    dept_id: str,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    dept = db.query(Department).filter_by(
        id=dept_id, company_id=current_user.company_id
    ).first()
    if not dept:
        raise HTTPException(404, "Departman bulunamadı.")
    return templates.TemplateResponse(
        "admin/departments/form.html",
        {
            "request": request, "current_user": current_user,
            "page_title": f"Departman: {dept.name}",
            "dept": dept,
            "mode": "edit",
        },
    )


@router.post("/{dept_id}/update", name="admin_department_update")
async def department_update(
    dept_id: str,
    name: str = Form(...),
    color: str = Form("#1A3A5C"),
    icon: str = Form("bi-people"),
    active: str = Form(""),
    access_event: str = Form(""),
    access_desk: str = Form(""),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    dept = db.query(Department).filter_by(
        id=dept_id, company_id=current_user.company_id
    ).first()
    if not dept:
        raise HTTPException(404, "Departman bulunamadı.")
    dept.name = name.strip()
    dept.color = color or "#1A3A5C"
    dept.icon = icon or "bi-people"
    dept.active = bool(active)
    dept.access_event = bool(access_event)
    dept.access_desk = bool(access_desk)
    db.commit()
    return RedirectResponse(url="/admin/departments?saved=1", status_code=303)


@router.post("/{dept_id}/delete", name="admin_department_delete")
async def department_delete(
    dept_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Soft delete — kullanıcı atamaları korunur, departman pasifleştirilir."""
    dept = db.query(Department).filter_by(
        id=dept_id, company_id=current_user.company_id
    ).first()
    if not dept:
        raise HTTPException(404, "Departman bulunamadı.")
    dept.active = False
    db.commit()
    return RedirectResponse(url="/admin/departments?deleted=1", status_code=303)


# ---------------------------------------------------------------------------
# Erişim matrisi
# ---------------------------------------------------------------------------

@router.get("/{dept_id}/access", response_class=HTMLResponse, name="admin_department_access")
async def department_access_get(
    dept_id: str,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    dept = db.query(Department).filter_by(
        id=dept_id, company_id=current_user.company_id
    ).first()
    if not dept:
        raise HTTPException(404, "Departman bulunamadı.")

    # Mevcut matrisi yükle: module_key → (can_view, can_edit)
    current_access = {
        ma.module_key: (ma.can_view, ma.can_edit)
        for ma in db.query(ModuleAccess).filter_by(department_id=dept_id).all()
    }

    # MODULES kataloğunu grupla
    module_groups = [
        ("Temel", ["dashboard"]),
        ("Satış / Operasyon", ["customers", "references", "invoices", "vendors"]),
        ("Muhasebe / Finans", [
            "cash", "banks", "cheques", "credit_cards", "general_expenses",
            "fund_pools", "budgets", "payments_weekly", "payment_instructions",
            "tax_reports", "edefter", "einvoice",
        ]),
        ("İnsan Kaynakları", ["employees", "leaves", "advances", "hbf", "bordro"]),
        ("Raporlar", ["reports_financial", "reports_hr"]),
    ]

    return templates.TemplateResponse(
        "admin/departments/access.html",
        {
            "request": request, "current_user": current_user,
            "page_title": f"Erişim Matrisi: {dept.name}",
            "dept": dept,
            "modules": MODULES,
            "module_groups": module_groups,
            "current_access": current_access,
        },
    )


@router.post("/{dept_id}/access", name="admin_department_access_save")
async def department_access_post(
    dept_id: str,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    dept = db.query(Department).filter_by(
        id=dept_id, company_id=current_user.company_id
    ).first()
    if not dept:
        raise HTTPException(404, "Departman bulunamadı.")

    form = await request.form()
    # Mevcut module access kayıtlarını oku
    existing = {
        ma.module_key: ma
        for ma in db.query(ModuleAccess).filter_by(department_id=dept_id).all()
    }

    for module_key in MODULES.keys():
        can_view = f"view__{module_key}" in form
        can_edit = f"edit__{module_key}" in form
        # Edit varsa view de zorunlu (mantıksal tutarlılık)
        if can_edit:
            can_view = True
        ma = existing.get(module_key)
        if ma:
            ma.can_view = can_view
            ma.can_edit = can_edit
        else:
            if can_view or can_edit:
                db.add(ModuleAccess(
                    department_id=dept_id,
                    module_key=module_key,
                    can_view=can_view,
                    can_edit=can_edit,
                ))
    db.commit()
    return RedirectResponse(
        url=f"/admin/departments/{dept_id}/access?saved=1",
        status_code=303,
    )
