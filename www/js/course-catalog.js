(function () {
    "use strict";

    function escapeHtml(value) {
        return String(value == null ? "" : value).replace(/[&<>"']/g, function (character) {
            return {
                "&": "&amp;",
                "<": "&lt;",
                ">": "&gt;",
                "\"": "&quot;",
                "'": "&#39;"
            }[character];
        });
    }

    function imageUrl(value) {
        if (typeof value !== "string" || !value.trim()) return "/img/course-1.jpg";
        try {
            var url = new URL(value, window.location.origin);
            if ((url.protocol === "http:" || url.protocol === "https:") &&
                    url.origin === window.location.origin) {
                return url.href;
            }
        } catch (error) {
            return "/img/course-1.jpg";
        }
        return "/img/course-1.jpg";
    }

    function playerUrl(courseId) {
        return "/courses-videos/videos.html?course_id=" + encodeURIComponent(courseId);
    }

    function actionMarkup(course) {
        if (course.enrolled) {
            return '<a class="btn btn-success w-100" href="' +
                playerUrl(course.id) + '">Continue learning</a>';
        }
        var action = Number(course.price) > 0 ? "buy" : "enroll";
        var label = action === "buy" ? "Buy with UPI" : "Enroll free";
        return '<button class="btn btn-primary w-100" type="button" data-course-action="' +
            action + '" data-course-id="' + escapeHtml(course.id) + '">' + label + "</button>" +
            '<p class="small text-danger mt-2 mb-0" data-course-error role="alert"></p>';
    }

    function cardMarkup(course) {
        var price = Number(course.price) || 0;
        var priceLabel = price > 0 ?
            "&#8377;" + price.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) :
            "Free";
        var level = course.level ? escapeHtml(course.level) : "All levels";
        var category = course.category ? escapeHtml(course.category) : "General";
        var duration = course.course_duration ? escapeHtml(course.course_duration) : "Self-paced";
        var description = course.description ? escapeHtml(course.description) : "Learn at your own pace.";
        var badge = price > 0 ? "PAID" : "FREE";

        return '<div class="col-lg-3 col-md-6" data-course-card>' +
            '<article class="course-item shadow h-100 d-flex flex-column">' +
            '<div class="position-relative overflow-hidden text-light image">' +
            '<img class="img-fluid w-100" src="' + escapeHtml(imageUrl(course.thumbnail)) +
            '" alt="' + escapeHtml(course.title) + '" loading="lazy">' +
            '<span class="px-2 py-1 fw-bold text-uppercase" style="position:absolute;top:15px;left:16px;' +
            'font-size:12px;border-radius:3px;background-color:' +
            (price > 0 ? "#0ed44c" : "#fb873f") + '">' + badge + "</span></div>" +
            '<div class="p-3 pb-2 flex-grow-1"><span class="small text-primary">' +
            category + "</span><h2 class=\"h5 mt-2 mb-2\">" + escapeHtml(course.title) +
            "</h2><p class=\"small text-muted mb-0\">" + description + "</p></div>" +
            '<div class="d-flex border-top py-2">' +
            '<small class="flex-fill text-center px-1"><i class="fa fa-book me-1"></i>' +
            escapeHtml(course.lesson_count || 0) + " lessons</small>" +
            '<small class="flex-fill text-center px-1"><i class="fa fa-user me-1"></i>' +
            level + "</small></div>" +
            '<div class="d-flex align-items-center justify-content-between p-3 pt-2">' +
            '<span class="small text-muted"><i class="fa fa-clock me-1"></i>' +
            duration + "</span><strong>" + priceLabel + "</strong></div>" +
            '<div class="px-3 pb-3 mt-auto">' + actionMarkup(course) + "</div>" +
            "</article></div>";
    }

    function showError(element, message, offerLogin) {
        var error = element.querySelector("[data-course-error]");
        if (!error) return;
        error.textContent = message;
        if (offerLogin) {
            var link = document.createElement("a");
            link.href = "/login.html";
            link.textContent = " Log in";
            error.appendChild(link);
        }
    }

    async function handleAction(button) {
        var card = button.closest("[data-course-card]");
        var courseId = button.getAttribute("data-course-id");
        var action = button.getAttribute("data-course-action");
        button.disabled = true;
        button.textContent = action === "buy" ? "Opening secure checkout…" : "Enrolling…";
        try {
            if (action === "buy") {
                var order = await KCAPI.api("/api/payments/upi/orders", {
                    method: "POST",
                    body: JSON.stringify({ course_id: Number(courseId) })
                });
                window.location.href = "/upi-payment.html?id=" +
                    encodeURIComponent(order.payment.id);
                return;
            }
            await KCAPI.api("/api/courses/" + encodeURIComponent(courseId) + "/enroll", {
                method: "POST",
                body: JSON.stringify({})
            });
            window.location.href = playerUrl(courseId);
        } catch (error) {
            var needsLogin = /authentication required|student account required/i.test(error.message);
            showError(
                card,
                needsLogin ? "Please sign in with a student account to continue." : error.message,
                needsLogin
            );
            button.disabled = false;
            button.textContent = action === "buy" ? "Buy with UPI" : "Enroll free";
        }
    }

    async function loadCatalog(element) {
        element.setAttribute("aria-live", "polite");
        element.innerHTML = '<div class="col-12 text-center text-muted py-4">Loading courses…</div>';
        try {
            var data = await KCAPI.api("/api/courses");
            var courses = Array.isArray(data.courses) ? data.courses : [];
            var limit = parseInt(element.getAttribute("data-course-limit") || "", 10);
            if (limit > 0) courses = courses.slice(0, limit);
            if (!courses.length) {
                element.innerHTML = '<div class="col-12 text-center text-muted py-4">' +
                    "No published courses are available yet.</div>";
                return;
            }
            element.innerHTML = courses.map(cardMarkup).join("");
            element.addEventListener("click", function (event) {
                var button = event.target.closest("[data-course-action]");
                if (button && element.contains(button)) handleAction(button);
            });
        } catch (error) {
            element.innerHTML = '<div class="col-12"><div class="alert alert-danger" role="alert">' +
                "Courses could not be loaded. " + escapeHtml(error.message) +
                '</div><button class="btn btn-outline-primary" type="button" data-retry>Try again</button></div>';
            element.addEventListener("click", function (event) {
                if (event.target.closest("[data-retry]")) loadCatalog(element);
            }, { once: true });
        }
    }

    document.querySelectorAll("[data-course-catalog]").forEach(loadCatalog);
})();
