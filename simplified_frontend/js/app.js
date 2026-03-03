// API Configuration - Auto-detect hostname for network access
// This allows access from phones/tablets on the same network
const getApiBase = () => {
    const hostname = window.location.hostname;
    const protocol = window.location.protocol;

    if (!hostname) {
        return `${protocol}//localhost:5001/api`;
    }

    if (hostname === 'localhost' || hostname === '127.0.0.1') {
        return `${protocol}//localhost:5001/api`;
    }

    return `${protocol}//${hostname}/api`;
};


const API_BASE = getApiBase();


// Global state
let currentUser = null;
let queuePollInterval = null;
let statsPollInterval = null;
let nowServingPollInterval = null;
let compactQueuePollInterval = null;
let adminCompactActive = false;
let hasNotifiedFiveAway = false;
let hasNotifiedTenAway = false;
let lastNotifiedQueueId = null;
let lastCalledQueueId = null;
let analyticsCharts = { numbersServed: null, avgServiceTime: null, peakHours: null };

const SERVICE_TYPES = [
    'submission_of_application_forms',
    'application_assessment_of_school_records',
    'releasing_of_school_records',
    'inquiry_follow_up',
    'faculty_tagging_room_assignments',
    'payment',
    'balance_inquiry',
    'claims'
];

const SERVICE_LABELS = {
    submission_of_application_forms: 'Submission of Application Forms',
    application_assessment_of_school_records: 'Application & Assessment of School Records',
    releasing_of_school_records: 'Releasing of School Records',
    inquiry_follow_up: 'Inquiry & Follow-Up',
    faculty_tagging_room_assignments: 'Faculty Tagging & Room Assignments',
    payment: 'Payment',
    balance_inquiry: 'Balance Inquiry',
    claims: 'Claims'
};

const ADMIN_SERVICE_LABELS = SERVICE_LABELS;

function isStaticAdmin() {
    return currentUser?.role === 'admin' && currentUser?.admin_type === 'static';
}

function formatServiceLabel(service) {
    if (!service) return 'Unassigned';
    return SERVICE_LABELS[service] || service.replace(/_/g, ' ');
}

function formatAdminServiceLabel(service) {
    return formatServiceLabel(service);
}

function isAdminCompactMode() {
    const params = new URLSearchParams(window.location.search);
    return params.get('admin_compact') === '1' || params.get('compact_admin') === '1' || params.get('compact') === '1';
}

function shouldUseCompactMode() {
    return isAdminCompactMode() || window.matchMedia('(max-width: 992px)').matches;
}

// Initialize app
document.addEventListener('DOMContentLoaded', function () {
    removeDuplicateStudentQueueCards();
    initApp();
    setupEventListeners();
});

function removeDuplicateStudentQueueCards() {
    const statusBlocks = Array.from(document.querySelectorAll('#my-queue-status'));
    if (statusBlocks.length <= 1) return;
    statusBlocks.slice(1).forEach(block => {
        const card = block.closest('.card');
        if (card) {
            card.remove();
        } else {
            block.remove();
        }
    });
}

// Check authentication status
async function checkAuthStatus() {
    try {
        const response = await fetch(`${API_BASE}/auth/me`, {
            credentials: 'include'
        });

        if (response.ok) {
            const user = await response.json();
            currentUser = user;
            showDashboard(user.role);
        } else {
            showLogin();
        }
    } catch (error) {
        console.error('Auth check failed:', error);
        showLogin();
    }
}

// Show login page
function showLogin() {
    showPage('login-page');
}

// Show dashboard based on role
function showDashboard(role) {
    showPage(role === 'admin' ? 'admin-dashboard' : 'student-dashboard');

    if (role === 'admin') {
        const adminName = currentUser.name || 'Admin';
        const nameElements = ['admin-header-name', 'sidebar-user-name'];
        nameElements.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.textContent = adminName;
        });

        // Set the role label dynamically based on admin type and service
        let roleLabel = 'System Administrator';
        if (currentUser.admin_type === 'appointed' && currentUser.admin_service) {
            // Convert snake_case service name to Title Case
            const serviceName = currentUser.admin_service
                .replace(/_/g, ' ')
                .replace(/\b\w/g, c => c.toUpperCase());
            roleLabel = serviceName + ' Admin';
        }
        const headerRoleEl = document.getElementById('admin-header-role');
        if (headerRoleEl) headerRoleEl.textContent = roleLabel;
        const sidebarRoleEl = document.getElementById('sidebar-user-role');
        if (sidebarRoleEl) sidebarRoleEl.textContent = roleLabel;

        // Mobile fallback if present
        const oldNameEl = document.getElementById('admin-user-name');
        if (oldNameEl) oldNameEl.textContent = adminName;

        syncAdminCompactMode(true);
    } else {
        // Put user name in the navbar title (replaces "Student Portal")
        const titleEl = document.getElementById('student-navbar-title');
        if (titleEl) {
            titleEl.textContent = currentUser.name || 'Student';
        }

        // Hide the old right-side name (kept for compatibility, but not used)
        const rightNameEl = document.getElementById('student-user-name');
        if (rightNameEl) rightNameEl.classList.add('d-none');

        loadStudentDashboard();
    }
}

function stopAdminPolling() {
    if (statsPollInterval) { clearInterval(statsPollInterval); statsPollInterval = null; }
    if (queuePollInterval) { clearInterval(queuePollInterval); queuePollInterval = null; }
}

function restoreAdminTabFromHash() {
    const hash = window.location.hash;
    if (hash && document.querySelector(`[href="${hash}"]`)) {
        const targetTabLink = document.querySelector(`[href="${hash}"]`);
        const tab = new bootstrap.Tab(targetTabLink);
        tab.show();
    }
}

function activateFullAdminView() {
    disableAdminCompactMode();
    configureAdminView();
    restoreAdminTabFromHash();
    loadAdminDashboard();
    loadServiceSettings();
}

function syncAdminCompactMode(force = false) {
    if (currentUser?.role !== 'admin') return;
    const wantsCompact = shouldUseCompactMode();
    if (wantsCompact) {
        if (!adminCompactActive || force) {
            enableAdminCompactMode();
        }
    } else if (adminCompactActive || force) {
        activateFullAdminView();
    }
}

function enableAdminCompactMode() {
    const adminDashboard = document.getElementById('admin-dashboard');
    const compactPanel = document.getElementById('admin-compact-panel');
    if (adminDashboard) adminDashboard.classList.add('admin-compact-mode');
    if (compactPanel) compactPanel.classList.remove('d-none');
    adminCompactActive = true;
    stopAdminPolling();
    loadAdminCompactQueue();
    if (!compactQueuePollInterval) {
        compactQueuePollInterval = setInterval(loadAdminCompactQueue, 3000);
    }
}

function disableAdminCompactMode() {
    const adminDashboard = document.getElementById('admin-dashboard');
    const compactPanel = document.getElementById('admin-compact-panel');
    if (adminDashboard) adminDashboard.classList.remove('admin-compact-mode');
    if (compactPanel) compactPanel.classList.add('d-none');
    if (compactQueuePollInterval) {
        clearInterval(compactQueuePollInterval);
        compactQueuePollInterval = null;
    }
    adminCompactActive = false;
}

// Setup event listeners
function setupEventListeners() {
    // Login form
    document.getElementById('login-form').addEventListener('submit', handleLogin);
    window.addEventListener('resize', () => syncAdminCompactMode());

    // Register form
    document.getElementById('register-form').addEventListener('submit', handleRegister);

    // Create admin form (static admin only)
    const createAdminForm = document.getElementById('create-admin-form');
    if (createAdminForm) {
        createAdminForm.addEventListener('submit', handleCreateAdmin);
    }

    // Creation Form Password Toggle
    window.toggleAdminCreatePassword = function () {
        const passwordInput = document.getElementById('new-admin-password');
        const toggleBtn = document.getElementById('toggle-admin-password');
        const icon = toggleBtn.querySelector('i');

        if (passwordInput.type === 'password') {
            passwordInput.type = 'text';
            icon.classList.replace('bi-eye', 'bi-eye-slash');
        } else {
            passwordInput.type = 'password';
            icon.classList.replace('bi-eye-slash', 'bi-eye');
        }
    };

    // Analytics sub-tab triggers
    ['analytics-served-panel', 'analytics-time-panel', 'analytics-peak-panel'].forEach(panelId => {
        const tabLink = document.querySelector(`[href="#${panelId}"]`);
        if (tabLink) {
            tabLink.addEventListener('shown.bs.tab', () => loadAdminAnalytics());
        }
    });

    // Join queue form
    document.getElementById('join-queue-form').addEventListener('submit', handleJoinQueue);

    // Verification form
    document.getElementById('verification-form').addEventListener('submit', handleVerification);

    // Service selection buttons (mobile-friendly) + student office filters
    document.addEventListener('click', function (e) {
        // Service button clicks
        if (e.target.closest('.service-btn')) {
            const serviceBtn = e.target.closest('.service-btn');
            const service = serviceBtn.dataset.service;

            // Remove active class from all service buttons
            document.querySelectorAll('.service-btn').forEach(btn => {
                btn.classList.remove('active');
            });

            // Add active class to clicked button
            serviceBtn.classList.add('active');

            // Set the hidden input value
            document.getElementById('service-type').value = service;

            // Check if both service and priority are selected, then submit
            const priority = document.getElementById('priority').value;
            if (service && priority) {
                // Small delay to show visual feedback
                setTimeout(() => {
                    document.getElementById('join-queue-form').dispatchEvent(new Event('submit'));
                }, 200);
            }
        }

        // Priority button clicks
        if (e.target.closest('.priority-btn')) {
            const priorityBtn = e.target.closest('.priority-btn');
            const priority = priorityBtn.dataset.priority;

            // Remove active class from all priority buttons
            document.querySelectorAll('.priority-btn').forEach(btn => {
                btn.classList.remove('active');
            });

            // Add active class to clicked button
            priorityBtn.classList.add('active');

            // Set the hidden input value
            document.getElementById('priority').value = priority;

            // Check if both service and priority are selected, then submit
            const service = document.getElementById('service-type').value;
            if (service && priority) {
                // Small delay to show visual feedback
                setTimeout(() => {
                    document.getElementById('join-queue-form').dispatchEvent(new Event('submit'));
                }, 200);
            }
        }

        // Student service office filters (Join Queue section)
        const officeFilterBtn = e.target.closest('.service-filter-btn');
        if (officeFilterBtn) {
            const filter = officeFilterBtn.dataset.officeFilter || 'accounting';
            document.querySelectorAll('.service-filter-btn').forEach(btn => {
                btn.classList.toggle('active', btn === officeFilterBtn && btn.classList.contains('service-filter-btn'));
            });
            document.querySelectorAll('.service-office-group').forEach(group => {
                const office = group.dataset.office;
                group.style.display = (filter === office) ? '' : 'none';
            });
        }

        // Now Serving filters (All / Registrar / Accounting)
        const nowFilterBtn = e.target.closest('.now-serving-filter-btn');
        if (nowFilterBtn) {
            const filter = nowFilterBtn.dataset.officeFilter || 'all';
            document.querySelectorAll('.now-serving-filter-btn').forEach(btn => {
                btn.classList.toggle('active', btn === nowFilterBtn);
            });
            document.querySelectorAll('#now-serving .col-12.col-md-4.col-lg-3').forEach(col => {
                const office = col.dataset.office || 'all';
                col.style.display = (filter === 'all' || filter === office) ? '' : 'none';
            });
        }

        // Admin service office filters
        const adminOfficeBtn = e.target.closest('.filter-btn[id^="filter-"][id$="-group"]');
        if (adminOfficeBtn) {
            const office = adminOfficeBtn.dataset.filter;
            const serviceButtons = document.querySelectorAll('#admin-service-filters .filter-btn');

            serviceButtons.forEach(btn => {
                const service = btn.dataset.filter;
                if (!service) { // "All" button
                    btn.style.display = 'block';
                    return;
                }

                const isRegistrar = ['submission_of_application_forms', 'application_assessment_of_school_records', 'releasing_of_school_records', 'inquiry_follow_up', 'faculty_tagging_room_assignments'].includes(service);
                const isAccounting = ['payment', 'balance_inquiry', 'claims'].includes(service);

                if (office === 'registrar') {
                    btn.style.display = isRegistrar ? 'block' : 'none';
                } else if (office === 'accounting') {
                    btn.style.display = isAccounting ? 'block' : 'none';
                } else {
                    btn.style.display = 'block';
                }
            });
        }

        // Sync Sidebar when clicking tabs/pills outside sidebar (like Quick Actions)
        if (e.target.closest('[data-bs-toggle="pill"]') || e.target.closest('[data-bs-toggle="tab"]')) {
            const toggle = e.target.closest('[data-bs-toggle="pill"]') || e.target.closest('[data-bs-toggle="tab"]');
            const target = toggle.getAttribute('href') || toggle.dataset.bsTarget;

            // Find the corresponding link in the sidebar
            const sidebarBtn = document.querySelector(`.sidebar-nav-links [href="${target}"]`);
            if (sidebarBtn) {
                // Use Bootstrap's API to ensure correct tab switching and avoid stacking
                const tab = bootstrap.Tab.getOrCreateInstance(sidebarBtn);
                tab.show();

                // If it's in a submenu, ensure it's expanded
                const parentSubmenu = sidebarBtn.closest('.submenu');
                if (parentSubmenu) {
                    const collapseObj = bootstrap.Collapse.getOrCreateInstance(parentSubmenu);
                    collapseObj.show();
                    const parentToggle = document.querySelector(`[data-bs-toggle="collapse"][href="#${parentSubmenu.id}"]`);
                    if (parentToggle) parentToggle.classList.remove('collapsed');
                }

                // Trigger data reload for the specific panel
                if (target === '#admin-list-panel') loadAdminList();
                if (target === '#user-list-panel') loadUserList();
                if (target === '#analytics-served-panel' || target === '#analytics-time-panel' || target === '#analytics-peak-panel' || target === '#my-analytics-panel') {
                    loadAdminAnalytics();
                    if (typeof loadMyAnalytics === 'function') loadMyAnalytics();
                }
                if (target === '#overview-panel') {
                    loadAdminStats();
                    loadQueueList();
                }
                if (target === '#service-control-panel') {
                    loadServiceSettings();
                }
            }
        }

        // Admin management actions
        const adminActionBtn = e.target.closest('button[data-admin-action]');
        if (adminActionBtn) {
            const action = adminActionBtn.dataset.adminAction;
            const adminId = adminActionBtn.dataset.adminId;
            if (action === 'delete-admin') {
                deleteAdmin(adminId);
            }
            if (action === 'update-role') {
                const selectEl = document.getElementById(`admin-role-${adminId}`);
                const newRole = selectEl ? selectEl.value : null;
                updateAdminRole(adminId, newRole);
            }
        }

        const userActionBtn = e.target.closest('button[data-user-action]');
        if (userActionBtn) {
            const action = userActionBtn.dataset.userAction;
            const userId = userActionBtn.dataset.userId;
            if (action === 'delete-user') {
                deleteUser(userId);
            }
        }

        // Service status toggles
        if (e.target.classList.contains('service-status-toggle')) {
            const service = e.target.dataset.service;
            const isOpen = e.target.checked;
            updateServiceSetting(service, { is_open: isOpen });
        }

        // Save limit button
        if (e.target.closest('.save-limit-btn')) {
            const btn = e.target.closest('.save-limit-btn');
            const service = btn.dataset.service;
            const input = document.getElementById(`limit-${service}`);
            const limit = input.value === '' ? null : parseInt(input.value, 10);
            updateServiceSetting(service, { daily_limit: limit });
        }

        // Sync button
        if (e.target.closest('.apply-settings-btn')) {
            loadServiceSettings();
        }

        // Compact admin queue actions
        const compactActionBtn = e.target.closest('[data-compact-action]');
        if (compactActionBtn) {
            const action = compactActionBtn.dataset.compactAction;
            const service = compactActionBtn.dataset.service;
            if (action === 'call') {
                const selectEl = document.getElementById(`compact-waiting-${service}`);
                const queueId = selectEl ? selectEl.value : '';
                if (!queueId) {
                    alert('Select a queue number to call.');
                    return;
                }
                queueAction(queueId, 'call').then(loadAdminCompactQueue);
            }
            if (action === 'next') {
                const queueId = compactActionBtn.dataset.queueId;
                if (!queueId) {
                    alert('No called queue to advance.');
                    return;
                }
                queueAction(queueId, 'next').then(loadAdminCompactQueue);
            }
            if (action === 'complete') {
                const queueId = compactActionBtn.dataset.queueId;
                if (!queueId) {
                    alert('No serving queue to complete.');
                    return;
                }
                queueAction(queueId, 'complete').then(loadAdminCompactQueue);
            }
            if (action === 'no_show') {
                const queueId = compactActionBtn.dataset.queueId;
                if (!queueId) {
                    alert('No serving queue to mark as no show.');
                    return;
                }
                queueAction(queueId, 'no_show').then(loadAdminCompactQueue);
            }
        }
    });
}

// Navigation
function showPage(pageId) {
    const pages = ['landing-page', 'login-page', 'admin-dashboard', 'student-dashboard'];
    pages.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            if (id === pageId) {
                el.classList.remove('d-none');
                // Use !important on all show calls so they can always be overridden consistently
                if (id === 'admin-dashboard') {
                    el.style.setProperty('display', 'flex', 'important');
                } else if (id === 'login-page') {
                    el.style.setProperty('display', 'flex', 'important');
                } else {
                    el.style.setProperty('display', 'block', 'important');
                }
            } else {
                el.classList.add('d-none');
                // MUST use setProperty with 'important' to override any previously set !important flex
                el.style.setProperty('display', 'none', 'important');
            }
        }
    });

    // Stop any active polling intervals when navigating away
    if (pageId !== 'admin-dashboard' && pageId !== 'student-dashboard') {
        if (statsPollInterval) { clearInterval(statsPollInterval); statsPollInterval = null; }
        if (queuePollInterval) { clearInterval(queuePollInterval); queuePollInterval = null; }
        if (compactQueuePollInterval) { clearInterval(compactQueuePollInterval); compactQueuePollInterval = null; }
    }
}

document.getElementById('nav-start-btn')?.addEventListener('click', () => showPage('login-page'));
document.getElementById('start-btn')?.addEventListener('click', () => showPage('login-page'));
document.getElementById('nav-signin-btn')?.addEventListener('click', () => showPage('login-page'));
document.getElementById('login-back-btn')?.addEventListener('click', () => showPage('landing-page'));

// Initial page check
async function initApp() {
    try {
        const response = await fetch(`${API_BASE}/auth/me`, {
            credentials: 'include'
        });

        if (response.ok) {
            const user = await response.json();
            currentUser = user;
            showDashboard(user.role);
        } else {
            showPage('landing-page');
        }
    } catch (error) {
        console.error('Auth check failed:', error);
        showPage('landing-page');
    }
}

// Handle login
async function handleLogin(e) {
    e.preventDefault();
    const email = document.getElementById('login-email').value;
    const password = document.getElementById('login-password').value;
    const errorDiv = document.getElementById('login-error');

    try {
        const response = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'include',
            body: JSON.stringify({ email, password })
        });

        const data = await response.json();

        if (response.ok) {
            currentUser = data;
            showDashboard(data.role);
            errorDiv.classList.add('d-none');
        } else {
            errorDiv.textContent = data.error || 'Login failed';
            errorDiv.classList.remove('d-none');
        }
    } catch (error) {
        errorDiv.textContent = 'Connection error. Please try again.';
        errorDiv.classList.remove('d-none');
    }
}

// Handle register
async function handleRegister(e) {
    e.preventDefault();
    const formData = {
        name: document.getElementById('register-name').value,
        email: document.getElementById('register-email').value,
        password: document.getElementById('register-password').value,
        student_id: document.getElementById('register-student-id').value || null
    };

    const errorDiv = document.getElementById('register-error');

    try {
        const response = await fetch(`${API_BASE}/auth/register`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'include',
            body: JSON.stringify(formData)
        });

        const data = await response.json();

        if (response.ok) {
            // Close modal and show success
            const modal = bootstrap.Modal.getInstance(document.getElementById('registerModal'));
            modal.hide();
            alert('Registration successful! Please login.');
            document.getElementById('register-form').reset();
        } else {
            errorDiv.textContent = data.error || 'Registration failed';
            errorDiv.classList.remove('d-none');
        }
    } catch (error) {
        errorDiv.textContent = 'Connection error. Please try again.';
        errorDiv.classList.remove('d-none');
    }
}

// Logout
async function logout() {
    try {
        await fetch(`${API_BASE}/auth/logout`, {
            method: 'POST',
            credentials: 'include'
        });
    } catch (error) {
        console.error('Logout error:', error);
    }

    currentUser = null;
    showLogin();
}

// Load admin dashboard
function loadAdminDashboard() {
    loadAdminStats();
    loadQueueList();
    loadHistory();

    // Start polling
    if (!statsPollInterval) statsPollInterval = setInterval(loadAdminStats, 5000);
    if (!queuePollInterval) queuePollInterval = setInterval(loadQueueList, 3000);
}

function configureAdminView() {
    const adminCreateTab = document.querySelector('[href="#admin-create-panel"]');
    const adminListTab = document.querySelector('[href="#admin-list-panel"]');
    const userListTab = document.querySelector('[href="#user-list-panel"]');
    const usersSubmenuToggle = document.querySelector('[href="#users-submenu"]');

    // Analytics sub-menus
    const analyticsSubmenuToggle = document.querySelector('[href="#analytics-submenu"]');
    const analyticsNavItem = analyticsSubmenuToggle ? analyticsSubmenuToggle.closest('.nav-item-with-submenu') : null;
    const myAnalyticsTab = document.querySelector('[href="#my-analytics-panel"]');

    const overviewTab = document.querySelector('[href="#overview-panel"]');

    if (isStaticAdmin()) {
        // System admin: show full management + system-wide analytics
        if (adminCreateTab) adminCreateTab.classList.remove('d-none');
        if (adminListTab) adminListTab.classList.remove('d-none');
        if (userListTab) userListTab.classList.remove('d-none');
        if (usersSubmenuToggle) usersSubmenuToggle.parentElement.classList.remove('d-none');
        if (analyticsNavItem) analyticsNavItem.classList.remove('d-none');
        // Hide personal analytics for system admin
        if (myAnalyticsTab) myAnalyticsTab.classList.add('d-none');

        // Default to admin list for static admins
        if (adminListTab) {
            const tab = new bootstrap.Tab(adminListTab);
            tab.show();
            const submenu = document.getElementById('users-submenu');
            if (submenu) {
                const collapse = bootstrap.Collapse.getOrCreateInstance(submenu);
                collapse.show();
                const toggle = document.querySelector('[href="#users-submenu"]');
                if (toggle) toggle.classList.remove('collapsed');
            }
        }
        loadAdminManagement();
    } else {
        // Appointed admin: hide management + system analytics, show personal analytics
        [adminCreateTab, adminListTab, userListTab, usersSubmenuToggle].forEach(el => {
            if (el) {
                const navItem = el.closest('.nav-item-with-submenu') || el.parentElement;
                navItem.classList.add('d-none');
            }
        });
        if (analyticsNavItem) analyticsNavItem.classList.add('d-none');
        if (myAnalyticsTab) myAnalyticsTab.classList.remove('d-none');

        // Show the My Analytics subtitle with the service name
        const subtitleEl = document.getElementById('my-analytics-subtitle');
        if (subtitleEl && currentUser.admin_service) {
            const svcName = currentUser.admin_service.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
            subtitleEl.textContent = `Your personal performance stats for the ${svcName} queue.`;
        }

        // Default to overview for appointed admins
        if (overviewTab) {
            const tab = new bootstrap.Tab(overviewTab);
            tab.show();
        }
    }

    const assignedService = currentUser?.admin_service;
    const filterButtons = Array.from(document.querySelectorAll('.filter-btn'));
    if (!isStaticAdmin() && assignedService) {
        filterButtons.forEach(btn => {
            const filterValue = btn.dataset.filter || '';
            const isAssigned = filterValue === assignedService;
            btn.classList.toggle('active', isAssigned);
            btn.disabled = !isAssigned;
            btn.classList.toggle('d-none', !isAssigned);
        });
    } else {
        filterButtons.forEach(btn => {
            btn.disabled = false;
            btn.classList.remove('d-none');
        });
    }
}

// Load admin stats
async function loadAdminStats() {
    try {
        const response = await fetch(`${API_BASE}/admin/stats`, {
            credentials: 'include'
        });

        if (response.ok) {
            const stats = await response.json();
            document.getElementById('stats-waiting').textContent = stats.total_waiting || 0;
            document.getElementById('stats-served').textContent = stats.total_served_today || 0;
            SERVICE_TYPES.forEach(service => {
                const el = document.getElementById(`stats-${service}`);
                if (el) el.textContent = stats.services_count?.[service] || 0;
            });
        }
    } catch (error) {
        console.error('Failed to load stats:', error);
    }
}

// Load queue list
async function loadQueueList() {
    // Get active filter from button
    const activeFilter = document.querySelector('.filter-btn.active');
    let serviceType = activeFilter ? activeFilter.dataset.filter : '';
    if (currentUser?.role === 'admin' && !isStaticAdmin() && currentUser?.admin_service) {
        serviceType = currentUser.admin_service;
    }

    await loadQueueListWithFilter(serviceType);
}

// Load queue list with filter
async function loadQueueListWithFilter(serviceType = '') {
    if (currentUser?.role === 'admin' && !isStaticAdmin() && currentUser?.admin_service) {
        serviceType = currentUser.admin_service;
    }
    try {
        const url = serviceType
            ? `${API_BASE}/queue/status?service_type=${serviceType}`
            : `${API_BASE}/queue/status`;

        const response = await fetch(url, {
            credentials: 'include'
        });

        if (response.ok) {
            const entries = await response.json();
            displayQueueList(entries);
        }
    } catch (error) {
        console.error('Failed to load queue:', error);
    }
}

// Display queue list
function displayQueueList(entries) {
    const container = document.getElementById('queue-list');

    if (entries.length === 0) {
        container.innerHTML = '<div class="col-12"><div class="alert alert-info">No entries in queue</div></div>';
        return;
    }

    container.innerHTML = entries.map(entry => {
        const statusBadge = {
            'waiting': '<span class="badge bg-warning">Waiting</span>',
            'called': '<span class="badge bg-info">Called</span>',
            'serving': '<span class="badge bg-success">Serving</span>'
        }[entry.status] || '<span class="badge bg-secondary">' + entry.status + '</span>';

        const priorityBadge = entry.priority === 'senior_pwd'
            ? '<span class="badge bg-danger">Senior/PWD</span>'
            : '';

        const actions = entry.status === 'waiting'
            ? `<button class="btn btn-sm btn-primary" onclick="queueAction('${entry.id}', 'call')">Call</button>`
            : entry.status === 'called'
                ? `<button class="btn btn-sm btn-success" onclick="queueAction('${entry.id}', 'next')">Next</button>`
                : `<button class="btn btn-sm btn-success" onclick="queueAction('${entry.id}', 'complete')">Complete</button>
               <button class="btn btn-sm btn-danger" onclick="queueAction('${entry.id}', 'no_show')">No Show</button>`;

        return `
            <div class="col-md-4 mb-3">
                <div class="card">
                    <div class="card-body">
                        <h5 class="card-title">${entry.queue_number} ${priorityBadge}</h5>
                        <p class="card-text">
                            <strong>${entry.user_name}</strong><br>
                            ${formatServiceLabel(entry.service_type)}<br>
                            ${statusBadge}
                        </p>
                        <div class="btn-group">${actions}</div>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

// Queue action
async function queueAction(queueId, action) {
    try {
        const response = await fetch(`${API_BASE}/queue/action`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'include',
            body: JSON.stringify({ queue_id: queueId, action: action })
        });

        if (response.ok) {
            loadQueueList();
            loadAdminStats();
            loadHistory();
        } else {
            const data = await response.json();
            alert(data.error || 'Action failed');
        }
    } catch (error) {
        alert('Connection error. Please try again.');
    }
}

// Load history
async function loadHistory() {
    try {
        const response = await fetch(`${API_BASE}/transactions/history`, {
            credentials: 'include'
        });

        if (response.ok) {
            const history = await response.json();
            displayHistory(history);
        }
    } catch (error) {
        console.error('Failed to load history:', error);
    }
}

// Load and display admin analytics (SuperAdmin only)
async function loadAdminAnalytics() {
    if (!isStaticAdmin()) return;
    // Read from whichever period selector is visible (each sub-panel has its own)
    const periodEl =
        document.getElementById('analytics-period-served') ||
        document.getElementById('analytics-period-time') ||
        document.getElementById('analytics-period-peak') ||
        document.getElementById('analytics-period');
    const days = periodEl ? parseInt(periodEl.value, 10) : 30;
    try {
        const response = await fetch(`${API_BASE}/admin/analytics?days=${days}`, { credentials: 'include' });
        if (!response.ok) {
            console.error('Analytics fetch failed');
            return;
        }
        const data = await response.json();
        renderAnalyticsCharts(data);
    } catch (err) {
        console.error('Analytics load failed:', err);
    }
}

function renderAnalyticsCharts(data) {
    let adminPerf = data.admin_performance || [];
    let peakHours = data.peak_hours || [];
    if (adminPerf.length === 0) adminPerf = [{ admin_name: 'No data', numbers_served: 0, avg_service_minutes: 0 }];
    if (peakHours.length === 0) peakHours = Array.from({ length: 24 }, (_, h) => ({ hour: h, hour_label: `${String(h).padStart(2, '0')}:00`, count: 0 }));
    const CHART_COLORS = {
        red: 'rgba(120, 0, 0, 0.8)',
        redLight: 'rgba(120, 0, 0, 0.5)',
        gold: 'rgba(201, 162, 39, 0.8)',
        goldLight: 'rgba(201, 162, 39, 0.5)',
    };

    const labels = adminPerf.map(a => a.admin_name || 'Unknown');
    const servedData = adminPerf.map(a => a.numbers_served || 0);
    const avgTimeData = adminPerf.map(a => parseFloat(a.avg_service_minutes) || 0);

    if (analyticsCharts.numbersServed) analyticsCharts.numbersServed.destroy();
    const ctx1 = document.getElementById('chart-numbers-served');
    if (ctx1) {
        analyticsCharts.numbersServed = new Chart(ctx1, {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    label: 'Numbers Served',
                    data: servedData,
                    backgroundColor: CHART_COLORS.redLight,
                    borderColor: CHART_COLORS.red,
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, ticks: { stepSize: 1 } }
                }
            }
        });
    }

    if (analyticsCharts.avgServiceTime) analyticsCharts.avgServiceTime.destroy();
    const ctx2 = document.getElementById('chart-avg-service-time');
    if (ctx2) {
        analyticsCharts.avgServiceTime = new Chart(ctx2, {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    label: 'Avg Service Time (min)',
                    data: avgTimeData,
                    backgroundColor: CHART_COLORS.goldLight,
                    borderColor: CHART_COLORS.gold,
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true }
                }
            }
        });
    }

    if (analyticsCharts.peakHours) analyticsCharts.peakHours.destroy();
    const ctx3 = document.getElementById('chart-peak-hours');
    if (ctx3) {
        analyticsCharts.peakHours = new Chart(ctx3, {
            type: 'bar',
            data: {
                labels: peakHours.map(p => p.hour_label),
                datasets: [{
                    label: 'Completions',
                    data: peakHours.map(p => p.count),
                    backgroundColor: CHART_COLORS.redLight,
                    borderColor: CHART_COLORS.red,
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, ticks: { stepSize: 1 } }
                }
            }
        });
    }
}

// Display history
function displayHistory(history) {
    const tbody = document.getElementById('history-tbody');

    if (history.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center">No transaction history</td></tr>';
        return;
    }

    tbody.innerHTML = history.map(trans => {
        return `
            <tr>
                <td>${trans.queue_number}</td>
                <td>${trans.user_name}</td>
                <td>${formatServiceLabel(trans.service_type)}</td>
                <td><span class="badge bg-success">${trans.status}</span></td>
                <td>${trans.wait_time_minutes ? trans.wait_time_minutes + ' min' : '-'}</td>
                <td>${trans.completed_at ? new Date(trans.completed_at).toLocaleString() : '-'}</td>
            </tr>
        `;
    }).join('');
}

// Load student dashboard
function loadStudentDashboard() {
    loadMyQueue();
    loadStudentHistory();
    loadNowServing();
    requestNotificationPermission();

    // Combined poll: fetch both my-queue and now-serving, update UI, check for 5-away notification
    const pollStudentQueue = async () => {
        try {
            const [queueRes, servingRes] = await Promise.all([
                fetch(`${API_BASE}/queue/my-queue`, { credentials: 'include' }),
                fetch(`${API_BASE}/queue/now-serving`, { credentials: 'include' })
            ]);
            const queue = queueRes.ok ? await queueRes.json() : null;
            const servingData = servingRes.ok ? await servingRes.json() : {};
            displayMyQueue(queue);
            displayNowServing(servingData);
            checkQueuePositionNotification(queue, servingData);
        } catch (err) {
            console.error('Queue poll failed:', err);
        }
    };

    pollStudentQueue();
    queuePollInterval = setInterval(pollStudentQueue, 3000);
}

async function loadAdminCompactQueue() {
    const container = document.getElementById('admin-compact-cards');
    if (!container) return;

    let serviceType = '';
    if (currentUser?.admin_type === 'appointed' && currentUser?.admin_service) {
        serviceType = currentUser.admin_service;
    }

    try {
        const url = serviceType
            ? `${API_BASE}/queue/status?service_type=${serviceType}`
            : `${API_BASE}/queue/status`;
        const response = await fetch(url, { credentials: 'include' });
        if (!response.ok) {
            container.innerHTML = '<div class="alert alert-danger">Failed to load queues.</div>';
            return;
        }
        const entries = await response.json();
        const grouped = SERVICE_TYPES.reduce((acc, service) => {
            acc[service] = [];
            return acc;
        }, {});
        entries.forEach(entry => {
            if (grouped[entry.service_type]) grouped[entry.service_type].push(entry);
        });

        const servicesToRender = serviceType ? [serviceType] : SERVICE_TYPES;
        container.innerHTML = servicesToRender.map(service => {
            const serviceEntries = grouped[service] || [];
            const waiting = serviceEntries.filter(e => e.status === 'waiting');
            const called = serviceEntries.find(e => e.status === 'called');
            const serving = serviceEntries.find(e => e.status === 'serving');
            const current = serving || called || waiting[0] || null;

            const statusLabel = serving
                ? 'Serving'
                : called
                    ? 'Called'
                    : waiting.length
                        ? 'Waiting'
                        : 'Idle';
            const statusClass = serving
                ? 'bg-success'
                : called
                    ? 'bg-info'
                    : waiting.length
                        ? 'bg-warning text-dark'
                        : 'bg-secondary';

            const waitingOptions = waiting.map(entry => {
                const name = entry.user_name ? ` - ${entry.user_name}` : '';
                return `<option value="${entry.id}">${entry.queue_number}${name}</option>`;
            }).join('');

            const callDisabled = waiting.length === 0;
            const calledId = called ? called.id : '';
            const servingId = serving ? serving.id : '';

            return `
                <div class="col-12 col-md-6 col-lg-4">
                    <div class="card compact-queue-card">
                        <div class="card-body">
                            <div class="d-flex justify-content-between align-items-center mb-2">
                                <div class="fw-bold">${formatServiceLabel(service)}</div>
                                <span class="badge ${statusClass}">${statusLabel}</span>
                            </div>
                            <div class="compact-queue-number">${current ? current.queue_number : '—'}</div>
                            <div class="text-muted small mb-3">${current ? (current.user_name || '') : 'No active queue'}</div>
                            <div class="d-flex gap-2 align-items-center mb-2">
                                <select class="form-select form-select-sm" id="compact-waiting-${service}">
                                    <option value="">Select queue...</option>
                                    ${waitingOptions}
                                </select>
                                <button class="btn btn-sm btn-primary" data-compact-action="call" data-service="${service}" ${callDisabled ? 'disabled' : ''}>Call</button>
                            </div>
                            <div class="d-flex flex-wrap gap-2">
                                <button class="btn btn-sm btn-outline-success" data-compact-action="next"
                                    data-service="${service}" data-queue-id="${calledId}" ${called ? '' : 'disabled'}>
                                    Next
                                </button>
                                <button class="btn btn-sm btn-outline-primary" data-compact-action="complete"
                                    data-service="${service}" data-queue-id="${servingId}" ${serving ? '' : 'disabled'}>
                                    Complete
                                </button>
                                <button class="btn btn-sm btn-outline-danger" data-compact-action="no_show"
                                    data-service="${service}" data-queue-id="${servingId}" ${serving ? '' : 'disabled'}>
                                    No Show
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    } catch (error) {
        container.innerHTML = '<div class="alert alert-danger">Connection error.</div>';
    }
}

// Request notification permission (for 5-away alert)
function requestNotificationPermission() {
    if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission();
    }
}

// Parse numeric part from queue number (e.g. "AF10" -> 10, "PY01" -> 1)
function parseQueueNumber(queueNumber) {
    if (!queueNumber || typeof queueNumber !== 'string') return null;
    const match = queueNumber.match(/(\d+)$/);
    return match ? parseInt(match[1], 10) : null;
}

// Check if user is 5 away and trigger notification (no duplicates)
function checkQueuePositionNotification(myQueue, servingData) {
    if (!myQueue || !servingData) return;

    // Reset notification state when user leaves queue or gets called/serving
    if (myQueue.status !== 'waiting') {
        hasNotifiedFiveAway = false;
        hasNotifiedTenAway = false;
        lastNotifiedQueueId = null;
        return;
    }

    const service = myQueue.service_type;
    const serviceInfo = servingData[service];
    if (!serviceInfo || !serviceInfo.serving || serviceInfo.serving.length === 0) return;

    const currentServing = serviceInfo.serving[0];
    const currentNumber = parseQueueNumber(currentServing?.queue_number);
    const myNumber = parseQueueNumber(myQueue.queue_number);
    if (currentNumber == null || myNumber == null) return;

    const positionAway = myNumber - currentNumber;
    if (positionAway <= 0) return;

    // User is 10 away
    if (positionAway === 10 && !hasNotifiedTenAway) {
        hasNotifiedTenAway = true;
        triggerPositionNotification(myQueue.queue_number, formatServiceLabel(service), 10);
    }

    // User is 5 away - notify once per queue session
    if (positionAway === 5 && !hasNotifiedFiveAway) {
        hasNotifiedFiveAway = true;
        triggerPositionNotification(myQueue.queue_number, formatServiceLabel(service), 5);
    }
}

// Show notification and vibrate when 5/10 away
function triggerPositionNotification(queueNumber, serviceLabel, count) {
    const title = 'Almost your turn!';
    const body = `Queue ${queueNumber} (${serviceLabel}) — you're ${count} away. Get ready!`;

    if ('Notification' in window && Notification.permission === 'granted') {
        try {
            new Notification(title, { body, icon: 'images/university-logo.png' });
        } catch (_) {
            new Notification(title, { body });
        }
    }

    if (navigator.vibrate) {
        navigator.vibrate([200, 100, 200, 100, 200]);
    }

    // In-app fallback: show prominent alert in queue status area
    showPositionInAppAlert(queueNumber, serviceLabel, count);
}

// In-app alert when 5/10 away
function showPositionInAppAlert(queueNumber, serviceLabel, count) {
    const statusDiv = document.getElementById('my-queue-status');
    if (!statusDiv) return;
    const alert = document.createElement('div');
    alert.className = `alert alert-${count === 10 ? 'info' : 'warning'} alert-dismissible fade show d-flex align-items-center mb-0 mt-2`;
    alert.setAttribute('role', 'alert');
    alert.innerHTML = `
        <i class="bi bi-bell-fill me-2" style="font-size: 1.5rem;"></i>
        <div class="flex-grow-1">
            <strong>Almost your turn!</strong> Queue ${queueNumber} — you're ${count} away. Get ready!
        </div>
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;
    statusDiv.insertAdjacentElement('afterend', alert);
    setTimeout(() => alert.remove(), 15000);
}

// Show notification and vibrate when 5 away
function triggerFiveAwayNotification(queueNumber, serviceLabel) {
    const title = 'Almost your turn!';
    const body = `Queue ${queueNumber} (${serviceLabel}) — you're 5 away. Get ready!`;

    if ('Notification' in window && Notification.permission === 'granted') {
        try {
            new Notification(title, { body, icon: 'images/university-logo.png' });
        } catch (_) {
            new Notification(title, { body });
        }
    }

    if (navigator.vibrate) {
        navigator.vibrate([200, 100, 200, 100, 200]);
    }

    // In-app fallback: show prominent alert in queue status area
    showFiveAwayInAppAlert(queueNumber, serviceLabel);
}

// In-app alert when 5 away (fallback if notifications blocked)
function showFiveAwayInAppAlert(queueNumber, serviceLabel) {
    const statusDiv = document.getElementById('my-queue-status');
    if (!statusDiv) return;
    const alert = document.createElement('div');
    alert.className = 'alert alert-warning alert-dismissible fade show d-flex align-items-center';
    alert.setAttribute('role', 'alert');
    alert.innerHTML = `
        <i class="bi bi-bell-fill me-2" style="font-size: 1.5rem;"></i>
        <div class="flex-grow-1">
            <strong>Almost your turn!</strong> Queue ${queueNumber} — you're 5 away. Get ready!
        </div>
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;
    statusDiv.insertAdjacentElement('afterend', alert);
    setTimeout(() => alert.remove(), 15000);
}

// Load now-serving status (public)
async function loadNowServing() {
    try {
        const response = await fetch(`${API_BASE}/queue/now-serving`, {
            credentials: 'include'
        });
        if (!response.ok) return;
        const data = await response.json();
        displayNowServing(data);
    } catch (_) {
        // no-op
    }
}

function displayNowServing(data) {
    SERVICE_TYPES.forEach((service) => {
        const numberEl = document.getElementById(`now-serving-${service}`);
        const statusEl = document.getElementById(`now-serving-${service}-status`);
        if (!numberEl || !statusEl) return;

        const servingList = data?.[service]?.serving || [];
        const current = servingList[0];

        if (!current) {
            numberEl.textContent = '—';
            statusEl.textContent = 'No one is being served';
            return;
        }

        numberEl.textContent = current.queue_number || '—';
        statusEl.textContent = current.status === 'serving' ? 'Now serving' : 'Now calling';
    });
}

// When user is waiting: show only their queue's Now Serving. When done: show all.
function updateNowServingVisibility(myQueue) {
    const cols = document.querySelectorAll('.now-serving-col');
    const filterBtns = document.querySelector('.now-serving-filters');
    const showAll = !myQueue || myQueue.status !== 'waiting';

    cols.forEach((col) => {
        const service = col.dataset.service;
        const isMyService = service === myQueue?.service_type;
        col.classList.toggle('d-none', !showAll && !isMyService);
    });

    if (filterBtns) {
        filterBtns.classList.toggle('d-none', !showAll);
    }
}

// Load my queue
async function loadMyQueue() {
    try {
        const response = await fetch(`${API_BASE}/queue/my-queue`, {
            credentials: 'include'
        });

        if (response.ok) {
            const queue = await response.json();
            displayMyQueue(queue);
        }
    } catch (error) {
        console.error('Failed to load my queue:', error);
    }
}

// Display my queue
function displayMyQueue(queue) {
    const statusDiv = document.getElementById('my-queue-status');
    updateNowServingVisibility(queue);

    if (!queue) {
        if (statusDiv) statusDiv.innerHTML = '<div class="alert alert-info">No active queue</div>';
        lastCalledQueueId = null;
        return;
    }

    const statusBadge = {
        'waiting': '<span class="badge bg-warning">Waiting</span>',
        'called': '<span class="badge bg-info">Called</span>',
        'serving': '<span class="badge bg-success">Serving</span>'
    }[queue.status] || '<span class="badge bg-secondary">' + queue.status + '</span>';

    statusDiv.innerHTML = `
        <div class="alert alert-success">
            <h5>Queue Number: ${queue.queue_number}</h5>
            <p>Service: ${formatServiceLabel(queue.service_type)}</p>
            <p>Status: ${statusBadge}</p>
            ${queue.estimated_wait_time ? `<p>Estimated wait: ${queue.estimated_wait_time} minutes</p>` : ''}
        </div>
    `;

    handleQueueCalledNotification(queue);
}

function handleQueueCalledNotification(queue) {
    if (!queue || !['called', 'serving'].includes(queue.status)) {
        return;
    }
    const queueId = queue.id || queue.queue_number;
    if (queueId === lastCalledQueueId) return;
    lastCalledQueueId = queueId;
    triggerQueueCalledAlert(queue);
}

function triggerQueueCalledAlert(queue) {
    const label = formatServiceLabel(queue.service_type);
    const message = `Queue ${queue.queue_number} (${label}) is now being called.`;
    let vibrated = false;

    if (navigator.vibrate) {
        vibrated = navigator.vibrate([300, 150, 300, 150, 300]);
    }

    if (!vibrated) {
        playQueueCallBeep();
    }

    showQueueCalledInAppAlert(message);

    if ('Notification' in window && Notification.permission === 'granted') {
        try {
            new Notification('Queue Called', { body: message, icon: 'images/university-logo.png' });
        } catch (_) {
            new Notification('Queue Called', { body: message });
        }
    }
}

function playQueueCallBeep() {
    try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const oscillator = ctx.createOscillator();
        const gain = ctx.createGain();
        oscillator.type = 'sine';
        oscillator.frequency.value = 880;
        gain.gain.value = 0.05;
        oscillator.connect(gain);
        gain.connect(ctx.destination);
        oscillator.start();
        setTimeout(() => {
            oscillator.stop();
            ctx.close();
        }, 300);
    } catch (_) {
        // If audio is blocked, no-op
    }
}

function showQueueCalledInAppAlert(message) {
    const statusDiv = document.getElementById('my-queue-status');
    if (!statusDiv) return;
    const alert = document.createElement('div');
    alert.className = 'alert alert-danger alert-dismissible fade show d-flex align-items-center mt-2';
    alert.setAttribute('role', 'alert');
    alert.innerHTML = `
        <i class="bi bi-broadcast me-2" style="font-size: 1.5rem;"></i>
        <div class="flex-grow-1">
            <strong>Queue Called</strong> ${message}
        </div>
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;
    statusDiv.insertAdjacentElement('afterend', alert);
    setTimeout(() => alert.remove(), 15000);
}

// Handle join queue
async function handleJoinQueue(e) {
    e.preventDefault();
    const serviceType = document.getElementById('service-type').value;
    const priority = document.getElementById('priority').value;

    if (!serviceType) {
        alert('Please select a service');
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/queue/join`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'include',
            body: JSON.stringify({ service_type: serviceType, priority: priority })
        });

        const data = await response.json();

        if (response.ok) {
            loadMyQueue();
            // Reset selection
            document.querySelectorAll('.service-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.priority-btn').forEach(btn => {
                btn.classList.remove('active');
                if (btn.dataset.priority === 'regular') {
                    btn.classList.add('active');
                }
            });
            document.getElementById('service-type').value = '';
            document.getElementById('priority').value = 'regular';

            // Show success message
            const statusDiv = document.getElementById('my-queue-status');
            statusDiv.innerHTML = '<div class="alert alert-success"><i class="bi bi-check-circle me-2"></i>Successfully joined queue! Your queue number is being assigned...</div>';

            // Refresh queue status after a moment
            setTimeout(() => {
                loadMyQueue();
            }, 1000);
        } else {
            alert(data.error || 'Failed to join queue');
        }
    } catch (error) {
        alert('Connection error. Please try again.');
    }
}

// Handle verification
async function handleVerification(e) {
    e.preventDefault();
    const fileInput = document.getElementById('receipt-file');
    const referenceNumber = document.getElementById('reference-number').value;
    const accountNumber = document.getElementById('account-number').value;
    const paymentMethod = document.getElementById('payment-method').value;
    const paymentAmount = document.getElementById('payment-amount').value;
    const paymentDate = document.getElementById('payment-date').value;
    const resultDiv = document.getElementById('verification-result');

    if (!fileInput.files[0]) {
        alert('Please select a file');
        return;
    }

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    formData.append('reference_number', referenceNumber);
    formData.append('account_number', accountNumber);
    formData.append('payment_method', paymentMethod);
    formData.append('payment_amount', paymentAmount);
    formData.append('payment_date', paymentDate);

    resultDiv.innerHTML = '<div class="alert alert-info">Verifying receipt... Please wait.</div>';

    try {
        const response = await fetch(`${API_BASE}/receipts/verify`, {
            method: 'POST',
            credentials: 'include',
            body: formData
        });

        const data = await response.json();

        if (response.ok) {
            const statusBadge = data.confidence_score >= 90
                ? '<span class="badge bg-success">VERIFIED</span>'
                : '<span class="badge bg-danger">NOT VERIFIED</span>';

            resultDiv.innerHTML = `
                <div class="alert alert-${data.confidence_score >= 90 ? 'success' : 'warning'}">
                    <h5>Verification Result: ${statusBadge}</h5>
                    <p>Confidence Score: ${data.confidence_score}%</p>
                    <p><strong>AI Analysis:</strong></p>
                    <pre class="bg-light p-2">${data.verification_result}</pre>
                </div>
            `;
        } else {
            resultDiv.innerHTML = `<div class="alert alert-danger">${data.error || 'Verification failed'}</div>`;
        }
    } catch (error) {
        resultDiv.innerHTML = '<div class="alert alert-danger">Connection error. Please try again.</div>';
    }
}

// Load student history
async function loadStudentHistory() {
    try {
        const response = await fetch(`${API_BASE}/transactions/history`, {
            credentials: 'include'
        });

        if (response.ok) {
            const history = await response.json();
            displayStudentHistory(history);
        }
    } catch (error) {
        console.error('Failed to load history:', error);
    }
}

// Display student history
function displayStudentHistory(history) {
    const tbody = document.getElementById('student-history-tbody');

    if (history.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center">No transaction history</td></tr>';
        return;
    }

    tbody.innerHTML = history.map(trans => {
        return `
            <tr>
                <td>${trans.queue_number}</td>
                <td>${formatServiceLabel(trans.service_type)}</td>
                <td><span class="badge bg-success">${trans.status}</span></td>
                <td>${trans.wait_time_minutes ? trans.wait_time_minutes + ' min' : '-'}</td>
                <td>${trans.completed_at ? new Date(trans.completed_at).toLocaleString() : '-'}</td>
            </tr>
        `;
    }).join('');
}


// Stop polling
function stopPolling() {
    if (queuePollInterval) {
        clearInterval(queuePollInterval);
        queuePollInterval = null;
    }
    if (statsPollInterval) {
        clearInterval(statsPollInterval);
        statsPollInterval = null;
    }
    if (nowServingPollInterval) {
        clearInterval(nowServingPollInterval);
        nowServingPollInterval = null;
    }
    if (compactQueuePollInterval) {
        clearInterval(compactQueuePollInterval);
        compactQueuePollInterval = null;
    }
    hasNotifiedFiveAway = false;
    lastNotifiedQueueId = null;
    lastCalledQueueId = null;
}

// Admin management (static admin only)
async function handleCreateAdmin(e) {
    e.preventDefault();
    const name = document.getElementById('new-admin-name').value;
    const email = document.getElementById('new-admin-email').value;
    const password = document.getElementById('new-admin-password').value;
    const adminService = document.getElementById('new-admin-role').value;

    try {
        const response = await fetch(`${API_BASE}/admin/admins`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'include',
            body: JSON.stringify({ name, email, password, admin_service: adminService })
        });
        const data = await response.json();
        if (!response.ok) {
            alert(data.error || 'Failed to create admin');
            return;
        }
        document.getElementById('create-admin-form').reset();
        await loadAdminManagement();
    } catch (error) {
        alert('Connection error. Please try again.');
    }
}


async function loadAdminManagement() {
    await Promise.all([loadAdminList(), loadUserList()]);
}

async function loadAdminList() {
    const tbody = document.getElementById('admin-list-tbody');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="7" class="text-center"><div class="spinner-border spinner-border-sm text-primary"></div> Loading admins...</td></tr>';
    try {
        const response = await fetch(`${API_BASE}/admin/admins`, {
            credentials: 'include'
        });
        const data = await response.json();
        if (!response.ok) {
            tbody.innerHTML = `<tr><td colspan="7" class="text-center">${data.error || 'Failed to load admins'}</td></tr>`;
            return;
        }
        const assignedServices = new Set(
            (data || [])
                .filter(admin => admin.admin_type === 'appointed' && admin.admin_service)
                .map(admin => admin.admin_service)
        );
        tbody.innerHTML = data.map(admin => {
            const isStatic = admin.admin_type === 'static';
            const roleSelect = isStatic
                ? `<span class="badge bg-secondary">Protected</span>`
                : `
                    <select class="form-select form-select-sm" id="admin-role-${admin.id}">
                        <option value="" ${!admin.admin_service ? 'selected' : ''}>Unassigned</option>
                        ${SERVICE_TYPES.map(service => `
                            <option value="${service}" ${admin.admin_service === service ? 'selected' : ''} ${assignedServices.has(service) && admin.admin_service !== service ? 'disabled' : ''}>${formatServiceLabel(service)}</option>
                        `).join('')}
                    </select>
                `;
            const actions = isStatic
                ? '—'
                : `
                    <div class="d-flex gap-2">
                        <button class="btn btn-sm btn-outline-primary" data-admin-action="update-role" data-admin-id="${admin.id}">Save</button>
                        <button class="btn btn-sm btn-danger" data-admin-action="delete-admin" data-admin-id="${admin.id}">Delete</button>
                    </div>
                `;

            const hasPassword = admin.plaintext_password && admin.plaintext_password.trim() !== '';
            const passwordHtml = hasPassword
                ? `
                    <div class="d-flex align-items-center" style="min-width: 130px;">
                        <input type="password" class="form-control form-control-sm border-0 bg-transparent p-0" 
                            value="${admin.plaintext_password}" readonly id="list-pass-${admin.id}"
                            style="width: 90px; font-family: monospace;">
                        <button class="btn btn-sm p-1 ms-1 text-secondary" type="button" onclick="window.toggleListPassword('${admin.id}')">
                            <i class="bi bi-eye"></i>
                        </button>
                    </div>
                `
                : `<span class="text-muted fst-italic small"><i class="bi bi-lock"></i> Not Available</span>`;

            return `
                <tr>
                    <td>${admin.name}</td>
                    <td>${admin.email}</td>
                    <td>${passwordHtml}</td>
                    <td><span class="badge ${isStatic ? 'bg-dark' : 'bg-secondary'}">${isStatic ? 'Static' : 'Appointed'}</span></td>
                    <td>${roleSelect}</td>
                    <td><small class="text-muted">${admin.created_at ? new Date(admin.created_at).toLocaleString() : '-'}</small></td>
                    <td>${actions}</td>
                </tr>
            `;
        }).join('');
        const createSelect = document.getElementById('new-admin-role');
        if (createSelect) {
            Array.from(createSelect.options).forEach(option => {
                option.disabled = assignedServices.has(option.value);
            });
            if (createSelect.selectedOptions.length && createSelect.selectedOptions[0].disabled) {
                const firstEnabled = Array.from(createSelect.options).find(option => !option.disabled);
                if (firstEnabled) createSelect.value = firstEnabled.value;
            }
            const createBtn = document.querySelector('#create-admin-form button[type="submit"]');
            const hasAvailableRole = Array.from(createSelect.options).some(option => !option.disabled);
            if (createBtn) createBtn.disabled = !hasAvailableRole;
            createSelect.disabled = !hasAvailableRole;
        }
    } catch (error) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center">Connection error</td></tr>';
    }
}

async function loadUserList() {
    const tbody = document.getElementById('user-list-tbody');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="4" class="text-center"><div class="spinner-border spinner-border-sm text-primary"></div> Loading students...</td></tr>';
    try {
        const response = await fetch(`${API_BASE}/admin/users`, {
            credentials: 'include'
        });
        const data = await response.json();
        if (!response.ok) {
            tbody.innerHTML = `<tr><td colspan="4" class="text-center">${data.error || 'Failed to load users'}</td></tr>`;
            return;
        }
        tbody.innerHTML = data.map(user => {
            return `
                <tr>
                    <td>${user.name}</td>
                    <td>${user.email}</td>
                    <td>${user.created_at ? new Date(user.created_at).toLocaleString() : '-'}</td>
                    <td>
                        <button class="btn btn-sm btn-danger" data-user-action="delete-user" data-user-id="${user.id}">Delete</button>
                    </td>
                </tr>
            `;
        }).join('');
    } catch (error) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-center">Connection error</td></tr>';
    }
}

async function updateAdminRole(adminId, adminService) {
    const normalizedService = adminService || null;
    try {
        const response = await fetch(`${API_BASE}/admin/admins/${adminId}`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'include',
            body: JSON.stringify({ admin_service: normalizedService })
        });
        const data = await response.json();
        if (!response.ok) {
            alert(data.error || 'Failed to update admin role');
            return;
        }
        await loadAdminList();
    } catch (error) {
        alert('Connection error. Please try again.');
    }
}

async function deleteAdmin(adminId) {
    if (!confirm('Delete this admin?')) return;
    try {
        const response = await fetch(`${API_BASE}/admin/admins/${adminId}`, {
            method: 'DELETE',
            credentials: 'include'
        });
        const data = await response.json();
        if (!response.ok) {
            alert(data.error || 'Failed to delete admin');
            return;
        }
        await loadAdminList();
    } catch (error) {
        alert('Connection error. Please try again.');
    }
}

async function deleteUser(userId) {
    if (!confirm('Delete this user?')) return;
    try {
        const response = await fetch(`${API_BASE}/admin/users/${userId}`, {
            method: 'DELETE',
            credentials: 'include'
        });
        const data = await response.json();
        if (!response.ok) {
            alert(data.error || 'Failed to delete user');
            return;
        }
        await loadUserList();
    } catch (error) {
        alert('Connection error. Please try again.');
    }
}

// Toggle password in admin list table
window.toggleListPassword = function (adminId) {
    const input = document.getElementById(`list-pass-${adminId}`);
    const btn = input.nextElementSibling;
    const icon = btn.querySelector('i');

    if (input.type === 'password') {
        input.type = 'text';
        icon.classList.replace('bi-eye', 'bi-eye-slash');
    } else {
        input.type = 'password';
        icon.classList.replace('bi-eye-slash', 'bi-eye');
    }
};

// Service Control functions
async function loadServiceSettings() {
    const tbody = document.getElementById('service-settings-tbody');
    if (!tbody) return;

    try {
        const response = await fetch(`${API_BASE}/admin/service-settings`, {
            credentials: 'include'
        });
        if (!response.ok) throw new Error('Failed to load settings');

        const settings = await response.json();
        renderServiceSettings(settings);
    } catch (error) {
        console.error('Error loading service settings:', error);
        tbody.innerHTML = `<tr><td colspan="4" class="text-center text-danger">Error loading settings: ${error.message}</td></tr>`;
    }
}

function renderServiceSettings(settings) {
    const tbody = document.getElementById('service-settings-tbody');
    if (!tbody) return;

    // Filter settings for appointed admins
    let filteredSettings = settings;
    if (currentUser?.admin_type === 'appointed' && currentUser?.admin_service) {
        filteredSettings = settings.filter(s => s.service_type === currentUser.admin_service);
    }

    if (filteredSettings.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-center">No service settings available.</td></tr>';
        return;
    }

    tbody.innerHTML = filteredSettings.map(setting => {
        const isOpen = !!setting.is_open;
        const limit = setting.daily_limit !== null ? setting.daily_limit : '';

        return `
            <tr>
                <td>
                    <div class="fw-bold">${formatServiceLabel(setting.service_type)}</div>
                    <small class="text-muted">${setting.service_type}</small>
                </td>
                <td>
                    <div class="form-check form-switch">
                        <input class="form-check-input service-status-toggle" type="checkbox" 
                            id="status-${setting.service_type}" 
                            data-service="${setting.service_type}"
                            ${isOpen ? 'checked' : ''}>
                        <label class="form-check-label" for="status-${setting.service_type}">
                            ${isOpen ? '<span class="badge bg-success">Open</span>' : '<span class="badge bg-danger">Closed</span>'}
                        </label>
                    </div>
                </td>
                <td>
                    <div class="input-group input-group-sm" style="max-width: 150px;">
                        <input type="number" class="form-control service-limit-input" 
                            value="${limit}" 
                            placeholder="No limit"
                            data-service="${setting.service_type}"
                            id="limit-${setting.service_type}">
                        <button class="btn btn-outline-secondary save-limit-btn" 
                            type="button" 
                            data-service="${setting.service_type}">
                            <i class="bi bi-save"></i>
                        </button>
                    </div>
                </td>
                <td class="text-end">
                    <button class="btn btn-sm btn-primary apply-settings-btn" data-service="${setting.service_type}">
                        Sync Now
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

// Helper to format service type into readable labels
function formatServiceLabel(serviceType) {
    if (!serviceType) return '';
    return serviceType
        .split('_')
        .map(word => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
}

async function updateServiceSetting(serviceType, updates) {
    try {
        const response = await fetch(`${API_BASE}/admin/service-settings/${serviceType}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify(updates)
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to update setting');
        }

        loadServiceSettings();
    } catch (error) {
        alert(error.message);
    }
}
