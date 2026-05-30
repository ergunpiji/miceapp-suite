"""
Backup SQLite'dan Railway PostgreSQL'e demo veri yükler.

Kullanım:
  DATABASE_URL="postgresql://..." python3 scripts/restore_from_backup.py

SQLite backup yolu SQLITE_PATH env ile override edilebilir.
Default: ~/Desktop/CLAUDE/E-Dem-backup-2026-04-29/edem.db
"""
import os
import sqlite3
import sys
from pathlib import Path

SQLITE_PATH = os.environ.get(
    "SQLITE_PATH",
    str(Path.home() / "Desktop/CLAUDE/E-Dem-backup-2026-04-29/edem.db"),
)
PG_URL = os.environ.get("DATABASE_URL", "").strip()

if not PG_URL:
    print("HATA: DATABASE_URL tanımlı değil.")
    print('Örnek: DATABASE_URL="postgresql://..." python3 scripts/restore_from_backup.py')
    sys.exit(1)

if PG_URL.startswith("postgres://"):
    PG_URL = PG_URL.replace("postgres://", "postgresql://", 1)

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    os.system(f"{sys.executable} -m pip install psycopg2-binary -q")
    import psycopg2
    import psycopg2.extras

print(f"[1] SQLite backup açılıyor: {SQLITE_PATH}")
src = sqlite3.connect(SQLITE_PATH)
src.row_factory = sqlite3.Row

print("[2] PostgreSQL'e bağlanılıyor...")
dst = psycopg2.connect(PG_URL)
dst.autocommit = False
cur = dst.cursor()


BOOL_COLS = {
    "event_types": {"active"},
    "users":       {"active"},
    "customers":   {"active"},
    "venues":      {"active"},
    "services":    {"active"},
}


def _railway_cols(table: str) -> set:
    """Railway'deki tablo sütun isimlerini döner."""
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name=%s",
        (table,),
    )
    return {row[0] for row in cur.fetchall()}


def _coerce(table: str, d: dict) -> dict:
    """SQLite 0/1 → Python bool (PostgreSQL BOOLEAN için)."""
    bool_fields = BOOL_COLS.get(table, set())
    return {
        k: bool(v) if k in bool_fields and v is not None else v
        for k, v in d.items()
    }


def _insert(table: str, row: sqlite3.Row, conflict_col: str = "id",
            allowed_cols: set | None = None, extra: dict | None = None) -> bool:
    d = _coerce(table, dict(row))
    if allowed_cols is not None:
        d = {k: v for k, v in d.items() if k in allowed_cols}
    if extra:
        d.update(extra)
    cols = ", ".join(d.keys())
    vals = ", ".join(["%s"] * len(d))
    sql = (
        f'INSERT INTO {table} ({cols}) VALUES ({vals}) '
        f'ON CONFLICT ({conflict_col}) DO NOTHING'
    )
    try:
        cur.execute(sql, list(d.values()))
        return cur.rowcount > 0
    except Exception as e:
        dst.rollback()
        print(f"  [!] {table} insert hatası: {e}")
        return False


totals = {}

# ── 1. Event types ──────────────────────────────────────────────────────────
# Backup ile Railway aynı IDs'e sahip olmayabilir; code unique.
# Çözüm: mevcut kod çakışan satırları sil, backup'tan yeniden ekle.
backup_et = src.execute("SELECT * FROM event_types").fetchall()
et_codes = [r["code"] for r in backup_et]
if et_codes:
    cur.execute(
        "DELETE FROM event_types WHERE code = ANY(%s)",
        (et_codes,),
    )
    dst.commit()

n = sum(1 for r in backup_et if _insert("event_types", r))
dst.commit()
totals["event_types"] = f"{n}/{len(backup_et)}"
print(f"  event_types:  {n}/{len(backup_et)} eklendi")

# ── 2. Users ─────────────────────────────────────────────────────────────────
# Backup UUID'leri requests.created_by FK'sı için şart; mevcut aynı email
# ama farklı UUID'li kayıtları sil, backup'tan yeniden ekle.
backup_users = src.execute("SELECT * FROM users").fetchall()
user_emails = [r["email"] for r in backup_users]
if user_emails:
    cur.execute(
        "DELETE FROM users WHERE email = ANY(%s)",
        (user_emails,),
    )
    dst.commit()

user_railway_cols = _railway_cols("users")
n = 0
for r in backup_users:
    d = {k: v for k, v in dict(r).items() if k in user_railway_cols}
    # org_title_id referans tutarsızlığı — NULL'a çek
    if "org_title_id" in d:
        d["org_title_id"] = None
    d = _coerce("users", d)
    cols = ", ".join(d.keys())
    vals = ", ".join(["%s"] * len(d))
    try:
        cur.execute(
            f"INSERT INTO users ({cols}) VALUES ({vals}) ON CONFLICT (id) DO NOTHING",
            list(d.values()),
        )
        if cur.rowcount > 0:
            n += 1
    except Exception as e:
        dst.rollback()
        print(f"  [!] users insert hatası: {e}")
dst.commit()
totals["users"] = f"{n}/{len(backup_users)}"
print(f"  users:        {n}/{len(backup_users)} eklendi")

# ── 3. Customers ─────────────────────────────────────────────────────────────
# Aynı şekilde: code eşleşen mevcut kayıtları sil, backup'tan yeniden ekle.
backup_cust = src.execute("SELECT * FROM customers").fetchall()
cust_codes = [r["code"] for r in backup_cust]
if cust_codes:
    cur.execute(
        "DELETE FROM customers WHERE code = ANY(%s)",
        (cust_codes,),
    )
    dst.commit()

cust_railway_cols = _railway_cols("customers")
n = 0
for r in backup_cust:
    d = {k: v for k, v in dict(r).items() if k in cust_railway_cols}
    if _insert.__wrapped__ if hasattr(_insert, "__wrapped__") else True:
        cols = ", ".join(d.keys())
        vals = ", ".join(["%s"] * len(d))
        try:
            cur.execute(
                f"INSERT INTO customers ({cols}) VALUES ({vals}) ON CONFLICT (id) DO NOTHING",
                list(d.values()),
            )
            if cur.rowcount > 0:
                n += 1
        except Exception as e:
            dst.rollback()
            print(f"  [!] customers insert hatası: {e}")
dst.commit()
totals["customers"] = f"{n}/{len(backup_cust)}"
print(f"  customers:    {n}/{len(backup_cust)} eklendi")

# ── 4. Venues ────────────────────────────────────────────────────────────────
rows = src.execute("SELECT * FROM venues").fetchall()
n = sum(1 for r in rows if _insert("venues", r))
dst.commit()
totals["venues"] = f"{n}/{len(rows)}"
print(f"  venues:       {n}/{len(rows)} eklendi")

# ── 5. Services ──────────────────────────────────────────────────────────────
rows = src.execute("SELECT * FROM services").fetchall()
n = sum(1 for r in rows if _insert("services", r))
dst.commit()
totals["services"] = f"{n}/{len(rows)}"
print(f"  services:     {n}/{len(rows)} eklendi")

# ── 6. Requests ──────────────────────────────────────────────────────────────
req_railway_cols = _railway_cols("requests")
# Backup'ta olmayan ama Railway şemasında NOT NULL olan kolonlar
REQ_EXTRA = {
    "is_funded": False,
    "is_fund_pool": False,
}

rows = src.execute("SELECT * FROM requests").fetchall()
n = 0
for r in rows:
    d = {k: v for k, v in dict(r).items() if k in req_railway_cols}
    d.update(REQ_EXTRA)
    cols = ", ".join(d.keys())
    vals = ", ".join(["%s"] * len(d))
    try:
        cur.execute(
            f'INSERT INTO requests ({cols}) VALUES ({vals}) ON CONFLICT (id) DO NOTHING',
            list(d.values()),
        )
        if cur.rowcount > 0:
            n += 1
    except Exception as e:
        dst.rollback()
        print(f"  [!] requests insert hatası ({r['request_no']}): {e}")
dst.commit()
totals["requests"] = f"{n}/{len(rows)}"
print(f"  requests:     {n}/{len(rows)} eklendi")

# ── 7. Budgets ───────────────────────────────────────────────────────────────
rows = src.execute("SELECT * FROM budgets").fetchall()
n = sum(1 for r in rows if _insert("budgets", r))
dst.commit()
totals["budgets"] = f"{n}/{len(rows)}"
print(f"  budgets:      {n}/{len(rows)} eklendi")

# ── 8. Customers contacts_json fix ──────────────────────────────────────────
try:
    cur.execute("UPDATE customers SET contacts_json = '[]' WHERE contacts_json IS NULL OR contacts_json = ''")
    dst.commit()
except Exception:
    dst.rollback()

src.close()
cur.close()
dst.close()

print("\n✓ Tamamlandı:")
for k, v in totals.items():
    print(f"   {k:20s}: {v}")
