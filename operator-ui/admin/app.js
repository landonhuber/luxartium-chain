import {roadmap, processes} from './workspace.js';
const h = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
const view = document.querySelector('#view');
let csrf = '';
let generation = 0;
let expiry;
const expired = () => { view.replaceChildren(); location.replace('/login'); };
const heading = (title, text) => `<div class="page-heading"><div><p class="eyebrow">PRIVATE OPERATOR WORKSPACE</p><h1>${title}</h1><p class="subtitle">${text}</p></div><span class="pill">OWNER ACCESS</span></div>`;

function overview() {
  return heading('Build with a clear view.', 'A workspace for the decisions and operations behind Luxartium.') + `<div class="workspace-note"><strong>Current priority: prepare for a hosted testnet.</strong><p>The currency and public explorer work locally. Next, demonstrate recovery and package a repeatable deployment before connecting outside operators.</p></div><div class="admin-grid"><a class="admin-card" href="#/roadmap"><span class="eyebrow">PLAN THE WORK</span><h2>Internal roadmap ↗</h2><p>Implementation milestones, dependencies and decisions still ahead.</p></a><a class="admin-card" href="#/processes"><span class="eyebrow">OPERATE THE NETWORK</span><h2>Processes ↗</h2><p>Local commands, funding, health checks, recovery and release procedures.</p></a><a class="admin-card" href="http://127.0.0.1:4173/"><span class="eyebrow">INSPECT THE CHAIN</span><h2>Network explorer ↗</h2><p>Public records: blocks, transactions and available account balances.</p></a><a class="admin-card" href="#/access"><span class="eyebrow">WORKSPACE ACCESS</span><h2>Access & activity ↗</h2><p>Owner session information and recent workspace sign-in events.</p></a></div><section class="panel"><div class="panel-heading"><h2>Available here</h2></div><div class="procedure-body"><p>Authenticated access to planning and operating guidance. Blockchain funding, key management and node controls use the existing local CLI.</p><p>Privileged browser controls, multi-operator accounts and durable audit storage require a future release.</p></div></section>`;
}
function access(session) {
  return heading('Access & activity', 'Your local owner session and workspace access events.') + `<div class="workspace-note"><strong>One local owner. No blockchain signing permissions.</strong><p>Sessions expire after 30 minutes without a workspace request or eight hours in total. Restarting the sites revokes every session. Sign out when finished.</p></div><section class="panel"><div class="panel-heading"><h2>Recent access events</h2><span class="muted">Since server startup · up to 100 events</span></div><div class="table-scroll"><table><thead><tr><th>Event</th><th>Time (UTC)</th></tr></thead><tbody>${session.events.map(e=>`<tr><td>${h(e.action)}</td><td>${h(e.time)}</td></tr>`).join('')}</tbody></table></div></section><p class="fine muted">This is an in-memory access record. It is not a durable audit log of chain or operator activity.</p>`;
}
async function render() {
  const token = ++generation;
  view.innerHTML = '<div class="loading">Verifying your session…</div>';
  try {
    const response = await fetch('/admin/api/session', {signal:AbortSignal.timeout(10000)});
    if (response.status === 401) return expired();
    if (!response.ok) throw new Error('The workspace is temporarily unavailable.');
    const session = await response.json();
    if (token !== generation) return;
    csrf = session.csrf;
    clearTimeout(expiry);
    expiry = setTimeout(expired, Math.max(0, session.expires_in) * 1000);
    const route = location.hash.slice(2) || 'overview';
    const labels = {overview:'Workspace', roadmap:'Internal roadmap', processes:'Processes', access:'Access & activity'};
    document.querySelector('#page-label').textContent = labels[route] || 'Page unavailable';
    document.title = `${labels[route] || 'Admin'} · Luxartium Admin`;
    document.querySelectorAll('[data-nav]').forEach(el => { if (el.dataset.nav === route) el.setAttribute('aria-current','page'); else el.removeAttribute('aria-current'); });
    view.innerHTML = route === 'overview' ? overview() : route === 'roadmap' ? roadmap() : route === 'processes' ? processes() : route === 'access' ? access(session) : heading('Page unavailable', 'Choose a section from the workspace navigation.');
  } catch (error) {
    if (token === generation) view.innerHTML = `<div class="notice">${h(error.message)} <button id="retry">Try again</button></div>`;
  }
}
async function logout() {
  try {
    const response = await fetch('/admin/logout', {method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:'{}',signal:AbortSignal.timeout(10000)});
    if (!response.ok && response.status !== 401) throw new Error('Sign-out failed. Try again.');
    expired();
  } catch (error) { view.innerHTML = `<div class="notice">${h(error.message)} <button id="retry">Reload workspace</button></div>`; }
}
document.addEventListener('click', event => {
  if (event.target.closest('.skip')) { event.preventDefault(); document.querySelector('#content').focus(); }
  if (event.target.closest('#logout, #mobile-logout')) logout();
  if (event.target.closest('#retry')) render();
});
window.addEventListener('hashchange', () => { render(); window.scrollTo(0,0); });
window.addEventListener('pagehide', () => { view.replaceChildren(); generation++; });
window.addEventListener('pageshow', () => render());
