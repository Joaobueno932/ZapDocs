/* ─── Toast ────────────────────────────────────────────────────────────── */

function toast(msg, type = 'success') {
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.innerHTML = `<span>${type === 'success' ? '✓' : '✕'}</span><span>${msg}</span>`;
  document.getElementById('toast-container').appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

/* ─── Modal ─────────────────────────────────────────────────────────────── */

function openModal(id) { document.getElementById(id).classList.add('open'); }
function closeModal(id) { document.getElementById(id).classList.remove('open'); }

document.addEventListener('click', e => {
  if (e.target.classList.contains('modal-overlay')) {
    e.target.classList.remove('open');
  }
});

/* ─── Dashboard — Upload & Convert ─────────────────────────────────────── */

let currentJobId = null;
let pollInterval = null;

function initDashboard() {
  const dropzone  = document.getElementById('dropzone');
  const fileInput = document.getElementById('file-input');

  if (!dropzone) return;

  dropzone.addEventListener('click', () => fileInput.click());

  fileInput.addEventListener('change', () => {
    if (fileInput.files[0]) setFile(fileInput.files[0]);
  });

  dropzone.addEventListener('dragover', e => {
    e.preventDefault();
    dropzone.classList.add('dragover');
  });
  dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
  dropzone.addEventListener('drop', e => {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (file) setFile(file);
  });
}

function setFile(file) {
  const dropzone = document.getElementById('dropzone');
  dropzone.classList.add('has-file');
  dropzone.innerHTML = `
    <div class="dropzone-icon">
      <svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm-1 1.5L18.5 9H13V3.5zM6 20V4h5v7h7v9H6z"/></svg>
    </div>
    <h3>Arquivo selecionado</h3>
    <p class="file-name">${file.name}</p>
    <p class="text-sm mt-4">Clique para trocar o arquivo</p>
  `;
  document.getElementById('file-input-hidden').fileObj = file;
}

async function startConvert() {
  const file = document.getElementById('file-input-hidden').fileObj;
  if (!file) { toast('Selecione um arquivo ZIP primeiro.', 'error'); return; }

  const formData = new FormData();
  formData.append('file', file);

  setUI('converting');

  try {
    const res  = await fetch('/convert', { method: 'POST', body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Erro ao iniciar conversão.');
    currentJobId = data.job_id;
    pollStatus();
  } catch (err) {
    setUI('idle');
    toast(err.message, 'error');
  }
}

function pollStatus() {
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(async () => {
    try {
      const res  = await fetch(`/status/${currentJobId}`);
      const data = await res.json();

      document.getElementById('progress-msg').textContent = data.message || '';

      if (data.status === 'done') {
        clearInterval(pollInterval);
        setUI('done', data.stats);
      } else if (data.status === 'error') {
        clearInterval(pollInterval);
        setUI('idle');
        toast(data.error || 'Erro na conversão.', 'error');
      }
    } catch {
      clearInterval(pollInterval);
      setUI('idle');
      toast('Erro ao verificar status.', 'error');
    }
  }, 900);
}

function setUI(state, stats) {
  const btnConvert  = document.getElementById('btn-convert');
  const progressSec = document.getElementById('progress-section');
  const resultCard  = document.getElementById('result-card');

  if (state === 'converting') {
    btnConvert.disabled = true;
    btnConvert.textContent = 'Convertendo...';
    progressSec.classList.add('visible');
    resultCard.classList.remove('visible');
  } else if (state === 'idle') {
    btnConvert.disabled = false;
    btnConvert.textContent = 'Converter para PDF';
    progressSec.classList.remove('visible');
  } else if (state === 'done') {
    btnConvert.disabled = false;
    btnConvert.textContent = 'Converter para PDF';
    progressSec.classList.remove('visible');

    if (stats) {
      document.getElementById('stat-msgs').textContent    = Number(stats.total_mensagens).toLocaleString('pt-BR');
      document.getElementById('stat-pages').textContent   = stats.paginas;
      document.getElementById('stat-period').textContent  = `${stats.periodo_inicio} – ${stats.periodo_fim}`;
      document.getElementById('stat-media').textContent   = stats.n_extraidos;
      document.getElementById('stat-name').textContent    = stats.nome;
    }
    document.getElementById('btn-download').onclick = () => {
      window.location.href = `/download/${currentJobId}`;
    };
    resultCard.classList.add('visible');
    toast('PDF gerado com sucesso!');
  }
}

/* ─── Admin — User Management ───────────────────────────────────────────── */

function initAdmin() {
  const form = document.getElementById('form-create-user');
  if (!form) return;

  form.addEventListener('submit', async e => {
    e.preventDefault();
    const btn  = form.querySelector('button[type=submit]');
    btn.disabled = true;

    const payload = {
      username: document.getElementById('new-username').value.trim(),
      password: document.getElementById('new-password').value.trim(),
      name:     document.getElementById('new-name').value.trim(),
      role:     document.getElementById('new-role').value,
    };

    try {
      const res  = await fetch('/admin/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error);
      closeModal('modal-create');
      toast(`Usuário "${payload.username}" criado com sucesso!`);
      setTimeout(() => location.reload(), 800);
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      btn.disabled = false;
    }
  });
}

async function permanentDelete(id, name) {
  if (!confirm(`Excluir permanentemente o usuário "${name}"?\n\nEsta ação não pode ser desfeita.`)) return;
  try {
    const res  = await fetch(`/admin/users/${id}/delete`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error);
    toast(`Usuário "${name}" excluído permanentemente.`);
    setTimeout(() => location.reload(), 800);
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function deleteUser(id, name) {
  if (!confirm(`Desativar o usuário "${name}"?`)) return;
  try {
    const res  = await fetch(`/admin/users/${id}`, { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error);
    toast(`Usuário "${name}" desativado.`);
    setTimeout(() => location.reload(), 800);
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function activateUser(id, name) {
  try {
    const res  = await fetch(`/admin/users/${id}/activate`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error);
    toast(`Usuário "${name}" reativado.`);
    setTimeout(() => location.reload(), 800);
  } catch (err) {
    toast(err.message, 'error');
  }
}

function openResetModal(id, name) {
  document.getElementById('reset-user-id').value   = id;
  document.getElementById('reset-user-name').textContent = name;
  document.getElementById('reset-password').value  = '';
  openModal('modal-reset');
}

function openLimitModal(id, name, count, limit) {
  document.getElementById('limit-user-id').value        = id;
  document.getElementById('limit-user-name').textContent = name;
  document.getElementById('limit-count-display').textContent = count;
  document.getElementById('limit-limit-display').textContent = limit === null ? '∞' : limit;
  document.getElementById('limit-set-value').value = limit === null ? '' : limit;
  document.getElementById('limit-add-value').value = '';
  openModal('modal-limit');
}

async function _submitLimit(action, value) {
  const id = document.getElementById('limit-user-id').value;
  try {
    const res  = await fetch(`/admin/users/${id}/limit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, value: value === '' ? null : Number(value) }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error);
    closeModal('modal-limit');
    toast('Limite atualizado com sucesso!');
    setTimeout(() => location.reload(), 800);
  } catch (err) {
    toast(err.message, 'error');
  }
}

function submitLimitSet() {
  const val = document.getElementById('limit-set-value').value.trim();
  _submitLimit('set', val);
}

function submitLimitAdd() {
  const val = document.getElementById('limit-add-value').value.trim();
  if (!val || Number(val) < 1) { toast('Informe um número válido para adicionar.', 'error'); return; }
  _submitLimit('add', val);
}

async function submitReset() {
  const id  = document.getElementById('reset-user-id').value;
  const pwd = document.getElementById('reset-password').value.trim();
  if (!pwd || pwd.length < 6) { toast('Senha deve ter no mínimo 6 caracteres.', 'error'); return; }

  try {
    const res  = await fetch(`/admin/users/${id}/reset`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: pwd }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error);
    closeModal('modal-reset');
    toast('Senha redefinida com sucesso!');
  } catch (err) {
    toast(err.message, 'error');
  }
}

/* ─── Init ───────────────────────────────────────────────────────────────── */

document.addEventListener('DOMContentLoaded', () => {
  initDashboard();
  initAdmin();
});
