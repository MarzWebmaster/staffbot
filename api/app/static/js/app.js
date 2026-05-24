/**
 * StaffBot.my — Shared API Client & Auth
 */
const API_BASE = '/api/v1';
let AUTH_TOKEN = localStorage.getItem('staffbot_token');
let USER_DATA = null;

// API Helper
async function api(path, options = {}) {
    const headers = { 'Content-Type': 'application/json', ...options.headers };
    if (AUTH_TOKEN) headers['Authorization'] = `Bearer ${AUTH_TOKEN}`;
    
    try {
        const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
        if (res.status === 401) { logout(); throw new Error('Session expired'); }
        if (!res.ok) { const err = await res.json().catch(() => ({ detail: res.statusText })); throw new Error(err.detail || 'Request failed'); }
        return await res.json();
    } catch (e) {
        if (e.message !== 'Session expired') showToast(e.message, 'error');
        throw e;
    }
}

// Auth
async function login(email, password) {
    const data = await api('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) });
    AUTH_TOKEN = data.access_token;
    localStorage.setItem('staffbot_token', AUTH_TOKEN);
    await loadProfile();
    return data;
}

async function register(data) {
    return api('/auth/register', { method: 'POST', body: JSON.stringify(data) });
}

async function loadProfile() {
    try {
        USER_DATA = await api('/auth/me');
        return USER_DATA;
    } catch { return null; }
}

function logout() {
    AUTH_TOKEN = null; USER_DATA = null;
    localStorage.removeItem('staffbot_token');
    // Redirect based on role
    const isAdmin = window.location.pathname.startsWith('/admin/');
    window.location.href = isAdmin ? '/admin/login.html' : '/customer/login.html';
}

// Check auth on page load
async function checkAuth(redirectTo = '/customer/login.html') {
    if (!AUTH_TOKEN) { window.location.href = redirectTo; return null; }
    const user = await loadProfile();
    if (!user) { window.location.href = redirectTo; return null; }
    return user;
}

// Toast notifications
function showToast(msg, type = 'info') {
    const container = document.getElementById('toast-container') || (() => {
        const c = document.createElement('div'); c.id = 'toast-container'; c.className = 'toast-container';
        document.body.appendChild(c); return c;
    })();
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = msg;
    container.appendChild(toast);
    setTimeout(() => { toast.remove(); }, 3000);
}

// Modal helpers
function openModal(id) { document.getElementById(id).classList.add('active'); }
function closeModal(id) { document.getElementById(id).classList.remove('active'); }
document.addEventListener('click', e => {
    if (e.target.classList.contains('modal-overlay')) e.target.classList.remove('active');
});

// Format helpers
function formatDate(d) { return new Date(d).toLocaleDateString('ms-MY', { day: 'numeric', month: 'short', year: 'numeric' }); }
function formatCurrency(n) { return `RM${Number(n).toFixed(2)}`; }
function statusBadge(status) {
    const map = { active: 'active', running: 'active', pending: 'pending', error: 'error', suspended: 'suspended', stopped: 'error', deploying: 'pending' };
    const cls = map[status] || 'pending';
    return `<span class="status-badge status-${cls}"><span class="status-dot dot-${cls}"></span>${status}</span>`;
}

// Load user info in sidebar
function renderSidebarUser(user) {
    const el = document.getElementById('sidebar-user');
    if (el) el.innerHTML = `
        <div class="user-badge">
            <div class="user-avatar">${user.name.charAt(0).toUpperCase()}</div>
            <div><div style="font-weight:600;font-size:14px">${user.name}</div><div style="font-size:12px;color:rgba(255,255,255,0.5)">${user.email}</div></div>
        </div>
    `;
}

// Init sidebar
document.addEventListener('DOMContentLoaded', () => {
    // Highlight active nav item
    const path = window.location.pathname;
    document.querySelectorAll('.sidebar-nav a').forEach(a => {
        if (a.getAttribute('href') === path.split('/').pop()) a.classList.add('active');
    });
    // Load user if token exists
    if (AUTH_TOKEN) loadProfile().then(u => { if (u) renderSidebarUser(u); });
});
