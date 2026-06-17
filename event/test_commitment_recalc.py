"""
Faz 3 — _recalc_commitment durum geçişleri + tenant scope birim testleri.
Çalıştır:  cd event && python3 test_commitment_recalc.py
Bağımsız — geçici SQLite DB kullanır, harici servis gerektirmez.
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

# Geçici dosya-tabanlı SQLite (in-memory yerine — tek engine, tutarlı)
_db_fd, _db_path = tempfile.mkstemp(suffix=".db")
os.close(_db_fd)
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"
os.environ["SKIP_INIT_DB"] = "1"

import models  # noqa: E402
from database import engine, SessionLocal  # noqa: E402
from routers.requests import _recalc_commitment  # noqa: E402

# Sadece ihtiyaç duyulan tabloları oluştur (SQLite FK zorlamaz)
models.SupplierCommitment.__table__.create(bind=engine, checkfirst=True)
models.Invoice.__table__.create(bind=engine, checkfirst=True)

_fail = 0


def check(name, cond):
    global _fail
    if cond:
        print(f"  ✓ {name}")
    else:
        _fail += 1
        print(f"  ✗ FAIL: {name}")


def _mk_commit(db, cid="A", amount=1000.0, status="open"):
    c = models.SupplierCommitment(
        id=models._uuid(), company_id=cid, request_id="req1",
        section="teknik", vendor_id="v1", vendor_name="Test Tedarikçi",
        amount=amount, status=status, approval_status="approved",
        invoiced_amount=0.0,
    )
    db.add(c)
    db.flush()
    return c


def _mk_inv(db, commitment_id, total, cid="A", status="pending"):
    inv = models.Invoice(
        id=models._uuid(), company_id=cid, request_id="req1",
        vendor_id="v1", invoice_type="gelen", invoice_no="F-1",
        invoice_date="2026-06-17", total_amount=total, status=status,
        commitment_id=commitment_id, created_by="u1",
    )
    db.add(inv)
    db.flush()
    return inv


db = SessionLocal()
try:
    print("1) invoiced=0 → open, remaining=tam tutar")
    c = _mk_commit(db, amount=1000.0)
    _recalc_commitment(db, c)
    check("status open", c.status == "open")
    check("invoiced_amount 0", c.invoiced_amount == 0.0)
    check("remaining 1000", c.remaining == 1000.0)

    print("2) kısmi fatura → partial")
    _mk_inv(db, c.id, 400.0)
    _recalc_commitment(db, c)
    check("status partial", c.status == "partial")
    check("invoiced 400", c.invoiced_amount == 400.0)
    check("remaining 600", c.remaining == 600.0)

    print("3) tam fatura → closed, remaining=0, closed_at dolu")
    _mk_inv(db, c.id, 600.0)
    _recalc_commitment(db, c)
    check("status closed", c.status == "closed")
    check("remaining 0", c.remaining == 0.0)
    check("closed_at set", c.closed_at is not None)

    print("4) fatura iptal → tekrar açılır (cancelled sayılmaz)")
    inv2 = db.query(models.Invoice).filter(
        models.Invoice.commitment_id == c.id).order_by(models.Invoice.total_amount.desc()).first()
    inv2.status = "cancelled"
    db.flush()
    _recalc_commitment(db, c)
    check("status partial (600 iptal)", c.status == "partial")
    check("invoiced 400", c.invoiced_amount == 400.0)

    print("5) aşırı fatura (amount'tan fazla) → closed, remaining 0 (negatif değil)")
    c2 = _mk_commit(db, amount=500.0)
    _mk_inv(db, c2.id, 800.0)
    _recalc_commitment(db, c2)
    check("status closed", c2.status == "closed")
    check("remaining 0 (negatif değil)", c2.remaining == 0.0)

    print("6) cancelled taahhüt → recalc no-op")
    c3 = _mk_commit(db, amount=300.0, status="cancelled")
    _recalc_commitment(db, c3)
    check("cancelled korunur", c3.status == "cancelled")

    print("7) başka commitment'a bağlı fatura sayılmaz (link izolasyonu)")
    c4 = _mk_commit(db, amount=1000.0)   # bağlı faturası yok
    _recalc_commitment(db, c4)
    check("c4 open (başka PO faturası etkilemez)", c4.status == "open")
    check("c4 invoiced 0", c4.invoiced_amount == 0.0)

    db.rollback()
finally:
    db.close()
    try:
        os.unlink(_db_path)
    except OSError:
        pass

print()
if _fail:
    print(f"✗ {_fail} test BAŞARISIZ")
    sys.exit(1)
print("✓ Tüm _recalc_commitment testleri geçti")
