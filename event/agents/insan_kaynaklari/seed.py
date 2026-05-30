"""HR Ajanı — Başlangıç verileri (seed)."""
from datetime import date

from sqlalchemy.orm import Session

from auth import hash_password
from models import Employee, FlexibleBenefit, HRUser, LeaveBalance


def seed_data(db: Session) -> None:
    if db.query(HRUser).count() > 0:
        return  # Zaten seed edilmiş

    # --- Demo çalışanlar ---
    employees = [
        Employee(
            employee_no="EMP-001",
            first_name="Ayşe",
            last_name="Yılmaz",
            email="ayse.yilmaz@sirket.com",
            phone="0532 111 22 33",
            hire_date=date(2020, 3, 1),
            department="İnsan Kaynakları",
            title="HR Direktörü",
            employment_type="tam_zamanli",
            status="aktif",
            annual_leave_days=21,
            gross_salary=75000.0,
        ),
        Employee(
            employee_no="EMP-002",
            first_name="Mehmet",
            last_name="Demir",
            email="mehmet.demir@sirket.com",
            phone="0533 222 33 44",
            hire_date=date(2021, 6, 15),
            department="Yazılım",
            title="Kıdemli Yazılım Geliştirici",
            employment_type="tam_zamanli",
            status="aktif",
            annual_leave_days=14,
            gross_salary=60000.0,
        ),
        Employee(
            employee_no="EMP-003",
            first_name="Zeynep",
            last_name="Kaya",
            email="zeynep.kaya@sirket.com",
            phone="0534 333 44 55",
            hire_date=date(2022, 9, 1),
            department="Pazarlama",
            title="Pazarlama Uzmanı",
            employment_type="tam_zamanli",
            status="aktif",
            annual_leave_days=14,
            gross_salary=45000.0,
        ),
        Employee(
            employee_no="EMP-004",
            first_name="Ali",
            last_name="Çelik",
            email="ali.celik@sirket.com",
            phone="0535 444 55 66",
            hire_date=date(2023, 2, 1),
            department="Finans",
            title="Muhasebe Uzmanı",
            employment_type="tam_zamanli",
            status="aktif",
            annual_leave_days=14,
            gross_salary=50000.0,
        ),
        Employee(
            employee_no="EMP-005",
            first_name="Fatma",
            last_name="Şahin",
            email="fatma.sahin@sirket.com",
            phone="0536 555 66 77",
            hire_date=date(2024, 1, 15),
            department="Yazılım",
            title="Junior Yazılım Geliştirici",
            employment_type="tam_zamanli",
            status="aktif",
            annual_leave_days=14,
            gross_salary=35000.0,
        ),
    ]
    db.add_all(employees)
    db.flush()  # ID'leri almak için flush

    # --- Kullanıcılar ---
    users = [
        HRUser(
            email="hr.admin@sirket.com",
            hashed_password=hash_password("Admin123"),
            role="hr_admin",
            employee_id=employees[0].id,
        ),
        HRUser(
            email="hr.manager@sirket.com",
            hashed_password=hash_password("Manager123"),
            role="hr_manager",
            employee_id=employees[1].id,
        ),
        HRUser(
            email="zeynep.kaya@sirket.com",
            hashed_password=hash_password("Employee123"),
            role="employee",
            employee_id=employees[2].id,
        ),
        HRUser(
            email="ali.celik@sirket.com",
            hashed_password=hash_password("Employee123"),
            role="employee",
            employee_id=employees[3].id,
        ),
        HRUser(
            email="fatma.sahin@sirket.com",
            hashed_password=hash_password("Employee123"),
            role="employee",
            employee_id=employees[4].id,
        ),
    ]
    db.add_all(users)
    db.flush()

    # --- Yönetici ilişkisini kur (Mehmet'in yöneticisi Ayşe) ---
    employees[1].manager_id = employees[0].id
    employees[2].manager_id = employees[0].id
    employees[3].manager_id = employees[0].id
    employees[4].manager_id = employees[1].id

    # --- Bu yıl için izin bakiyeleri ---
    current_year = date.today().year
    for emp in employees:
        db.add(LeaveBalance(
            employee_id=emp.id,
            year=current_year,
            total_days=emp.annual_leave_days,
            used_days=0,
            pending_days=0,
        ))

    # --- Esnek yan hak havuzları (1000 puan/yıl) ---
    for emp in employees:
        db.add(FlexibleBenefit(
            employee_id=emp.id,
            year=current_year,
            total_points=1000,
            used_points=0,
        ))

    db.commit()
    print("✅ HR Ajanı seed verisi oluşturuldu.")
    print("   hr.admin@sirket.com    / Admin123")
    print("   hr.manager@sirket.com  / Manager123")
    print("   zeynep.kaya@sirket.com / Employee123")
