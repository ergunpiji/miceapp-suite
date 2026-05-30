/* Otomatik tablo sıralama — tüm <table> elementleri için.
   Devre dışı bırakmak için <table class="no-sort"> veya <th class="no-sort">
   <tbody> içindeki <tr class="no-sort"> satırları sıralamaya dahil edilmez (alt toplam vb).
   Hücreye data-sort="..." verilirse sıralama o değere göre yapılır. */
(function () {
  'use strict';

  var TR = new Intl.Collator('tr', { sensitivity: 'base' });
  var DATE_RE = /^\d{1,2}\.\d{1,2}\.\d{4}$/;
  var NUM_RE = /^-?[\d.,\s₺%]+$/;

  function cellValue(cell) {
    if (cell == null) return '';
    if (cell.dataset && cell.dataset.sort !== undefined) return cell.dataset.sort;
    return (cell.textContent || '').trim();
  }

  function parseNumber(v) {
    var s = v.replace(/[₺\s%]/g, '');
    if (s.indexOf('.') !== -1 && s.indexOf(',') !== -1) {
      s = s.replace(/\./g, '').replace(',', '.');
    } else if (s.indexOf(',') !== -1) {
      s = s.replace(',', '.');
    }
    var n = parseFloat(s);
    return isNaN(n) ? null : n;
  }

  function detectType(values) {
    var allDate = true, allNum = true, seen = false;
    for (var i = 0; i < values.length; i++) {
      var v = values[i];
      if (!v || v === '—' || v === '-') continue;
      seen = true;
      if (!DATE_RE.test(v)) allDate = false;
      if (!NUM_RE.test(v) || parseNumber(v) === null) allNum = false;
      if (!allDate && !allNum) break;
    }
    if (!seen) return 'text';
    if (allDate) return 'date';
    if (allNum) return 'num';
    return 'text';
  }

  function toKey(v, type) {
    if (!v || v === '—' || v === '-') {
      return type === 'text' ? '' : -Infinity;
    }
    if (type === 'date') {
      var p = v.split('.');
      return parseInt(p[2], 10) * 10000 + parseInt(p[1], 10) * 100 + parseInt(p[0], 10);
    }
    if (type === 'num') {
      var n = parseNumber(v);
      return n === null ? -Infinity : n;
    }
    return v.toLocaleLowerCase('tr');
  }

  function attachSort(table) {
    var thead = table.tBodies && table.tHead ? table.tHead : null;
    if (!thead) return;
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var headerRows = thead.rows;
    if (!headerRows.length) return;
    var headerRow = headerRows[headerRows.length - 1];
    var ths = headerRow.cells;

    Array.prototype.forEach.call(ths, function (th, colIdx) {
      if (th.classList.contains('no-sort')) return;
      th.style.cursor = 'pointer';
      th.style.userSelect = 'none';
      th.setAttribute('title', 'Sıralamak için tıklayın');

      var arrow = document.createElement('span');
      arrow.className = 'sort-arrow';
      arrow.style.cssText = 'opacity:.35;margin-left:4px;font-size:10px;display:inline-block;';
      arrow.textContent = '↕';
      th.appendChild(arrow);

      th.addEventListener('click', function (e) {
        if (e.target.tagName === 'A' || e.target.tagName === 'INPUT' ||
            e.target.tagName === 'SELECT' || e.target.tagName === 'BUTTON') return;

        var dir = th.dataset.sortDir === 'asc' ? 'desc' : 'asc';

        Array.prototype.forEach.call(ths, function (other) {
          if (other === th) return;
          other.dataset.sortDir = '';
          var oa = other.querySelector('.sort-arrow');
          if (oa) { oa.textContent = '↕'; oa.style.opacity = '.35'; }
        });
        th.dataset.sortDir = dir;
        arrow.textContent = dir === 'asc' ? '▲' : '▼';
        arrow.style.opacity = '1';

        var allRows = Array.prototype.slice.call(tbody.rows);
        var sortable = [];
        var fixed = [];
        allRows.forEach(function (r) {
          (r.classList.contains('no-sort') ? fixed : sortable).push(r);
        });

        var sample = sortable.map(function (r) { return cellValue(r.cells[colIdx]); });
        var type = detectType(sample);

        sortable.sort(function (a, b) {
          var ka = toKey(cellValue(a.cells[colIdx]), type);
          var kb = toKey(cellValue(b.cells[colIdx]), type);
          if (type === 'text') {
            return dir === 'asc' ? TR.compare(ka, kb) : TR.compare(kb, ka);
          }
          if (ka < kb) return dir === 'asc' ? -1 : 1;
          if (ka > kb) return dir === 'asc' ? 1 : -1;
          return 0;
        });

        var frag = document.createDocumentFragment();
        sortable.forEach(function (r) { frag.appendChild(r); });
        fixed.forEach(function (r) { frag.appendChild(r); });
        tbody.appendChild(frag);
      });
    });
  }

  function init() {
    document.querySelectorAll('table').forEach(function (t) {
      if (t.classList.contains('no-sort')) return;
      if (t.dataset.sortAttached) return;
      t.dataset.sortAttached = '1';
      attachSort(t);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
