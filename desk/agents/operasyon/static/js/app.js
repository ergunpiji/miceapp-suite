// Silme onayı
document.querySelectorAll('form[data-confirm]').forEach(form => {
  form.addEventListener('submit', e => {
    if (!confirm(form.dataset.confirm)) e.preventDefault();
  });
});

// URL'deki flash mesajları
const params = new URLSearchParams(window.location.search);
const imported = params.get('imported');
const skipped  = params.get('skipped');
if (imported) {
  const alert = document.createElement('div');
  alert.className = 'alert alert-success';
  let msg = `✅ ${imported} katılımcı başarıyla içe aktarıldı.`;
  if (skipped && parseInt(skipped) > 0) {
    msg += ` <span style="opacity:.8">(${skipped} tekrar/boş kayıt atlandı)</span>`;
  }
  alert.innerHTML = msg;
  const main = document.querySelector('.main-content');
  if (main) main.prepend(alert);
  window.history.replaceState({}, '', window.location.pathname);
}

// Dosya yükleme drag & drop
const uploadArea = document.getElementById('upload-area');
const fileInput = document.getElementById('file-input');

if (uploadArea && fileInput) {
  uploadArea.addEventListener('click', () => fileInput.click());

  uploadArea.addEventListener('dragover', e => {
    e.preventDefault();
    uploadArea.classList.add('dragover');
  });

  uploadArea.addEventListener('dragleave', () => {
    uploadArea.classList.remove('dragover');
  });

  uploadArea.addEventListener('drop', e => {
    e.preventDefault();
    uploadArea.classList.remove('dragover');
    if (e.dataTransfer.files.length) {
      fileInput.files = e.dataTransfer.files;
      showFileName(e.dataTransfer.files[0].name);
      uploadArea.closest('form').submit();
    }
  });

  fileInput.addEventListener('change', () => {
    if (fileInput.files.length) {
      showFileName(fileInput.files[0].name);
      fileInput.closest('form').submit();
    }
  });

  function showFileName(name) {
    const hint = uploadArea.querySelector('.upload-area-hint');
    if (hint) hint.textContent = `Seçilen: ${name} — yükleniyor...`;
  }
}
