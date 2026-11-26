(function () {
    "use strict";

    var tickets = [];
    var selectedTicketId = null;
    var socket = null;

    function escapeHtml(value) {
        var element = document.createElement("span");
        element.textContent = value == null ? "" : String(value);
        return element.innerHTML;
    }

    function error(message) {
        document.getElementById("support-error").textContent = message || "";
    }

    function selectedTicket() {
        return tickets.find(function (ticket) { return ticket.id === selectedTicketId; });
    }

    async function refreshTickets() {
        var result = await KCAPI.api("/api/support/tickets");
        tickets = result.tickets || [];
        document.getElementById("support-ticket-list").innerHTML = tickets.length ? tickets.map(function (ticket) {
            return '<button class="btn btn-sm w-100 text-start mb-2 ' +
                (selectedTicketId === ticket.id ? "btn-primary" : "btn-outline-secondary") +
                '" data-ticket-id="' + ticket.id + '"><strong>' + escapeHtml(ticket.subject) +
                "</strong><br><span>" + escapeHtml(ticket.status) + " · unread " +
                escapeHtml(ticket.unread_count) + "</span></button>";
        }).join("") : '<p class="text-muted small mb-0">You have no support requests yet.</p>';
        document.querySelectorAll("[data-ticket-id]").forEach(function (button) {
            button.addEventListener("click", function () {
                selectTicket(Number(button.dataset.ticketId));
            });
        });
        if (selectedTicketId && selectedTicket()) await loadMessages();
    }

    async function selectTicket(ticketId) {
        if (socket && socket.connected && selectedTicketId !== null) {
            socket.emit("support_leave_ticket", { ticket_id: selectedTicketId });
        }
        selectedTicketId = ticketId;
        var subject = selectedTicket();
        document.getElementById("support-conversation-title").textContent =
            subject ? subject.subject : "Your conversation";
        document.getElementById("support-reply").disabled = false;
        document.getElementById("support-attachment").disabled = false;
        document.querySelector("#support-reply-form button").disabled = false;
        if (socket && socket.connected) socket.emit("support_join_ticket", { ticket_id: ticketId });
        await refreshTickets();
    }

    async function loadMessages() {
        if (!selectedTicketId) return;
        var result = await KCAPI.api("/api/support/tickets/" + selectedTicketId + "/messages");
        var container = document.getElementById("support-conversation");
        container.innerHTML = result.messages.length ? result.messages.map(function (message) {
            return '<div class="mb-3"><strong>' + escapeHtml(message.sender_name) +
                '</strong><div class="mt-1" style="white-space:pre-wrap;overflow-wrap:anywhere">' +
                escapeHtml(message.body) + "</div>" +
                (message.attachment_url ? '<a href="' + escapeHtml(message.attachment_url) +
                    '">' + escapeHtml(message.attachment_name) + "</a>" : "") +
                '<small class="d-block text-muted mt-1">' + escapeHtml(message.created_at) + "</small></div>";
        }).join("") : '<p class="text-muted mb-0">No messages in this request.</p>';
        container.scrollTop = container.scrollHeight;
        await KCAPI.api("/api/support/tickets/" + selectedTicketId + "/read", {
            method: "POST", body: JSON.stringify({})
        });
    }

    document.getElementById("support-ticket-form").addEventListener("submit", async function (event) {
        event.preventDefault();
        error("");
        try {
            var result = await KCAPI.api("/api/support/tickets", {
                method: "POST",
                body: JSON.stringify({
                    subject: document.getElementById("support-subject").value,
                    message: document.getElementById("support-first-message").value
                })
            });
            this.reset();
            await refreshTickets();
            await selectTicket(result.ticket.id);
        } catch (failure) { error(failure.message); }
    });

    document.getElementById("support-reply-form").addEventListener("submit", async function (event) {
        event.preventDefault();
        if (!selectedTicketId) return;
        error("");
        var message = document.getElementById("support-reply").value;
        var attachment = document.getElementById("support-attachment").files[0];
        try {
            if (attachment) {
                var formData = new FormData(this);
                await KCAPI.upload("/api/support/tickets/" + selectedTicketId + "/attachments", formData);
                this.reset();
                await loadMessages();
                await refreshTickets();
            } else if (socket && socket.connected) {
                socket.emit("support_send_message", {
                    ticket_id: selectedTicketId, message: message
                }, function (response) {
                    if (response && response.error) {
                        error(response.error);
                        return;
                    }
                    document.getElementById("support-reply-form").reset();
                    loadMessages();
                    refreshTickets();
                });
            } else {
                await KCAPI.api("/api/support/tickets/" + selectedTicketId + "/messages", {
                    method: "POST", body: JSON.stringify({ message: message })
                });
                this.reset();
                await loadMessages();
                await refreshTickets();
            }
        } catch (failure) { error(failure.message); }
    });

    if (window.io) {
        socket = window.io(KCAPI.base || undefined, { withCredentials: true });
        socket.on("connect", function () {
            if (selectedTicketId !== null) socket.emit("support_join_ticket", { ticket_id: selectedTicketId });
        });
        socket.on("support_message", function (message) {
            if (message.ticket_id === selectedTicketId) loadMessages();
            refreshTickets();
        });
        socket.on("support_ticket_updated", function () { refreshTickets(); });
    }

    refreshTickets().catch(function (failure) { error(failure.message); });
})();
