self.addEventListener("push", function(event) {
    let data = {
        title: "🔧 Nová porucha stroje",
        body: "Byla nahlášena nová porucha.",
        url: "/hlavni"
    };

    if (event.data) {
        try {
            data = event.data.json();
        } catch (e) {
            data.body = event.data.text();
        }
    }

    const options = {
        body: data.body,
        data: {
            url: data.url || "/hlavni"
        },
        tag: "nova-porucha",
        renotify: true,
        vibrate: [250, 120, 250]
    };

    event.waitUntil(
        self.registration.showNotification(data.title, options)
    );
});


self.addEventListener("notificationclick", function(event) {
    event.notification.close();

    const cil = event.notification.data && event.notification.data.url
        ? event.notification.data.url
        : "/hlavni";

    event.waitUntil(
        clients.matchAll({
            type: "window",
            includeUncontrolled: true
        }).then(function(clientList) {
            for (const client of clientList) {
                if ("focus" in client) {
                    client.navigate(cil);
                    return client.focus();
                }
            }

            if (clients.openWindow) {
                return clients.openWindow(cil);
            }
        })
    );
});
