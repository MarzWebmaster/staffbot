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

// Check ADMIN auth — customer will be redirected to customer login
async function checkAdminAuth() {
    if (!AUTH_TOKEN) { window.location.href = '/admin/login.html'; return null; }
    try {
        const user = await loadProfile();
        if (!user) { window.location.href = '/admin/login.html'; return null; }
        // Verify admin access by calling a protected admin endpoint
        const adminCheck = await fetch(`${API_BASE}/admin/dashboard`, {
            headers: { 'Authorization': `Bearer ${AUTH_TOKEN}` }
        });
        if (adminCheck.status === 403) {
            // Customer trying to access admin — KICK OUT
            localStorage.removeItem('staffbot_token');
            AUTH_TOKEN = null;
            USER_DATA = null;
            window.location.href = '/customer/login.html';
            return null;
        }
        return user;
    } catch (e) {
        window.location.href = '/admin/login.html';
        return null;
    }
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
function formatDate(d) { return new Date(d).toLocaleDateString('en-US', { day: 'numeric', month: 'short', year: 'numeric' }); }
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
function renderSidebar(active) {
    const nav = document.getElementById('sidebar-nav');
    if (!nav) return;
    
    // Menu definition
    const menus = [
        { href: 'dashboard.html', icon: '📊', label: 'Dashboard', id: 'dashboard' },
        { 
            href: 'users.html',
            icon: '👥', label: 'Users', id: 'users-parent', submenu: [
                { href: 'users.html', label: '👥 All Users', id: 'users' },
            ]
        },
        { href: 'subdomains.html', icon: '🌐', label: 'Subdomains', id: 'subdomains' },
        { href: 'packages.html', icon: '📦', label: 'Package', id: 'packages' },
        { 
            href: 'billing.html',
            icon: '💰', label: 'Billing', id: 'billing', submenu: [
                { href: 'usage.html', label: '📈 Usage', id: 'usage' }
            ]
        },
        { 
            href: 'affiliates.html',
            icon: '🤝', label: 'Affiliate', id: 'affiliate', submenu: [
                { href: 'affiliates.html', label: '📊 Dashboard', id: 'affiliates' },
                { href: 'affiliate-list.html', label: '📋 Affiliates List', id: 'affiliate-list' },
                { href: 'affiliate-payouts.html', label: '💰 Payouts', id: 'payout-requests' },
                { href: 'affiliate-leaderboard.html', label: '🏆 Leaderboard', id: 'leaderboard' },
                { href: 'affiliate-settings.html', label: '⚙️ Settings', id: 'affiliate-settings' }
            ]
        },
        { 
            icon: '⚙️', label: 'Settings', id: 'settings', submenu: [
                { href: 'settings.html', label: '⚙️ General', id: 'settings-general' },
                { href: 'payments.html', label: '💳 Payment Gateway', id: 'payments' },
                { href: 'providers.html', label: '🔌 LLM Providers', id: 'providers' },
{ href: 'token-topups.html', label: '💰 Token Top-Up', id: 'token-topups' },
                { href: 'policy.html', label: '🛡️ Policy', id: 'policy' }
            ]
        },
    ];

    // Check if active is in a submenu -> open that submenu
    const submenuParents = {};
    menus.forEach(m => {
        if (m.submenu) {
            m.submenu.forEach(s => { submenuParents[s.id] = m.id; });
        }
    });
    const parentSub = submenuParents[active];
    
    let html = '';
    menus.forEach(m => {
        const isActive = m.id === active;
        const hasActiveChild = m.submenu && m.submenu.some(s => s.id === active);
        const cls = isActive || hasActiveChild ? ' class="active"' : '';
        
        if (m.submenu) {
            const subOpen = hasActiveChild ? ' open' : '';
            if (m.href) {
                // Parent with both href (navigate) and submenu toggle via arrow
                html += `<div style="display:flex;align-items:center">`;
                html += `<a href="${m.href}"${cls} style="flex:1"><span>${m.icon}</span><span>${m.label}</span></a>`;
                html += `<span onclick="toggleSubmenu('${m.id}-sub')" style="cursor:pointer;padding:12px 16px;font-size:10px;transition:transform 0.3s;display:inline-block" id="${m.id}-arrow">${hasActiveChild ? '▾' : '▸'}</span>`;
                html += `</div>`;
            } else {
                html += `<a onclick="toggleSubmenu('${m.id}-sub')"${cls}><span>${m.icon}</span><span>${m.label}</span><span style="margin-left:auto;font-size:10px;transition:transform 0.3s" id="${m.id}-arrow">${hasActiveChild ? '▾' : '▸'}</span></a>`;
            }
            html += `<div class="submenu${subOpen}" id="${m.id}-sub">`;
            m.submenu.forEach(s => {
                const sActive = s.id === active;
                html += `<a href="${s.href}"${sActive ? ' class="active"' : ''}>${s.label}</a>`;
            });
            html += `</div>`;
        } else {
            html += `<a href="${m.href}"${cls}><span>${m.icon}</span><span>${m.label}</span></a>`;
        }
    });
    
    html += `<a href="#" onclick="logout()" style="margin-top:20px;border-top:1px solid rgba(255,255,255,0.1);padding-top:20px"><span>🚪</span><span>Logout</span></a>`;
    nav.innerHTML = html;
}

// Auto-close mobile sidebar when clicking a nav link
document.addEventListener('click', function(e) {
    const link = e.target.closest('.sidebar-nav a');
    if (link && window.innerWidth <= 768) {
        toggleSidebar();
    }
});

function toggleSubmenu(id) {
    const sub = document.getElementById(id);
    if (!sub) return;
    sub.classList.toggle('open');
    // Update arrow
    const parentId = id.replace('-sub', '');
    const arrow = document.getElementById(parentId + '-arrow');
    if (arrow) arrow.textContent = sub.classList.contains('open') ? '▾' : '▸';
}

function toggleSidebar() {
    var sidebar = document.querySelector('.sidebar');
    var overlay = document.querySelector('.sidebar-overlay');
    if (!sidebar) return;
    sidebar.classList.toggle('open');
    if (overlay) overlay.classList.toggle('active');
}

// Close sidebar on overlay click
document.addEventListener('click', function(e) {
    if (e.target.classList.contains('sidebar-overlay')) {
        document.querySelector('.sidebar').classList.remove('open');
        e.target.classList.remove('active');
    }
});

// Auto-close mobile sidebar when clicking a nav link
document.addEventListener('click', function(e) {
    var link = e.target.closest('.sidebar-nav a');
    if (link && window.innerWidth <= 768) {
        document.querySelector('.sidebar').classList.remove('open');
        document.querySelector('.sidebar-overlay').classList.remove('active');
    }
});

// Init on page load
document.addEventListener('DOMContentLoaded', function() {
    if (AUTH_TOKEN) loadProfile().then(function(u) { if (u) renderSidebarUser(u); });
});


// ========================================
// PERFORMANCE OPTIMIZATIONS
// ========================================

// API cache — sessionStorage with 5-min TTL
const apiCache = {
    set(key, data, ttl = 300000) {
        try {
            sessionStorage.setItem("cache_" + key, JSON.stringify({ data, expires: Date.now() + ttl }));
        } catch(e) { /* quota exceeded, skip */ }
    },
    get(key) {
        try {
            const raw = sessionStorage.getItem("cache_" + key);
            if (!raw) return null;
            const entry = JSON.parse(raw);
            if (Date.now() > entry.expires) { sessionStorage.removeItem("cache_" + key); return null; }
            return entry.data;
        } catch(e) { return null; }
    },
    clear() {
        Object.keys(sessionStorage).filter(k => k.startsWith("cache_")).forEach(k => sessionStorage.removeItem(k));
    }
};

// API with cache
async function apiCached(path, options = {}, ttl = 300000) {
    const cacheKey = path + JSON.stringify(options);
    const cached = apiCache.get(cacheKey);
    if (cached) return cached;
    const data = await api(path, options);
    apiCache.set(cacheKey, data, ttl);
    return data;
}

// Parallel API calls — resolve all or fail fast
async function apiAll(...calls) {
    const results = await Promise.allSettled(calls);
    return results.map((r, i) => {
        if (r.status === 'fulfilled') return r.value;
        console.warn('API call ' + i + ' failed:', r.reason);
        return null;
    });
}

// Skeleton loader
function showSkeleton(containerId, count = 3) {
    const el = document.getElementById(containerId);
    if (!el) return;
    el.innerHTML = Array(count).fill('<div class="skeleton-card"><div class="skeleton-line w-60"></div><div class="skeleton-line w-80"></div><div class="skeleton-line w-40"></div></div>').join('');
}

// Debounce
function debounce(fn, delay = 300) {
    let timer;
    return function(...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), delay);
    };
}


// HTML escape — prevent XSS in innerHTML
function escapeHtml(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

// Safe innerHTML setter
function safeInnerHTML(el, html) {
    if (typeof el === "string") el = document.getElementById(el);
    if (!el) return;
    el.innerHTML = html;
}
