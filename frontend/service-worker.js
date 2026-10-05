self.addEventListener("push", e => {
    e.waitUntil(
        self.registration.showNotification("すくすくステップ", {
            body: e.data.text()
        })
    );
});
