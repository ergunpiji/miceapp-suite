"""
Bordro Modülü — Türkiye mevzuatına uygun SGK/GV/DV hesaplama
"""

import calendar
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import get_current_user, require_gm, get_company_id
from database import get_db
from models import (
    Employee, PayrollRecord, PayrollSettings,
    SalaryPayment, GeneralExpense, GeneralExpenseCategory,
    BankAccount, BankMovement, CashBook, CashEntry,
    LeaveRequest, LeaveType, PublicHoliday, User,
)
from templates_config import templates

router = APIRouter(prefix="/bordro", tags=["bordro"])


# ---------------------------------------------------------------------------
# 2026 Gelir Vergisi dilimleri (kümülatif yıllık matrah)
# ---------------------------------------------------------------------------

GV_BRACKETS_2026 = [
    (230_000,      0.15),
    (400_000,      0.20),
    (1_900_000,    0.27),
    (4_500_000,    0.35),
    (float("inf"), 0.40),
]


def _progressive_tax(cumulative: float) -> float:
    """Kümülatif GV matrahı üzerinden kümülatif vergi hesapla."""
    tax = 0.0
    prev = 0.0
    for limit, rate in GV_BRACKETS_2026:
        if cumulative <= prev:
            break
        taxable = min(cumulative, limit) - prev
        tax += taxable * rate
        prev = limit
    return tax


def _get_settings(db: Session, year: int, company_id: str = None) -> PayrollSettings:
    # Şirket bazlı kayıt ara
    if company_id:
        s = db.query(PayrollSettings).filter(
            PayrollSettings.year == year,
            PayrollSettings.company_id == company_id,
        ).first()
        if not s:
            # Yoksa global (company_id=NULL) kaydı klonla veya sıfırdan oluştur
            template = db.query(PayrollSettings).filter(
                PayrollSettings.year == year,
                PayrollSettings.company_id == None,  # noqa: E711
            ).first()
            if template:
                s = PayrollSettings(
                    year=year, company_id=company_id,
                    sgk_employee_rate=template.sgk_employee_rate,
                    sgk_employer_rate=template.sgk_employer_rate,
                    unemployment_emp_rate=template.unemployment_emp_rate,
                    unemployment_empl_rate=template.unemployment_empl_rate,
                    sgdp_employee_rate=template.sgdp_employee_rate,
                    sgdp_employer_rate=template.sgdp_employer_rate,
                    stamp_tax_rate=template.stamp_tax_rate,
                    gv_istisnasi=template.gv_istisnasi,
                    dv_istisnasi=template.dv_istisnasi,
                    kidem_tavan=template.kidem_tavan,
                    weekly_hours=template.weekly_hours,
                    asgari_ucret_brut=template.asgari_ucret_brut,
                )
            else:
                s = PayrollSettings(year=year, company_id=company_id)
            db.add(s)
            db.commit()
            db.refresh(s)
        return s
    # company_id yoksa global kaydı döndür (veya oluştur)
    s = db.query(PayrollSettings).filter(
        PayrollSettings.year == year,
        PayrollSettings.company_id == None,  # noqa: E711
    ).first()
    if not s:
        s = PayrollSettings(year=year, company_id=None)
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


def _get_salary_cat(db: Session) -> int:
    cat = db.query(GeneralExpenseCategory).filter_by(name="Maaş").first()
    if not cat:
        parent = db.query(GeneralExpenseCategory).filter_by(name="Personel").first()
        cat = GeneralExpenseCategory(name="Maaş", parent_id=parent.id if parent else None)
        db.add(cat)
        db.flush()
    return cat.id


def _clip_leave_days(r: "LeaveRequest", period_start: date, period_end: date) -> float:
    """Bir izin talebinin döneme düşen gün sayısını hesaplar (orantılı bölme)."""
    if r.start_date >= period_start and r.end_date <= period_end:
        return float(r.total_days)  # tamamen dönem içinde
    # Dönem dışına taşıyor — toplam süreye oranla kliple
    total_span = (r.end_date - r.start_date).days + 1
    if total_span <= 0:
        return 0.0
    clipped_start = max(r.start_date, period_start)
    clipped_end   = min(r.end_date, period_end)
    clipped_span  = (clipped_end - clipped_start).days + 1
    return round(r.total_days * clipped_span / total_span, 2)


def _unpaid_leave_days(db: Session, emp_id: str,
                       period_start: date, period_end: date) -> tuple[float, list]:
    """Dönem içindeki onaylı ücretsiz izin günlerini döner (NULL-safe)."""
    from sqlalchemy import or_
    rows = (
        db.query(LeaveRequest)
        .join(LeaveType, LeaveRequest.leave_type_id == LeaveType.id)
        .filter(
            LeaveRequest.employee_id == emp_id,
            LeaveRequest.status == "onaylandi",
            LeaveRequest.start_date <= period_end,
            LeaveRequest.end_date >= period_start,
            or_(LeaveRequest.payroll_processed == False,
                LeaveRequest.payroll_processed == None),  # NULL-safe
            LeaveType.is_paid == False,
        )
        .all()
    )
    total = sum(_clip_leave_days(r, period_start, period_end) for r in rows)
    return round(total, 1), rows


def _paid_leave_days(db: Session, emp_id: str,
                     period_start: date, period_end: date) -> float:
    """Dönem içindeki onaylı ücretli izin günlerini döner (bilgi amaçlı)."""
    rows = (
        db.query(LeaveRequest)
        .join(LeaveType, LeaveRequest.leave_type_id == LeaveType.id)
        .filter(
            LeaveRequest.employee_id == emp_id,
            LeaveRequest.status == "onaylandi",
            LeaveRequest.start_date <= period_end,
            LeaveRequest.end_date >= period_start,
            LeaveType.is_paid == True,
        )
        .all()
    )
    return round(sum(_clip_leave_days(r, period_start, period_end) for r in rows), 1)


def _calc_sgk_days(db: Session, period_start: date, period_end: date,
                   unpaid_days: float, paid_days: float) -> tuple[int, int, int, int]:
    """SGK günleri: (sgk_gun, fiili_calisma, hafta_tatili, resmi_tatil_weekday)."""
    year  = period_start.year
    month = period_start.month
    total_cal = calendar.monthrange(year, month)[1]

    # Hafta sonu (Cumartesi + Pazar)
    hafta = sum(1 for d in range(1, total_cal + 1)
                if date(year, month, d).weekday() >= 5)

    # Hafta içi resmi tatiller
    holidays = db.query(PublicHoliday).filter(
        PublicHoliday.date >= period_start,
        PublicHoliday.date <= period_end,
    ).all()
    resmi = sum(1 for h in holidays if h.date.weekday() < 5)

    # SGK günü: takvim günü (max 30) − ücretsiz izin günleri
    sgk_gun = max(0, min(total_cal, 30) - int(unpaid_days))

    # Fiili çalışma = SGK günü − hafta tatili − ücretli izin − ücretsiz izin
    fiili = max(0, sgk_gun - hafta - int(paid_days) - int(unpaid_days))

    return sgk_gun, fiili, hafta, resmi


def _calc_payroll(rec: PayrollRecord, s: PayrollSettings,
                  prev_cum_gv: float = 0.0) -> PayrollRecord:
    """PDF formülüne göre tüm hesaplama alanlarını doldurur."""
    gross          = rec.gross_salary or 0.0
    overtime_hours = rec.overtime_hours or 0.0
    unpaid_days    = rec.unpaid_leave_days or 0.0
    meal_nakit     = rec.meal_nakit or 0.0
    meal_ayni      = rec.meal_ayni or 0.0
    transport      = rec.transport or 0.0
    other_add      = rec.other_additions or 0.0
    adv_ded        = rec.advance_deduction or 0.0
    other_ded      = rec.other_deductions or 0.0

    daily_gross = gross / 30
    hourly = gross / (s.weekly_hours * 4.33) if s.weekly_hours else 0
    overtime_pay = round(hourly * 1.5 * overtime_hours, 2)

    normal_earnings = round(gross - unpaid_days * daily_gross, 2)
    total_gross = round(
        normal_earnings + meal_nakit + meal_ayni
        + transport + overtime_pay + other_add, 2
    )

    sgk_base = round(total_gross - meal_ayni, 2)

    if rec.is_retired_worker:
        sgk_emp   = round(sgk_base * s.sgdp_employee_rate, 2)
        unemp_emp = 0.0
        sgk_empl  = round(sgk_base * s.sgdp_employer_rate, 2)
        unemp_empl = 0.0
    else:
        sgk_emp   = round(sgk_base * s.sgk_employee_rate, 2)
        unemp_emp = round(sgk_base * s.unemployment_emp_rate, 2)
        sgk_empl  = round(sgk_base * s.sgk_employer_rate, 2)
        unemp_empl = round(sgk_base * s.unemployment_empl_rate, 2)

    gv_base = round(total_gross - meal_ayni - sgk_emp - unemp_emp, 2)
    cum_gv  = round(prev_cum_gv + gv_base, 2)
    income_tax = round(
        max(0.0, _progressive_tax(cum_gv)
            - _progressive_tax(prev_cum_gv)
            - s.gv_istisnasi), 2
    )

    dv_base   = round(total_gross - meal_ayni, 2)
    stamp_tax = round(max(0.0, dv_base * s.stamp_tax_rate - s.dv_istisnasi), 2)

    ele_gecen = round(
        total_gross - sgk_emp - unemp_emp - income_tax - stamp_tax
        - meal_ayni - adv_ded - other_ded, 2
    )
    employer_cost = round(total_gross + sgk_empl + unemp_empl, 2)

    rec.overtime_pay       = overtime_pay
    rec.normal_earnings    = normal_earnings
    rec.total_gross        = total_gross
    rec.sgk_base           = sgk_base
    rec.sgk_employee       = sgk_emp
    rec.unemployment_emp   = unemp_emp
    rec.sgk_employer       = sgk_empl
    rec.unemployment_empl  = unemp_empl
    rec.gv_base            = gv_base
    rec.cumulative_gv_base = cum_gv
    rec.income_tax         = income_tax
    rec.stamp_tax_base     = dv_base
    rec.stamp_tax          = stamp_tax
    rec.ele_gecen          = ele_gecen
    rec.employer_cost      = employer_cost
    rec.updated_at         = datetime.utcnow()
    return rec


def _prev_cum_gv(db: Session, emp_id: str, period: str, company_id: str = None) -> float:
    """Önceki ayların kümülatif GV matrahını döner."""
    year = int(period[:4])
    q = db.query(PayrollRecord).filter(
        PayrollRecord.employee_id == emp_id,
        PayrollRecord.period.like(f"{year}-%"),
        PayrollRecord.period < period,
        PayrollRecord.status != "taslak",
    )
    if company_id:
        q = q.filter(PayrollRecord.company_id == company_id)
    prev_recs = q.order_by(PayrollRecord.period).all()
    if not prev_recs:
        return 0.0
    return prev_recs[-1].cumulative_gv_base


# ---------------------------------------------------------------------------
# Kıdem / İhbar hesaplama yardımcıları
# ---------------------------------------------------------------------------

def _kidem_ihbar(emp: Employee, end_date: date, sustained_benefits: float = 0.0,
                 tavan: float = 49329.0):
    """Kıdem ve ihbar tazminatını hesapla. Döner: (kidem, ihbar, years, notice_weeks)"""
    start = emp.start_date
    delta = end_date - start
    years_exact = delta.days / 365.25
    # İşe başlama yılı tam yıl sayısı (1 yıldan az → 0)
    full_years = int(years_exact)

    daily_gross = (emp.gross_salary + sustained_benefits) / 30
    annual_gross_30 = daily_gross * 30  # 1 yıllık kıdem = 30 günlük brüt

    # Kıdem
    kidem = round(full_years * min(annual_gross_30, tavan), 2) if full_years >= 1 else 0.0

    # İhbar süresi (hafta)
    if years_exact < 0.5:
        notice_weeks = 2
    elif years_exact < 1.5:
        notice_weeks = 4
    elif years_exact < 3:
        notice_weeks = 6
    else:
        notice_weeks = 8
    ihbar = round(notice_weeks * 7 * daily_gross, 2)

    return kidem, ihbar, full_years, notice_weeks


# ---------------------------------------------------------------------------
# Listele
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse, name="bordro_list")
async def bordro_list(
    request: Request,
    period: str = None,
    current_user: User = Depends(require_gm),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    if not period:
        period = date.today().strftime("%Y-%m")

    records = (
        db.query(PayrollRecord)
        .filter(PayrollRecord.company_id == cid, PayrollRecord.period == period)
        .join(Employee, PayrollRecord.employee_id == Employee.id)
        .order_by(Employee.name)
        .all()
    )
    employees = db.query(Employee).filter(
        Employee.company_id == cid, Employee.active == True  # noqa: E712
    ).order_by(Employee.name).all()
    paid_emp_ids = {r.employee_id for r in records}
    unpaid_employees = [e for e in employees if e.id not in paid_emp_ids]

    total_net   = sum(r.ele_gecen for r in records)
    total_gross = sum(r.total_gross for r in records)
    total_cost  = sum(r.employer_cost for r in records)
    bank_accounts = db.query(BankAccount).filter(
        BankAccount.company_id == cid
    ).order_by(BankAccount.name).all()

    return templates.TemplateResponse("bordro/list.html", {
        "request": request, "current_user": current_user,
        "period": period,
        "records": records,
        "unpaid_employees": unpaid_employees,
        "total_net": total_net,
        "total_gross": total_gross,
        "total_cost": total_cost,
        "bank_accounts": bank_accounts,
        "page_title": f"Bordro — {period}",
    })


# ---------------------------------------------------------------------------
# Toplu taslak oluştur
# ---------------------------------------------------------------------------

@router.post("/generate", name="bordro_generate")
async def bordro_generate(
    request: Request,
    period: str = Form(...),
    current_user: User = Depends(require_gm),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    year = int(period[:4])
    month = int(period[5:])
    period_start = date(year, month, 1)
    period_end   = date(year, month, calendar.monthrange(year, month)[1])
    settings     = _get_settings(db, year, cid)

    employees = db.query(Employee).filter(
        Employee.company_id == cid, Employee.active == True  # noqa: E712
    ).all()
    for emp in employees:
        unpaid_days, _ = _unpaid_leave_days(db, emp.id, period_start, period_end)
        paid_days      = _paid_leave_days(db, emp.id, period_start, period_end)
        sgk_gun, fiili, hafta, resmi = _calc_sgk_days(
            db, period_start, period_end, unpaid_days, paid_days
        )
        prev_gv = _prev_cum_gv(db, emp.id, period, cid)

        existing = db.query(PayrollRecord).filter(
            PayrollRecord.company_id == cid,
            PayrollRecord.employee_id == emp.id,
            PayrollRecord.period == period,
        ).first()
        if existing:
            if existing.status == "taslak":
                existing.gross_salary      = emp.gross_salary
                existing.is_retired_worker = emp.is_retired
                existing.unpaid_leave_days = unpaid_days
                existing.paid_leave_days   = paid_days
                existing.sgk_gun           = sgk_gun
                existing.fiili_calisma_gun = fiili
                existing.hafta_tatili      = hafta
                existing.resmi_tatil_gun   = resmi
                existing.updated_at        = datetime.utcnow()
                _calc_payroll(existing, settings, prev_gv)
            continue

        rec = PayrollRecord(
            employee_id=emp.id,
            period=period,
            gross_salary=emp.gross_salary,
            is_retired_worker=emp.is_retired,
            unpaid_leave_days=unpaid_days,
            paid_leave_days=paid_days,
            sgk_gun=sgk_gun,
            fiili_calisma_gun=fiili,
            hafta_tatili=hafta,
            resmi_tatil_gun=resmi,
            company_id=cid,
        )
        _calc_payroll(rec, settings, prev_gv)
        db.add(rec)

    db.commit()
    return RedirectResponse(url=f"/bordro?period={period}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Ayarlar  (/{record_id}'den ÖNCE olmalı — route çakışmasını önler)
# ---------------------------------------------------------------------------

@router.get("/settings/edit", response_class=HTMLResponse, name="bordro_settings")
async def bordro_settings_get(
    request: Request,
    year: int = None,
    current_user: User = Depends(require_gm),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    year = year or date.today().year
    settings = _get_settings(db, year, cid)
    return templates.TemplateResponse("bordro/settings.html", {
        "request": request, "current_user": current_user,
        "settings": settings,
        "page_title": f"Bordro Ayarları — {year}",
    })


@router.post("/settings/edit", name="bordro_settings_post")
async def bordro_settings_post(
    year: int = Form(...),
    sgk_employee_rate: float      = Form(...),
    sgk_employer_rate: float      = Form(...),
    unemployment_emp_rate: float  = Form(...),
    unemployment_empl_rate: float = Form(...),
    sgdp_employee_rate: float     = Form(...),
    sgdp_employer_rate: float     = Form(...),
    stamp_tax_rate: float         = Form(...),
    gv_istisnasi: float           = Form(...),
    dv_istisnasi: float           = Form(...),
    kidem_tavan: float            = Form(...),
    weekly_hours: int             = Form(...),
    asgari_ucret_brut: float      = Form(...),
    current_user: User = Depends(require_gm),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    s = _get_settings(db, year, cid)
    s.sgk_employee_rate      = sgk_employee_rate
    s.sgk_employer_rate      = sgk_employer_rate
    s.unemployment_emp_rate  = unemployment_emp_rate
    s.unemployment_empl_rate = unemployment_empl_rate
    s.sgdp_employee_rate     = sgdp_employee_rate
    s.sgdp_employer_rate     = sgdp_employer_rate
    s.stamp_tax_rate         = stamp_tax_rate
    s.gv_istisnasi           = gv_istisnasi
    s.dv_istisnasi           = dv_istisnasi
    s.kidem_tavan            = kidem_tavan
    s.weekly_hours           = weekly_hours
    s.asgari_ucret_brut      = asgari_ucret_brut
    s.updated_at             = datetime.utcnow()
    db.commit()
    return RedirectResponse(url=f"/bordro/settings/edit?year={year}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Personel pusulalarım listesi  (/{record_id}'den ÖNCE olmalı)
# ---------------------------------------------------------------------------

@router.get("/pusulalarim", response_class=HTMLResponse, name="bordro_pusulalarim")
async def bordro_pusulalarim(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    emp = db.query(Employee).filter(
        Employee.company_id == cid,
        Employee.user_id == current_user.id,
        Employee.active == True,  # noqa: E712
    ).first()
    if not emp:
        raise HTTPException(404, "Personel kaydınız bulunamadı.")
    records = (
        db.query(PayrollRecord)
        .filter(
            PayrollRecord.company_id == cid,
            PayrollRecord.employee_id == emp.id,
            PayrollRecord.status != "taslak",
        )
        .order_by(PayrollRecord.period.desc())
        .all()
    )
    return templates.TemplateResponse("bordro/pusulalarim.html", {
        "request": request, "current_user": current_user,
        "emp": emp, "records": records,
        "page_title": "Pusulalarım",
    })


# ---------------------------------------------------------------------------
# Kıdem / İhbar  (/{record_id}'den ÖNCE olmalı — route çakışmasını önler)
# ---------------------------------------------------------------------------

@router.get("/kidem-ihbar", response_class=HTMLResponse, name="bordro_kidem_ihbar")
async def kidem_ihbar_page(
    request: Request,
    current_user: User = Depends(require_gm),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    employees = db.query(Employee).filter(
        Employee.company_id == cid, Employee.active == True  # noqa: E712
    ).order_by(Employee.name).all()
    return templates.TemplateResponse("bordro/kidem_ihbar.html", {
        "request": request, "current_user": current_user,
        "employees": employees,
        "today": date.today().isoformat(),
        "page_title": "Kıdem & İhbar Hesaplama",
    })


@router.get("/kidem-ihbar/calc", response_class=JSONResponse, name="bordro_kidem_ihbar_calc")
async def kidem_ihbar_calc(
    employee_id: str,
    end_date: str,
    sustained_benefits: float = 0.0,
    current_user: User = Depends(require_gm),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    emp = db.query(Employee).filter(
        Employee.company_id == cid, Employee.id == employee_id
    ).first()
    if not emp:
        raise HTTPException(404)
    year = date.today().year
    settings = _get_settings(db, year, cid)
    try:
        edate = date.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(400, "Geçersiz tarih.")
    kidem, ihbar, full_years, notice_weeks = _kidem_ihbar(
        emp, edate, sustained_benefits, settings.kidem_tavan
    )
    return {
        "kidem": kidem,
        "ihbar": ihbar,
        "full_years": full_years,
        "notice_weeks": notice_weeks,
        "daily_gross": round((emp.gross_salary + sustained_benefits) / 30, 2),
        "tavan": settings.kidem_tavan,
    }


# ---------------------------------------------------------------------------
# Detay — turnusol görünümü
# ---------------------------------------------------------------------------

@router.get("/{record_id}", response_class=HTMLResponse, name="bordro_detail")
async def bordro_detail(
    record_id: str,
    request: Request,
    current_user: User = Depends(require_gm),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    rec = db.query(PayrollRecord).filter(
        PayrollRecord.company_id == cid, PayrollRecord.id == record_id
    ).first()
    if not rec:
        raise HTTPException(404)
    settings = _get_settings(db, int(rec.period[:4]), cid)
    bank_accounts = db.query(BankAccount).filter(
        BankAccount.company_id == cid
    ).order_by(BankAccount.name).all()
    return templates.TemplateResponse("bordro/detail.html", {
        "request": request, "current_user": current_user,
        "rec": rec,
        "emp": rec.employee,
        "settings": settings,
        "bank_accounts": bank_accounts,
        "page_title": f"Bordro — {rec.employee.name} — {rec.period}",
    })


# ---------------------------------------------------------------------------
# Yazdır / PDF — personel + GM erişebilir
# ---------------------------------------------------------------------------

@router.get("/{record_id}/print", response_class=HTMLResponse, name="bordro_print")
async def bordro_print(
    record_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    rec = db.query(PayrollRecord).filter(
        PayrollRecord.company_id == cid, PayrollRecord.id == record_id
    ).first()
    if not rec:
        raise HTTPException(404)
    emp = rec.employee

    # Erişim: Admin/GM hepsini görebilir; çalışan sadece kendi pusulasını
    if not (current_user.is_admin or current_user.is_approver):
        if emp.user_id != current_user.id:
            raise HTTPException(403, "Bu pusulayı görme yetkiniz yok.")

    settings = _get_settings(db, int(rec.period[:4]), cid)

    # Gösterim için brüt GV hesapla (istisna uygulanmadan önce)
    prev_cum = round((rec.cumulative_gv_base or 0) - (rec.gv_base or 0), 2)
    gross_gv = round(max(0.0, _progressive_tax(rec.cumulative_gv_base or 0)
                         - _progressive_tax(prev_cum)), 2)
    gv_istisna_applied = round(min(settings.gv_istisnasi, gross_gv), 2)

    total_deductions = round(
        (rec.sgk_employee or 0) + (rec.unemployment_emp or 0)
        + (rec.income_tax or 0) + (rec.stamp_tax or 0)
        + (rec.meal_ayni or 0) + (rec.advance_deduction or 0)
        + (rec.other_deductions or 0), 2
    )
    from templates_config import company as company_fn
    co = {
        "name":       company_fn("name", "—"),
        "tax_number": company_fn("tax_number", ""),
        "tax_office": company_fn("tax_office", ""),
        "address":    company_fn("address", ""),
        "phone":      company_fn("phone", ""),
        "email":      company_fn("email", ""),
        "logo_path":      company_fn("logo_path", ""),
        "logo_dark_path": company_fn("logo_dark_path", ""),
    }
    return templates.TemplateResponse("bordro/print.html", {
        "request": request, "current_user": current_user,
        "rec": rec, "emp": emp, "settings": settings,
        "company": co,
        "gross_gv": gross_gv,
        "gv_istisna_applied": gv_istisna_applied,
        "total_deductions": total_deductions,
        "is_admin_view": current_user.is_admin or current_user.is_approver,
        "page_title": f"Ücret Pusulası — {emp.name} — {rec.period}",
    })


# ---------------------------------------------------------------------------
# Düzenle & yeniden hesapla
# ---------------------------------------------------------------------------

@router.post("/{record_id}/edit", name="bordro_edit")
async def bordro_edit(
    record_id: str,
    gross_salary: float    = Form(...),
    overtime_hours: float  = Form(0.0),
    meal_nakit: float      = Form(0.0),
    meal_ayni: float       = Form(0.0),
    transport: float       = Form(0.0),
    other_additions: float = Form(0.0),
    unpaid_leave_days: float = Form(0.0),
    advance_deduction: float = Form(0.0),
    other_deductions: float  = Form(0.0),
    is_retired_worker: bool  = Form(False),
    notes: str             = Form(""),
    current_user: User = Depends(require_gm),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    rec = db.query(PayrollRecord).filter(
        PayrollRecord.company_id == cid, PayrollRecord.id == record_id
    ).first()
    if not rec or rec.status == "odendi":
        raise HTTPException(400, "Kayıt bulunamadı veya ödenmiş.")

    year  = int(rec.period[:4])
    month = int(rec.period[5:])
    settings = _get_settings(db, year, cid)
    prev_gv  = _prev_cum_gv(db, rec.employee_id, rec.period, cid)
    period_start = date(year, month, 1)
    period_end   = date(year, month, calendar.monthrange(year, month)[1])

    sgk_gun, fiili, hafta, resmi = _calc_sgk_days(
        db, period_start, period_end, unpaid_leave_days,
        _paid_leave_days(db, rec.employee_id, period_start, period_end),
    )

    rec.gross_salary       = gross_salary
    rec.overtime_hours     = overtime_hours
    rec.meal_nakit         = meal_nakit
    rec.meal_ayni          = meal_ayni
    rec.transport          = transport
    rec.other_additions    = other_additions
    rec.unpaid_leave_days  = unpaid_leave_days
    rec.advance_deduction  = advance_deduction
    rec.other_deductions   = other_deductions
    rec.is_retired_worker  = is_retired_worker
    rec.notes              = notes.strip()
    rec.sgk_gun            = sgk_gun
    rec.fiili_calisma_gun  = fiili
    rec.hafta_tatili       = hafta
    rec.resmi_tatil_gun    = resmi

    _calc_payroll(rec, settings, prev_gv)
    db.commit()
    return RedirectResponse(url=f"/bordro/{record_id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Onayla
# ---------------------------------------------------------------------------

@router.post("/{record_id}/approve", name="bordro_approve")
async def bordro_approve(
    record_id: str,
    current_user: User = Depends(require_gm),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    rec = db.query(PayrollRecord).filter(
        PayrollRecord.company_id == cid, PayrollRecord.id == record_id
    ).first()
    if not rec or rec.status != "taslak":
        raise HTTPException(400)
    rec.status = "onaylandi"
    rec.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(url=f"/bordro/{record_id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Tek kayıt öde
# ---------------------------------------------------------------------------

@router.post("/{record_id}/pay", name="bordro_pay")
async def bordro_pay(
    record_id: str,
    payment_method: str = Form("banka"),
    bank_account_id: Optional[int] = Form(None),
    current_user: User = Depends(require_gm),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    rec = db.query(PayrollRecord).filter(
        PayrollRecord.company_id == cid, PayrollRecord.id == record_id
    ).first()
    if not rec or rec.status != "onaylandi":
        raise HTTPException(400, "Bordro onaylı değil.")

    emp = rec.employee
    year = int(rec.period[:4])
    month = int(rec.period[5:])
    period_start = date(year, month, 1)
    period_end   = date(year, month, calendar.monthrange(year, month)[1])

    cat_id = _get_salary_cat(db)
    paid_at   = datetime.utcnow()
    paid_date = paid_at.date()

    expense = GeneralExpense(
        category_id=cat_id,
        expense_date=paid_date,
        amount=rec.ele_gecen,
        payment_method=payment_method,
        employee_id=emp.id,
        source="salary",
        description=f"Bordro — {emp.name} — {rec.period}",
        created_by=current_user.id,
        company_id=cid,
    )
    db.add(expense)
    db.flush()

    sp = SalaryPayment(
        employee_id=emp.id,
        period=rec.period,
        gross_amount=rec.total_gross,
        net_amount=rec.ele_gecen,
        payment_method=payment_method,
        bank_account_id=bank_account_id if payment_method == "banka" else None,
        paid_at=paid_at,
        general_expense_id=expense.id,
        notes=f"Bordro #{rec.id}",
    )
    db.add(sp)
    db.flush()

    if payment_method == "banka" and bank_account_id:
        db.add(BankMovement(
            account_id=bank_account_id,
            movement_date=paid_date,
            movement_type="cikis",
            amount=rec.ele_gecen,
            description=f"Bordro — {emp.name} — {rec.period}",
            company_id=cid,
        ))
    else:
        book = db.query(CashBook).filter(CashBook.company_id == cid).first()
        if book:
            db.add(CashEntry(
                book_id=book.id,
                entry_date=paid_date,
                entry_type="cikis",
                amount=rec.ele_gecen,
                description=f"Bordro — {emp.name} — {rec.period}",
                company_id=cid,
            ))

    rec.salary_payment_id = sp.id
    rec.status = "odendi"
    rec.updated_at = datetime.utcnow()

    # Ücretsiz izinleri işlendi olarak işaretle
    _, unpaid_leaves = _unpaid_leave_days(db, emp.id, period_start, period_end)
    for lr in unpaid_leaves:
        lr.payroll_processed = True

    db.commit()
    return RedirectResponse(url=f"/bordro/{rec.id}", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Toplu ödeme
# ---------------------------------------------------------------------------

@router.post("/pay-all", name="bordro_pay_all")
async def bordro_pay_all(
    period: str = Form(...),
    payment_method: str = Form("banka"),
    bank_account_id: Optional[int] = Form(None),
    current_user: User = Depends(require_gm),
    db: Session = Depends(get_db),
    cid: int = Depends(get_company_id),
):
    year  = int(period[:4])
    month = int(period[5:])
    period_start = date(year, month, 1)
    period_end   = date(year, month, calendar.monthrange(year, month)[1])

    records = db.query(PayrollRecord).filter(
        PayrollRecord.company_id == cid,
        PayrollRecord.period == period,
        PayrollRecord.status == "onaylandi",
    ).all()
    if not records:
        return RedirectResponse(url=f"/bordro?period={period}", status_code=status.HTTP_302_FOUND)

    cat_id    = _get_salary_cat(db)
    paid_at   = datetime.utcnow()
    paid_date = paid_at.date()
    total     = sum(r.ele_gecen for r in records)

    # Tek banka/kasa hareketi (toplam)
    if payment_method == "banka" and bank_account_id:
        db.add(BankMovement(
            account_id=bank_account_id,
            movement_date=paid_date,
            movement_type="cikis",
            amount=total,
            description=f"Toplu Bordro — {period} — {len(records)} çalışan",
            company_id=cid,
        ))
    else:
        book = db.query(CashBook).filter(CashBook.company_id == cid).first()
        if book:
            db.add(CashEntry(
                book_id=book.id,
                entry_date=paid_date,
                entry_type="cikis",
                amount=total,
                description=f"Toplu Bordro — {period} — {len(records)} çalışan",
                company_id=cid,
            ))

    for rec in records:
        emp = rec.employee
        expense = GeneralExpense(
            category_id=cat_id,
            expense_date=paid_date,
            amount=rec.ele_gecen,
            payment_method=payment_method,
            employee_id=emp.id,
            source="salary",
            description=f"Bordro — {emp.name} — {rec.period}",
            created_by=current_user.id,
            company_id=cid,
        )
        db.add(expense)
        db.flush()

        sp = SalaryPayment(
            employee_id=emp.id,
            period=rec.period,
            gross_amount=rec.total_gross,
            net_amount=rec.ele_gecen,
            payment_method=payment_method,
            bank_account_id=bank_account_id if payment_method == "banka" else None,
            paid_at=paid_at,
            general_expense_id=expense.id,
            notes=f"Bordro #{rec.id} — toplu",
        )
        db.add(sp)
        db.flush()

        rec.salary_payment_id = sp.id
        rec.status = "odendi"
        rec.updated_at = datetime.utcnow()

        _, unpaid_leaves = _unpaid_leave_days(db, emp.id, period_start, period_end)
        for lr in unpaid_leaves:
            lr.payroll_processed = True

    db.commit()
    return RedirectResponse(url=f"/bordro?period={period}", status_code=status.HTTP_302_FOUND)
