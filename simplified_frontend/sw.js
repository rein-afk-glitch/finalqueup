/* eslint-disable no-undef */
self.addEventListener('message', (event) => {
    const data = event.data || {};
    if (data.type !== 'show-notification') return;
    const title = data.title || 'Queue Update';
    const options = data.options || {};
    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('push', (event) => {
    let payload = {};
    if (event.data) {
        try {
            payload = event.data.json();
        } catch (_) {
            payload = { body: event.data.text() };
        }
    }
    const title = payload.title || 'Queue Update';
    const options = {
        body: payload.body || 'You have a new queue update.',
        icon: payload.icon || 'images/university-logo.png',
        tag: payload.tag,
        renotify: true,
        data: { url: payload.url || '/' }
    };
    if (payload.vibrate) {
        options.vibrate = payload.vibrate;
    }
    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const targetUrl = event.notification?.data?.url || '/';
    event.waitUntil(
        self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
            for (const client of clients) {
                if ('focus' in client) {
                    client.navigate(targetUrl);
                    return client.focus();
                }
            }
            if (self.clients.openWindow) {
                return self.clients.openWindow(targetUrl);
            }
            return null;
        })
    );
});
