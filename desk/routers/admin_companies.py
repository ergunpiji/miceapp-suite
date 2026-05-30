"""
Şirket Yönetimi — super_admin: tüm şirketleri listeler, oluşturur, düzenler, kullanıcı atar.
"""
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Company, User, ROLE_LABELS
from templates_config import templates

router = APIRouter(prefix="/admin/companies", tags=["admin_companies"])


def _require_super_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Bu sayfa için Süper Admin yetkisi gereklidir.")
    return current_user


@router.get("", response_class=HTMLResponse, name="admin_companies_list")
async def companies_list(
    request: Request,
    current_user: User = Depends(_require_super_admin),
    db: Session = Depends(get_db),
):
    companies = db.query(Company).order_by(Company.name).all()
    user_counts = {}
    for c in companies:
        user_counts[c.id] = db.query(User).filter(User.company_id == c.id, User.active == True).count()  # noqa: E712
    return templates.TemplateResponse(
        "admin/companies/list.html",
        {
            "request": request,
            "current_user": current_user,
            "companies": companies,
            "user_counts": user_counts,
            "page_title": "Şirket Yönetimi",
        },
    )


@router.get("/new", response_class=HTMLResponse, name="admin_company_new_get")
async def company_new_get(
    request: Request,
    current_user: User = Depends(_require_super_admin),
):
    return templates.TemplateResponse(
        "admin/companies/form.html",
        {
            "request": request,
            "current_user": current_user,
            "co": None,
            "page_title": "Yeni Şirket",
        },
    )


@router.post("/new", name="admin_company_new_post")
async def company_new_post(
    request: Request,
    name: str = Form(...),
    short_name: str = Form(""),
    tax_no: str = Form(""),
    tax_office: str = Form(""),
    address: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    active: str = Form("on"),
    current_user: User = Depends(_require_super_admin),
    db: Session = Depends(get_db),
):
    c = Company(
        name=name.strip(),
        short_name=short_name.strip() or None,
        tax_no=tax_no.strip() or None,
        tax_office=tax_office.strip() or None,
        address=address.strip() or None,
        phone=phone.strip() or None,
        email=email.strip() or None,
        active=(active == "on"),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return RedirectResponse(url=f"/admin/companies/{c.id}/edit?saved=1",
                            status_code=status.HTTP_302_FOUND)


@router.get("/{company_id}/edit", response_class=HTMLResponse, name="admin_company_edit_get")
async def company_edit_get(
    company_id: str,
    request: Request,
    saved: int = 0,
    current_user: User = Depends(_require_super_admin),
    db: Session = Depends(get_db),
):
    c = db.query(Company).filter(Company.id == company_id).first()
    if not c:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        "admin/companies/form.html",
        {
            "request": request,
            "current_user": current_user,
            "co": c,
            "saved": bool(saved),
            "page_title": f"Şirket Düzenle — {c.name}",
        },
    )


@router.post("/{company_id}/edit", name="admin_company_edit_post")
async def company_edit_post(
    company_id: str,
    name: str = Form(...),
    short_name: str = Form(""),
    tax_no: str = Form(""),
    tax_office: str = Form(""),
    address: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    active: str = Form(""),
    current_user: User = Depends(_require_super_admin),
    db: Session = Depends(get_db),
):
    c = db.query(Company).filter(Company.id == company_id).first()
    if not c:
        raise HTTPException(status_code=404)
    c.name       = name.strip()
    c.short_name = short_name.strip() or None
    c.tax_no     = tax_no.strip() or None
    c.tax_office = tax_office.strip() or None
    c.address    = address.strip() or None
    c.phone      = phone.strip() or None
    c.email      = email.strip() or None
    c.active     = (active == "on")
    db.commit()
    return RedirectResponse(url=f"/admin/companies/{company_id}/edit?saved=1",
                            status_code=status.HTTP_302_FOUND)


@router.get("/{company_id}/users", response_class=HTMLResponse, name="admin_company_users")
async def company_users(
    company_id: str,
    request: Request,
    current_user: User = Depends(_require_super_admin),
    db: Session = Depends(get_db),
):
    c = db.query(Company).filter(Company.id == company_id).first()
    if not c:
        raise HTTPException(status_code=404)
    assigned = db.query(User).filter(User.company_id == company_id).order_by(User.name).all()
    unassigned = db.query(User).filter(
        (User.company_id == None) | (User.company_id != company_id)  # noqa: E711
    ).order_by(User.name).all()
    return templates.TemplateResponse(
        "admin/companies/users.html",
        {
            "request": request,
            "current_user": current_user,
            "co": c,
            "assigned": assigned,
            "unassigned": unassigned,
            "role_labels": ROLE_LABELS,
            "page_title": f"Kullanıcılar — {c.name}",
        },
    )


@router.post("/{company_id}/users/assign", name="admin_company_user_assign")
async def company_user_assign(
    company_id: str,
    user_id: str = Form(...),
    current_user: User = Depends(_require_super_admin),
    db: Session = Depends(get_db),
):
    c = db.query(Company).filter(Company.id == company_id).first()
    if not c:
        raise HTTPException(status_code=404)
    u = db.query(User).filter(User.id == user_id).first()
    if u:
        u.company_id = company_id
        db.commit()
    return RedirectResponse(url=f"/admin/companies/{company_id}/users",
                            status_code=status.HTTP_302_FOUND)


@router.post("/{company_id}/users/{user_id}/remove", name="admin_company_user_remove")
async def company_user_remove(
    company_id: str,
    user_id: str,
    current_user: User = Depends(_require_super_admin),
    db: Session = Depends(get_db),
):
    u = db.query(User).filter(User.id == user_id, User.company_id == company_id).first()
    if u:
        u.company_id = None
        db.commit()
    return RedirectResponse(url=f"/admin/companies/{company_id}/users",
                            status_code=status.HTTP_302_FOUND)


