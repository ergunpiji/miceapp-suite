"""
Eski sistemden (e-dem) yeni sisteme (prizmafinans) fatura verisi aktarır.

Eski şema:
  invoices: id(uuid), request_id(uuid), vendor_id(uuid), vendor_name(text),
            invoice_type, invoice_no, invoice_date, due_date,
            amount(net), vat_rate(yüzde: 20.0), vat_amount, total_amount,
            lines_json, status, payment_status, paid_at, payment_method,
            bank_account_id, credit_card_id, created_at

Kullanım:
  OLD_DB="postgresql://..." NEW_DB="postgresql://..." python3 migrate_invoices.py
  DRY_RUN=1  → yazmadan kontrol
"""
import os, sys, json as _json

try:
    import psycopg2, psycopg2.extras
except ImportError:
    os.system(f"{sys.executable} -m pip install psycopg2-binary -q")
    import psycopg2, psycopg2.extras

OLD_DB   = os.environ.get("OLD_DB", "").strip()
NEW_DB   = os.environ.get("NEW_DB", "").strip()
DRY_RUN  = os.environ.get("DRY_RUN", "0") == "1"

def fix(u):
    return u.replace("postgres://", "postgresql://", 1) if u.startswith("postgres://") else u

if not OLD_DB or not NEW_DB:
    print("HATA: OLD_DB ve NEW_DB gerekli."); sys.exit(1)

print("[1] Bağlanılıyor...")
old_conn = psycopg2.connect(fix(OLD_DB))
new_conn = psycopg2.connect(fix(NEW_DB))
old_cur  = old_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
new_cur  = new_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

# ── Eski request_id (uuid) → request_no → yeni ref_id (int) ──────────────────
old_cur.execute("SELECT id, request_no FROM requests")
old_req_no = {r["id"]: (r["request_no"] or "").strip().upper() for r in old_cur.fetchall()}

new_cur.execute('SELECT id, ref_no FROM "references"')
new_ref_by_no = {(r["ref_no"] or "").strip().upper(): r["id"] for r in new_cur.fetchall()}
print(f"[2] Yeni DB referans sayısı: {len(new_ref_by_no)}")

# ── Eski vendor_id (uuid) → isim ─────────────────────────────────────────────
try:
    old_cur.execute("SELECT id, name FROM financial_vendors")
    old_vendor_map = {r["id"]: (r["name"] or "").strip() for r in old_cur.fetchall()}
except Exception:
    old_vendor_map = {}

# ── Yeni vendor isim → id ─────────────────────────────────────────────────────
new_cur.execute("SELECT id, name FROM financial_vendors")
new_vendor_by_name = {(r["name"] or "").strip().lower(): r["id"] for r in new_cur.fetchall()}

# ── Admin kullanıcı ───────────────────────────────────────────────────────────
new_cur.execute("SELECT id FROM users WHERE is_admin = TRUE ORDER BY id LIMIT 1")
admin_id = new_cur.fetchone()["id"]

# ── Mevcut faturalar (tekrar önleme) ──────────────────────────────────────────
new_cur.execute("SELECT invoice_no, invoice_date FROM invoices WHERE invoice_no != ''")
existing = {(r["invoice_no"].strip(), str(r["invoice_date"])) for r in new_cur.fetchall()}
print(f"[3] Yeni DB mevcut fatura: {len(existing)}")

# ── Eski faturaları çek ───────────────────────────────────────────────────────
old_cur.execute("SELECT * FROM invoices ORDER BY invoice_date, created_at")
rows = old_cur.fetchall()
print(f"[4] Eski DB'de {len(rows)} fatura.\n")

# ── Tip normalizasyonu ────────────────────────────────────────────────────────
VALID_TYPES = {"gelen", "kesilen", "komisyon", "iade_gelen", "iade_kesilen"}
TYPE_MAP = {
    "incoming": "gelen", "outgoing": "kesilen", "commission": "komisyon",
    "incoming_refund": "iade_gelen", "outgoing_refund": "iade_kesilen",
    "in": "gelen", "out": "kesilen",
}
def norm_type(v):
    if not v: return "gelen"
    v = str(v).lower().strip()
    return v if v in VALID_TYPES else TYPE_MAP.get(v, "gelen")

# ── Durum normalizasyonu ──────────────────────────────────────────────────────
def norm_status(status, payment_status=None):
    if payment_status and str(payment_status).lower() == "paid":
        return "paid"
    s = str(status or "").lower().strip()
    if s == "paid":      return "paid"
    if s == "cancelled": return "cancelled"
    if s == "draft":     return "draft"
    return "approved"

# ── Ödeme yöntemi normalizasyonu ──────────────────────────────────────────────
VALID_PM = {"nakit", "banka", "kredi_karti", "cek", "acik_hesap"}
PM_MAP = {"cash": "nakit", "bank": "banka", "credit_card": "kredi_karti",
          "cheque": "cek", "check": "cek", "open": "acik_hesap"}
def norm_pm(v):
    if not v: return None
    v = str(v).lower().strip()
    return v if v in VALID_PM else PM_MAP.get(v)

# ── lines_json → items_json dönüşümü ─────────────────────────────────────────
def convert_lines(lines_raw):
    """Eski lines_json formatını yeni items_json formatına çevirir."""
    if not lines_raw:
        return None
    try:
        if isinstance(lines_raw, str):
            lines = _json.loads(lines_raw)
        else:
            lines = lines_raw
        if not isinstance(lines, list) or not lines:
            return None
        items = []
        for ln in lines:
            desc    = str(ln.get("description") or ln.get("desc") or "").strip()
            net     = float(ln.get("amount") or ln.get("net") or 0)
            vat_pct = float(ln.get("vat_rate") or ln.get("vat_pct") or 0)
            vat_amt = float(ln.get("vat_amount") or ln.get("vat_amt") or 0)
            if vat_pct > 1:
                pass  # zaten yüzde (20 gibi)
            else:
                vat_pct = vat_pct * 100  # oran (0.20) → yüzde (20)
            items.append({
                "desc":    desc,
                "net":     net,
                "vat_pct": vat_pct,
                "vat_amt": vat_amt,
                "total":   net + vat_amt,
            })
        return _json.dumps(items, ensure_ascii=False) if items else None
    except Exception:
        return None

# ── Aktarım ───────────────────────────────────────────────────────────────────
inserted = skipped = errors = 0

for row in rows:
    try:
        invoice_date = row.get("invoice_date")
        if not invoice_date:
            print(f"  ATLA (tarih yok): id={row.get('id')}")
            skipped += 1; continue

        invoice_no = str(row.get("invoice_no") or "").strip()
        key = (invoice_no, str(invoice_date))
        if invoice_no and key in existing:
            print(f"  ATLA (mevcut): {invoice_no} / {invoice_date}")
            skipped += 1; continue

        # Temel alanlar
        inv_type   = norm_type(row.get("invoice_type"))
        status     = norm_status(row.get("status"), row.get("payment_status"))
        pm         = norm_pm(row.get("payment_method"))
        due_date   = row.get("due_date")
        paid_at    = row.get("paid_at")
        currency   = str(row.get("currency") or "TRY")[:3]
        notes      = str(row.get("notes") or "").strip()
        created_at = row.get("created_at")

        # Tutar: amount=net, vat_rate yüzde → oran
        amount   = float(row.get("amount") or row.get("net_amount") or 0)
        vat_pct  = float(row.get("vat_rate") or 0)
        vat_rate = round(vat_pct / 100.0, 4) if vat_pct > 1 else round(vat_pct, 4)

        # Referans eşleştir
        new_rid = None
        req_uuid = row.get("request_id")
        if req_uuid and req_uuid in old_req_no:
            ref_no = old_req_no[req_uuid]
            new_rid = new_ref_by_no.get(ref_no)
            if not new_rid:
                print(f"  [UYR] Referans eşleşmedi: {ref_no} (fatura {row.get('id')})")

        # Tedarikçi eşleştir — önce uuid map, fallback: vendor_name alanı
        new_vid = None
        v_uuid  = row.get("vendor_id")
        v_name  = str(row.get("vendor_name") or "").strip()
        if v_uuid and v_uuid in old_vendor_map:
            v_name = old_vendor_map[v_uuid]
        if v_name:
            new_vid = new_vendor_by_name.get(v_name.lower())
            if not new_vid:
                print(f"  [UYR] Tedarikçi eşleşmedi: '{v_name}' (fatura {row.get('id')})")

        # lines_json → items_json
        items_json = convert_lines(row.get("lines_json") or row.get("items_json"))

        if DRY_RUN:
            print(f"  DRY: {inv_type} | {invoice_no or '—'} | {invoice_date} | "
                  f"{amount:.2f} {currency} | vat={vat_rate:.2f} | "
                  f"ref→{new_rid} | vendor→{new_vid} | {status}")
            inserted += 1
            if invoice_no:
                existing.add(key)
            continue

        new_cur.execute("""
            INSERT INTO invoices
                (ref_id, vendor_id, invoice_type, invoice_no, invoice_date,
                 amount, vat_rate, currency, status, payment_method,
                 paid_at, due_date, items_json, notes, created_by, created_at)
            VALUES
                (%s, %s, %s, %s, %s,
                 %s, %s, %s, %s, %s,
                 %s, %s, %s, %s, %s, %s)
        """, (
            new_rid, new_vid, inv_type,
            invoice_no, invoice_date,
            amount, vat_rate, currency, status, pm,
            paid_at, due_date, items_json, notes,
            admin_id, created_at,
        ))
        print(f"  EKLENDİ: {inv_type} | {invoice_no or '—'} | {invoice_date} | {amount:.2f} {currency}")
        inserted += 1
        if invoice_no:
            existing.add(key)

    except Exception as e:
        print(f"  HATA (id={row.get('id')}): {e}")
        if not DRY_RUN:
            new_conn.rollback()
        errors += 1

if not DRY_RUN:
    new_conn.commit()

print(f"\n{'DRY RUN — ' if DRY_RUN else ''}Tamamlandı: {inserted} eklendi, {skipped} atlandı, {errors} hata.")
old_cur.close(); old_conn.close()
new_cur.close(); new_conn.close()
