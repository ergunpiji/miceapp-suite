"""
Eski sistemden (e-dem) yeni sisteme (prizmafinans) tedarikçi verisi aktarır.
Mevcut kayıtları günceller (address, phone, email, payment_term alanlarını doldurur).

Kullanım:
  OLD_DB="postgresql://..." NEW_DB="postgresql://..." python3 migrate_vendors.py
"""

import os, sys

try:
    import psycopg2, psycopg2.extras
except ImportError:
    os.system(f"{sys.executable} -m pip install psycopg2-binary -q")
    import psycopg2, psycopg2.extras

OLD_DB = os.environ.get("OLD_DB", "").strip()
NEW_DB = os.environ.get("NEW_DB", "").strip()

def fix(url):
    return url.replace("postgres://", "postgresql://", 1) if url.startswith("postgres://") else url

OLD_DB, NEW_DB = fix(OLD_DB), fix(NEW_DB)

print("[1] Eski DB'ye bağlanılıyor...")
old_conn = psycopg2.connect(OLD_DB)
old_cur  = old_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

print("[2] Yeni DB'ye bağlanılıyor...")
new_conn = psycopg2.connect(NEW_DB)
new_cur  = new_conn.cursor()

old_cur.execute("""
    SELECT name, tax_number, tax_office, address, email, phone, payment_term, notes, is_active
    FROM financial_vendors ORDER BY name
""")
rows = old_cur.fetchall()
print(f"[3] {len(rows)} tedarikçi bulundu.")

inserted = updated = skipped = 0

for row in rows:
    name = (row["name"] or "").strip()
    if not name:
        continue

    address      = (row.get("address") or "").strip()
    phone        = (row.get("phone") or "").strip()
    email        = (row.get("email") or "").strip()
    payment_term = row.get("payment_term") or 30
    tax_no       = (row.get("tax_number") or "").strip()
    tax_office   = (row.get("tax_office") or "").strip()
    notes        = (row.get("notes") or "").strip()
    active       = bool(row.get("is_active", True))

    # Yeni DB'de var mı?
    new_cur.execute("SELECT id FROM financial_vendors WHERE LOWER(name) = LOWER(%s)", (name,))
    existing = new_cur.fetchone()

    if existing:
        # Güncelle — yeni alanları doldur
        new_cur.execute("""
            UPDATE financial_vendors
            SET address=%s, phone=%s, email=%s, payment_term=%s,
                tax_no=%s, tax_office=%s, notes=%s, active=%s
            WHERE id=%s
        """, (address, phone, email, payment_term, tax_no, tax_office, notes, active, existing[0]))
        print(f"  GÜNCELLENDİ: {name}")
        updated += 1
    else:
        new_cur.execute("""
            INSERT INTO financial_vendors
                (name, vendor_type, iban, tax_no, tax_office, address, phone, email,
                 payment_term, contact, notes, active, created_at)
            VALUES (%s,'','', %s, %s, %s, %s, %s, %s, '', %s, %s, NOW())
        """, (name, tax_no, tax_office, address, phone, email, payment_term, notes, active))
        print(f"  EKLENDİ: {name}")
        inserted += 1

new_conn.commit()
print(f"\nTamamlandı: {inserted} eklendi, {updated} güncellendi, {skipped} atlandı.")
old_cur.close(); old_conn.close()
new_cur.close(); new_conn.close()
