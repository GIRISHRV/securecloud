const state = { profile: null, resource: null, editingId: null };

const elements = {
  appName: document.querySelector('#app-name'), profileKind: document.querySelector('#profile-kind'),
  title: document.querySelector('#view-title'), description: document.querySelector('#view-description'),
  navigation: document.querySelector('#resource-navigation'), overview: document.querySelector('#overview-view'),
  resourceView: document.querySelector('#resource-view'), summary: document.querySelector('#summary-metrics'),
  records: document.querySelector('#records-body'), recordsHead: document.querySelector('#records-head'),
  recordCount: document.querySelector('#record-count'), empty: document.querySelector('#empty-message'),
  form: document.querySelector('#record-form'), fields: document.querySelector('#record-fields'),
  formTitle: document.querySelector('#form-title'), saveRecord: document.querySelector('#save-record'),
  openForm: document.querySelector('#open-form'), cancelForm: document.querySelector('#cancel-form'),
  health: document.querySelector('#health-status'), error: document.querySelector('#error-message'),
};

async function request(path, options) {
  const response = await fetch(path, {
    ...options, headers: { 'Content-Type': 'application/json', ...(options?.headers ?? {}) },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.status === 204 ? null : response.json();
}

function showError(message) { elements.error.textContent = message; elements.error.hidden = false; }
function clearError() { elements.error.hidden = true; elements.error.textContent = ''; }

function createNavigation(profile) {
  const fragment = document.createDocumentFragment();
  for (const resource of profile.resources) {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'nav-item'; button.dataset.resource = resource.id;
    button.textContent = resource.label; fragment.append(button);
  }
  elements.navigation.replaceChildren(fragment);
}

function setActiveNavigation(resourceId) {
  document.querySelectorAll('.nav-item').forEach((item) => {
    const active = resourceId ? item.dataset.resource === resourceId : item.dataset.view === 'overview';
    item.classList.toggle('is-active', active);
    if (active) item.setAttribute('aria-current', 'page'); else item.removeAttribute('aria-current');
  });
}

function closeRecordForm() {
  state.editingId = null; elements.form.reset(); elements.form.hidden = true;
}

async function showOverview() {
  clearError(); state.resource = null; setActiveNavigation(null);
  elements.overview.hidden = false; elements.resourceView.hidden = true;
  elements.title.textContent = 'Overview'; elements.description.textContent = state.profile.description;
  try {
    const summary = await request('/api/summary');
    const fragment = document.createDocumentFragment();
    for (const resource of state.profile.resources) {
      const metric = document.createElement('div'); metric.className = 'metric';
      const value = document.createElement('strong'); value.textContent = String(summary.counts[resource.id] ?? 0);
      const label = document.createElement('span'); label.textContent = resource.label;
      metric.append(value, label); fragment.append(metric);
    }
    elements.summary.replaceChildren(fragment);
  } catch (error) { showError(error.message); }
}

function buildFields(resource) {
  const fragment = document.createDocumentFragment();
  for (const field of resource.fields) {
    const wrapper = document.createElement('div'); wrapper.className = 'field';
    const label = document.createElement('label'); label.htmlFor = `field-${field.id}`; label.textContent = field.label;
    let input;
    if (field.kind === 'select') {
      input = document.createElement('select');
      const placeholder = document.createElement('option');
      placeholder.value = ''; placeholder.textContent = 'Select…'; placeholder.disabled = true; placeholder.selected = true;
      input.append(placeholder);
      for (const value of field.options) {
        const option = document.createElement('option'); option.value = value; option.textContent = value; input.append(option);
      }
    } else {
      input = document.createElement('input'); input.type = field.kind; input.maxLength = field.maxLength;
    }
    input.id = `field-${field.id}`; input.name = field.id; input.required = field.required;
    wrapper.append(label, input); fragment.append(wrapper);
  }
  elements.fields.replaceChildren(fragment);
}

function buildTableHead(resource) {
  const fragment = document.createDocumentFragment();
  for (const field of resource.fields) {
    const heading = document.createElement('th'); heading.scope = 'col'; heading.textContent = field.label; fragment.append(heading);
  }
  const actions = document.createElement('th'); actions.scope = 'col'; actions.textContent = 'Actions'; fragment.append(actions);
  elements.recordsHead.replaceChildren(fragment);
}

function openRecordForm(record = null) {
  state.editingId = record?.id ?? null; elements.form.reset();
  elements.formTitle.textContent = `${record ? 'Edit' : 'Add'} ${state.resource.singular}`;
  elements.saveRecord.textContent = record ? 'Save changes' : `Add ${state.resource.singular}`;
  if (record) for (const field of state.resource.fields) elements.form.elements[field.id].value = record[field.id] ?? '';
  elements.form.hidden = false; elements.form.elements[state.resource.fields[0].id].focus();
}

async function deleteRecord(record) {
  if (!window.confirm(`Delete this ${state.resource.singular}?`)) return;
  clearError();
  try {
    await request(`/api/resources/${state.resource.id}/${record.id}`, { method: 'DELETE' });
    await showResource(state.resource.id);
  } catch (error) { showError(error.message); }
}

function renderRecords(items) {
  const fragment = document.createDocumentFragment();
  for (const record of items) {
    const row = document.createElement('tr');
    for (const field of state.resource.fields) {
      const cell = document.createElement('td'); cell.textContent = String(record[field.id] ?? '—'); row.append(cell);
    }
    const actions = document.createElement('td'); actions.className = 'actions-cell';
    const edit = document.createElement('button'); edit.type = 'button'; edit.className = 'table-action'; edit.textContent = 'Edit';
    edit.addEventListener('click', () => openRecordForm(record));
    const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'table-action danger-action'; remove.textContent = 'Delete';
    remove.addEventListener('click', () => deleteRecord(record)); actions.append(edit, remove); row.append(actions); fragment.append(row);
  }
  elements.records.replaceChildren(fragment);
  elements.recordCount.textContent = `${items.length} ${items.length === 1 ? 'record' : 'records'}`;
  elements.empty.hidden = items.length !== 0;
}

async function showResource(resourceId) {
  clearError(); const resource = state.profile.resources.find((item) => item.id === resourceId); if (!resource) return;
  state.resource = resource; setActiveNavigation(resource.id); elements.overview.hidden = true; elements.resourceView.hidden = false;
  closeRecordForm(); elements.title.textContent = resource.label; elements.description.textContent = resource.description;
  elements.openForm.textContent = `Add ${resource.singular}`; buildFields(resource); buildTableHead(resource);
  try { const result = await request(`/api/resources/${resource.id}`); renderRecords(result.items); }
  catch (error) { showError(error.message); }
}

async function initialize() {
  try {
    state.profile = await request('/api/profile'); document.title = state.profile.name;
    elements.appName.textContent = state.profile.name;
    elements.profileKind.textContent = state.profile.id === 'hospital' ? 'Clinical operations' : 'Academic operations';
    elements.health.textContent = 'Connected'; elements.health.classList.add('is-healthy');
    createNavigation(state.profile); await showOverview();
  } catch (error) { elements.health.textContent = 'Unavailable'; showError(`The application API is unavailable. ${error.message}`); }
}

document.querySelector('.sidebar').addEventListener('click', (event) => {
  const button = event.target.closest('button'); if (!button) return;
  if (button.dataset.view === 'overview') showOverview();
  if (button.dataset.resource) showResource(button.dataset.resource);
});
elements.openForm.addEventListener('click', () => openRecordForm());
elements.cancelForm.addEventListener('click', closeRecordForm);
elements.form.addEventListener('submit', async (event) => {
  event.preventDefault(); if (!state.resource) return; clearError();
  const data = new FormData(elements.form);
  const payload = Object.fromEntries(state.resource.fields.map((field) => [field.id, data.get(field.id)]));
  const path = state.editingId ? `/api/resources/${state.resource.id}/${state.editingId}` : `/api/resources/${state.resource.id}`;
  try {
    await request(path, { method: state.editingId ? 'PUT' : 'POST', body: JSON.stringify(payload) });
    closeRecordForm(); await showResource(state.resource.id);
  } catch (error) { showError(error.message); }
});

initialize();
