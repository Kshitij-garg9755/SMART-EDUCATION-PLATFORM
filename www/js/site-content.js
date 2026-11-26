(function () {
    "use strict";

    var base = window.KC_API_BASE || "";
    fetch(base + "/api/public/content", { credentials: "include" })
        .then(function (response) {
            if (!response.ok) throw new Error("Unable to load public website content.");
            return response.json();
        })
        .then(function (data) {
            var content = data.content || {};
            document.querySelectorAll("[data-site-content]").forEach(function (element) {
                var key = element.dataset.siteContent;
                if (typeof content[key] === "string" && content[key].trim()) {
                    element.textContent = content[key];
                }
            });
            document.querySelectorAll("[data-site-content-href]").forEach(function (element) {
                var key = element.dataset.siteContentHref;
                var value = content[key];
                if (typeof value !== "string" || !value.trim()) return;
                if (key === "contact_email") {
                    element.setAttribute("href", "mailto:" + value);
                } else if (key.indexOf("social_") === 0 && value.indexOf("https://") === 0) {
                    element.setAttribute("href", value);
                    element.setAttribute("target", "_blank");
                    element.setAttribute("rel", "noopener noreferrer");
                }
            });
            if (data.announcements && data.announcements.length) {
                var banner = document.createElement("section");
                banner.className = "container mt-3";
                banner.setAttribute("aria-live", "polite");
                data.announcements.forEach(function (announcement) {
                    var item = document.createElement("div");
                    item.className = "alert alert-info mb-2";
                    var title = document.createElement("strong");
                    title.textContent = announcement.title;
                    var message = document.createElement("p");
                    message.className = "mb-0 mt-1";
                    message.textContent = announcement.content;
                    item.append(title, message);
                    banner.appendChild(item);
                });
                document.body.insertBefore(banner, document.body.firstChild);
            }
        })
        .catch(function (error) {
            console.error(error);
        });
})();
