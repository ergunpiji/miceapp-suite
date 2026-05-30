"""HR Ajanı — Bordro ve Fazla Mesai."""
from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_current_user, require_hr_admin, require_hr_manager_or_admin
from database import get_db
from models import (
    OVERTIME_RATES, PAYROLL_STATUSES,
    Employee, HRUser, Notification, OvertimeRecord, PayrollRecord,
)
from routers.notifications import create_notification
from templates_config import templates

router = APIRouter(prefix="/payroll", tags=["payroll"])

# ---------------------------------------------------------------------------
# Türkiye 2026 Bordro Sabitleri
# ---------------------------------------------------------------------------
SGK_EMPLOYEE_RATE   = 0.075   # Çalışan SGK payı (7.5%)
SGK_EMPLOYER_RATE   = 0.2475  # Teşvikli işveren SGK (24.75%)
STAMP_TAX_RATE      = 0.00759

# Asgari ücret GV/DV aylık istisna tutarları (2026)
ASGARI_GV_ISTISNASI = 4_211.33
ASGARI_DV_ISTISNASI = 250.70

# Gelir Vergisi kümülatif yıllık dilimleri (2026)
GV_BRACKETS_2026 = [
    (230_000,       0.15),
    (400_000,       0.20),
    (1_900_000,     0.27),
    (4_500_000,     0.35),
    (float("inf"),  0.40),
]


def _calc_cumulative_gv(cumulative_base: float) -> float:
    """Kümülatif yıllık matrah üzerinden GV hesabı (istisna uygulanmadan)."""
    tax = 0.0
    prev = 0.0
    for limit, rate in GV_BRACKETS_2026:
        if cumulative_base <= prev:
            break
        tax += (min(cumulative_base, limit) - prev) * rate
        prev = limit
    return round(tax, 2)


def _calc_payroll(
    gross: float,
    overtime_pay: float = 0.0,
    meal_ayni: float = 0.0,       # Ayni yemek — SGK/GV matrahına dahil değil, ödenmiyor
    meal_nakit: float = 0.0,      # Nakit yemek — SGK/GV matrahına dahil
    other_additions: float = 0.0, # Diğer ekler (dil tazminatı vb.) — SGK/GV dahil
    prev_cumulative_gv: float = 0.0,  # Önceki aydan devreden kümülatif GV matrahı
) -> dict:
    """PDF turnusolüne göre tam bordro hesabı."""

    # 1. Tüm Gelirler Toplamı
    total_gross = round(gross + overtime_pay + meal_ayni + meal_nakit + other_additions, 2)

    # 2. SGK Aylık Matrahı (ayni yardım SGK'dan muaf)
    sgk_base = round(total_gross - meal_ayni, 2)

    # 3. SGK Kesintileri
    sgk_emp  = round(sgk_base * SGK_EMPLOYEE_RATE, 2)
    sgk_empr = round(sgk_base * SGK_EMPLOYER_RATE, 2)

    # 4. GV Aylık Matrahı
    gv_base = round(sgk_base - sgk_emp, 2)

    # 5. Kümülatif GV hesabı
    cumulative_gv = round(prev_cumulative_gv + gv_base, 2)
    gv_raw = _calc_cumulative_gv(cumulative_gv) - _calc_cumulative_gv(prev_cumulative_gv)
    income_tax = round(max(0.0, gv_raw - ASGARI_GV_ISTISNASI), 2)

    # 6. Damga Vergisi
    dv_base = sgk_base  # DV matrahı = SGK matrahı
    stamp_tax = round(max(0.0, dv_base * STAMP_TAX_RATE - ASGARI_DV_ISTISNASI), 2)

    # 7. Ele Geçen Ücret (nakit ödemeler - kesintiler)
    ele_gecen = round(total_gross - sgk_emp - income_tax - stamp_tax - meal_ayni, 2)

    # 8. Net Maaş (çalışanın eline geçen - özel kesintiler = ele_gecen bu senaryoda)
    net = ele_gecen

    return {
        "gross_salary":             gross,
        "overtime_pay":             overtime_pay,
        "meal_allowance":           meal_nakit,
        "meal_allowance_ayni":      meal_ayni,
        "other_additions":          other_additions,
        "total_gross":              total_gross,
        "sgk_monthly_base":         sgk_base,
        "sgk_employee":             sgk_emp,
        "sgk_employer":             sgk_empr,
        "gv_monthly_base":          gv_base,
        "cumulative_gv_base":       cumulative_gv,
        "asgari_ucret_istisnasi_gv": ASGARI_GV_ISTISNASI,
        "asgari_ucret_istisnasi_dv": ASGARI_DV_ISTISNASI,
        "income_tax":               income_tax,
        "stamp_tax":                stamp_tax,
        "ele_gecen_ucret":          ele_gecen,
        "net_salary":               net,
    }


@router.get("", response_class=HTMLResponse)
async def list_payrolls(
    request: Request,
    year: int = 0,
    month: int = 0,
    status: str = "",
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

    query = db.query(PayrollRecord).filter(
        PayrollRecord.period_year == year,
        PayrollRecord.period_month == month,
    )
    if current_user.role == "employee" and current_user.employee:
        query = query.filter(PayrollRecord.employee_id == current_user.employee.id)
    if status:
        query = query.filter(PayrollRecord.status == status)

    payrolls = query.order_by(PayrollRecord.employee_id).all()
    years = list(range(today.year - 2, today.year + 1))

    return templates.TemplateResponse(
        "payroll/list.html",
        {
            "request": request, "active": "payroll", "user": current_user,
            "payrolls": payrolls, "year": year, "month": month, "status_filter": status,
            "years": years, "payroll_statuses": PAYROLL_STATUSES,
            "unread_count": unread_count,
        },
    )


@router.post("/generate")
async def generate_payrolls(
    year: int = Form(...),
    month: int = Form(...),
    current_user: HRUser = Depends(require_hr_admin),
    db: Session = Depends(get_db),
):
    """Belirtilen ay için tüm aktif çalışanlara taslak bordro oluşturur."""
    employees = db.query(Employee).filter(Employee.status == "aktif").all()
    created = 0
    for emp in employees:
        existing = db.query(PayrollRecord).filter(
            PayrollRecord.employee_id == emp.id,
            PayrollRecord.period_year == year,
            PayrollRecord.period_month == month,
        ).first()
        if existing:
            continue

        # O ay onaylı overtime
        from sqlalchemy import extract
        overtime_records = db.query(OvertimeRecord).filter(
            OvertimeRecord.employee_id == emp.id,
            OvertimeRecord.status == "onaylandi",
            OvertimeRecord.payroll_id == None,
            extract("year", OvertimeRecord.work_date) == year,
            extract("month", OvertimeRecord.work_date) == month,
        ).all()

        hourly_rate = emp.gross_salary / 225  # Aylık 225 saatlik standart
        overtime_pay = sum(r.hours * hourly_rate * r.rate for r in overtime_records)

        # Son yemek kartı yüklemesini al (ayni olarak işle)
        from models import MealCard
        last_meal = (
            db.query(MealCard)
            .filter(
                MealCard.employee_id == emp.id,
                MealCard.period_year == year,
                MealCard.period_month == month,
            )
            .first()
        )
        meal_ayni = last_meal.amount if last_meal else 0.0

        # Önceki aydan kümülatif GV matrahını al
        prev_month = month - 1
        prev_year = year
        if prev_month == 0:
            prev_month = 12
            prev_year = year - 1

        prev_pr = db.query(PayrollRecord).filter(
            PayrollRecord.employee_id == emp.id,
            PayrollRecord.period_year == prev_year,
            PayrollRecord.period_month == prev_month,
        ).first()
        prev_cumulative_gv = prev_pr.cumulative_gv_base if prev_pr else 0.0

        calc = _calc_payroll(
            emp.gross_salary,
            overtime_pay=overtime_pay,
            meal_ayni=meal_ayni,
            prev_cumulative_gv=prev_cumulative_gv,
        )
        pr = PayrollRecord(
            employee_id=emp.id,
            period_year=year,
            period_month=month,
            **calc,
        )
        db.add(pr)
        db.flush()

        # Overtime'ları bordroyla eşleştir
        for r in overtime_records:
            r.payroll_id = pr.id

        created += 1

    db.commit()
    return RedirectResponse(url=f"/payroll?year={year}&month={month}", status_code=302)


@router.get("/{payroll_id}", response_class=HTMLResponse)
async def payroll_detail(
    payroll_id: str,
    request: Request,
    current_user: HRUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pr = db.query(PayrollRecord).filter(PayrollRecord.id == payroll_id).first()
    if not pr:
        raise HTTPException(status_code=404)
    if current_user.role == "employee":
        if not current_user.employee or current_user.employee.id != pr.employee_id:
            raise HTTPException(status_code=403)

    unread_count = db.query(func.count(Notification.id)).filter(
        Notification.user_id == current_user.id, Notification.is_read == False
    ).scalar() or 0

    # Bu bordrodaki overtime kayıtları
    overtime_rows = db.query(OvertimeRecord).filter(OvertimeRecord.payroll_id == payroll_id).all()

    return templates.TemplateResponse(
        "payroll/detail.html",
        {
            "request": request, "active": "payroll", "user": current_user,
            "payroll": pr, "overtime_rows": overtime_rows, "unread_count": unread_count,
            "SGK_EMPLOYEE_RATE": SGK_EMPLOYEE_RATE,
            "SGK_EMPLOYER_RATE": SGK_EMPLOYER_RATE,
            "prev_cumulative_gv": round(pr.cumulative_gv_base - pr.gv_monthly_base, 2),
        },
    )


@router.post("/{payroll_id}/edit")
async def edit_payroll(
    payroll_id: str,
    gross_salary: float = Form(...),
    meal_allowance_ayni: float = Form(0.0),
    meal_allowance: float = Form(0.0),
    other_additions: float = Form(0.0),
    other_deductions: float = Form(0.0),
    notes: str = Form(""),
    current_user: HRUser = Depends(require_hr_admin),
    db: Session = Depends(get_db),
):
    pr = db.query(PayrollRecord).filter(PayrollRecord.id == payroll_id).first()
    if not pr or pr.status != "taslak":
        raise HTTPException(status_code=400, detail="Sadece taslak bordro düzenlenebilir")

    # Önceki aydan kümülatif GV'yi tekrar hesapla
    prev_month = pr.period_month - 1
    prev_year = pr.period_year
    if prev_month == 0:
        prev_month = 12
        prev_year = pr.period_year - 1
    prev_pr = db.query(PayrollRecord).filter(
        PayrollRecord.employee_id == pr.employee_id,
        PayrollRecord.period_year == prev_year,
        PayrollRecord.period_month == prev_month,
    ).first()
    prev_cumulative_gv = prev_pr.cumulative_gv_base if prev_pr else 0.0

    calc = _calc_payroll(
        gross=gross_salary,
        overtime_pay=pr.overtime_pay,
        meal_ayni=meal_allowance_ayni,
        meal_nakit=meal_allowance,
        other_additions=other_additions,
        prev_cumulative_gv=prev_cumulative_gv,
    )
    for k, v in calc.items():
        setattr(pr, k, v)
    pr.other_deductions = other_deductions
    pr.notes = notes or None
    pr.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(url=f"/payroll/{payroll_id}", status_code=302)


@router.post("/{payroll_id}/approve")
async def approve_payroll(
    payroll_id: str,
    current_user: HRUser = Depends(require_hr_admin),
    db: Session = Depends(get_db),
):
    pr = db.query(PayrollRecord).filter(PayrollRecord.id == payroll_id).first()
    if not pr or pr.status != "taslak":
        raise HTTPException(status_code=400)
    pr.status = "onaylandi"
    pr.updated_at = datetime.utcnow()

    emp = db.query(Employee).filter(Employee.id == pr.employee_id).first()
    if emp and emp.user:
        create_notification(
            db, emp.user.id, "bordro",
            f"{pr.period_label} Bordronuz Hazır",
            f"Net maaşınız: ₺{pr.net_salary:,.2f}",
            ref_type="payroll", ref_id=pr.id,
        )
    db.commit()
    return RedirectResponse(url=f"/payroll/{payroll_id}", status_code=302)


@router.post("/{payroll_id}/mark-paid")
async def mark_paid(
    payroll_id: str,
    payment_date: str = Form(...),
    current_user: HRUser = Depends(require_hr_admin),
    db: Session = Depends(get_db),
):
    pr = db.query(PayrollRecord).filter(PayrollRecord.id == payroll_id).first()
    if not pr or pr.status != "onaylandi":
        raise HTTPException(status_code=400)
    pr.status = "odendi"
    pr.payment_date = date.fromisoformat(payment_date)
    pr.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(url=f"/payroll/{payroll_id}", status_code=302)


# ---------------------------------------------------------------------------
# Fazla Mesai
# ---------------------------------------------------------------------------
@router.get("/overtime/list", response_class=HTMLResponse)
async def list_overtime(
    request: Request,
    status: str = "",
    current_user: HRUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    unread_count = db.query(func.count(Notification.id)).filter(
        Notification.user_id == current_user.id, Notification.is_read == False
    ).scalar() or 0

    query = db.query(OvertimeRecord)
    if current_user.role == "employee" and current_user.employee:
        query = query.filter(OvertimeRecord.employee_id == current_user.employee.id)
    if status:
        query = query.filter(OvertimeRecord.status == status)
    records = query.order_by(OvertimeRecord.work_date.desc()).all()

    return templates.TemplateResponse(
        "payroll/overtime.html",
        {
            "request": request, "active": "payroll", "user": current_user,
            "records": records, "status_filter": status, "unread_count": unread_count,
        },
    )


@router.post("/overtime/new")
async def create_overtime(
    employee_id: str = Form(""),
    work_date: str = Form(...),
    hours: float = Form(...),
    reason: str = Form(""),
    current_user: HRUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role == "employee":
        if not current_user.employee:
            raise HTTPException(status_code=400)
        employee_id = current_user.employee.id

    record = OvertimeRecord(
        employee_id=employee_id,
        work_date=date.fromisoformat(work_date),
        hours=hours,
        reason=reason or None,
        rate=1.5,
    )
    db.add(record)
    db.flush()

    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    managers = db.query(HRUser).filter(HRUser.role.in_(["hr_admin", "hr_manager"])).all()
    for mgr in managers:
        create_notification(
            db, mgr.id, "overtime_talebi",
            f"Overtime Talebi: {emp.full_name if emp else ''}",
            f"{work_date} tarihinde {hours} saat fazla mesai",
            ref_type="overtime", ref_id=record.id,
        )

    db.commit()
    return RedirectResponse(url="/payroll/overtime/list", status_code=302)


@router.post("/overtime/{record_id}/approve")
async def approve_overtime(
    record_id: str,
    rate: float = Form(1.5),
    current_user: HRUser = Depends(require_hr_manager_or_admin),
    db: Session = Depends(get_db),
):
    record = db.query(OvertimeRecord).filter(OvertimeRecord.id == record_id).first()
    if not record or record.status != "beklemede":
        raise HTTPException(status_code=400)
    record.status = "onaylandi"
    record.rate = rate
    record.approved_by = current_user.id
    record.approved_at = datetime.utcnow()

    emp = db.query(Employee).filter(Employee.id == record.employee_id).first()
    if emp and emp.user:
        create_notification(
            db, emp.user.id, "overtime_onay",
            "Overtime Talebiniz Onaylandı",
            f"{record.work_date.strftime('%d.%m.%Y')} tarihli {record.hours}s mesainiz onaylandı ({record.rate_label})",
            ref_type="overtime", ref_id=record.id,
        )

    db.commit()
    return RedirectResponse(url="/payroll/overtime/list", status_code=302)


@router.post("/overtime/{record_id}/reject")
async def reject_overtime(
    record_id: str,
    current_user: HRUser = Depends(require_hr_manager_or_admin),
    db: Session = Depends(get_db),
):
    record = db.query(OvertimeRecord).filter(OvertimeRecord.id == record_id).first()
    if not record or record.status != "beklemede":
        raise HTTPException(status_code=400)
    record.status = "reddedildi"
    record.approved_by = current_user.id
    record.approved_at = datetime.utcnow()

    emp = db.query(Employee).filter(Employee.id == record.employee_id).first()
    if emp and emp.user:
        create_notification(
            db, emp.user.id, "overtime_onay",
            "Overtime Talebiniz Reddedildi",
            f"{record.work_date.strftime('%d.%m.%Y')} tarihli mesai talebi reddedildi.",
            ref_type="overtime", ref_id=record.id,
        )

    db.commit()
    return RedirectResponse(url="/payroll/overtime/list", status_code=302)
