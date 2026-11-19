/* Web push for a critical alert: shows the notification the server sent and opens the page it names when it is clicked. Nothing is cached here. */
self.addEventListener('push', (event) => {
  let data = { title: 'A.C.O.R.N', body: 'A critical alert needs attention.', url: '/alerts' };
  try {
    if (event.data) data = { ...data, ...event.data.json() };
  } catch (e) {
    /* a message that is not JSON shows the default text */
  }
  event.waitUntil(self.registration.showNotification(data.title, { body: data.body, data: { url: data.url }, tag: 'acorn-critical-alert' }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/alerts';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windows) => {
      for (const w of windows) {
        if ('focus' in w) {
          w.navigate(url);
          return w.focus();
        }
      }
      return self.clients.openWindow(url);
    })
  );
});
