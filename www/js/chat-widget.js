(function () {
    "use strict";

    if (document.getElementById("chatShell")) return;

    fetch("/api/auth/me", {credentials: "include"})
        .then(function (response) {
            if (response.status === 401) return null;
            if (!response.ok) throw new Error("Unable to load the student profile.");
            return response.json();
        })
        .then(function (data) {
            if (!data || !data.authenticated || !data.user || data.user.role !== "student") return;
            createWidget();
        })
        .catch(function (error) {
            console.error("KHITIJ CHAT widget could not start:", error);
        });

    function createWidget() {
        var stylesheet = document.createElement("link");
        stylesheet.rel = "stylesheet";
        stylesheet.href = "/css/chat-widget.css";
        document.head.appendChild(stylesheet);

        document.querySelectorAll('a[href="login.html"]').forEach(function (link) {
            link.href = "dashboard.html";
            link.title = "Student profile";
            link.setAttribute("aria-label", "Student profile");
        });

        var widget = document.createElement("div");
        widget.className = "kc-chat-widget";

        var toggle = document.createElement("button");
        toggle.className = "kc-chat-toggle";
        toggle.type = "button";
        toggle.setAttribute("aria-label", "Open KHITIJ CHAT");
        toggle.setAttribute("aria-controls", "kc-chat-panel");
        toggle.setAttribute("aria-expanded", "false");
        toggle.title = "Open KHITIJ CHAT";
        toggle.appendChild(createChatIcon());

        var panel = document.createElement("section");
        panel.className = "kc-chat-panel";
        panel.id = "kc-chat-panel";
        panel.setAttribute("role", "dialog");
        panel.setAttribute("aria-label", "KHITIJ CHAT");
        panel.hidden = true;

        var header = document.createElement("header");
        header.className = "kc-chat-panel-header";
        var title = document.createElement("div");
        title.className = "kc-chat-panel-title";
        var name = document.createElement("strong");
        name.textContent = "KHITIJ CHAT";
        var subtitle = document.createElement("span");
        subtitle.textContent = "Student conversations";
        title.append(name, subtitle);

        var close = document.createElement("button");
        close.className = "kc-chat-close";
        close.type = "button";
        close.textContent = "×";
        close.setAttribute("aria-label", "Close KHITIJ CHAT");
        header.append(title, close);

        var frame = document.createElement("iframe");
        frame.className = "kc-chat-frame";
        frame.title = "KHITIJ CHAT student conversations";
        frame.loading = "lazy";
        panel.append(header, frame);
        widget.append(panel, toggle);
        document.body.appendChild(widget);

        function openWidget() {
            panel.hidden = false;
            toggle.setAttribute("aria-expanded", "true");
            if (!frame.src) frame.src = "/chat.html?widget=1";
            close.focus();
        }

        function closeWidget() {
            panel.hidden = true;
            toggle.setAttribute("aria-expanded", "false");
            toggle.focus();
        }

        toggle.addEventListener("click", function () {
            if (panel.hidden) openWidget();
            else closeWidget();
        });
        close.addEventListener("click", closeWidget);
        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape" && !panel.hidden) closeWidget();
        });
        document.querySelectorAll('a[href="chat.html"]').forEach(function (link) {
            link.addEventListener("click", function (event) {
                event.preventDefault();
                openWidget();
            });
        });
    }

    function createChatIcon() {
        var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", "0 0 24 24");
        svg.setAttribute("aria-hidden", "true");
        var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("d", "M20.5 11.5a8.5 8.5 0 0 1-12.6 7.4L3 20l1.2-4.6A8.5 8.5 0 1 1 20.5 11.5Z");
        path.setAttribute("fill", "none");
        path.setAttribute("stroke", "currentColor");
        path.setAttribute("stroke-linecap", "round");
        path.setAttribute("stroke-linejoin", "round");
        path.setAttribute("stroke-width", "1.8");
        svg.appendChild(path);
        return svg;
    }
})();
