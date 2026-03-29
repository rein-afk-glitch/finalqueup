const fs = require('fs');

let code = fs.readFileSync('simplified_frontend/js/app.js', 'utf8');

const endpointsToBust = [
    '/transactions/history',
    '/queue/my-queue',
    '/admin/queues',
    '/admin/services',
    '/auth/me'
];

endpointsToBust.forEach(endpoint => {
    // We look for EXACTLY \`\${API_BASE}endpoint\`
    const escapeEndpoint = endpoint.replace(/\\//g, '\\/');
    const regex = new RegExp(\`\\\\\\\`\\\\\\\\\\$\\\\{API_BASE\\\\}\${escapeEndpoint}\\\\\\\`\`, 'g');
    code = code.replace(regex, \`\\\`\\\${API_BASE}\${endpoint}?t=\\\${Date.now()}\\\`\`);
});

fs.writeFileSync('simplified_frontend/js/app.js', code);

// Bump HTML cache again just to ensure the new JS downloads
let html = fs.readFileSync('simplified_frontend/index.html', 'utf8');
html = html.replace(/js\/app\.js\?v=\d+/g, 'js/app.js?v=' + Date.now());
fs.writeFileSync('simplified_frontend/index.html', html);

console.log('Applied GET fetch cache busting.');
