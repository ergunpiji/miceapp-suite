"""HR Ajanı — Yemek Kartı ve Esnek Yan Haklar."""
from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_current_user, require_hr_admin
from database import get_db
from models import (
    BENEFIT_CATEGORIES, MEAL_PROVIDERS,
    BenefitSpending, Employee, FlexibleBenefit, HRUser, MealCard, Notification,
)
from templates_config import templates

router = APIRouter(prefix="/benefits", tags=["benefits"])


# ============================================================================
# Yemek Kartı
# ============================================================================
@router.get("/meal-cards", response_class=HTMLResponse)
async def list_meal_cards(
    request: Request,
    year: int = 0,
    month: int = 0,
    current_user: HRUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    unread_count = db.query(func.count(Notification.id)).filter(
        Notification.user_id == current_user.id, Notification.is_read == False
    ).scalar() or 0

    today = date.today()
    if not year:
        year = today.year
    if not month:
        month = today.month

    query = db.query(MealCard).filter(
        MealCard.period_year == year, MealCard.period_month == month
    )
    if current_user.role == "employee" and current_user.employee:
        query = query.filter(MealCard.employee_id == current_user.employee.id)

    cards = query.order_by(MealCard.loaded_at.desc()).all()
    years = list(range(today.year - 1, today.year + 2))

    employees = []
    if current_user.role == "hr_admin":
        employees = db.query(Employee).filter(Employee.status == "aktif").order_by(Employee.first_name).all()

    total = sum(c.amount for c in cards)

    return templates.TemplateResponse(
        "benefits/meal_cards.html",
        {
            "request": request, "active": "benefits", "user": current_user,
            "cards": cards, "year": year, "month": month, "years": years,
            "employees": employees, "providers": MEAL_PROVIDERS,
            "total": total, "unread_count": unread_count,
        },
    )


@router.post("/meal-cards/new")
async def create_meal_card(
    employee_id: str = Form(""),
    card_no: str = Form(""),
    provider: str = Form("Ticket"),
    amount: float = Form(...),
    monthly_limit: float = Form(0.0),
    loaded_at: str = Form(...),
    period_year: int = Form(...),
    period_month: int = Form(...),
    notes: str = Form(""),
    current_user: HRUser = Depends(require_hr_admin),
    db: Session = Depends(get_db),
):
    card = MealCard(
        employee_id=employee_id,
        card_no=card_no or None,
        provider=provider,
        amount=amount,
        monthly_limit=monthly_limit,
        loaded_at=date.fromisoformat(loaded_at),
        period_year=period_year,
        period_month=period_month,
        notes=notes or None,
    )
    db.add(card)
    db.commit()
    return RedirectResponse(url=f"/benefits/meal-cards?year={period_year}&month={period_month}", status_code=302)


@router.post("/meal-cards/{card_id}/delete")
async def delete_meal_card(
    card_id: str,
    current_user: HRUser = Depends(require_hr_admin),
    db: Session = Depends(get_db),
):
    card = db.query(MealCard).filter(MealCard.id == card_id).first()
    if card:
        year, month = card.period_year, card.period_month
        db.delete(card)
        db.commit()
        return RedirectResponse(url=f"/benefits/meal-cards?year={year}&month={month}", status_code=302)
    raise HTTPException(status_code=404)


# ============================================================================
# Esnek Yan Haklar
# ============================================================================
@router.get("/flexible", response_class=HTMLResponse)
async def list_flexible(
    request: Request,
    year: int = 0,
    current_user: HRUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    unread_count = db.query(func.count(Notification.id)).filter(
        Notification.user_id == current_user.id, Notification.is_read == False
    ).scalar() or 0

    if not year:
        year = date.today().year

    query = db.query(FlexibleBenefit).filter(FlexibleBenefit.year == year)
    if current_user.role == "employee" and current_user.employee:
        query = query.filter(FlexibleBenefit.employee_id == current_user.employee.id)

    benefits = query.all()
    years = list(range(date.today().year - 1, date.today().year + 2))

    employees = []
    if current_user.role == "hr_admin":
        employees = db.query(Employee).filter(Employee.status == "aktif").order_by(Employee.first_name).all()

    return templates.TemplateResponse(
        "benefits/flexible.html",
        {
            "request": request, "active": "benefits", "user": current_user,
            "benefits": benefits, "year": year, "years": years,
            "employees": employees, "categories": BENEFIT_CATEGORIES,
            "unread_count": unread_count,
        },
    )


@router.post("/flexible/assign")
async def assign_flexible_benefit(
    employee_id: str = Form(...),
    year: int = Form(...),
    total_points: int = Form(...),
    notes: str = Form(""),
    current_user: HRUser = Depends(require_hr_admin),
    db: Session = Depends(get_db),
):
    existing = db.query(FlexibleBenefit).filter(
        FlexibleBenefit.employee_id == employee_id,
        FlexibleBenefit.year == year,
    ).first()
    if existing:
        existing.total_points = total_points
        existing.notes = notes or None
    else:
        db.add(FlexibleBenefit(
            employee_id=employee_id, year=year,
            total_points=total_points, notes=notes or None,
        ))
    db.commit()
    return RedirectResponse(url=f"/benefits/flexible?year={year}", status_code=302)


@router.get("/flexible/{benefit_id}", response_class=HTMLResponse)
async def flexible_detail(
    benefit_id: str,
    request: Request,
    current_user: HRUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    benefit = db.query(FlexibleBenefit).filter(FlexibleBenefit.id == benefit_id).first()
    if not benefit:
        raise HTTPException(status_code=404)
    if current_user.role == "employee":
        if not current_user.employee or current_user.employee.id != benefit.employee_id:
            raise HTTPException(status_code=403)

    unread_count = db.query(func.count(Notification.id)).filter(
        Notification.user_id == current_user.id, Notification.is_read == False
    ).scalar() or 0

    return templates.TemplateResponse(
        "benefits/flexible_detail.html",
        {
            "request": request, "active": "benefits", "user": current_user,
            "benefit": benefit, "categories": BENEFIT_CATEGORIES, "unread_count": unread_count,
        },
    )


@router.post("/flexible/{benefit_id}/spend")
async def add_spending(
    benefit_id: str,
    category: str = Form("diger"),
    description: str = Form(...),
    points: int = Form(...),
    spend_date: str = Form(...),
    current_user: HRUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    benefit = db.query(FlexibleBenefit).filter(FlexibleBenefit.id == benefit_id).first()
    if not benefit:
        raise HTTPException(status_code=404)

    # Çalışan sadece kendi hakkında
    if current_user.role == "employee":
        if not current_user.employee or current_user.employee.id != benefit.employee_id:
            raise HTTPException(status_code=403)

    if benefit.remaining_points < points:
        raise HTTPException(status_code=400, detail="Yetersiz puan bakiyesi")

    spending = BenefitSpending(
        flexible_benefit_id=benefit_id,
        category=category,
        description=description,
        points=points,
        spend_date=date.fromisoformat(spend_date),
    )
    db.add(spending)
    benefit.used_points += points
    db.commit()
    return RedirectResponse(url=f"/benefits/flexible/{benefit_id}", status_code=302)


@router.post("/flexible/{benefit_id}/spendings/{spending_id}/delete")
async def delete_spending(
    benefit_id: str,
    spending_id: str,
    current_user: HRUser = Depends(require_hr_admin),
    db: Session = Depends(get_db),
):
    spending = db.query(BenefitSpending).filter(BenefitSpending.id == spending_id).first()
    if spending:
        benefit = db.query(FlexibleBenefit).filter(FlexibleBenefit.id == benefit_id).first()
        if benefit:
            benefit.used_points = max(0, benefit.used_points - spending.points)
        db.delete(spending)
        db.commit()
    return RedirectResponse(url=f"/benefits/flexible/{benefit_id}", status_code=302)
