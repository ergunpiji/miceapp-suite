"""
Türk e-fatura PDF parser — AI'sız, regex + pdfplumber ile.

Temel sorunların çözümü:
- Python upper() Türkçe i/İ/ı ayrımını korumaz → normalize() fonksiyonu kullanılır
- Konaklama Vergisi tablo "Diğer Vergiler" sütunu VEYA özet satırından alınır
- Kalem tutarı "Mal Hizmet Tutarı" (son sütun) olarak belirlenir
"""
from __future__ import annotations

import io
import re
from typing import Optional


# ---------------------------------------------------------------------------
# Türkçe-güvenli string araçları
# ---------------------------------------------------------------------------

_TR_MAP = str.maketrans("İıĞğŞşÇçÖöÜü", "IiGgSsCcOoUu")

def _norm(s: str) -> str:
    """Türkçe karakterleri ASCII'ye çevirip büyük harfe al — karşılaştırma için."""
    return str(s or "").translate(_TR_MAP).upper()


def _tr_float(s) -> Optional[float]:
    """'1.234,56 TL' veya '122.704,15TL' → 1234.56"""
    s = str(s or "").strip()
    # TL, ₺, % işaretlerini temizle
    s = re.sub(r'[TLtl₺%=\s]', '', s)
    s = re.sub(r'[^0-9,.]', '', s)
    if not s:
        return None
    # Türk formatı: binlik=nokta, ondalık=virgül → 1.234,56
    if ',' in s and '.' in s:
        s = s.replace('.', '').replace(',', '.')
    elif ',' in s:
        s = s.replace(',', '.')
    try:
        v = float(s)
        return v if v >= 0 else None
    except ValueError:
        return None


def _parse_date(s: str) -> Optional[str]:
    """DD-MM-YYYY veya DD.MM.YYYY → YYYY-MM-DD"""
    if not s:
        return None
    m = re.match(r'(\d{1,2})[-./](\d{1,2})[-./](\d{4})', s.strip())
    if m:
        return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    m = re.match(r'(\d{4})[-./](\d{1,2})[-./](\d{1,2})', s.strip())
    if m:
        return s.strip()[:10]
    return None


def _clean(s) -> str:
    return str(s or "").strip()


# ---------------------------------------------------------------------------
# Debug yardımcısı
# ---------------------------------------------------------------------------

def _debug_extract(file_bytes: bytes) -> dict:
    """Ham pdfplumber çıktısını döndür — Railway loglarında görülür."""
    try:
        import pdfplumber
    except ImportError:
        return {}
    text = ""
    tables = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text += (page.extract_text(x_tolerance=2, y_tolerance=2) or "") + "\n"
            for tbl in (page.extract_tables() or []):
                tables.append(tbl)
    return {"text": text[:3000], "tables": tables}


# ---------------------------------------------------------------------------
# Ana parser
# ---------------------------------------------------------------------------

def parse_invoice(file_bytes: bytes, filename: str = "invoice.pdf") -> dict:
    """
    PDF faturayı parse eder.

    Döndürülen dict:
        invoice_no, invoice_date, due_date, vendor_name,
        description, currency, grand_total_incl,
        lines: [{description, amount, vat_rate}]
    """
    try:
        import pdfplumber
    except ImportError:
        raise ValueError("pdfplumber kurulu değil.")

    result: dict = {
        "invoice_no":       None,
        "invoice_date":     None,
        "due_date":         None,
        "vendor_name":      None,
        "description":      None,
        "currency":         "TRY",
        "grand_total_incl": None,
        "lines":            [],
    }

    all_text  = ""
    all_tables: list = []

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            all_text += (page.extract_text(x_tolerance=2, y_tolerance=2) or "") + "\n"
            for tbl in (page.extract_tables() or []):
                all_tables.append(tbl)

    # ── Fatura No ─────────────────────────────────────────────────────────────
    for pat in [
        r'Fatura No\s*[:\s]+([A-Z0-9]{5,30})',
        r'FATURA NO\s*[:\s]+([A-Z0-9]{5,30})',
    ]:
        m = re.search(pat, all_text, re.IGNORECASE)
        if m:
            result["invoice_no"] = _clean(m.group(1))
            break

    # ── Tarihler ──────────────────────────────────────────────────────────────
    for label, key in [
        ("Fatura Tarihi", "invoice_date"),
        ("Vade Tarihi",   "due_date"),
        ("Son Ödeme",     "due_date"),
    ]:
        m = re.search(rf'{re.escape(label)}\s*[:\s]+(\d{{1,2}}[-./]\d{{1,2}}[-./]\d{{4}})',
                      all_text, re.IGNORECASE)
        if m and not result[key]:
            result[key] = _parse_date(m.group(1))

    # ── Tedarikçi Adı ─────────────────────────────────────────────────────────
    result["vendor_name"] = _extract_vendor_name(all_text)

    # ── Para Birimi ───────────────────────────────────────────────────────────
    if re.search(r'\bEUR\b|€', all_text):
        result["currency"] = "EUR"
    elif re.search(r'\bUSD\b', all_text):
        result["currency"] = "USD"

    # ── Genel Toplam ──────────────────────────────────────────────────────────
    for pat in [
        r'Ödenecek Tutar[\s:]*([0-9.,]+)\s*TL',
        r'Vergiler Dahil Toplam Tutar[\s:]*([0-9.,]+)\s*TL',
        r'GENEL TOPLAM[\s:]*([0-9.,]+)',
    ]:
        m = re.search(pat, all_text, re.IGNORECASE)
        if m:
            v = _tr_float(m.group(1))
            if v and v > 0:
                result["grand_total_incl"] = v
                break

    # ── Kalem Satırları ───────────────────────────────────────────────────────
    result["lines"] = _extract_all_lines(all_text, all_tables)

    # ── Notlar ────────────────────────────────────────────────────────────────
    notes = [
        _clean(m.group(1))
        for m in re.finditer(r'Not:\s*(.+)', all_text, re.IGNORECASE)
        if not _clean(m.group(1)).upper().startswith("YALNIZ") and len(_clean(m.group(1))) > 3
    ]
    if notes:
        result["description"] = "; ".join(notes[:3])

    return result


# ---------------------------------------------------------------------------
# Tedarikçi adı
# ---------------------------------------------------------------------------

def _extract_vendor_name(text: str) -> Optional[str]:
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    sayin_idx = next(
        (i for i, l in enumerate(lines) if re.match(r'^SAYIN\b', l, re.IGNORECASE)),
        None,
    )
    skip = re.compile(
        r'Vergi Dairesi|Mersis|Phone|Fax|Mah\.|Cad\.|Sok\.|Posta Kodu|'
        r'^\+?\(?\d|e-FATURA|e-ARŞİV|ETTN|www\.|http',
        re.IGNORECASE,
    )
    rng = lines[:sayin_idx] if sayin_idx else lines[:8]
    for l in rng:
        if not skip.search(l) and len(l) > 5:
            return l
    return None


# ---------------------------------------------------------------------------
# Tüm kalemleri çıkar (tablo + konaklama vergisi)
# ---------------------------------------------------------------------------

def _extract_all_lines(text: str, tables: list) -> list:
    # Önce tablodan dene, sonra metinden
    lines = _extract_lines_from_tables(tables)
    if not lines:
        lines = _extract_lines_from_text(text)

    # Konaklama vergisini ayrı ekle
    kv = _extract_accommodation_tax(text, tables)
    if kv is not None:
        # Zaten eklenmemişse ekle
        already = any(_norm(l.get("description", "")).startswith("KONAKLAMA VERG")
                      for l in lines)
        if not already:
            lines.append({
                "description": "Konaklama Vergisi",
                "amount":      round(kv, 2),
                "vat_rate":    0,
            })
    return lines


# ---------------------------------------------------------------------------
# Konaklama vergisi tutarı
# ---------------------------------------------------------------------------

def _extract_accommodation_tax(text: str, tables: list) -> Optional[float]:
    """
    Konaklama vergisini bul. İki kaynağa sırayla bakar:
    1. Tablo 'Diğer Vergiler' sütunu
    2. Özet satırı: 'Hesaplanan KONAKLAMA VERGİSİ(% 2) 2.454,08TL'
    """
    # 1. Tablodan
    for tbl in tables:
        if not tbl or len(tbl) < 2:
            continue
        header_norm = [_norm(c) for c in (tbl[0] or [])]
        other_col = next(
            (i for i, h in enumerate(header_norm)
             if "DIGER VERGI" in h or "DIGER VERGİ" in h or "DIGER VERGI" in h),
            None,
        )
        if other_col is None:
            # "DİĞER" kalıbını da ara (normalize sonrası "DIGER" olur)
            other_col = next(
                (i for i, h in enumerate(header_norm) if "DIGER" in h),
                None,
            )
        if other_col is None:
            continue
        for row in tbl[1:]:
            if not row or other_col >= len(row):
                continue
            cell = _clean(row[other_col])
            if "KONAKLAMA" not in _norm(cell):
                continue
            # "KONAKLAMA VERGİSİ (%2,00)\n=2.454,08TL" → tutarı çek
            m = re.search(r'[=\s]([0-9.,]+)\s*TL', cell, re.IGNORECASE)
            if m:
                v = _tr_float(m.group(1))
                if v and v > 0:
                    return v

    # 2. Özet metinden: hem "(%2)" hem "(% 2)" formatını yakala
    for pat in [
        r'KONAKLAMA\s+VERG[İI]S[İI]\s*\(\s*%?\s*\d+[,.]?\d*\s*\)\s*([0-9.,]+)\s*TL',
        r'KONAKLAMA\s+VERG[İI]S[İI].*?([0-9.,]+)\s*TL',
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            v = _tr_float(m.group(1))
            if v and v > 0:
                return v

    return None


# ---------------------------------------------------------------------------
# Tablo tabanlı kalem çıkarma
# ---------------------------------------------------------------------------

def _extract_lines_from_tables(tables: list) -> list:
    """
    pdfplumber tablosundan kalem satırlarını parse et.

    Sütun eşleştirmesi _norm() ile yapılır (Türkçe i/İ/ı sorununu önler).

    Türk e-fatura tablo sütunları (normalize edilmiş isimler):
      SIRA NO | MAL HIZMET | MIKTAR | BIRIM FIYAT | ISKONTO ORANI | ISKONTO TUTARI
      | KDV ORANI | KDV TUTARI | DIGER VERGILER | MAL HIZMET TUTARI
    """
    lines = []

    for tbl in tables:
        if not tbl or len(tbl) < 2:
            continue

        raw_header = tbl[0] or []
        header_norm = [_norm(c) for c in raw_header]

        # Kalem tablosu mu? "MAL" ve ("FIYAT" veya "TUTAR") içermeli
        has_desc  = any("MAL" in h or "HIZMET" in h or "ACIKLAMA" in h
                        for h in header_norm)
        has_price = any("FIYAT" in h or "TUTAR" in h or "BEDEL" in h
                        for h in header_norm)
        if not (has_desc and has_price):
            continue

        # Sütun indekslerini bul (normalize karşılaştırma)
        desc_col   = _col(header_norm, ["MAL HIZMET", "HIZMET ADI", "ACIKLAMA", "MAL/HIZMET"])
        # "Mal Hizmet Tutarı" = son fiyat sütunu (birim fiyattan farklı, iskonto/kdv sonrası)
        amt_col    = _col(header_norm, ["MAL HIZMET TUTARI", "HIZMET TUTARI", "TUTAR"])
        birim_col  = _col(header_norm, ["BIRIM FIYAT", "BIRIM"])
        kdv_col    = _col(header_norm, ["KDV ORANI", "KDV %"])
        other_col  = _col(header_norm, ["DIGER VERGI", "DIGER"])

        # Fallback: desc 2. sütun, amt son sütun
        if desc_col is None:
            desc_col = 1
        if amt_col is None:
            amt_col = len(raw_header) - 1  # son sütun

        for row in tbl[1:]:
            if not row:
                continue
            desc = _clean(row[desc_col]) if desc_col < len(row) else ""
            if not desc:
                continue
            # Toplam/iskonto/başlık satırlarını atla
            if re.search(r'TOPLAM|GENEL|ISKONTO|YALNIZ|SIRA NO|MAL HIZMET$',
                         _norm(desc)):
                continue

            # ── Tutar: önce amt_col, sonra row'daki en büyük sayısal değer ──
            # En büyük TL değeri = Mal Hizmet Tutarı (iskonto/kdv miktarlarından büyük)
            amount = None
            if amt_col < len(row):
                amount = _tr_float(row[amt_col])
            if not amount:
                # Tüm hücrelerden sayısal değerleri topla (Diğer Vergiler hariç)
                candidates = []
                for i, cell in enumerate(row):
                    if other_col is not None and i == other_col:
                        continue
                    v = _tr_float(cell)
                    if v and v > 0:
                        candidates.append(v)
                if candidates:
                    amount = max(candidates)  # en büyük = Mal Hizmet Tutarı

            # ── KDV Oranı: kdv_col'dan al, yoksa satırdaki geçerli % oranı ──
            vat_rate = 20  # varsayılan
            if kdv_col is not None and kdv_col < len(row):
                raw = _clean(row[kdv_col])
                raw_clean = re.sub(r'[^0-9,.]', '', raw).replace(',', '.')
                try:
                    vat_rate = int(float(raw_clean))
                except (ValueError, TypeError):
                    pass
            if vat_rate == 20 and kdv_col is None:
                # Tüm satırı birleştir, % değerlerini tara
                row_text = ' '.join(_clean(c) for c in row)
                pcts = [int(p.split(',')[0])
                        for p in re.findall(r'%\s*(\d{1,2}[,.]?\d*)', row_text)]
                for p in pcts:
                    if p in _VALID_VAT and p != 0:
                        vat_rate = p
                        break

            if desc and amount and amount > 0:
                lines.append({
                    "description": desc,
                    "amount":      round(amount, 2),
                    "vat_rate":    vat_rate,
                })

    return lines


def _col(header_norm: list, candidates: list) -> Optional[int]:
    """Normalize edilmiş header'da aday isimleri ara (kısmi eşleşme)."""
    for cand in candidates:
        cand_norm = _norm(cand)
        for i, h in enumerate(header_norm):
            if cand_norm in h:
                return i
    return None


# ---------------------------------------------------------------------------
# Metin tabanlı kalem çıkarma (tablo başarısız olursa fallback)
# ---------------------------------------------------------------------------

# Geçerli KDV oranları — Konaklama Vergisi (%2) burada YOK
_VALID_VAT = {0, 1, 8, 10, 18, 20}


def _extract_lines_from_text(text: str) -> list:
    """
    Türk e-fatura metninden kalem satırlarını çıkar.

    Yaklaşım: satır numarası (1, 2, 3...) ile başlayan blokları bul,
    her bloktan açıklama + KDV oranı + tutar çıkar.

    Tipik satır (tek veya çok satır olabilir):
      1 KONAKLAMA 1Adet 122.704,15TL %0,00 0,00TL %10,00 12.270,42TL ... 122.704,15TL
      2 TOPLANTI BEDELİ 1Adet 147.581,01TL ...
    """
    lines = []

    # Tüm metni normalize et: birden fazla boşluğu tek boşluğa indir
    flat = re.sub(r'[ \t]+', ' ', text)

    # Satır numarasıyla başlayan blokları böl
    # Blok: "1 KONAKLAMA ..." → bir sonraki "2 " ya da toplam satırına kadar
    block_splits = list(re.finditer(r'(?:^|\n)\s*(\d{1,3})\s+([A-ZÇĞİÖŞÜ])', flat))

    # Toplam bölümünün başlangıcını bul (bloğun bitişini sınırla)
    total_start = len(flat)
    for marker in ['Mal Hizmet Toplam', 'MAL HIZMET TOPLAM', 'Toplam İskonto', 'GENEL TOPLAM']:
        idx = flat.find(marker)
        if 0 < idx < total_start:
            total_start = idx

    for k, bm in enumerate(block_splits):
        block_end = block_splits[k + 1].start() if k + 1 < len(block_splits) else total_start
        block = flat[bm.start():block_end].strip()

        sira = int(bm.group(1))
        if sira > 50:  # Makul olmayan sıra numarası
            continue

        # ── Açıklama: satır numarasından sonra gelen büyük harfli kelimeler ──
        desc_m = re.match(
            r'^\s*\d{1,3}\s+'
            r'([A-ZÇĞİÖŞÜ][A-ZÇĞİÖŞÜa-zçğışöü\s/&\-]{1,60?}?)'
            r'(?:\s+\d|\s+%)',
            block,
        )
        desc = _clean(desc_m.group(1)) if desc_m else ""
        if not desc:
            # Fallback: sıra numarasından sonraki ilk kelime(ler)
            desc_m2 = re.match(r'^\s*\d{1,3}\s+(.+?)(?=\s+\d[\d.]*\s*(?:Adet|KG|adet|m2)?)', block)
            desc = _clean(desc_m2.group(1)) if desc_m2 else ""

        if not desc or re.search(r'TOPLAM|GENEL|ISKONTO|YALNIZ', _norm(desc)):
            continue

        # ── KDV Oranı: blokta geçen tüm % değerlerini bul, geçerli KDV oranını seç ──
        pcts = [int(p.split(',')[0]) for p in re.findall(r'%\s*(\d{1,2}[,.]?\d*)', block)]
        vat_rate = 20  # varsayılan
        # İskonto genellikle %0 — onu geç, ilk geçerli KDV oranını al
        for p in pcts:
            if p in _VALID_VAT and p != 0:
                vat_rate = p
                break

        # ── Tutar: bloktaki en büyük TL değeri = Mal Hizmet Tutarı ──
        tl_values = [_tr_float(v) for v in re.findall(r'([0-9.,]+)\s*TL', block)]
        tl_values = [v for v in tl_values if v and v > 0]
        if not tl_values:
            continue
        amount = max(tl_values)

        lines.append({
            "description": desc,
            "amount":      round(amount, 2),
            "vat_rate":    vat_rate,
        })

    return lines
