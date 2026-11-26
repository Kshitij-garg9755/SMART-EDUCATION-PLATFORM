(function () {
    "use strict";

    function escapeHtml(value) {
        var element = document.createElement("span");
        element.textContent = value == null ? "" : String(value);
        return element.innerHTML;
    }

    function setError(message) {
        document.getElementById("payment-error").textContent = message || "";
    }

    function renderHistory(payments) {
        var container = document.getElementById("payment-history");
        if (!payments.length) {
            container.innerHTML = '<p class="text-muted mb-0">No payment requests yet.</p>';
            return;
        }
        container.innerHTML = '<div class="table-responsive"><table class="table align-middle"><thead><tr>' +
            "<th>Course</th><th>Amount</th><th>Status</th><th>Reference</th><th>Submitted</th><th>Action</th>" +
            "</tr></thead><tbody>" + payments.map(function (payment) {
                var action = "—";
                if (payment.provider === "upi_gateway" &&
                    ["processing", "pending", "under_review"].indexOf(payment.status) !== -1) {
                    action = '<a class="btn btn-sm btn-outline-primary" href="/upi-payment.html?id=' +
                        encodeURIComponent(payment.id) + '">Open payment</a>';
                } else if (payment.receipt_url) {
                    action = '<a class="btn btn-sm btn-outline-primary" href="' +
                        escapeHtml(payment.receipt_url) + '">Download receipt</a>';
                }
                return "<tr><td>" + escapeHtml(payment.course_title) + "</td><td>₹" +
                    escapeHtml(payment.amount) + "</td><td>" +
                    escapeHtml(payment.status) + "</td><td>" +
                    escapeHtml(payment.transaction_reference || payment.gateway_order_id ||
                        payment.remarks || "—") + "</td><td>" +
                    escapeHtml(payment.created_at || "—") + "</td><td>" + action + "</td></tr>";
            }).join("") + "</tbody></table></div>";
    }

    async function refreshHistory() {
        var result = await KCAPI.api("/api/payments/mine");
        renderHistory(result.payments);
    }

    Promise.all([
        KCAPI.api("/api/courses"),
        KCAPI.api("/api/public/content"),
        refreshHistory()
    ]).then(function (results) {
        var courses = results[0].courses.filter(function (course) {
            return Number(course.price) > 0;
        });
        var select = document.getElementById("payment-course");
        var onlineSelect = document.getElementById("upi-payment-course");
        select.innerHTML = courses.length ? courses.map(function (course) {
            return '<option value="' + course.id + '">' + escapeHtml(course.title) +
                " — ₹" + escapeHtml(course.price) + "</option>";
        }).join("") : '<option value="">No paid courses currently available</option>';
        onlineSelect.innerHTML = select.innerHTML;
        select.disabled = !courses.length;
        onlineSelect.disabled = !courses.length;
        if (results[1].content.payment_instructions) {
            document.getElementById("payment-instructions").textContent =
                results[1].content.payment_instructions;
        }
        document.getElementById("manual-payment-form").querySelector("button[type=submit]").disabled =
            !courses.length;
        document.getElementById("upi-checkout-form").querySelector("button[type=submit]").disabled =
            !courses.length;
    }).catch(function (error) {
        setError(error.message);
        document.getElementById("upi-payment-error").textContent = error.message;
    });

    document.getElementById("upi-checkout-form").addEventListener("submit", async function (event) {
        event.preventDefault();
        var error = document.getElementById("upi-payment-error");
        error.textContent = "";
        var button = this.querySelector("button[type=submit]");
        button.disabled = true;
        try {
            var result = await KCAPI.api("/api/payments/upi/orders", {
                method: "POST",
                body: JSON.stringify({
                    course_id: Number(document.getElementById("upi-payment-course").value)
                })
            });
            window.location.href = "/upi-payment.html?id=" + encodeURIComponent(result.payment.id);
        } catch (requestError) {
            error.textContent = requestError.message;
        } finally {
            button.disabled = !document.getElementById("upi-payment-course").value;
        }
    });

    document.getElementById("manual-payment-form").addEventListener("submit", async function (event) {
        event.preventDefault();
        setError("");
        var form = this;
        var proof = document.getElementById("payment-proof").files[0];
        if (proof && proof.size > 5 * 1024 * 1024) {
            setError("Payment proof must be 5 MB or smaller.");
            return;
        }
        try {
            await KCAPI.upload("/api/payments/manual", new FormData(form));
            form.reset();
            await refreshHistory();
            setError("");
        } catch (error) {
            setError(error.message);
        }
    });
})();
