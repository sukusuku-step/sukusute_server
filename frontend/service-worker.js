self.addEventListener("push", e => {
    e.waitUntil(
        self.registration.showNotification("すくすくステップ", {
            body: event.data.text()
        });
    );
});
