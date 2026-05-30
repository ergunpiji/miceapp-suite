/* ======================================================================
   PrizmaUI — Animated counter · Toast · Empty state
   ====================================================================== */

// ── 1. Animated Counter ───────────────────────────────────────────────
(function () {
  function fmt(v) {
    const abs = Math.abs(v);
    const s = new Intl.NumberFormat('tr-TR', {
      minimumFractionDigits: 2, maximumFractionDigits: 2,
    }).format(abs);
    return (v < 0 ? '-' : '') + s + ' ₺';
  }

  function ease(t) { return 1 - Math.pow(1 - t, 4); } // easeOutQuart

  function run(el, target, ms) {
    const t0 = performance.now();
    (function tick(now) {
      const p = Math.min((now - t0) / ms, 1);
      el.textContent = fmt(target * ease(p));
      if (p < 1) requestAnimationFrame(tick);
      else el.textContent = fmt(target);
    })(t0);
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-counter]').forEach(function (el) {
      var v = parseFloat(el.dataset.counter);
      if (!isNaN(v)) run(el, v, 1100);
    });
  });
})();

// ── 2. Toast Notifications ────────────────────────────────────────────
(function () {
  function container() {
    var c = document.getElementById('prizma-toasts');
    if (!c) {
      c = document.createElement('div');
      c.id = 'prizma-toasts';
      document.body.appendChild(c);
    }
    return c;
  }

  window.showToast = function (msg, type, ms) {
    type = type || 'success';
    ms   = ms   || 3500;
    var icons = { success: 'check-circle-fill', error: 'x-circle-fill',
                  warning: 'exclamation-triangle-fill', info: 'info-circle-fill' };
    var el = document.createElement('div');
    el.className = 'pz-toast pz-toast-' + type;
    el.innerHTML = '<i class="bi bi-' + (icons[type] || 'info-circle-fill') + '"></i><span>' + msg + '</span>';
    container().appendChild(el);
    requestAnimationFrame(function () { requestAnimationFrame(function () { el.classList.add('show'); }); });
    setTimeout(function () {
      el.classList.remove('show');
      setTimeout(function () { el.remove(); }, 380);
    }, ms);
  };

  // URL param auto-toast: ?_ok=Mesaj or ?_err=Mesaj
  document.addEventListener('DOMContentLoaded', function () {
    var p = new URLSearchParams(location.search);
    if (p.get('_ok'))  showToast(decodeURIComponent(p.get('_ok')),  'success');
    if (p.get('_err')) showToast(decodeURIComponent(p.get('_err')), 'error');
    if (p.has('_ok') || p.has('_err')) {
      p.delete('_ok'); p.delete('_err');
      history.replaceState(null, '', location.pathname + (p.toString() ? '?' + p : ''));
    }
  });
})();

// ── 3. Auto-enhance empty table cells ────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('td[colspan]').forEach(function (td) {
    var txt = td.textContent.trim();
    if (!txt) return;
    var isEmpty = /yok\.|yok$|bulunamadı|kayıt yok/i.test(txt);
    if (!isEmpty) return;
    td.innerHTML =
      '<div class="pz-empty">' +
        '<i class="bi bi-inbox"></i>' +
        '<span>' + txt + '</span>' +
      '</div>';
  });
});
