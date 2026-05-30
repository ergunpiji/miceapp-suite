"""
Demo hesap sıfırlama endpoint'i
POST /admin/reset-demo?token=<DEMO_RESET_SECRET>
Kimlik doğrulama: URL token (Railway cron veya manuel curl)
"""

import os
from datetime import datetime

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text

from database import SessionLocal, _seed_demo_company
from models import Company

router = APIRouter(tags=["admin"])

# Demo şirkete ait tüm veriler bu sırada silinir (FK bağımlılıkları nedeniyle)
_DEMO_TABLES_IN_ORDER = [
    "invoice_payments",
    "vendor_prepayments",
    "payment_instructions",
    "manual_payment_lines",
    "invoices",
    "hbf_forms",
    "cash_entries",
    "bank_movements",
    "employee_advances",
    "leave_requests",
    "leave_balances",
    "salary_payments",
    "employee_benefits",
    "employee_personal_info",
    "employee_assets",
    "employee_documents",
    "employee_career_events",
    "payroll_records",
    "payroll_decisions",
    "employees",
    '"references"',
    "customer_prepayments",
    "customers",
    "financial_vendors",
    "general_expenses",
    "general_expense_categories",
    "fund_transfers",
    "fund_pools",
    "annual_budgets",
    "budget_lines",
    "fixed_expenses",
    "cheques",
    "credit_card_txns",
    "credit_card_statements",
    "credit_cards",
    "bank_accounts",
    "cash_day_closes",
    "cash_books",
    "notifications",
    "users",
]


@router.post("/admin/reset-demo", name="admin_reset_demo")
async def reset_demo(token: str = Query(...)):
    """Demo şirketin tüm verisini siler ve yeniden seed eder."""
    secret = os.environ.get("DEMO_RESET_SECRET", "")
    if not secret or token != secret:
        return JSONResponse({"ok": False, "error": "Yetkisiz"}, status_code=403)

    db = SessionLocal()
    try:
        demo = db.query(Company).filter_by(name="Demo A.Ş.").first()
        if not demo:
            return JSONResponse({"ok": False, "error": "Demo şirket bulunamadı"}, status_code=404)
        cid = demo.id

        for tbl in _DEMO_TABLES_IN_ORDER:
            try:
                db.execute(text(f"DELETE FROM {tbl} WHERE company_id = :cid"), {"cid": cid})
                db.commit()
            except Exception as e:
                db.rollback()
                print(f"[reset-demo] {tbl} silinemedi: {e}", flush=True)

        demo.demo_reset_at = datetime.utcnow()
        db.commit()
        print(f"[reset-demo] Demo A.Ş. (id={cid}) sıfırlandı.", flush=True)
    except Exception as exc:
        db.rollback()
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
    finally:
        db.close()

    # Yeni örnek veri ekle
    _seed_demo_company()
    return JSONResponse({"ok": True, "reset_at": datetime.utcnow().isoformat()})
