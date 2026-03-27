const fs = require('fs');
let appJs = fs.readFileSync('simplified_frontend/js/app.js', 'utf8');

const t1 = "function setupEventListeners() {";
const r1 = `function setupEventListeners() {\n    const regPass = document.getElementById('register-password');
    if (regPass) {
        regPass.addEventListener('input', (e) => {
            const val = e.target.value;
            const reqs = document.getElementById('password-requirements');
            if (reqs) reqs.style.display = 'block';
            
            const check = (id, regex) => {
                const el = document.getElementById(id);
                if (!el) return;
                const icon = el.querySelector('i');
                const passed = regex.test(val);
                if (passed) {
                    el.style.color = '#198754';
                    icon.className = 'bi bi-check-circle-fill text-success me-1';
                } else {
                    el.style.color = '';
                    icon.className = 'bi bi-x-circle text-danger me-1';
                }
            };
            
            check('req-length', /.{8,}/);
            check('req-upper', /[A-Z]/);
            check('req-lower', /[a-z]/);
            check('req-number', /[0-9]/);
            check('req-special', /[!@#$%^&*(),.?":{}|<>\-_+=\\[\\]~\\/]/);
        });
    }`;

const t2 = `const errorDiv = document.getElementById('register-error');\n\n    try {`;
const r2 = `const errorDiv = document.getElementById('register-error');

    const complexityRegex = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\\d)(?=.*[!@#$%^&*(),.?":{}|<>\-_+=\\[\\]~\\/]).{8,}$/;
    if (!complexityRegex.test(formData.password)) {
        errorDiv.textContent = 'Password must meet all security requirements.';
        errorDiv.classList.remove('d-none');
        return;
    }

    try {`;

if (appJs.includes(t1) && appJs.includes(t2)) {
    appJs = appJs.replace(t1, r1);
    appJs = appJs.replace(t2, r2);
    fs.writeFileSync('simplified_frontend/js/app.js', appJs);
    
    let html = fs.readFileSync('simplified_frontend/index.html', 'utf8');
    html = html.replace(/js\\/app\\.js\\?v=\\d+/g, 'js/app.js?v=' + Date.now());
    fs.writeFileSync('simplified_frontend/index.html', html);
    
    console.log("Patched app.js securely.");
} else {
    console.log("Failed to find targets.");
}
