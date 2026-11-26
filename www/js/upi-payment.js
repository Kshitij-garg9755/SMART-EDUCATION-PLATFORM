(function () {
    "use strict";

    var paymentId = new URLSearchParams(window.location.search).get("id");
    var timer = null;
    var checking = false;
    var terminalStatuses = ["captured", "expired", "failed"];

    function safeHttpUrl(value) {
        try {
            var url = new URL(value, window.location.origin);
            return url.protocol === "https:" || url.protocol === "http:" ? url.href : "";
        } catch (error) {
            return "";
        }
    }

    function showError(message) {
        var element = document.getElementById("upi-payment-error");
        element.textContent = message;
        element.classList.remove("d-none");
    }

    function render(payment) {
        document.getElementById("upi-payment-loading").classList.add("d-none");
        document.getElementById("upi-payment-content").classList.remove("d-none");
        document.getElementById("upi-course-title").textContent = payment.course_title;
        document.getElementById("upi-student-name").textContent = payment.student_name;
        document.getElementById("upi-amount").textContent =
            payment.currency + " " + payment.amount;
        document.getElementById("upi-reference").textContent =
            payment.gateway_order_id || ("KC-UPI-" + payment.id);
        document.getElementById("upi-expiry").textContent = payment.expires_at ?
            new Date(payment.expires_at).toLocaleString() : "Not available";

        var thumbnail = safeHttpUrl(payment.course_thumbnail);
        if (thumbnail) {
            var image = document.getElementById("upi-course-thumbnail");
            image.src = thumbnail;
            image.alt = payment.course_title;
            image.classList.remove("d-none");
        }
        if (payment.environment === "sandbox") {
            document.getElementById("upi-environment-warning").classList.remove("d-none");
        }
        var qr = safeHttpUrl(payment.qr_url);
        if (qr) {
            document.getElementById("upi-qr").src = qr;
            document.getElementById("upi-qr").classList.remove("d-none");
            document.getElementById("upi-checkout-hint").textContent =
                "Scan this dynamic QR code with your UPI app.";
        }
        if (typeof payment.upi_intent === "string" &&
                payment.upi_intent.indexOf("upi://pay?") === 0) {
            var intent = document.getElementById("upi-open-app");
            intent.href = payment.upi_intent;
            intent.classList.remove("d-none");
        }
        var checkout = safeHttpUrl(payment.checkout_url);
        if (checkout) {
            var hosted = document.getElementById("upi-hosted-checkout");
            hosted.href = checkout;
            hosted.classList.remove("d-none");
            if (!qr) {
                document.getElementById("upi-checkout-hint").textContent =
                    "Continue to the gateway's secure hosted payment page.";
            }
        }

        var messages = {
            processing: "Preparing your payment order…",
            pending: "Awaiting payment. Course access starts only after verified payment.",
            under_review: "Payment is under review by the gateway. Course access is not active yet.",
            captured: payment.environment === "sandbox" ?
                "Sandbox payment verified for testing. No course access was activated." :
                "Payment successful. Your course access is active.",
            expired: "Payment expired. Return to your dashboard to start a new payment.",
            failed: "Payment failed. Return to your dashboard to try again."
        };
        document.getElementById("upi-status").textContent =
            messages[payment.status] || "Payment status: " + payment.status;
        if (payment.course_url && payment.environment === "live" &&
                payment.status === "captured") {
            var courseLink = document.getElementById("upi-open-course");
            courseLink.href = payment.course_url;
            courseLink.classList.remove("d-none");
        }
        if (payment.receipt_url) {
            var receipt = document.getElementById("upi-receipt");
            receipt.href = payment.receipt_url;
            receipt.classList.remove("d-none");
        }
        document.getElementById("upi-check-status").disabled =
            terminalStatuses.indexOf(payment.status) !== -1;
        if (terminalStatuses.indexOf(payment.status) !== -1 && timer) {
            window.clearInterval(timer);
            timer = null;
        }
    }

    async function checkStatus(showFailure) {
        if (checking) return;
        checking = true;
        try {
            var result = await KCAPI.api("/api/payments/upi/" +
                encodeURIComponent(paymentId) + "/check", {
                    method: "POST",
                    body: JSON.stringify({})
                });
            render(result.payment);
            document.getElementById("upi-payment-error").classList.add("d-none");
        } catch (error) {
            if (showFailure) showError(error.message);
        } finally {
            checking = false;
        }
    }

    async function start() {
        if (!paymentId || !/^\d+$/.test(paymentId)) {
            showError("A valid payment reference is required.");
            document.getElementById("upi-payment-loading").classList.add("d-none");
            return;
        }
        try {
            var result = await KCAPI.api("/api/payments/upi/" + encodeURIComponent(paymentId));
            render(result.payment);
            if (terminalStatuses.indexOf(result.payment.status) === -1) {
                await checkStatus(false);
                timer = window.setInterval(function () { checkStatus(false); }, 20000);
            }
        } catch (error) {
            document.getElementById("upi-payment-loading").classList.add("d-none");
            showError(error.message);
        }
    }

    document.getElementById("upi-check-status").addEventListener("click", function () {
        checkStatus(true);
    });
    start();
})();
