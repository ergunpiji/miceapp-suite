"""
E-dem Köprü Servisi

E-dem'in SQLite veritabanını okuyarak referansları (Request) ve onaylı
bütçeleri (Budget) katılımcı ajanına sunar.

DB yolu: EDEM_DB_PATH env değişkeninden okunur,
         yoksa ../../edem.db (göreceli yol) kullanılır.
"""

import sqlite3
import json
import os
from pathlib import Path
from dataclasses import dataclass
from datetime import date

# E-dem DB yolu
_DEFAULT_DB = Path(__file__).parent.parent.parent.parent / "edem.db"
EDEM_DB_PATH = os.environ.get("EDEM_DB_PATH", str(_DEFAULT_DB))

# Katılımcı ajanında gösterilecek E-dem statüleri
VISIBLE_STATUSES = {
    "pending":          "Beklemede",
    "in_progress":      "İşlemde",
    "venues_contacted": "Mekanlarla İletişimde",
    "budget_ready":     "Bütçe Hazır",
    "completed":        "Tamamlandı",
}


def _fmt(ymd: str | None) -> str:
    """'2026-05-13' → '13.05.2026', None → ''"""
    if not ymd:
        return ""
    try:
        y, m, d = ymd.split("-")
        return f"{d}.{m}.{y}"
    except Exception:
        return ymd or ""


@dataclass
class EdemReference:
    id: str
    request_no: str
    event_name: str
    client_name: str
    status: str
    status_label: str
    check_in: str | None       # YYYY-MM-DD
    check_out: str | None
    accom_check_in: str | None
    accom_check_out: str | None
    city: str | None
    attendee_count: int | None
    venue_name: str | None     # onaylı bütçeden gelen mekan adı
    confirmed_budget_id: str | None


def _connect() -> sqlite3.Connection | None:
    """E-dem DB bağlantısı açar. Dosya yoksa None döner."""
    if not Path(EDEM_DB_PATH).exists():
        return None
    conn = sqlite3.connect(EDEM_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def is_available() -> bool:
    """E-dem DB erişilebilir mi?"""
    return Path(EDEM_DB_PATH).exists()


def get_references(search: str = "") -> list[EdemReference]:
    """
    Katılımcı ajanında gösterilebilecek E-dem referanslarını döner.
    Sadece aktif / tamamlanmış referanslar listelenir.
    """
    conn = _connect()
    if not conn:
        return []

    try:
        query = """
            SELECT
                r.id, r.request_no, r.event_name, r.client_name,
                r.status, r.check_in, r.check_out,
                r.accom_check_in, r.accom_check_out,
                r.city, r.attendee_count, r.confirmed_budget_id,
                b.venue_name
            FROM requests r
            LEFT JOIN budgets b ON b.id = r.confirmed_budget_id
            WHERE r.status IN ({})
            ORDER BY r.check_in DESC
        """.format(",".join("?" * len(VISIBLE_STATUSES)))

        params = list(VISIBLE_STATUSES.keys())

        if search:
            query = """
                SELECT
                    r.id, r.request_no, r.event_name, r.client_name,
                    r.status, r.check_in, r.check_out,
                    r.accom_check_in, r.accom_check_out,
                    r.city, r.attendee_count, r.confirmed_budget_id,
                    b.venue_name
                FROM requests r
                LEFT JOIN budgets b ON b.id = r.confirmed_budget_id
                WHERE r.status IN ({})
                  AND (r.event_name LIKE ? OR r.client_name LIKE ? OR r.request_no LIKE ?)
                ORDER BY r.check_in DESC
            """.format(",".join("?" * len(VISIBLE_STATUSES)))
            params += [f"%{search}%", f"%{search}%", f"%{search}%"]

        rows = conn.execute(query, params).fetchall()

        return [
            EdemReference(
                id=r["id"],
                request_no=r["request_no"] or "",
                event_name=r["event_name"] or "",
                client_name=r["client_name"] or "",
                status=r["status"],
                status_label=VISIBLE_STATUSES.get(r["status"], r["status"]),
                check_in=_fmt(r["check_in"]),
                check_out=_fmt(r["check_out"]),
                accom_check_in=_fmt(r["accom_check_in"]),
                accom_check_out=_fmt(r["accom_check_out"]),
                city=r["city"],
                attendee_count=r["attendee_count"],
                venue_name=r["venue_name"],
                confirmed_budget_id=r["confirmed_budget_id"],
            )
            for r in rows
        ]
    finally:
        conn.close()


@dataclass
class BudgetRow:
    section: str          # accommodation, meeting, fb, teknik, dekor, transfer, tasarim, other
    service_name: str
    unit: str
    qty: float
    nights: int
    cost_price: float
    sale_price: float
    vat_rate: float
    notes: str


# E-dem section → katılımcı ajanı supplier_type eşlemesi
SECTION_TO_SUPPLIER_TYPE = {
    "accommodation": "hotel",
    "meeting":       "other",
    "fb":            "catering",
    "teknik":        "technical",
    "dekor":         "decor",
    "transfer":      "transfer",
    "tasarim":       "design",
    "other":         "other",
}

# E-dem section → SESSION_TYPES eşlemesi
SECTION_TO_SESSION_TYPE = {
    "meeting":  "plenary",
    "fb":       "meal",
    "transfer": "transfer",
    "other":    "other",
}


def get_budget_rows(edem_request_id: str) -> tuple[str, list[BudgetRow]]:
    """
    Verilen E-dem referansı için en iyi bütçenin satırlarını döner.
    Öncelik sırası: approved > pending_manager > draft_edem
    Dönüş: (venue_name, [BudgetRow])
    """
    conn = _connect()
    if not conn:
        return "", []

    try:
        # En iyi bütçeyi bul
        row = conn.execute("""
            SELECT id, venue_name, rows_json, budget_status
            FROM budgets
            WHERE request_id = ?
            ORDER BY
                CASE budget_status
                    WHEN 'approved'        THEN 1
                    WHEN 'pending_manager' THEN 2
                    WHEN 'draft_manager'   THEN 3
                    WHEN 'draft_edem'      THEN 4
                    ELSE 5
                END
            LIMIT 1
        """, [edem_request_id]).fetchone()

        if not row:
            return "", []

        venue_name = row["venue_name"] or ""
        rows_raw = json.loads(row["rows_json"] or "[]")

        result = []
        for r in rows_raw:
            if r.get("is_service_fee") or r.get("section") == "service_fee":
                continue
            result.append(BudgetRow(
                section=r.get("section", "other"),
                service_name=r.get("service_name", ""),
                unit=r.get("unit", "Adet"),
                qty=float(r.get("qty") or 1),
                nights=int(r.get("nights") or 1),
                cost_price=float(r.get("cost_price") or 0),
                sale_price=float(r.get("sale_price") or 0),
                vat_rate=float(r.get("vat_rate") or 0),
                notes="",
            ))

        return venue_name, result
    finally:
        conn.close()


def get_reference(request_id: str) -> EdemReference | None:
    """Tek bir referansı ID'ye göre getirir."""
    conn = _connect()
    if not conn:
        return None

    try:
        row = conn.execute("""
            SELECT
                r.id, r.request_no, r.event_name, r.client_name,
                r.status, r.check_in, r.check_out,
                r.accom_check_in, r.accom_check_out,
                r.city, r.attendee_count, r.confirmed_budget_id,
                b.venue_name
            FROM requests r
            LEFT JOIN budgets b ON b.id = r.confirmed_budget_id
            WHERE r.id = ?
        """, [request_id]).fetchone()

        if not row:
            return None

        return EdemReference(
            id=row["id"],
            request_no=row["request_no"] or "",
            event_name=row["event_name"] or "",
            client_name=row["client_name"] or "",
            status=row["status"],
            status_label=VISIBLE_STATUSES.get(row["status"], row["status"]),
            check_in=_fmt(row["check_in"]),
            check_out=_fmt(row["check_out"]),
            accom_check_in=_fmt(row["accom_check_in"]),
            accom_check_out=_fmt(row["accom_check_out"]),
            city=row["city"],
            attendee_count=row["attendee_count"],
            venue_name=row["venue_name"],
            confirmed_budget_id=row["confirmed_budget_id"],
        )
    finally:
        conn.close()
