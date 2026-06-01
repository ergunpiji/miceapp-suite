"""
Kullanıcı yönetimi (admin only)
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from typing import Optional

from auth import get_current_user, require_admin, hash_password
from database import get_db
from models import (
    User, Employee, Company, Department, UserDepartment,
    ROLE_ORDER, ROLE_LABELS,
)
from templates_config import templates

router = APIRouter(prefix="/users", tags=["users"])


def _get_form_context(db, current_user, user=None, error=None, page_title="Kullanıcı", req_company_id=None):
    cid = req_company_id or (user.company_id if user else None) or current_user.company_id

    if cid:
        employees = db.query(Employee).filter(
            Employee.active == True,  # noqa: E712
            Employee.company_id == cid,
        ).order_by(Employee.name).all()
        managers = db.query(User).filter(
            User.active == True,  # noqa: E712
            User.company_id == cid,
            User.role.in_(["mudur", "genel_mudur", "admin", "super_admin"]),
        ).order_by(User.name).all()
    else:
        employees = db.query(Employee).filter(Employee.active == True).order_by(Employee.name).all()  # noqa: E712
        managers = db.query(User).filter(
            User.active == True,  # noqa: E712
            User.role.in_(["mudur", "genel_mudur", "admin", "super_admin"]),
        ).order_by(User.name).all()

    if user:
        managers = [m for m in managers if m.id != user.id]

    linked_employee = None
    if user:
        linked_employee = db.query(Employee).filter(Employee.user_id == user.id).first()

    companies = None
    if current_user.role == "super_admin":
        companies = db.query(Company).filter(Company.active == True).order_by(Company.name).all()  # noqa: E712

    # Departman listesi + bu user'ın atanmış olduğu departmanlar (RBAC v2)
    all_departments = []
    user_dept_ids: set[int] = set()
    head_dept_ids: set[int] = set()
    if cid:
        all_departments = (
            db.query(Department)
            .filter(Department.company_id == cid, Department.active == True)  # noqa: E712
            .order_by(Department.name).all()
        )
    if user:
        for ud in db.query(UserDepartment).filter_by(user_id=user.id).all():
            user_dept_ids.add(ud.department_id)
            if ud.is_head:
                head_dept_ids.add(ud.department_id)

    return {
        "current_user": current_user,
        "user": user,
        "employees": employees,
        "managers": managers,
        "roles": ROLE_ORDER,
        "role_labels": ROLE_LABELS,
        "page_title": page_title,
        "error": error,
        "linked_employee": linked_employee,
        "companies": companies,
        "selected_company_id": cid,
        "all_departments": all_departments,
        "user_dept_ids": user_dept_ids,
        "head_dept_ids": head_dept_ids,
    }


def _save_user_departments(
    db: Session, user_id: str, company_id: str | None,
    department_ids: list[int], head_dept_ids: list[int],
) -> None:
    """Bir kullanıcının departman atamalarını günceller (eskiyi temizle, yeniyi yaz)."""
    if not company_id:
        return
    # Sadece bu şirkete ait departmanlara izin ver
    valid_ids = {
        d_id for (d_id,) in
        db.query(Department.id).filter(Department.company_id == company_id).all()
    }
    db.query(UserDepartment).filter_by(user_id=user_id).delete()
    for d_id in department_ids:
        try:
            d_id_int = int(d_id)
        except (TypeError, ValueError):
            continue
        if d_id_int not in valid_ids:
            continue
        is_head = d_id_int in {int(x) for x in head_dept_ids if str(x).isdigit()}
        db.add(UserDepartment(
            user_id=user_id, department_id=d_id_int, is_head=is_head,
        ))


@router.get("", response_class=HTMLResponse, name="users_list")
async def users_list(
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.query(User)
    if current_user.role != "super_admin":
        q = q.filter(User.company_id == current_user.company_id)
    users = q.order_by(User.name).all()
    return templates.TemplateResponse(
        "users/list.html",
        {"request": request, "current_user": current_user,
         "users": users, "role_labels": ROLE_LABELS, "page_title": "Kullanıcılar"},
    )


@router.get("/new", response_class=HTMLResponse, name="user_new_get")
async def user_new_get(
    request: Request,
    company_id: Optional[str] = None,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    ctx = _get_form_context(db, current_user, page_title="Yeni Kullanıcı", req_company_id=company_id)
    return templates.TemplateResponse("users/form.html", {"request": request, **ctx})


@router.post("/new", name="user_new_post")
async def user_new_post(
    request: Request,
    name: str = Form(...),
    surname: str = Form(""),
    title: str = Form(""),
    phone: str = Form(""),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form("kullanici"),
    manager_id: Optional[str] = Form(None),
    employee_id: str = Form(""),
    company_id: Optional[str] = Form(None),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    # department_ids ve head_dept_ids form'dan multi-value gelir — manuel parse
    form = await request.form()
    department_ids = form.getlist("department_ids")
    head_dept_ids = form.getlist("head_dept_ids")
    email = email.strip().lower()
    if role not in ROLE_ORDER:
        role = "kullanici"
    if role == "super_admin" and not current_user.has_role_min("super_admin"):
        role = "admin"
    if db.query(User).filter(User.email == email).first():
        ctx = _get_form_context(db, current_user, page_title="Yeni Kullanıcı",
                                error=f"'{email}' e-posta adresi zaten kayıtlı.",
                                req_company_id=company_id)
        return templates.TemplateResponse("users/form.html",
                                          {"request": request, **ctx}, status_code=400)

    assigned_company_id = company_id if current_user.role == "super_admin" else current_user.company_id

    u = User(
        name=name.strip(),
        surname=surname.strip() or None,
        title=title.strip() or None,
        phone=phone.strip() or None,
        email=email,
        password_hash=hash_password(password),
        role=role,
        manager_id=manager_id or None,
        company_id=assigned_company_id,
        active=True,
    )
    db.add(u)
    db.flush()
    if employee_id:
        emp = db.get(Employee, int(employee_id))
        if emp:
            old = db.query(Employee).filter(Employee.user_id == u.id).first()
            if old:
                old.user_id = None
            emp.user_id = u.id
    # Departman atamaları
    _save_user_departments(
        db, u.id, u.company_id,
        list(department_ids), list(head_dept_ids),
    )
    db.commit()
    return RedirectResponse(url="/users", status_code=status.HTTP_302_FOUND)


@router.get("/{user_id}/edit", response_class=HTMLResponse, name="user_edit_get")
async def user_edit_get(
    user_id: str,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404)
    if current_user.role != "super_admin" and u.company_id != current_user.company_id:
        raise HTTPException(status_code=403)
    ctx = _get_form_context(db, current_user, user=u, page_title=f"Düzenle — {u.name}")
    return templates.TemplateResponse("users/form.html", {"request": request, **ctx})


@router.post("/{user_id}/edit", name="user_edit_post")
async def user_edit_post(
    user_id: str,
    request: Request,
    name: str = Form(...),
    surname: str = Form(""),
    title: str = Form(""),
    phone: str = Form(""),
    email: str = Form(...),
    password: str = Form(""),
    role: str = Form("kullanici"),
    manager_id: Optional[str] = Form(None),
    active: str = Form("1"),
    employee_id: str = Form(""),
    company_id: Optional[str] = Form(None),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    form = await request.form()
    department_ids = form.getlist("department_ids")
    head_dept_ids = form.getlist("head_dept_ids")
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404)
    if current_user.role != "super_admin" and u.company_id != current_user.company_id:
        raise HTTPException(status_code=403)
    email = email.strip().lower()
    if role not in ROLE_ORDER:
        role = "kullanici"
    if role == "super_admin" and not current_user.has_role_min("super_admin"):
        role = u.role
    existing = db.query(User).filter(User.email == email, User.id != user_id).first()
    if existing:
        ctx = _get_form_context(db, current_user, user=u,
                                page_title=f"Düzenle — {u.name}",
                                error=f"'{email}' e-posta adresi zaten kayıtlı.")
        return templates.TemplateResponse("users/form.html",
                                          {"request": request, **ctx}, status_code=400)
    u.name = name.strip()
    u.surname = surname.strip() or None
    u.title = title.strip() or None
    u.phone = phone.strip() or None
    u.email = email
    u.role = role
    u.manager_id = manager_id or None
    u.active = (active == "1")
    if password.strip():
        u.password_hash = hash_password(password.strip())

    if current_user.role == "super_admin" and company_id:
        u.company_id = company_id

    old_link = db.query(Employee).filter(Employee.user_id == user_id).first()
    if old_link:
        old_link.user_id = None
    if employee_id:
        emp = db.get(Employee, int(employee_id))
        if emp:
            emp.user_id = user_id

    # Departman atamaları
    _save_user_departments(
        db, u.id, u.company_id,
        list(department_ids), list(head_dept_ids),
    )

    db.commit()
    return RedirectResponse(url="/users", status_code=status.HTTP_302_FOUND)


@router.post("/{user_id}/delete", name="user_delete")
async def user_delete(
    user_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Kendi hesabınızı silemezsiniz.")
    u = db.get(User, user_id)
    if u and current_user.role != "super_admin" and u.company_id != current_user.company_id:
        raise HTTPException(status_code=403)
    if u:
        u.active = False
        db.commit()
    return RedirectResponse(url="/users", status_code=status.HTTP_302_FOUND)
