"""
Türkiye Fatura Okuma Agenti
---------------------------
Claude tool_use ile garantili yapılandırılmış çıktı.
Türkiye KDV mevzuatı, e-Fatura/e-Arşiv/kağıt fatura formatlarını destekler.
"""
import base64
import os

# ---------------------------------------------------------------------------
# Tool şeması — Claude bu araç tanımını kullanarak çıktı üretir.
# JSON parse hatası olmaz; alan tipleri schema tarafından garantilenir.
# ---------------------------------------------------------------------------
INVOICE_TOOL = {
    "name": "extract_invoice",
    "description": (
        "Fatura görselinden veya PDF'inden yapılandırılmış muhasebe verisi çıkar. "
        "Tüm tutarlar KDV hariç (matrah) olmalıdır."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "invoice_no": {
                "type": "string",
                "description": "Fatura/fiş numarası (ETTN, seri-sıra no vb.)"
            },
            "invoice_date": {
                "type": "string",
                "description": "Fatura kesim tarihi — YYYY-MM-DD"
            },
            "due_date": {
                "type": "string",
                "description": "Son ödeme / vade tarihi — YYYY-MM-DD. Yoksa boş string."
            },
            "vendor_name": {
                "type": "string",
                "description": "Faturayı kesen (satan) tarafın ticari unvanı"
            },
            "description": {
                "type": "string",
                "description": "Fatura üzerindeki genel açıklama / sipariş notu. Yoksa boş string."
            },
            "currency": {
                "type": "string",
                "description": "Para birimi kodu: TRY, USD, EUR, GBP. Varsayılan TRY.",
                "enum": ["TRY", "USD", "EUR", "GBP", "CHF"]
            },
            "grand_total_incl": {
                "type": "number",
                "description": "KDV dahil genel toplam (faturanın en alt satırı)"
            },
            "lines": {
                "type": "array",
                "description": "Fatura kalemleri. Her farklı KDV oranı ayrı satır.",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {
                            "type": "string",
                            "description": "Kalem adı / hizmet açıklaması"
                        },
                        "amount": {
                            "type": "number",
                            "description": (
                                "KDV HARİÇ matrah tutarı. "
                                "Faturada 'Matrah' sütunu varsa onu al. "
                                "Yoksa: kdv_dahil ÷ (1 + kdv_oranı/100)"
                            )
                        },
                        "vat_rate": {
                            "type": "integer",
                            "description": (
                                "KDV oranı tam sayı. Geçerli değerler: 0, 1, 8, 10, 18, 20. "
                                "ZORUNLU: 'Konaklama Vergisi' satırı için her zaman 0 yaz — "
                                "bu vergi KDV kanunu kapsamında değildir, üzerine KDV uygulanmaz. "
                                "Diğer bilinmeyen oranları en yakın geçerli değere yuvarla."
                            )
                        },
                        "vat_amount": {
                            "type": "number",
                            "description": "KDV tutarı. Faturada yoksa: amount × vat_rate / 100"
                        },
                        "total_incl": {
                            "type": "number",
                            "description": "KDV dahil satır toplamı"
                        }
                    },
                    "required": ["description", "amount", "vat_rate"]
                }
            }
        },
        "required": ["invoice_no", "invoice_date", "vendor_name", "lines"]
    }
}

# ---------------------------------------------------------------------------
# Sistem promptu — Türkiye vergi ve faturalama mevzuatı
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
Sen Türkiye vergi mevzuatına ve faturalama sistemine hakim, deneyimli bir mali müşavirsin.
Görevin: Sana iletilen fatura görselinden veya PDF'inden yapılandırılmış muhasebe verisi çıkarmak.

## Türkiye KDV Sistemi (01.07.2023 sonrası geçerli oranlar)
| Oran | Uygulama Alanı |
|------|---------------|
| %0   | İhracat, transit taşımacılık, temel gıda (süt, yumurta, ekmek, sebze/meyve), sağlık, eğitim |
| %1   | Tarım ürünleri, bazı işlenmiş gıdalar, gazete/dergi |
| %10  | Restoran/kafe/yemek hizmetleri, su ürünleri |
| %20  | Genel standart oran — akaryakıt, elektronik, tekstil, inşaat, danışmanlık, kira, vs. |

## Konaklama hizmetleri KDV oranı
- Otel/pansiyon geceleme hizmeti → KDV **%10**

**DİKKAT**: %8, %13, %15, %18, %25 gibi oranlar Türkiye'de GÜNCEL DEĞİLDİR.
- Faturada %18 görürsen → %20 olarak yuvarla (2023 öncesi fatura olabilir)
- Faturada %8 görürsen → %10 olarak yuvarla (2023 öncesi fatura olabilir)
- Yabancı ülke faturasındaysa (€/$) orijinal oranı en yakın Türkiye oranına yuvarla
- Kesinlikle emin olamıyorsan %20 kullan

## Fatura Türleri ve Özellikleri
- **e-Fatura (GIB)**: ETTN numarası, QR kod, "Bu belge 5070 sayılı kanun..." ibaresi
- **e-Arşiv Fatura**: "e-Arşiv Fatura" ibaresi, internet satış faturası
- **e-SMM (Serbest Meslek Makbuzu)**: Tevkifat/stopaj satırı olabilir — bunu vat_rate=0 satır olarak ekle
- **Kağıt Fatura**: Matbaa baskılı seri/sıra numarası (örn: ABC/2024-001)
- **Perakende Fiş**: Kasa fişi, KDV ayrı gösterilmeyebilir — oranı hizmet türünden çıkar

## Matrah (KDV Hariç Tutar) Hesaplama — Öncelik Sırası
1. Faturada **"Matrah"** veya **"KDV Hariç Tutar"** veya **"Net Tutar"** sütunu/satırı varsa → BUNU AL
2. Faturada **"KDV Tutarı"** ayrı gösteriliyorsa → matrah = kdv_dahil_toplam − kdv_tutarı
3. Hiçbiri yoksa → matrah = kdv_dahil_toplam ÷ (1 + kdv_oranı/100)
   - Örnek %10: 1.100 ÷ 1.10 = 1.000,00
   - Örnek %20: 1.200 ÷ 1.20 = 1.000,00

## ⚠️ KONAKLAMAVERGİSİ — EN ÖNEMLİ KURAL
Faturada "Konaklama Vergisi" satırı varsa:
- Bu satır için **vat_rate = 0** yaz. Kesinlikle 2, 10 veya başka bir sayı YAZMA.
- Konaklama Vergisi, KDV kanunu kapsamında DEĞİLDİR. Üzerine KDV uygulanmaz.
- vat_amount = 0, total_incl = amount (tutarın kendisi)
- Geceleme satırından AYRI bir kalem olarak çıkar.

Doğru örnek — otel faturası:
  lines[0]: description="Konaklama Hizmeti", amount=10000, vat_rate=10, vat_amount=1000
  lines[1]: description="Konaklama Vergisi", amount=200, vat_rate=0, vat_amount=0

Yanlış örnek (YAPMA):
  lines[1]: description="Konaklama Vergisi", amount=200, vat_rate=2, vat_amount=4  ← YANLIŞ
  lines[1]: description="Konaklama Vergisi", amount=200, vat_rate=10, vat_amount=20 ← YANLIŞ

## Çıkarma Kuralları
- Her **farklı KDV oranı** için ayrı satır oluştur
- "Ara Toplam", "KDV Toplamı", "Genel Toplam" satırlarını lines'a **EKLEME**
- Hizmet bedeli / komisyon / kargo satırları varsa ayrı kalem olarak ekle
- Tevkifat / stopaj varsa (e-SMM) → ayrı satır, vat_rate=0, açıklamaya "Tevkifat" yaz
- Tüm tutarlar orijinal para biriminde olmalı

## Tarih Çevirme
- "11 Nisan 2026" → "2026-04-11"
- "11/04/2026" veya "11.04.2026" → "2026-04-11"
- "04-11-2026" (ABD formatı) → tarihin fatura bağlamına göre değerlendir
"""

# ---------------------------------------------------------------------------
# Ana fonksiyon
# ---------------------------------------------------------------------------
VALID_VAT = {0, 1, 8, 10, 18, 20}


def _snap_vat(vr: int) -> int:
    """Geçersiz KDV oranını en yakın geçerli değere yuvarla."""
    if vr in VALID_VAT:
        return vr
    return min(VALID_VAT, key=lambda x: abs(x - vr))


def parse_invoice(file_bytes: bytes, filename: str, api_key: str) -> dict:
    """
    Tool use ile fatura parse et; doğrulanmış dict döndür.

    Returns:
        {
          "invoice_no": str,
          "invoice_date": str,       # YYYY-MM-DD
          "due_date": str,            # YYYY-MM-DD veya ""
          "vendor_name": str,
          "description": str,
          "currency": str,
          "grand_total_incl": float,
          "lines": [
              {"description": str, "amount": float,
               "vat_rate": int, "vat_amount": float, "total_incl": float}
          ]
        }

    Raises:
        ValueError: API yanıtı geçersizse
        Exception:  Anthropic API hatası
    """
    import anthropic

    ext = os.path.splitext(filename)[1].lower()
    b64 = base64.standard_b64encode(file_bytes).decode()

    if ext == ".pdf":
        content_block = {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
        }
    else:
        mime_map = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png",  ".webp": "image/webp",
        }
        mime = mime_map.get(ext, "image/jpeg")
        content_block = {
            "type": "image",
            "source": {"type": "base64", "media_type": mime, "data": b64},
        }

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        tools=[INVOICE_TOOL],
        tool_choice={"type": "any"},   # mutlaka extract_invoice tool'unu çağırır
        messages=[{
            "role": "user",
            "content": [
                content_block,
                {"type": "text", "text": "Bu faturadan tüm bilgileri çıkar."},
            ],
        }],
    )

    # tool_use bloğunu bul
    tool_block = next(
        (b for b in response.content if hasattr(b, "type") and b.type == "tool_use"),
        None
    )
    if not tool_block:
        raise ValueError("AI fatura verisi döndürmedi. Lütfen tekrar deneyin.")

    data: dict = tool_block.input

    # Varsayılanlar
    data.setdefault("due_date", "")
    data.setdefault("description", "")
    data.setdefault("currency", "TRY")
    data.setdefault("grand_total_incl", 0.0)

    # Satır düzeltme + doğrulama
    for ln in data.get("lines", []):
        # KDV oranı snap
        vr = int(ln.get("vat_rate") or 20)
        ln["vat_rate"] = _snap_vat(vr)

        amt = float(ln.get("amount") or 0)

        # vat_amount yoksa hesapla
        if not ln.get("vat_amount"):
            ln["vat_amount"] = round(amt * ln["vat_rate"] / 100, 2)

        # total_incl yoksa hesapla
        if not ln.get("total_incl"):
            ln["total_incl"] = round(amt + ln["vat_amount"], 2)

    # grand_total_incl yoksa satırlardan türet
    if not data["grand_total_incl"] and data.get("lines"):
        data["grand_total_incl"] = round(
            sum(ln.get("total_incl", 0) for ln in data["lines"]), 2
        )

    return data
