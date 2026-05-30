"""Finans Ajanı — Bütçe vs Gerçekleşen"""
from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from database import get_db
from models import (
    ActualEntry, BUDGET_CATEGORIES, BUDGET_CATEGORY_LABELS,
    PAYMENT_METHODS, BudgetLine, Project, PROJECT_STATUSES,
)
from templates_config import templates

router = APIRouter(prefix="/projects", tags=["budget_actual"])


# ---------------------------------------------------------------------------
# Proje listesi
# ---------------------------------------------------------------------------
@router.get("", response_class=HTMLResponse, name="projects_list")
async def projects_list(request: Request, db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    return templates.TemplateResponse(
        request,
        "budget_actual/list.html",
        {
            "active": "budget_actual",
            "projects": projects,
            "statuses": PROJECT_STATUSES,
        },
    )


# ---------------------------------------------------------------------------
# Yeni proje formu
# ---------------------------------------------------------------------------
@router.get("/new", response_class=HTMLResponse, name="project_new")
async def project_new(request: Request):
    return templates.TemplateResponse(
        request,
        "budget_actual/form.html",
        {
            "active": "budget_actual",
            "project": None,
            "statuses": PROJECT_STATUSES,
        },
    )


@router.post("/new")
async def project_create(
    request: Request,
    name: str = Form(...),
    edem_request_no: str = Form(""),
    customer_name: str = Form(""),
    event_date: str = Form(""),
    event_end_date: str = Form(""),
    status: str = Form("aktif"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    project = Project(
        name=name,
        edem_request_no=edem_request_no or None,
        customer_name=customer_name or None,
        event_date=date.fromisoformat(event_date) if event_date else None,
        event_end_date=date.fromisoformat(event_end_date) if event_end_date else None,
        status=status,
        notes=notes or None,
    )
    db.add(project)
    db.commit()
    return RedirectResponse(url=f"/projects/{project.id}", status_code=303)


# ---------------------------------------------------------------------------
# Proje detay — bütçe vs gerçekleşen
# ---------------------------------------------------------------------------
@router.get("/{project_id}", response_class=HTMLResponse, name="project_detail")
async def project_detail(project_id: str, request: Request, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Proje bulunamadı.")

    # Kategoriye göre grupla
    grouped: dict[str, dict] = {}
    for cat in BUDGET_CATEGORIES:
        key = cat["value"]
        lines = [bl for bl in project.budget_lines if bl.category == key]
        if lines:
            grouped[key] = {
                "label": cat["label"],
                "lines": lines,
                "budgeted": sum(bl.amount for bl in lines),
                "actual": sum(bl.actual_total for bl in lines),
            }

    # Kategorisiz satırlar
    uncategorized = [bl for bl in project.budget_lines if bl.category not in BUDGET_CATEGORY_LABELS]

    return templates.TemplateResponse(
        request,
        "budget_actual/detail.html",
        {
            "active": "budget_actual",
            "project": project,
            "grouped": grouped,
            "uncategorized": uncategorized,
            "categories": BUDGET_CATEGORIES,
            "payment_methods": PAYMENT_METHODS,
        },
    )


# ---------------------------------------------------------------------------
# Proje düzenle
# ---------------------------------------------------------------------------
@router.get("/{project_id}/edit", response_class=HTMLResponse, name="project_edit")
async def project_edit(project_id: str, request: Request, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Proje bulunamadı.")
    return templates.TemplateResponse(
        request,
        "budget_actual/form.html",
        {
            "active": "budget_actual",
            "project": project,
            "statuses": PROJECT_STATUSES,
        },
    )


@router.post("/{project_id}/edit")
async def project_update(
    project_id: str,
    name: str = Form(...),
    edem_request_no: str = Form(""),
    customer_name: str = Form(""),
    event_date: str = Form(""),
    event_end_date: str = Form(""),
    status: str = Form("aktif"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Proje bulunamadı.")
    project.name = name
    project.edem_request_no = edem_request_no or None
    project.customer_name = customer_name or None
    project.event_date = date.fromisoformat(event_date) if event_date else None
    project.event_end_date = date.fromisoformat(event_end_date) if event_end_date else None
    project.status = status
    project.notes = notes or None
    db.commit()
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


# ---------------------------------------------------------------------------
# Bütçe satırı ekle
# ---------------------------------------------------------------------------
@router.post("/{project_id}/budget-lines/add")
async def budget_line_add(
    project_id: str,
    description: str = Form(...),
    category: str = Form("other"),
    amount: float = Form(0.0),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404)
    line = BudgetLine(
        project_id=project_id,
        description=description,
        category=category,
        amount=amount,
        notes=notes or None,
        sort_order=len(project.budget_lines),
    )
    db.add(line)
    db.commit()
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


# ---------------------------------------------------------------------------
# Bütçe satırı sil
# ---------------------------------------------------------------------------
@router.post("/{project_id}/budget-lines/{line_id}/delete")
async def budget_line_delete(
    project_id: str,
    line_id: str,
    db: Session = Depends(get_db),
):
    line = db.query(BudgetLine).filter(
        BudgetLine.id == line_id, BudgetLine.project_id == project_id
    ).first()
    if line:
        db.delete(line)
        db.commit()
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


# ---------------------------------------------------------------------------
# Gerçekleşen gider ekle
# ---------------------------------------------------------------------------
@router.post("/{project_id}/actual/add")
async def actual_entry_add(
    project_id: str,
    entry_date: str = Form(...),
    description: str = Form(...),
    amount: float = Form(0.0),
    category: str = Form("other"),
    budget_line_id: str = Form(""),
    supplier_name: str = Form(""),
    invoice_no: str = Form(""),
    payment_method: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404)
    entry = ActualEntry(
        project_id=project_id,
        entry_date=date.fromisoformat(entry_date),
        description=description,
        amount=amount,
        category=category,
        budget_line_id=budget_line_id or None,
        supplier_name=supplier_name or None,
        invoice_no=invoice_no or None,
        payment_method=payment_method or None,
        notes=notes or None,
    )
    db.add(entry)
    db.commit()
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


# ---------------------------------------------------------------------------
# Gerçekleşen gider sil
# ---------------------------------------------------------------------------
@router.post("/{project_id}/actual/{entry_id}/delete")
async def actual_entry_delete(
    project_id: str,
    entry_id: str,
    db: Session = Depends(get_db),
):
    entry = db.query(ActualEntry).filter(
        ActualEntry.id == entry_id, ActualEntry.project_id == project_id
    ).first()
    if entry:
        db.delete(entry)
        db.commit()
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)
