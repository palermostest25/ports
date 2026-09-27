const state = {
  snapshot: null,
  view: 'published',
  query: '',
  containerState: 'all',
  loading: false,
  autoRefresh: localStorage.getItem('ports:autoRefresh') !== 'false',
};

const ui = {
  connection: document.querySelector('#connection'),
  connectionText: document.querySelector('#connectionText'),
  refreshButton: document.querySelector('#refreshButton'),
  themeButton: document.querySelector('#themeButton'),
  autoRefresh: document.querySelector('#autoRefresh'),
  metricContainers: document.querySelector('#metricContainers'),
  metricRunning: document.querySelector('#metricRunning'),
  metricPublished: document.querySelector('#metricPublished'),
  metricPorts: document.querySelector('#metricPorts'),
  errorBanner: document.querySelector('#errorBanner'),
  errorText: document.querySelector('#errorText'),
  publishedBadge: document.querySelector('#publishedBadge'),
  unpublishedBadge: document.querySelector('#unpublishedBadge'),
  conflictBadge: document.querySelector('#conflictBadge'),
  toolbar: document.querySelector('#containerToolbar'),
  searchInput: document.querySelector('#searchInput'),
  stateFilter: document.querySelector('#stateFilter'),
  updatedText: document.querySelector('#updatedText'),
  content: document.querySelector('#content'),
  footerMeta: document.querySelector('#footerMeta'),
  toasts: document.querySelector('#toasts'),
};

function escapeHTML(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function relativeTime(epochSeconds) {
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - epochSeconds));
  if (seconds < 5) return 'Updated just now';
  if (seconds < 60) return `Updated ${seconds}s ago`;
  return `Updated ${Math.floor(seconds / 60)}m ago`;
}

function toast(message, error = false) {
  const item = document.createElement('div');
  item.className = `toast${error ? ' error' : ''}`;
  item.textContent = message;
  ui.toasts.append(item);
  setTimeout(() => item.remove(), 3500);
}

async function requestSnapshot(force = false) {
  const response = await fetch(`/api/snapshot${force ? '?refresh=1' : ''}`, { cache: 'no-store' });
  if (!response.ok) throw new Error(`Snapshot request failed (${response.status})`);
  return response.json();
}

function setConnection(connected, version) {
  ui.connection.className = `connection ${connected ? 'is-online' : 'is-offline'}`;
  ui.connectionText.textContent = connected ? `Docker ${version || 'online'}` : 'Docker offline';
}

function renderChrome() {
  const data = state.snapshot;
  if (!data) return;
  const published = data.containers.filter(item => item.ports.length > 0).length;
  const unpublished = data.containers.length - published;
  setConnection(data.connected, data.docker_version);
  ui.metricContainers.textContent = data.metrics.total;
  ui.metricRunning.textContent = data.metrics.running;
  ui.metricPublished.textContent = data.metrics.published;
  ui.metricPorts.textContent = data.metrics.unique_ports;
  ui.publishedBadge.textContent = published;
  ui.unpublishedBadge.textContent = unpublished;
  ui.conflictBadge.textContent = data.collisions.length;
  ui.errorBanner.hidden = data.connected;
  ui.errorText.textContent = data.error || 'Check the socket proxy and try again.';
  ui.updatedText.textContent = relativeTime(data.generated_at);
  ui.footerMeta.textContent = `${data.settings.demo_mode ? 'Demo data' : 'Read-only Docker view'}${data.docker_version ? ` · Docker ${data.docker_version}` : ''}`;
}

function matchesFilters(container) {
  const query = state.query.trim().toLowerCase();
  const stateMatch = state.containerState === 'all'
    || (state.containerState === 'running' && container.state === 'running')
    || (state.containerState === 'stopped' && container.state !== 'running');
  if (!stateMatch) return false;
  if (!query) return true;
  const haystack = [
    container.name, container.id, container.image, container.stack, container.state,
    ...container.ports.flatMap(port => [port.host_port, port.container_port, port.host_ip]),
  ].join(' ').toLowerCase();
  return haystack.includes(query);
}

const containerIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6.5 12 3l8 3.5v11L12 21l-8-3.5v-11ZM4 6.5l8 3.5 8-3.5M12 10v11"/></svg>';
const copyIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="11" height="11" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/></svg>';

function portChip(port) {
  const reachability = port.reachable === true ? 'yes' : port.reachable === false ? 'no' : '';
  return `<span class="port-chip">
    <a class="port-link" href="${escapeHTML(port.href)}" target="_blank" rel="noopener noreferrer" title="${escapeHTML(`${port.host_ip}:${port.host_port} → ${port.container_port}/${port.protocol}`)}">
      ${reachability ? `<span class="reachability ${reachability}"></span>` : ''}
      <span class="scheme">${escapeHTML(port.scheme.toUpperCase())}</span>
      <span>${port.host_port}</span>
      <span class="port-target">→ ${port.container_port}</span>
    </a>
    <button class="copy-port" type="button" data-copy="${port.host_port}" aria-label="Copy port ${port.host_port}" title="Copy port">${copyIcon}</button>
  </span>`;
}

function renderContainers(wantPublished) {
  const containers = state.snapshot.containers
    .filter(item => wantPublished ? item.ports.length > 0 : item.ports.length === 0)
    .filter(matchesFilters);
  if (!containers.length) {
    ui.content.innerHTML = emptyState(
      wantPublished ? 'No published ports found' : 'Every matching container has a published port',
      state.query ? 'Clear the search or change the state filter.' : 'This view will update automatically when Docker changes.'
    );
    return;
  }
  ui.content.innerHTML = `<div class="container-head"><span>Container</span><span>Stack</span><span>Image & state</span><span>Published ports</span></div>
    <div class="container-list">${containers.map(container => `
      <article class="container-row">
        <div class="container-primary">
          <span class="container-glyph">${containerIcon}</span>
          <span class="container-name"><strong>${escapeHTML(container.name)}</strong><span>${escapeHTML(container.id)}</span></span>
        </div>
        <div class="stack-name">${escapeHTML(container.stack || 'Standalone')}</div>
        <div class="image-name" title="${escapeHTML(container.image)}">
          ${escapeHTML(container.image)}
          <span class="state-line"><span class="state-pill ${container.state === 'running' ? 'running' : ''}">${escapeHTML(container.state)}</span>${container.health ? `<span class="health">· ${escapeHTML(container.health)}</span>` : ''}</span>
        </div>
        <div class="ports-cell">${container.ports.length ? container.ports.map(portChip).join('') : '<span class="image-name">No host bindings</span>'}</div>
      </article>`).join('')}</div>`;
}

function renderRanges() {
  const ranges = state.snapshot.ranges;
  ui.content.innerHTML = `<div class="range-grid">${ranges.map(range => {
    const usedPercent = Math.min(100, range.size ? range.used_count / range.size * 100 : 0);
    return `<article class="range-card">
      <div class="range-top"><div><h3>${escapeHTML(range.label)}</h3><p>${range.used_count} used${range.reserved_count ? ` · ${range.reserved_count} reserved` : ''}</p></div><span class="range-count">${range.available_count.toLocaleString()} free</span></div>
      <div class="capacity" title="${usedPercent.toFixed(1)}% used"><span style="width:${Math.max(usedPercent, range.used_count ? 1 : 0)}%"></span></div>
      <div class="port-list">${range.available.map(port => `<button class="free-port" type="button" data-copy="${port}" title="Copy port ${port}">${port}</button>`).join('')}</div>
      <div class="range-footer">First ${range.available.length} available ports shown</div>
    </article>`;
  }).join('')}</div>`;
}

function renderConflicts() {
  const collisions = state.snapshot.collisions;
  if (!collisions.length) {
    ui.content.innerHTML = emptyState('No port collisions', 'Every exact host IP and port binding is unique.');
    return;
  }
  ui.content.innerHTML = `<div class="conflict-list">${collisions.map(item => `
    <article class="conflict-item"><strong>${escapeHTML(item.binding)}</strong><span>${escapeHTML(item.containers.join(' · '))}</span></article>
  `).join('')}</div>`;
}

function emptyState(title, description) {
  return `<div class="empty-state"><div>
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6.5 12 3l8 3.5v11L12 21l-8-3.5v-11ZM4 6.5l8 3.5 8-3.5M12 10v11"/></svg>
    <strong>${escapeHTML(title)}</strong><span>${escapeHTML(description)}</span>
  </div></div>`;
}

function renderContent() {
  if (!state.snapshot) return;
  ui.toolbar.hidden = !['published', 'unpublished'].includes(state.view);
  if (!state.snapshot.connected && ['published', 'unpublished'].includes(state.view)) {
    ui.content.innerHTML = emptyState('Waiting for Docker', state.snapshot.error || 'Check the connection and refresh.');
    return;
  }
  if (state.view === 'published') renderContainers(true);
  if (state.view === 'unpublished') renderContainers(false);
  if (state.view === 'available') renderRanges();
  if (state.view === 'conflicts') renderConflicts();
}

function render() {
  renderChrome();
  renderContent();
}

async function load(force = false, quiet = false) {
  if (state.loading) return;
  state.loading = true;
  ui.refreshButton.disabled = true;
  ui.refreshButton.classList.add('is-spinning');
  try {
    state.snapshot = await requestSnapshot(force);
    render();
    if (force && !quiet) toast('Docker snapshot refreshed');
  } catch (error) {
    if (!quiet) toast(error.message, true);
  } finally {
    state.loading = false;
    ui.refreshButton.disabled = false;
    ui.refreshButton.classList.remove('is-spinning');
  }
}

document.querySelector('.tabs').addEventListener('click', event => {
  const tab = event.target.closest('[data-view]');
  if (!tab) return;
  state.view = tab.dataset.view;
  document.querySelectorAll('.tab').forEach(item => {
    const active = item === tab;
    item.classList.toggle('is-active', active);
    item.setAttribute('aria-selected', String(active));
  });
  renderContent();
});

ui.content.addEventListener('click', async event => {
  const copy = event.target.closest('[data-copy]');
  if (!copy) return;
  event.preventDefault();
  try {
    await navigator.clipboard.writeText(copy.dataset.copy);
    toast(`Copied port ${copy.dataset.copy}`);
  } catch {
    toast('Could not access the clipboard', true);
  }
});

ui.searchInput.addEventListener('input', () => { state.query = ui.searchInput.value; renderContent(); });
ui.stateFilter.addEventListener('change', () => { state.containerState = ui.stateFilter.value; renderContent(); });
ui.refreshButton.addEventListener('click', () => load(true));
ui.autoRefresh.checked = state.autoRefresh;
ui.autoRefresh.addEventListener('change', () => {
  state.autoRefresh = ui.autoRefresh.checked;
  localStorage.setItem('ports:autoRefresh', String(state.autoRefresh));
});

const storedTheme = localStorage.getItem('ports:theme');
if (storedTheme) document.documentElement.dataset.theme = storedTheme;
ui.themeButton.addEventListener('click', () => {
  const next = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
  document.documentElement.dataset.theme = next;
  localStorage.setItem('ports:theme', next);
});

setInterval(() => {
  if (state.snapshot) ui.updatedText.textContent = relativeTime(state.snapshot.generated_at);
}, 1000);
setInterval(() => { if (state.autoRefresh && !document.hidden) load(true, true); }, 15000);
document.addEventListener('visibilitychange', () => { if (!document.hidden && state.autoRefresh) load(true, true); });

load();
