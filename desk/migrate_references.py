"""
Eski sistemden (requests tablosu) yeni sisteme (references tablosu) referans aktarır.

Kullanım:
  OLD_DB="postgresql://..." NEW_DB="postgresql://..." python3 migrate_references.py
  DRY_RUN=1  → yazmadan kontrol
"""
import os, sys

try:
    import psycopg2, psycopg2.extras
except ImportError:
    os.system(f"{sys.executable} -m pip install psycopg2-binary -q")
    import psycopg2, psycopg2.extras

OLD_DB  = os.environ.get("OLD_DB", "").strip()
NEW_DB  = os.environ.get("NEW_DB", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"

def fix(u): return u.replace("postgres://", "postgresql://", 1) if u.startswith("postgres://") else u

if not OLD_DB or not NEW_DB:
    print("HATA: OLD_DB ve NEW_DB gerekli."); sys.exit(1)

print("[1] Bağlanılıyor...")
old_conn = psycopg2.connect(fix(OLD_DB))
new_conn = psycopg2.connect(fix(NEW_DB))
old_cur  = old_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
new_cur  = new_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

# ── Yeni DB'de mevcut ref_no'lar ─────────────────────────────────────────────
new_cur.execute('SELECT ref_no FROM "references"')
existing = {r["ref_no"].strip().upper() for r in new_cur.fetchall()}
print(f"[2] Yeni DB mevcut referans: {len(existing)}")

# ── Eski müşteri eşleştirmesi (uuid → yeni int id, isim üzerinden) ────────────
old_cur.execute("SELECT id, name FROM customers")
old_customers = {r["id"]: (r["name"] or "").strip() for r in old_cur.fetchall()}

new_cur.execute("SELECT id, name FROM customers")
new_customers_by_name = {(r["name"] or "").strip().lower(): r["id"] for r in new_cur.fetchall()}

# ── Admin user ────────────────────────────────────────────────────────────────
new_cur.execute("SELECT id FROM users WHERE is_admin = TRUE ORDER BY id LIMIT 1")
admin_id = new_cur.fetchone()["id"]

# ── Status map ────────────────────────────────────────────────────────────────
STATUS_MAP = {
    "draft": "aktif", "pending": "aktif", "in_progress": "aktif",
    "venues_contacted": "aktif", "budget_ready": "aktif",
    "completed": "tamamlandi", "cancelled": "iptal",
}

# ── Event type map ────────────────────────────────────────────────────────────
EVENT_MAP = {
    "toplanti": "toplanti", "konferans": "konferans", "gala": "gala",
    "egitim": "egitim", "lansman": "lansman",
}

def norm_event(v):
    if not v: return "diger"
    v = str(v).lower().strip()
    return EVENT_MAP.get(v, "diger")

def norm_status(v):
    if not v: return "aktif"
    return STATUS_MAP.get(str(v).lower().strip(), "aktif")

# ── Eski requests çek ─────────────────────────────────────────────────────────
old_cur.execute("SELECT * FROM requests ORDER BY created_at")
rows = old_cur.fetchall()
print(f"[3] Eski DB'de {len(rows)} requests bulundu.\n")

inserted = skipped = errors = 0

for row in rows:
    try:
        ref_no = (row.get("request_no") or "").strip().upper()
        if not ref_no:
            print(f"  ATLA (request_no yok): id={row['id']}"); skipped += 1; continue

        if ref_no in existing:
            print(f"  ATLA (mevcut): {ref_no}"); skipped += 1; continue

        title      = (row.get("event_name") or ref_no).strip()[:300]
        event_type = norm_event(row.get("event_type"))
        status     = norm_status(row.get("status"))
        check_in   = row.get("check_in") or row.get("accom_check_in")
        check_out  = row.get("check_out") or row.get("accom_check_out")
        notes      = (row.get("notes") or "").strip()
        created_at = row.get("created_at")

        # Müşteri eşleştir
        old_cid = row.get("customer_id")
        new_cid = None
        if old_cid and old_cid in old_customers:
            cname = old_customers[old_cid].lower()
            new_cid = new_customers_by_name.get(cname)
            if not new_cid:
                print(f"  [UYR] Müşteri eşleşmedi: '{old_customers[old_cid]}' ({ref_no})")

        if DRY_RUN:
            print(f"  DRY: {ref_no} | {title[:50]} | {event_type} | {status} | {check_in}~{check_out} | müşteri→{new_cid}")
            inserted += 1; existing.add(ref_no); continue

        new_cur.execute("""
            INSERT INTO "references" (ref_no, customer_id, title, event_type, check_in, check_out,
                                      status, notes, created_by, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (ref_no, new_cid, title, event_type, check_in, check_out,
              status, notes, admin_id, created_at))
        existing.add(ref_no)
        print(f"  EKLENDİ: {ref_no} | {title[:50]}")
        inserted += 1

    except Exception as e:
        print(f"  HATA (id={row.get('id')}): {e}"); errors += 1

if not DRY_RUN:
    new_conn.commit()

print(f"\n{'DRY RUN — ' if DRY_RUN else ''}Tamamlandı: {inserted} eklendi, {skipped} atlandı, {errors} hata.")
for c in [old_conn, new_conn]: c.close()
