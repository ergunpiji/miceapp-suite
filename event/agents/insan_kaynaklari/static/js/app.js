/* HR Ajanı — Yardımcı JS */

// Modal dışına tıklayınca kapat
document.addEventListener('click', function(e) {
  if (e.target.classList.contains('modal-overlay')) {
    e.target.classList.remove('open');
  }
});

// Escape tuşu ile modal kapat
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal-overlay.open').forEach(function(m) {
      m.classList.remove('open');
    });
  }
});

// Bildirim sayısı periyodik kontrol (30sn)
function refreshNotifCount() {
  fetch('/notifications/count')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var badge = document.querySelector('.notif-badge');
      if (data.count > 0) {
        if (!badge) {
          badge = document.createElement('span');
          badge.className = 'notif-badge';
          var notifLink = document.querySelector('a[href="/notifications"]');
          if (notifLink) notifLink.appendChild(badge);
        }
        badge.textContent = data.count;
      } else if (badge) {
        badge.remove();
      }
    })
    .catch(function() {});
}

setInterval(refreshNotifCount, 30000);

// Confirm helper — form submit onaylama
document.querySelectorAll('[data-confirm]').forEach(function(el) {
  el.addEventListener('click', function(e) {
    if (!confirm(el.dataset.confirm)) e.preventDefault();
  });
});
