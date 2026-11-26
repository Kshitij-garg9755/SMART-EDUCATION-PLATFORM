(function () {
    "use strict";

    var apiBase = window.KC_API_BASE || "";

    async function getCsrfToken() {
        var response = await fetch(apiBase + "/api/csrf", { credentials: "include" });
        if (!response.ok) throw new Error("Unable to initialize secure form.");
        var data = await response.json();
        return data.csrfToken;
    }

    async function api(path, options) {
        options = options || {};
        options.credentials = "include";
        options.headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
        if (options.method && options.method !== "GET") {
            options.headers["X-CSRFToken"] = await getCsrfToken();
        }
        var response = await fetch(apiBase + path, options);
        var data = await response.json().catch(function () { return {}; });
        if (!response.ok) {
            throw new Error(data.error || data.message || "Request failed.");
        }
        return data;
    }

    async function upload(path, formData) {
        var headers = { "X-CSRFToken": await getCsrfToken() };
        var response = await fetch(apiBase + path, {
            method: "POST",
            credentials: "include",
            headers: headers,
            body: formData
        });
        var data = await response.json().catch(function () { return {}; });
        if (!response.ok) throw new Error(data.error || data.message || "Upload failed.");
        return data;
    }

    window.KCAPI = { api: api, upload: upload, base: apiBase };
})();
