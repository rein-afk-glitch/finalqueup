const fs = require('fs');

let code = fs.readFileSync('simplified_backend/app.py', 'utf8');

// 1. Remove the accidental "priority" from the global transaction history query
code = code.replace(
    /SELECT id, user_name, service_type, queue_number, status, wait_time_minutes, completed_at, 'queue' as type, priority\n                    FROM transaction_history/g,
    "SELECT id, user_name, service_type, queue_number, status, wait_time_minutes, completed_at, 'queue' as type\n                    FROM transaction_history"
);

// 2. Add 'priority' where it ACTUALLY belongs: the get_my_queue command block
code = code.replace(
    /SELECT id, queue_number, service_type, status, estimated_wait_time, wait_time_minutes\n            FROM queue_entries/g,
    "SELECT id, queue_number, service_type, status, estimated_wait_time, wait_time_minutes, priority\n            FROM queue_entries"
);

fs.writeFileSync('simplified_backend/app.py', code);
console.log('SQL patches applied correctly.');
