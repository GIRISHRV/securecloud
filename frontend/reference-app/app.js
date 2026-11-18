const state = { profile: null, resource: null };

const elements = {
  appName: document.querySelector('#app-name'),
  profileKind: document.querySelector('#profile-kind'),
  title: document.querySelector('#view-title'),
  description: document.querySelector('#view-description'),
  navigation: document.querySelector('#resource-navigation'),
  overview: document.querySelector('#overview-view'),
  resourceView: document.querySelector('#resource-view'),
  summary: document.querySelector('#summary-metrics'),
  records: document.querySelector('#records-body'),
  recordCount: document.querySelector('#record-count'),
  empty: document.querySelector('#empty-message'),
  form: document.querySelector('#record-form'),
  openForm: document.querySelector('#open-form'),
  cancelForm: document.querySelector('#cancel-form'),
  health: document.querySelector('#health-status'),
  error: document.querySelector('#error-message'),
};

async function request(path, options) {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options?.headers ?? {}) },
  });
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json();
}

function showError(message) {
  elements.error.textContent = message;
  elements.error.hidden = false;
}

function clearError() {
  elements.error.hidden = true;
  elements.error.textContent = '';
}

function createNavigation(profile) {
  const fragment = document.createDocumentFragment();
  for (const resource of profile.resources) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'nav-item';
    button.dataset.resource = resource.id;
    button.textContent = resource.label;
    fragment.append(button);
  }
  elements.navigation.replaceChildren(fragment);
}

function setActiveNavigation(resourceId) {
  document.querySelectorAll('.nav-item').forEach((item) => {
    const active = resourceId ? item.dataset.resource === resourceId : item.dataset.view === 'overview';
    item.classList.toggle('is-active', active);
    item.setAttribute('aria-current', active ? 'page' : 'false');
  });
}

async function showOverview() {
  clearError();
  state.resource = null;
  setActiveNavigation(null);
  elements.overview.hidden = false;
  elements.resourceView.hidden = true;
  elements.title.textContent = 'Overview';
  elements.description.textContent = state.profile.description;
  try {
    const summary = await request('/api/summary');
    const fragment = document.createDocumentFragment();
    for (const resource of state.profile.resources) {
      const metric = document.createElement('div');
      metric.className = 'metric';
      const value = document.createElement('strong');
      value.textContent = String(summary.counts[resource.id] ?? 0);
      const label = document.createElement('span');
      label.textContent = resource.label;
      metric.append(value, label);
      fragment.append(metric);
    }
    elements.summary.replaceChildren(fragment);
  } catch (error) {
    showError(error.message);
  }
}

function renderRecords(items) {
  const fragment = document.createDocumentFragment();
  for (const record of items) {
    const row = document.createElement('tr');
    for (const value of [record.name, record.detail || '—', record.status, record.id]) {
      const cell = document.createElement('td');
      cell.textContent = String(value);
      row.append(cell);
    }
    fragment.append(row);
  }
  elements.records.replaceChildren(fragment);
  elements.recordCount.textContent = `${items.length} ${items.length === 1 ? 'record' : 'records'}`;
  elements.empty.hidden = items.length !== 0;
}

async function showResource(resourceId) {
  clearError();
  const resource = state.profile.resources.find((item) => item.id === resourceId);
  if (!resource) return;
  state.resource = resource;
  setActiveNavigation(resource.id);
  elements.overview.hidden = true;
  elements.resourceView.hidden = false;
  elements.form.hidden = true;
  elements.title.textContent = resource.label;
  elements.description.textContent = `Manage ${resource.label.toLowerCase()}.`;
  try {
    const result = await request(`/api/resources/${resource.id}`);
    renderRecords(result.items);
  } catch (error) {
    showError(error.message);
  }
}

async function initialize() {
  try {
    state.profile = await request('/api/profile');
    document.title = state.profile.name;
    elements.appName.textContent = state.profile.name;
    elements.profileKind.textContent = state.profile.id === 'hospital' ? 'Clinical operations' : 'Academic operations';
    elements.health.textContent = 'Connected';
    elements.health.classList.add('is-healthy');
    createNavigation(state.profile);
    await showOverview();
  } catch (error) {
    elements.health.textContent = 'Unavailable';
    showError(`The application API is unavailable. ${error.message}`);
  }
}

document.querySelector('.sidebar').addEventListener('click', (event) => {
  const button = event.target.closest('button');
  if (!button) return;
  if (button.dataset.view === 'overview') showOverview();
  if (button.dataset.resource) showResource(button.dataset.resource);
});

elements.openForm.addEventListener('click', () => {
  elements.form.hidden = false;
  document.querySelector('#record-name').focus();
});

elements.cancelForm.addEventListener('click', () => {
  elements.form.reset();
  elements.form.hidden = true;
});

elements.form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!state.resource) return;
  clearError();
  const data = new FormData(elements.form);
  try {
    await request(`/api/resources/${state.resource.id}`, {
      method: 'POST',
      body: JSON.stringify({
        name: data.get('name'),
        detail: data.get('detail'),
        status: data.get('status'),
      }),
    });
    elements.form.reset();
    elements.form.hidden = true;
    await showResource(state.resource.id);
  } catch (error) {
    showError(error.message);
  }
});

initialize();
