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
let hasNotifiedFiveAway = false;
let lastNotifiedQueueId = null;
let hasVibratedForCalled = false;
let lastVibratedCalledQueueId = null;
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

// Initialize app
document.addEventListener('DOMContentLoaded', function() {
    checkAuthStatus();
    setupEventListeners();
});

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
    document.getElementById('login-page').classList.remove('d-none');
    document.getElementById('admin-dashboard').classList.add('d-none');
    document.getElementById('student-dashboard').classList.add('d-none');
    stopPolling();
}

// Show dashboard based on role
function showDashboard(role) {
    document.getElementById('login-page').classList.add('d-none');
    
    if (role === 'admin') {
        document.getElementById('admin-dashboard').classList.remove('d-none');
        document.getElementById('student-dashboard').classList.add('d-none');
        const roleLabel = isStaticAdmin()
            ? 'Static Admin'
            : `${formatAdminServiceLabel(currentUser.admin_service)} Admin`;
        document.getElementById('admin-user-name').textContent = `${currentUser.name} (${roleLabel})`;
        configureAdminView();
        loadAdminDashboard();
    } else {
        document.getElementById('student-dashboard').classList.remove('d-none');
        document.getElementById('admin-dashboard').classList.add('d-none');
        // Put user name in the navbar title (replaces "Student Portal")
        const titleEl = document.getElementById('student-navbar-title');
        if (titleEl) titleEl.textContent = currentUser.name || 'Student';

        // Hide the old right-side name (kept for compatibility, but not used)
        const rightNameEl = document.getElementById('student-user-name');
        if (rightNameEl) rightNameEl.classList.add('d-none');

        loadStudentDashboard();
    }
}

// Setup event listeners
function setupEventListeners() {
    // Login form
    document.getElementById('login-form').addEventListener('submit', handleLogin);
    
    // Register form
    document.getElementById('register-form').addEventListener('submit', handleRegister);

    // Create admin form (static admin only)
    const createAdminForm = document.getElementById('create-admin-form');
    if (createAdminForm) {
        createAdminForm.addEventListener('submit', handleCreateAdmin);
    }

    // Analytics tab and period
    const analyticsTabEl = document.getElementById('analytics-tab');
    const analyticsPanelEl = document.getElementById('analytics-panel');
    if (analyticsTabEl && analyticsPanelEl) {
        document.getElementById('admin-tabs')?.addEventListener('shown.bs.tab', (e) => {
            if (e.target.id === 'analytics-tab') loadAdminAnalytics();
        });
        const periodSelect = document.getElementById('analytics-period');
        if (periodSelect) {
            periodSelect.addEventListener('change', loadAdminAnalytics);
        }
    }
    
    // Join queue form
    document.getElementById('join-queue-form').addEventListener('submit', handleJoinQueue);
    
    // Verification form
    document.getElementById('verification-form').addEventListener('submit', handleVerification);
    
    // Service selection buttons (mobile-friendly) + student office filters
    document.addEventListener('click', function(e) {
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

        // Filter button clicks (admin dashboard)
        if (e.target.closest('.filter-btn')) {
            const filterBtn = e.target.closest('.filter-btn');
            if (filterBtn.disabled) return;
            const filterValue = filterBtn.dataset.filter;
            
            // Remove active class from all filter buttons
            document.querySelectorAll('.filter-btn').forEach(btn => {
                btn.classList.remove('active');
            });
            
            // Add active class to clicked button
            filterBtn.classList.add('active');
            
            // Load queue list with filter
            loadQueueListWithFilter(filterValue);
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
    });
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
    if (isStaticAdmin()) {
        loadHistory();
        return;
    }

    loadAdminStats();
    loadQueueList();
    loadHistory();

    // Start polling
    statsPollInterval = setInterval(loadAdminStats, 5000);
    queuePollInterval = setInterval(loadQueueList, 3000);
}

function configureAdminView() {
    const adminManagementTab = document.getElementById('admin-management-tab');
    const adminManagementSection = document.getElementById('admin-management-section');
    const adminStatsRow = document.getElementById('admin-stats-row');
    const queueTab = document.getElementById('queue-tab');
    const queuePanel = document.getElementById('queue-panel');
    const analyticsTab = document.getElementById('analytics-tab');
    const analyticsPanel = document.getElementById('analytics-panel');
    if (isStaticAdmin()) {
        if (adminManagementTab) adminManagementTab.classList.remove('d-none');
        if (adminManagementSection) adminManagementSection.classList.remove('d-none');
        if (analyticsTab) analyticsTab.classList.remove('d-none');
        if (analyticsPanel) analyticsPanel.classList.remove('d-none');
        if (adminStatsRow) adminStatsRow.classList.add('d-none');
        if (queueTab) queueTab.classList.add('d-none');
        if (queuePanel) queuePanel.classList.add('d-none');
        if (queueTab) queueTab.classList.remove('active');
        if (queuePanel) queuePanel.classList.remove('show', 'active');
        const historyTab = document.getElementById('history-tab');
        const historyPanel = document.getElementById('history-panel');
        if (historyTab) historyTab.classList.remove('active');
        if (historyPanel) historyPanel.classList.remove('show', 'active');
        if (adminManagementTab) adminManagementTab.classList.add('active');
        const adminManagementPanel = document.getElementById('admin-management-panel');
        if (adminManagementPanel) adminManagementPanel.classList.add('show', 'active');
        loadAdminManagement();
    } else {
        if (adminManagementTab) adminManagementTab.classList.add('d-none');
        if (adminManagementSection) adminManagementSection.classList.add('d-none');
        if (analyticsTab) analyticsTab.classList.add('d-none');
        if (analyticsPanel) analyticsPanel.classList.add('d-none');
        if (adminStatsRow) adminStatsRow.classList.remove('d-none');
        if (queueTab) queueTab.classList.remove('d-none');
        if (queuePanel) queuePanel.classList.remove('d-none');
        if (adminManagementTab) adminManagementTab.classList.remove('active');
        const adminManagementPanel = document.getElementById('admin-management-panel');
        if (adminManagementPanel) adminManagementPanel.classList.remove('show', 'active');
        if (queueTab) queueTab.classList.add('active');
        if (queuePanel) queuePanel.classList.add('show', 'active');
    }

    const assignedService = currentUser?.admin_service;
    const filterButtons = Array.from(document.querySelectorAll('.filter-btn'));
    const statsCards = Array.from(document.querySelectorAll('[data-service]'));
    if (!isStaticAdmin() && assignedService) {
        filterButtons.forEach(btn => {
            const filterValue = btn.dataset.filter || '';
            const isAssigned = filterValue === assignedService;
            btn.classList.toggle('active', isAssigned);
            btn.disabled = !isAssigned;
            btn.classList.toggle('d-none', !isAssigned);
        });

        statsCards.forEach(card => {
            card.classList.toggle('d-none', card.dataset.service !== assignedService);
        });
    } else {
        filterButtons.forEach(btn => {
            btn.disabled = false;
            btn.classList.remove('d-none');
        });
        statsCards.forEach(card => {
            card.classList.remove('d-none');
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
    const periodEl = document.getElementById('analytics-period');
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

// Switch student view to the Join Queue panel (Now Serving + My Queue)
function switchToStudentJoinQueuePanel() {
    const tabEl = document.getElementById('join-queue-tab');
    if (tabEl && typeof bootstrap !== 'undefined' && bootstrap.Tab) {
        const tab = bootstrap.Tab.getOrCreateInstance(tabEl);
        tab.show();
    }
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

// Request notification permission (for 5-away alert)
function requestNotificationPermission() {
    if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission();
    }
}

// Parse numeric part from queue number (e.g. "AF10" -> 10, "PY01" -> 1)
function parseQueueNumber(queueNumber) {
    if (queueNumber == null) return null;
    const s = typeof queueNumber === 'string' ? queueNumber : String(queueNumber);
    const match = s.match(/(\d+)$/);
    return match ? parseInt(match[1], 10) : null;
}

// Check if user is 5 away and trigger notification (no duplicates)
function checkQueuePositionNotification(myQueue, servingData) {
    if (!myQueue || !servingData) return;

    // Reset notification state when user leaves queue or gets called/serving
    if (myQueue.status !== 'waiting') {
        hasNotifiedFiveAway = false;
        lastNotifiedQueueId = null;
        hasVibratedForCalled = false;
        lastVibratedCalledQueueId = null;
        return;
    }

    const service = myQueue.service_type;
    const serviceInfo = servingData[service];
    if (!serviceInfo || !serviceInfo.serving || serviceInfo.serving.length === 0) return;

    const currentServing = serviceInfo.serving[0];
    const currentQueueNumberRaw = currentServing?.queue_number;
    const currentNumber = parseQueueNumber(currentQueueNumberRaw);
    const myNumber = parseQueueNumber(myQueue.queue_number);
    const myQueueNumberRaw = (myQueue.queue_number || '').toString().trim();

    // User's number is called / being served — vibrate once (compare by string and by numeric part)
    const isMyNumberCalled = myQueueNumberRaw && (
        myQueueNumberRaw === (currentQueueNumberRaw || '').toString().trim() ||
        (currentNumber != null && myNumber != null && myNumber <= currentNumber)
    );
    if (isMyNumberCalled && myQueue.id !== lastVibratedCalledQueueId) {
        hasVibratedForCalled = true;
        lastVibratedCalledQueueId = myQueue.id;
        triggerCalledNotification(myQueue.queue_number, formatServiceLabel(service));
        return;
    }
    if (currentNumber != null && myNumber != null && myNumber <= currentNumber) return;

    const positionAway = currentNumber != null && myNumber != null ? myNumber - currentNumber : 1;

    // User is 5 away - notify once per queue session
    if (positionAway === 5 && myQueue.id !== lastNotifiedQueueId) {
        hasNotifiedFiveAway = true;
        lastNotifiedQueueId = myQueue.id;
        triggerFiveAwayNotification(myQueue.queue_number, formatServiceLabel(service));
    }
}

// Vibrate and notify when user's number is called
function triggerCalledNotification(queueNumber, serviceLabel) {
    const title = "You're up!";
    const body = `Queue ${queueNumber} (${serviceLabel}) — your number was called. Please proceed.`;

    if ('Notification' in window && Notification.permission === 'granted') {
        try {
            new Notification(title, { body, icon: 'images/university-logo.png' });
        } catch (_) {
            new Notification(title, { body });
        }
    }

    // Vibration (works on Android; often ignored on iOS/desktop without user gesture)
    try {
        if (typeof navigator !== 'undefined' && navigator.vibrate) {
            navigator.vibrate([400, 150, 400, 150, 400]);
        }
    } catch (_) {}

    // In-app alert so user always sees feedback (e.g. when vibration is blocked or unsupported)
    showCalledInAppAlert(queueNumber, serviceLabel);
}

// In-app "You're up!" alert when number is called (always shown)
function showCalledInAppAlert(queueNumber, serviceLabel) {
    const statusDiv = document.getElementById('my-queue-status');
    if (!statusDiv) return;
    const alert = document.createElement('div');
    alert.className = 'alert alert-success alert-dismissible fade show d-flex align-items-center';
    alert.setAttribute('role', 'alert');
    alert.innerHTML = `
        <i class="bi bi-telephone-fill me-2" style="font-size: 1.5rem;"></i>
        <div class="flex-grow-1">
            <strong>You're up!</strong> Queue ${queueNumber} — your number was called. Please proceed to ${serviceLabel}.
        </div>
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;
    statusDiv.insertAdjacentElement('afterend', alert);
    setTimeout(() => alert.remove(), 20000);
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
            
            // Direct user to Now Serving / My Queue section so they see they joined
            switchToStudentJoinQueuePanel();
            setTimeout(() => {
                const el = document.getElementById('my-queue-status');
                if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }, 100);
            // Refresh queue status after a moment so their number appears
            setTimeout(() => {
                loadMyQueue();
                const el = document.getElementById('my-queue-status');
                if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
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
    const resultDiv = document.getElementById('verification-result');
    
    if (!fileInput.files[0]) {
        alert('Please select a file');
        return;
    }
    
    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    formData.append('reference_number', referenceNumber);
    formData.append('account_number', accountNumber);
    
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
    hasNotifiedFiveAway = false;
    lastNotifiedQueueId = null;
    hasVibratedForCalled = false;
    lastVibratedCalledQueueId = null;
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
    try {
        const response = await fetch(`${API_BASE}/admin/admins`, {
            credentials: 'include'
        });
        const data = await response.json();
        if (!response.ok) {
            tbody.innerHTML = `<tr><td colspan="6" class="text-center">${data.error || 'Failed to load admins'}</td></tr>`;
            return;
        }
        tbody.innerHTML = data.map(admin => {
            const isStatic = admin.admin_type === 'static';
            const roleSelect = isStatic
                ? `<span class="badge bg-secondary">Protected</span>`
                : `
                    <select class="form-select form-select-sm" id="admin-role-${admin.id}">
                        ${SERVICE_TYPES.map(service => `
                            <option value="${service}" ${admin.admin_service === service ? 'selected' : ''}>${formatServiceLabel(service)}</option>
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
            return `
                <tr>
                    <td>${admin.name}</td>
                    <td>${admin.email}</td>
                    <td>${isStatic ? 'Static' : 'Appointed'}</td>
                    <td>${roleSelect}</td>
                    <td>${admin.created_at ? new Date(admin.created_at).toLocaleString() : '-'}</td>
                    <td>${actions}</td>
                </tr>
            `;
        }).join('');
    } catch (error) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center">Connection error</td></tr>';
    }
}

async function loadUserList() {
    const tbody = document.getElementById('user-list-tbody');
    if (!tbody) return;
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
    if (!adminService) return;
    try {
        const response = await fetch(`${API_BASE}/admin/admins/${adminId}`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'include',
            body: JSON.stringify({ admin_service: adminService })
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
