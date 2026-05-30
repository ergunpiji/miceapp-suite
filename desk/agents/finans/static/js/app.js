// Finans Ajanı — Genel JS

// Modal aç/kapat
document.addEventListener("click", (e) => {
  const trigger = e.target.closest("[data-modal]");
  if (trigger) {
    const id = trigger.dataset.modal;
    document.getElementById(id)?.classList.add("open");
  }
  if (e.target.classList.contains("modal-overlay")) {
    e.target.classList.remove("open");
  }
  if (e.target.closest("[data-close-modal]")) {
    e.target.closest(".modal-overlay")?.classList.remove("open");
  }
});

// Silme onayı
document.addEventListener("submit", (e) => {
  const form = e.target;
  if (form.dataset.confirm) {
    if (!confirm(form.dataset.confirm)) {
      e.preventDefault();
    }
  }
});

// E-fatura satır hesaplama
function recalcLine(row) {
  const qty       = parseFloat(row.querySelector(".line-qty")?.value) || 0;
  const unitPrice = parseFloat(row.querySelector(".line-unit-price")?.value) || 0;
  const vatRate   = parseFloat(row.querySelector(".line-vat-rate")?.value) || 0;
  const excl      = qty * unitPrice;
  const vat       = excl * vatRate / 100;
  const incl      = excl + vat;
  const exclEl    = row.querySelector(".line-amount-excl");
  const vatEl     = row.querySelector(".line-vat-amount");
  const inclEl    = row.querySelector(".line-amount-incl");
  if (exclEl) exclEl.textContent = formatCurrency(excl);
  if (vatEl)  vatEl.textContent  = formatCurrency(vat);
  if (inclEl) inclEl.textContent = formatCurrency(incl);
  recalcTotals();
}

function recalcTotals() {
  const rows = document.querySelectorAll(".invoice-line-row");
  let totalExcl = 0, totalVat = 0;
  rows.forEach(row => {
    const qty       = parseFloat(row.querySelector(".line-qty")?.value) || 0;
    const unitPrice = parseFloat(row.querySelector(".line-unit-price")?.value) || 0;
    const vatRate   = parseFloat(row.querySelector(".line-vat-rate")?.value) || 0;
    const excl      = qty * unitPrice;
    const vat       = excl * vatRate / 100;
    totalExcl += excl;
    totalVat  += vat;
  });
  const totalEl     = document.getElementById("total-excl");
  const vatTotalEl  = document.getElementById("total-vat");
  const inclTotalEl = document.getElementById("total-incl");
  if (totalEl)     totalEl.textContent     = formatCurrency(totalExcl);
  if (vatTotalEl)  vatTotalEl.textContent  = formatCurrency(totalVat);
  if (inclTotalEl) inclTotalEl.textContent = formatCurrency(totalExcl + totalVat);
}

function formatCurrency(val) {
  return "₺" + val.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

// Fatura satır dinleyicileri
document.addEventListener("input", (e) => {
  const row = e.target.closest(".invoice-line-row");
  if (row && (
    e.target.classList.contains("line-qty") ||
    e.target.classList.contains("line-unit-price") ||
    e.target.classList.contains("line-vat-rate")
  )) {
    recalcLine(row);
  }
});

// Fatura satır ekle
const addLineBtn = document.getElementById("add-invoice-line");
if (addLineBtn) {
  addLineBtn.addEventListener("click", () => {
    const tbody = document.getElementById("invoice-lines");
    const idx   = tbody.querySelectorAll(".invoice-line-row").length;
    const vat_opts = [0, 1, 8, 10, 18, 20].map(r =>
      `<option value="${r}" ${r === 20 ? "selected" : ""}>${r}%</option>`
    ).join("");
    const row = document.createElement("tr");
    row.className = "invoice-line-row";
    row.innerHTML = `
      <td><input class="line-desc" name="line_description" placeholder="Hizmet açıklaması" required></td>
      <td><input class="line-unit" name="line_unit" value="Adet" style="width:70px"></td>
      <td><input class="line-qty"  name="line_qty"  type="number" value="1" min="0" step="any" style="width:70px"></td>
      <td><input class="line-unit-price" name="line_unit_price" type="number" value="0" min="0" step="any" style="width:110px"></td>
      <td><select class="line-vat-rate" name="line_vat_rate">${vat_opts}</select></td>
      <td class="line-amount-excl text-right">₺0,00</td>
      <td class="line-vat-amount  text-right">₺0,00</td>
      <td class="line-amount-incl text-right font-mono">₺0,00</td>
      <td><button type="button" class="btn btn-xs btn-danger remove-line">✕</button></td>
    `;
    tbody.appendChild(row);
    row.querySelector(".remove-line").addEventListener("click", () => {
      row.remove();
      recalcTotals();
    });
  });
}

// Sayfa yüklenince mevcut satırları hesapla
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".invoice-line-row").forEach(recalcLine);
});
