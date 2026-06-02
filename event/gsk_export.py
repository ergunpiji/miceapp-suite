"""
gsk_export.py — GSK şablon doldurma modülü (event app)

Kullanım:
    from gsk_export import fill_gsk_template, LineItem
    result = fill_gsk_template(template_path, output_path,
                               items_by_section=..., header=...,
                               commission_rate=0.055)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from openpyxl import load_workbook


# ---------------------------------------------------------------------------
# Şablon yapısı  (gerçek .xlsx ile satır numaralarını teyit et)
# ---------------------------------------------------------------------------

GSK_SECTIONS: dict[str, dict] = {
    "hekim_yiyecek":       {"label": "Hekim Yiyecek",       "rows": (13, 14, 15),                "vat_cell": "J12"},
    "hekim_icecek":        {"label": "Hekim İçecek",         "rows": (17,),                       "vat_cell": "J16"},
    "staff_yiyecek":       {"label": "Staff Yiyecek",        "rows": (20, 21),                    "vat_cell": "J19"},
    "staff_icecek":        {"label": "Staff İçecek",          "rows": (23,),                       "vat_cell": "J22"},
    "konusmaci_konaklama": {"label": "Konuşmacı Konaklama",  "rows": (26, 27),                    "vat_cell": "J25"},
    "konusmaci_ulasim":    {"label": "Konuşmacı Ulaşım",     "rows": (30,),                       "vat_cell": "J29"},
    "diger_hizmetler":     {"label": "Diğer Hizmetler",      "rows": (33, 34, 35, 36, 37, 38, 39), "vat_cell": "J32"},
}

SECTION_LABELS = {k: v["label"] for k, v in GSK_SECTIONS.items()}

COMMISSION_CELL = "B10"

DEFAULT_VAT_RATES: dict[str, float] = {
    "J12": 0.10,  # Hekim Yiyecek
    "J16": 0.20,  # Hekim İçecek
    "J19": 0.10,  # Staff Yiyecek
    "J22": 0.20,  # Staff İçecek
    "J25": 0.10,  # Konuşmacı Konaklama  ← teyit et
    "J29": 0.20,  # Konuşmacı Ulaşım
    "J32": 0.20,  # Diğer Hizmetler
}

HEADER_CELLS: dict[str, str] = {
    "toplanti_adi":   "B2",
    "tarih":          "B3",
    "opsiyon_tarihi": "B4",
    "saat":           "B5",
    "mekan":          "B6",
    "acente":         "B7",
    "gsk_grup":       "B8",
    "yetkili":        "B9",
}

DATA_COLS = "ABCDEFGHIJ"


@dataclass
class LineItem:
    description: str
    unit_price:  float
    quantity:    float = 1.0
    days:        float = 1.0
    rate:        float = 1.0    # kur (TL=1.0)


class GSKOverflowError(Exception):
    def __init__(self, overflow: list[tuple[str, int, int]]):
        self.overflow = overflow
        detail = "; ".join(f"{name}: {n} kalem > {cap} satır" for name, n, cap in overflow)
        super().__init__(f"Bölüm satır kapasitesi aşıldı → {detail}")


def _abs(cell: str) -> str:
    col = "".join(c for c in cell if c.isalpha())
    row = "".join(c for c in cell if c.isdigit())
    return f"${col}${row}"


_COMM_ABS = _abs(COMMISSION_CELL)   # "$B$10"


def _write_item(ws, r: int, item: LineItem, vat_abs: str) -> None:
    ws[f"A{r}"] = item.description
    ws[f"B{r}"] = item.unit_price
    ws[f"C{r}"] = item.rate
    ws[f"D{r}"] = f"=B{r}*C{r}"
    ws[f"E{r}"] = f"=B{r}*(1+{_COMM_ABS})"
    ws[f"F{r}"] = item.quantity
    ws[f"G{r}"] = item.days
    ws[f"H{r}"] = f"=B{r}*F{r}*G{r}"
    ws[f"I{r}"] = f"=E{r}*F{r}*G{r}"
    # Servis bedelinin KDV'si üründen bağımsız, her zaman %20
    ws[f"J{r}"] = f"=H{r}*(1+{vat_abs})+(I{r}-H{r})*1.2"


def _clear_row(ws, r: int) -> None:
    for col in DATA_COLS:
        ws[f"{col}{r}"] = None


def compute_totals(
    items_by_section: dict[str, list[LineItem]],
    commission_rate: float,
    vat_rates: Optional[dict[str, float]] = None,
) -> dict:
    """Excel formüllerinin Python aynası — app özeti için."""
    vat_rates = {**DEFAULT_VAT_RATES, **(vat_rates or {})}
    h = i = j = 0.0
    per_section: dict[str, dict] = {}
    for key, sec in GSK_SECTIONS.items():
        items = items_by_section.get(key) or []
        vat = vat_rates.get(sec["vat_cell"], 0.0)
        sh = si = sj = 0.0
        for it in items:
            _h = it.unit_price * it.quantity * it.days
            _e = it.unit_price * (1 + commission_rate)
            _i = _e * it.quantity * it.days
            _j = _h * (1 + vat) + (_i - _h) * 1.2
            sh += _h; si += _i; sj += _j
        per_section[key] = {"H": round(sh, 2), "I": round(si, 2), "J": round(sj, 2)}
        h += sh; i += si; j += sj
    return {
        "H41_servis_haric_kdv_haric": round(h, 2),
        "I41_servis_dahil_kdv_haric": round(i, 2),
        "J41_servis_dahil_kdv_dahil": round(j, 2),
        "per_section": per_section,
    }


def fill_gsk_template(
    template_path: str,
    output_path: str,
    *,
    items_by_section: dict[str, list[LineItem]],
    header: Optional[dict[str, str]] = None,
    commission_rate: float = 0.055,
    vat_rates: Optional[dict[str, float]] = None,
    gsk_sheet_name: Optional[str] = None,
) -> dict:
    """Şablonu doldurur, output_path'e kaydeder. Dict döner."""
    vat_rates = {**DEFAULT_VAT_RATES, **(vat_rates or {})}

    unknown = set(items_by_section) - set(GSK_SECTIONS)
    if unknown:
        raise KeyError(f"Bilinmeyen bölüm: {sorted(unknown)}. Geçerli: {sorted(GSK_SECTIONS)}")

    # Taşma kontrolü — dosyaya dokunmadan önce
    overflow = [
        (GSK_SECTIONS[k]["label"], len(v), len(GSK_SECTIONS[k]["rows"]))
        for k, v in items_by_section.items()
        if len(v) > len(GSK_SECTIONS[k]["rows"])
    ]
    if overflow:
        raise GSKOverflowError(overflow)

    wb = load_workbook(template_path)
    ws = wb[gsk_sheet_name] if gsk_sheet_name else wb.active

    if header:
        for field, cell in HEADER_CELLS.items():
            if field in header and header[field] is not None:
                ws[cell] = header[field]

    ws[COMMISSION_CELL] = commission_rate
    try:
        ws[COMMISSION_CELL].number_format = "0.0%"
    except Exception:
        pass

    for cell_ref, rate in vat_rates.items():
        ws[cell_ref] = rate
        try:
            ws[cell_ref].number_format = "0%"
        except Exception:
            pass

    filled_rows: list[tuple[str, int]] = []
    empty_sections: list[str] = []

    for key, sec in GSK_SECTIONS.items():
        items = items_by_section.get(key) or []
        if not items:
            empty_sections.append(sec["label"])
            for r in sec["rows"]:
                _clear_row(ws, r)
            continue
        vat_abs = _abs(sec["vat_cell"])
        for idx, r in enumerate(sec["rows"]):
            if idx < len(items):
                _write_item(ws, r, items[idx], vat_abs)
                filled_rows.append((sec["label"], r))
            else:
                _clear_row(ws, r)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    wb.save(output_path)

    return {
        "filled_rows":     filled_rows,
        "empty_sections":  empty_sections,
        "totals":          compute_totals(items_by_section, commission_rate, vat_rates),
        "output_path":     output_path,
    }
