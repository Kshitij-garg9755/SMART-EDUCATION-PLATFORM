(function () {
    "use strict";

    var permissions = [];
    var activeTicket = null;
    var supportTickets = [];
    var adminUserId = null;
    var supportSocket = null;
    var joinedTicket = null;
    var adminRoles = [];
    var alertTimer;
    var views = {
        dashboard: loadDashboard,
        students: loadStudents,
        courses: loadCourses,
        categories: loadCategories,
        lessons: loadLessons,
        notes: loadNotes,
        payments: loadPayments,
        enrollments: loadEnrollments,
        certificates: loadCertificates,
        activity: loadActivity,
        support: loadSupport,
        reviews: loadReviews,
        announcements: loadAnnouncements,
        content: loadContent,
        reports: loadReports,
        admins: loadAdmins,
        audit: loadAudit,
        settings: loadSettings
    };

    function escapeHtml(value) {
        var element = document.createElement("span");
        element.textContent = value == null ? "" : String(value);
        return element.innerHTML;
    }

    function api(path, options) {
        return KCAPI.api(path, options);
    }

    function showAlert(message, isError) {
        var element = document.getElementById("admin-alert");
        element.textContent = message;
        element.className = "alert " + (isError ? "alert-danger" : "alert-success");
        window.clearTimeout(alertTimer);
        alertTimer = window.setTimeout(function () {
            element.classList.add("d-none");
        }, 5000);
    }

    function table(headers, rows) {
        if (!rows.length) return '<div class="admin-empty">No records found.</div>';
        return '<div class="admin-table-wrap"><table class="table table-hover admin-table"><thead><tr>' +
            headers.map(function (header) { return "<th>" + escapeHtml(header) + "</th>"; }).join("") +
            "</tr></thead><tbody>" + rows.map(function (row) {
                return "<tr>" + row.map(function (cell) { return "<td>" + cell + "</td>"; }).join("") + "</tr>";
            }).join("") + "</tbody></table></div>";
    }

    function status(value) {
        return '<span class="admin-status">' + escapeHtml(value || "—") + "</span>";
    }

    function button(label, action, id, style) {
        return '<button class="btn btn-sm ' + (style || "btn-outline-primary") +
            '" data-action="' + escapeHtml(action) + '" data-id="' + escapeHtml(id) + '">' +
            escapeHtml(label) + "</button>";
    }

    async function loadDashboard() {
        var result = await api("/api/admin/stats");
        var stats = [
            ["Students", result.students],
            ["Courses", result.courses],
            ["Enrollments", result.enrollments],
            ["Verified revenue", "₹" + Number(result.revenue || 0).toLocaleString()]
        ];
        document.getElementById("dashboard-stats").innerHTML = stats.map(function (item) {
            return '<div class="col-sm-6 col-xl-3"><div class="admin-stat"><span>' +
                escapeHtml(item[0]) + "</span><strong>" + escapeHtml(item[1]) + "</strong></div></div>";
        }).join("");
        document.getElementById("recent-students").innerHTML = table(
            ["Name", "Email", "Status"],
            (result.recent_users || []).map(function (student) {
                return [escapeHtml(student.full_name), escapeHtml(student.email),
                    status(student.account_status)];
            })
        );
    }

    async function loadStudents() {
        var search = document.getElementById("student-search").value.trim();
        var result = await api("/api/admin/users?limit=100&search=" + encodeURIComponent(search));
        document.getElementById("students-table").innerHTML = table(
            ["Student", "Email", "Status", "Joined", "Action"],
            result.users.map(function (student) {
                return [escapeHtml(student.full_name), escapeHtml(student.email), status(student.account_status),
                    escapeHtml(student.created_at || "—"),
                    button(student.account_status === "active" ? "Suspend" : "Activate",
                        "toggle-student", student.id)];
            })
        );
    }

    async function loadCourses() {
        var result = await api("/api/admin/courses");
        document.getElementById("courses-table").innerHTML = table(
            ["Course", "Category", "Price", "Status", "Lessons", "Action"],
            result.courses.map(function (course) {
                return [escapeHtml(course.title), escapeHtml(course.category || "—"),
                    "₹" + escapeHtml(course.price), status(course.status),
                    escapeHtml(course.lessons_count || (course.lessons || []).length || 0),
                    button("Edit", "edit-course", course.id) + " " +
                    button("Lessons", "manage-course-lessons", course.id) + " " +
                    button("Duplicate", "duplicate-course", course.id) + " " +
                    button("Archive", "archive-course", course.id, "btn-outline-danger")];
            })
        );
    }

    async function loadCategories() {
        var result = await api("/api/admin/categories");
        document.getElementById("categories-table").innerHTML = table(
            ["Name", "Description", "Action"],
            result.categories.map(function (category) {
                var actions = category.id ? button("Edit", "edit-category", category.id) + " " +
                    button("Delete", "delete-category", category.id, "btn-outline-danger") :
                    '<span class="text-muted">Used by existing courses</span>';
                return [escapeHtml(category.name), escapeHtml(category.description), actions];
            })
        );
    }

    async function loadCourseOptions(selectId) {
        var result = await api("/api/admin/courses");
        var select = document.getElementById(selectId);
        var previous = select.value;
        select.innerHTML = result.courses.map(function (course) {
            return '<option value="' + course.id + '">' + escapeHtml(course.title) + "</option>";
        }).join("");
        if (previous) select.value = previous;
        return result.courses;
    }

    async function loadLessons() {
        var courses = await loadCourseOptions("lesson-course");
        var select = document.getElementById("lesson-course");
        if (!courses.length) {
            document.getElementById("lessons-table").innerHTML =
                '<div class="admin-empty">Create a course before adding lessons.</div>';
            return;
        }
        var result = await api("/api/admin/courses/" + select.value + "/lessons");
        document.getElementById("lessons-table").innerHTML = table(
            ["Order", "Lesson", "Duration", "Preview", "Video", "Action"],
            result.lessons.map(function (lesson) {
                return [escapeHtml(lesson.lesson_order), escapeHtml(lesson.title),
                    escapeHtml(lesson.duration || "—"), status(lesson.is_preview ? "yes" : "no"),
                    escapeHtml(lesson.video_url || "—"),
                    '<input class="form-control form-control-sm mb-1" type="file" accept="video/mp4,video/webm,video/quicktime" data-video-input="' +
                    lesson.id + '">' + button("Upload video", "upload-lesson-video", lesson.id) + " " +
                    button("Delete", "delete-lesson", lesson.id, "btn-outline-danger")];
            })
        );
    }

    async function loadNotes() {
        var courses = await loadCourseOptions("note-course");
        var result = await api("/api/admin/notes");
        document.getElementById("note-form").querySelector("button[type=submit]").disabled = !courses.length;
        document.getElementById("notes-table").innerHTML = table(
            ["Title", "Course", "File", "Published", "Created", "Action"],
            result.notes.map(function (note) {
                return [escapeHtml(note.title), escapeHtml(note.course_id), escapeHtml(note.file_name),
                    status(note.is_published ? "yes" : "no"), escapeHtml(note.created_at),
                    button("Delete", "delete-note", note.id, "btn-outline-danger")];
            })
        );
    }

    async function loadPayments() {
        var params = new URLSearchParams();
        var filter = document.getElementById("payment-status").value;
        var environment = document.getElementById("payment-environment").value;
        var search = document.getElementById("payment-search").value.trim();
        if (filter) params.set("status", filter);
        if (environment) params.set("environment", environment);
        if (search) params.set("search", search);
        var result = await api("/api/admin/payments?" + params.toString());
        document.getElementById("payments-table").innerHTML = table(
            ["Student", "Course", "Amount", "Method", "Environment", "Gateway order / reference", "Status", "Verified", "Review"],
            result.payments.map(function (payment) {
                var proof = payment.proof_url ?
                    '<a class="btn btn-sm btn-outline-secondary" href="' + escapeHtml(payment.proof_url) +
                    '" target="_blank" rel="noopener">Proof</a> ' : "";
                var actions = proof;
                if (payment.provider === "upi_gateway") {
                    actions += button("Events", "payment-events", payment.id);
                }
                if (payment.status === "pending" && payment.provider === "manual") {
                    actions += button("Approve", "approve-payment", payment.id, "btn-success") + " " +
                        button("Reject", "reject-payment", payment.id, "btn-outline-danger");
                }
                return [escapeHtml(payment.student.full_name), escapeHtml(payment.course.title),
                    "₹" + escapeHtml(payment.amount), escapeHtml(payment.method || payment.provider),
                    escapeHtml(payment.environment || "—"),
                    escapeHtml(payment.gateway_order_id || payment.transaction_id || "—"),
                    status(payment.status), escapeHtml(payment.verified_at || "—"), actions || "—"];
            })
        );
        var eventParams = new URLSearchParams();
        if (environment) eventParams.set("environment", environment);
        var events = await api("/api/admin/payment-gateway-events?" + eventParams.toString());
        document.getElementById("payment-events-table").innerHTML = table(
            ["Received", "Environment", "Source", "Event", "Order", "Result", "Error"],
            events.events.map(function (item) {
                return [escapeHtml(item.received_at || "—"), escapeHtml(item.environment),
                    escapeHtml(item.source), escapeHtml(item.event_type || "—"),
                    escapeHtml(item.gateway_order_id || "—"), status(item.result),
                    escapeHtml(item.error_code || "—")];
            })
        );
    }

    async function loadEnrollments() {
        var result = await api("/api/admin/enrollments");
        document.getElementById("enrollments-table").innerHTML = table(
            ["Student", "Email", "Course", "Payment", "Access", "Expiry", "Action"],
            result.enrollments.map(function (item) {
                return [escapeHtml(item.student.full_name), escapeHtml(item.student.email),
                    escapeHtml(item.course_title), status(item.payment_status), status(item.access_status),
                    escapeHtml(item.access_expires_at || "Never"),
                    button(item.access_status === "active" ? "Suspend" : "Activate",
                        "toggle-enrollment", item.id)];
            })
        );
    }

    async function loadCertificates() {
        var result = await api("/api/admin/certificates");
        document.getElementById("certificates-table").innerHTML = table(
            ["Student", "Course", "Certificate", "Issued", "Status", "Action"],
            result.certificates.map(function (certificate) {
                var action = certificate.revoked_at ?
                    button("Reissue", "reissue-certificate", certificate.id, "btn-outline-success") :
                    button("Revoke", "revoke-certificate", certificate.id, "btn-outline-danger");
                return [escapeHtml(certificate.student_name), escapeHtml(certificate.course_title),
                    escapeHtml(certificate.certificate_number), escapeHtml(certificate.issue_date || "—"),
                    status(certificate.revoked_at ? "revoked" : "active"), action];
            })
        );
    }

    async function loadActivity() {
        var result = await api("/api/admin/activity");
        document.getElementById("activity-table").innerHTML = table(
            ["Student", "Event", "Details", "When"],
            result.activity.map(function (item) {
                return [escapeHtml(item.student_name), escapeHtml(item.event),
                    escapeHtml(item.details), escapeHtml(item.created_at)];
            })
        );
    }

    async function loadSupport() {
        var result = await api("/api/admin/support/tickets");
        supportTickets = result.tickets;
        var list = document.getElementById("support-list");
        list.innerHTML = result.tickets.length ? result.tickets.map(function (ticket) {
            return '<button class="support-ticket' + (activeTicket === ticket.id ? " active" : "") +
                '" data-action="open-ticket" data-id="' + ticket.id + '"><strong>' +
                escapeHtml(ticket.student.full_name) + " · " + escapeHtml(ticket.subject) +
                "</strong><span>" + escapeHtml(ticket.last_message || "No messages") + " · " +
                escapeHtml(ticket.status) + " · unread " + escapeHtml(ticket.unread_count) +
                "</span></button>";
        }).join("") : '<div class="admin-empty">No support tickets.</div>';
        if (activeTicket) await loadTicket(activeTicket);
    }

    async function loadTicket(ticketId) {
        var result = await api("/api/support/tickets/" + ticketId + "/messages");
        var ticket = supportTickets.find(function (item) { return item.id === ticketId; });
        if (!ticket) return;
        if (supportSocket && supportSocket.connected && joinedTicket !== ticketId) {
            if (joinedTicket !== null) supportSocket.emit("support_leave_ticket", { ticket_id: joinedTicket });
            supportSocket.emit("support_join_ticket", { ticket_id: ticketId });
            joinedTicket = ticketId;
        }
        await api("/api/support/tickets/" + ticketId + "/read", {
            method: "POST", body: JSON.stringify({})
        });
        var canManage = permissions.includes("support.manage");
        var assignees = canManage ?
            (await api("/api/admin/support/assignees")).admins : [];
        var controls = canManage ?
            '<div class="d-flex flex-wrap gap-2"><select class="form-select w-auto" id="ticket-status">' +
            ["open", "in_progress", "resolved"].map(function (value) {
                return '<option value="' + value + '"' + (ticket.status === value ? " selected" : "") +
                    ">" + escapeHtml(value.replace("_", " ")) + "</option>";
            }).join("") + '</select><select class="form-select w-auto" id="ticket-priority">' +
            ["low", "normal", "high", "urgent"].map(function (value) {
                return '<option value="' + value + '"' + (ticket.priority === value ? " selected" : "") +
                    ">" + escapeHtml(value) + "</option>";
            }).join("") + '</select><select class="form-select w-auto" id="ticket-assignee">' +
            '<option value="">Unassigned</option>' + assignees.map(function (admin) {
                return '<option value="' + admin.id + '"' +
                    (ticket.assigned_admin_id === admin.id ? " selected" : "") + ">" +
                    escapeHtml(admin.full_name) + "</option>";
            }).join("") + "</select></div>" : status(ticket.status);
        var detail = document.getElementById("support-detail");
        detail.innerHTML = '<div class="admin-card-heading"><div><h2>' +
            escapeHtml(ticket.subject) + "</h2><p class=\"text-muted mb-0\">" +
            escapeHtml(ticket.student.full_name) + "</p></div>" + controls + "</div><div class=\"support-thread\">" +
            result.messages.map(function (message) {
                return '<div class="support-message' + (message.sender_id === adminUserId ? " mine" : "") +
                    '"><strong>' + escapeHtml(message.sender_name) +
                    (message.is_internal ? " · internal note" : "") + "</strong><div>" +
                    escapeHtml(message.body) + "</div>" +
                    (message.attachment_url ? '<a href="' + escapeHtml(message.attachment_url) +
                    '" target="_blank" rel="noopener">' + escapeHtml(message.attachment_name) + "</a>" : "") +
                    '<small class="d-block text-muted mt-1">' + escapeHtml(message.created_at) +
                    "</small></div>";
            }).join("") + "</div>" + (canManage ?
                '<form class="support-compose" id="support-reply-form">' +
                '<div class="flex-grow-1"><textarea class="form-control" name="message" maxlength="4000" placeholder="Write a reply or internal note..." required></textarea>' +
                '<input class="form-control form-control-sm mt-2" name="file" type="file" accept=".png,.jpg,.jpeg,.pdf,.txt">' +
                '<label class="form-check mt-2"><input class="form-check-input" name="is_internal" type="checkbox">' +
                '<span class="form-check-label">Internal note (admins only)</span></label></div>' +
                '<button class="btn btn-primary align-self-start" type="submit">Send</button></form>' : "");
        detail.scrollTop = detail.scrollHeight;
        if (canManage) {
            ["ticket-status", "ticket-priority", "ticket-assignee"].forEach(function (controlId) {
                detail.querySelector("#" + controlId).addEventListener("change", async function () {
                    var update = {};
                    if (controlId === "ticket-status") update.status = this.value;
                    if (controlId === "ticket-priority") update.priority = this.value;
                    if (controlId === "ticket-assignee") update.assigned_admin_id = this.value || null;
                    try {
                        await api("/api/admin/support/tickets/" + ticketId, {
                            method: "PATCH", body: JSON.stringify(update)
                        });
                        showAlert("Support ticket updated.");
                        await loadSupport();
                    } catch (error) { showAlert(error.message, true); }
                });
            });
        }
        var replyForm = detail.querySelector("#support-reply-form");
        if (replyForm) replyForm.addEventListener("submit", async function (event) {
            event.preventDefault();
            var formData = new FormData(this);
            var body = formData.get("message");
            var attachment = formData.get("file");
            var isInternal = formData.get("is_internal") === "on";
            var form = this;
            var sendWithSocket = function () {
                supportSocket.emit("support_send_message", {
                    ticket_id: ticketId, message: body, is_internal: isInternal
                }, function (response) {
                    if (response && response.error) {
                        showAlert(response.error, true);
                        return;
                    }
                    form.reset();
                    loadSupport();
                });
            };
            try {
                if (attachment && attachment.size) {
                    formData.set("is_internal", isInternal ? "true" : "false");
                    await KCAPI.upload("/api/support/tickets/" + ticketId + "/attachments", formData);
                    form.reset();
                    await loadSupport();
                } else if (isInternal) {
                    await api("/api/support/tickets/" + ticketId + "/messages", {
                        method: "POST", body: JSON.stringify({ message: body, is_internal: true })
                    });
                    form.reset();
                    await loadSupport();
                } else if (supportSocket && supportSocket.connected) {
                    sendWithSocket();
                } else {
                    await api("/api/support/tickets/" + ticketId + "/messages", {
                        method: "POST", body: JSON.stringify({ message: body })
                    });
                    form.reset();
                    await loadSupport();
                }
            } catch (error) { showAlert(error.message, true); }
        });
    }

    async function loadReviews() {
        var result = await api("/api/admin/reviews");
        document.getElementById("reviews-table").innerHTML = table(
            ["Student", "Course", "Rating", "Review", "Status", "Moderation"],
            result.reviews.map(function (review) {
                var next = review.status === "published" ? "hidden" : "published";
                return [escapeHtml(review.student.full_name), escapeHtml(review.course_title),
                    escapeHtml(review.rating) + "/5", escapeHtml(review.review), status(review.status),
                    button(next === "hidden" ? "Hide" : "Publish", "moderate-review", review.id)];
            })
        );
    }

    async function loadAnnouncements() {
        var result = await api("/api/admin/announcements");
        document.getElementById("announcements-list").innerHTML = table(
            ["Title", "Content", "Status", "Created", "Action"],
            result.announcements.map(function (item) {
                return [escapeHtml(item.title), escapeHtml(item.content), status(item.is_published ? "published" : "draft"),
                    escapeHtml(item.created_at), button(item.is_published ? "Unpublish" : "Publish",
                        "toggle-announcement", item.id)];
            })
        );
    }

    async function loadContent() {
        var result = await api("/api/admin/content");
        var current = {};
        result.content.forEach(function (item) { current[item.key] = item.content; });
        var fields = [
            ["home_hero_title", "Homepage hero title"],
            ["home_hero_subtitle", "Homepage hero subtitle"],
            ["home_about_title", "About section title"],
            ["home_about_body", "About section text"],
            ["contact_email", "Contact email"],
            ["contact_phone", "Contact phone"],
            ["footer_text", "Footer text"],
            ["payment_instructions", "Student payment instructions"],
            ["social_twitter", "X / Twitter URL"],
            ["social_facebook", "Facebook URL"],
            ["social_youtube", "YouTube URL"],
            ["social_linkedin", "LinkedIn URL"]
        ];
        document.getElementById("content-fields").innerHTML = fields.map(function (field) {
            var value = current[field[0]] || "";
            var control = field[0].indexOf("_body") >= 0 || field[0].indexOf("subtitle") >= 0 ||
                field[0].indexOf("footer") >= 0 || field[0].indexOf("instructions") >= 0 ?
                "textarea" : "input";
            return '<form class="admin-form-row content-form" data-key="' + field[0] + '"><label class="form-label">' +
                escapeHtml(field[1]) + "</label>" + (control === "textarea" ?
                    '<textarea class="form-control" maxlength="3000">' + escapeHtml(value) + "</textarea>" :
                    '<input class="form-control" maxlength="500" value="' + escapeHtml(value) + '">') +
                '<button class="btn btn-outline-primary btn-sm">Save</button></form>';
        }).join("");
        document.querySelectorAll(".content-form").forEach(function (form) {
            form.addEventListener("submit", async function (event) {
                event.preventDefault();
                var input = this.querySelector("input,textarea");
                try {
                    await api("/api/admin/content/" + encodeURIComponent(this.dataset.key), {
                        method: "PUT", body: JSON.stringify({ content: input.value })
                    });
                    showAlert("Website content saved.");
                } catch (error) { showAlert(error.message, true); }
            });
        });
    }

    async function loadReports() {
        var range = document.getElementById("report-range").value;
        var result = await api("/api/admin/reports?range=" + encodeURIComponent(range));
        var values = [
            ["New students", result.new_students], ["Enrollments", result.enrollments],
            ["Pending payments", result.pending_payments], ["Approved payments", result.approved_payments],
            ["Verified revenue", "₹" + Number(result.verified_revenue || 0).toLocaleString()],
            ["Support tickets", result.support_tickets]
        ];
        document.getElementById("report-results").innerHTML = '<div class="row g-3 mt-1">' +
            values.map(function (item) {
                return '<div class="col-sm-6 col-xl-4"><div class="admin-stat"><span>' +
                    escapeHtml(item[0]) + "</span><strong>" + escapeHtml(item[1]) + "</strong></div></div>";
            }).join("") + "</div>" + table(["Course", "Enrollments"],
                result.course_enrollments.map(function (item) {
                    return [escapeHtml(item.title), escapeHtml(item.enrollments)];
                }));
    }

    async function loadAdmins() {
        var result = await api("/api/admin/roles");
        adminRoles = result.roles.filter(function (role) { return role.name !== "super_admin"; });
        document.getElementById("admin-role-select").innerHTML = adminRoles.map(function (role) {
            return '<option value="' + role.id + '">' + escapeHtml(role.name) + "</option>";
        }).join("");
        document.getElementById("role-permissions").innerHTML = result.permissions.map(function (permission) {
            return '<option value="' + escapeHtml(permission.code) + '">' +
                escapeHtml(permission.code + " — " + permission.description) + "</option>";
        }).join("");
        var adminsResult = await api("/api/admin/admins");
        document.getElementById("admins-table").innerHTML = table(
            ["Name", "Email", "Role", "Status", "Action"],
            adminsResult.admins.map(function (administrator) {
                if (administrator.role === "super_admin") {
                    return [escapeHtml(administrator.full_name), escapeHtml(administrator.email),
                        status("Super Admin"), status(administrator.account_status), "—"];
                }
                var roleSelect = '<select class="form-select form-select-sm" data-admin-role-select="' +
                    administrator.id + '">' + adminRoles.map(function (role) {
                        return '<option value="' + role.id + '"' +
                            (administrator.admin_role_id === role.id ? " selected" : "") + ">" +
                            escapeHtml(role.name) + "</option>";
                    }).join("") + "</select>";
                return [escapeHtml(administrator.full_name), escapeHtml(administrator.email),
                    roleSelect, status(administrator.account_status),
                    button("Save role", "assign-admin-role", administrator.id) + " " +
                    button(administrator.account_status === "active" ? "Deactivate" : "Activate",
                        "toggle-admin", administrator.id)];
            })
        );
        var customRoles = result.roles.filter(function (role) { return !role.is_system; });
        document.getElementById("roles-table").innerHTML = table(
            ["Role", "Description", "Permissions", "Action"],
            customRoles.map(function (role) {
                var options = result.permissions.map(function (permission) {
                    return '<option value="' + escapeHtml(permission.code) + '"' +
                        (role.permissions.includes(permission.code) ? " selected" : "") + ">" +
                        escapeHtml(permission.code) + "</option>";
                }).join("");
                return [escapeHtml(role.name), escapeHtml(role.description),
                    '<select class="form-select form-select-sm" multiple data-role-permissions="' +
                    role.id + '">' + options + "</select>",
                    button("Save permissions", "save-role-permissions", role.id)];
            })
        );
    }

    async function loadAudit() {
        var result = await api("/api/admin/audit-logs");
        document.getElementById("audit-table").innerHTML = table(
            ["When", "Administrator", "Action", "Module", "Target", "Reason"],
            result.logs.map(function (item) {
                return [escapeHtml(item.created_at), escapeHtml(item.admin_name), escapeHtml(item.action),
                    escapeHtml(item.module), escapeHtml(item.target_type + " " + (item.target_id || "")),
                    escapeHtml(item.reason || "—")];
            })
        );
    }

    async function loadSettings() {
        var result = await api("/api/admin/settings");
        document.getElementById("settings-details").innerHTML = table(
            ["Setting", "Current value"],
            Object.keys(result).map(function (key) {
                var value = result[key];
                if (typeof value === "boolean") value = value ? "Configured" : "Not configured";
                return [escapeHtml(key.replace(/_/g, " ")), escapeHtml(value)];
            })
        );
    }

    async function openView(name) {
        if (!views[name]) return;
        document.querySelectorAll(".admin-view").forEach(function (view) {
            view.classList.toggle("d-none", view.id !== "view-" + name);
        });
        document.querySelectorAll(".admin-nav").forEach(function (item) {
            item.classList.toggle("active", item.dataset.view === name);
        });
        try { await views[name](); }
        catch (error) { showAlert(error.message, true); }
    }

    document.querySelectorAll(".admin-nav").forEach(function (item) {
        item.addEventListener("click", function () { openView(item.dataset.view); });
    });
    document.querySelectorAll("[data-open-view]").forEach(function (item) {
        item.addEventListener("click", function () { openView(item.dataset.openView); });
    });
    document.getElementById("student-search-button").addEventListener("click", loadStudents);
    document.getElementById("student-search").addEventListener("keydown", function (event) {
        if (event.key === "Enter") loadStudents();
    });
    document.getElementById("payments-refresh").addEventListener("click", loadPayments);
    document.getElementById("payment-status").addEventListener("change", loadPayments);
    document.getElementById("payment-environment").addEventListener("change", loadPayments);
    document.getElementById("payment-search").addEventListener("keydown", function (event) {
        if (event.key === "Enter") loadPayments();
    });
    document.getElementById("support-refresh").addEventListener("click", loadSupport);
    document.getElementById("reports-refresh").addEventListener("click", loadReports);
    document.getElementById("report-range").addEventListener("change", loadReports);

    document.body.addEventListener("click", async function (event) {
        var target = event.target.closest("[data-action]");
        if (!target) return;
        var id = target.dataset.id;
        var action = target.dataset.action;
        try {
            if (action === "open-ticket") {
                activeTicket = Number(id);
                await loadSupport();
            } else if (action === "approve-payment") {
                await api("/api/admin/payments/" + id + "/approve", {
                    method: "POST", body: JSON.stringify({})
                });
                showAlert("Payment approved; course access is active.");
                await loadPayments();
            } else if (action === "reject-payment") {
                var reason = window.prompt("Enter the reason for rejecting this payment:");
                if (!reason) return;
                await api("/api/admin/payments/" + id + "/reject", {
                    method: "POST", body: JSON.stringify({ reason: reason })
                });
                showAlert("Payment rejected. No course access was granted.");
                await loadPayments();
            } else if (action === "payment-events") {
                var history = await api("/api/admin/payments/" + id + "/events");
                document.getElementById("payment-detail-events").innerHTML =
                    '<h3 class="h6 mt-4">Payment #' + escapeHtml(id) + " verification history</h3>" +
                    table(["Received", "Environment", "Source", "Event", "Sequence", "Result", "Error"],
                        history.events.map(function (item) {
                            return [escapeHtml(item.received_at || "—"), escapeHtml(item.environment),
                                escapeHtml(item.source), escapeHtml(item.event_type || "—"),
                                escapeHtml(item.event_sequence == null ? "—" : item.event_sequence),
                                status(item.result), escapeHtml(item.error_code || "—")];
                        }));
            } else if (action === "duplicate-course") {
                await api("/api/admin/courses/" + id + "/duplicate", {
                    method: "POST", body: JSON.stringify({})
                });
                showAlert("Course duplicated as a draft.");
                await loadCourses();
            } else if (action === "manage-course-lessons") {
                await loadCourseOptions("lesson-course");
                document.getElementById("lesson-course").value = id;
                await openView("lessons");
            } else if (action === "edit-course") {
                var courseTitle = window.prompt("Course title:");
                if (!courseTitle) return;
                var coursePrice = Number(window.prompt("Course price:", "0"));
                var courseStatus = window.prompt("Course status: draft, published, or archived", "draft");
                if (!Number.isFinite(coursePrice) || coursePrice < 0 ||
                        !["draft", "published", "archived"].includes(courseStatus)) {
                    showAlert("Enter a valid course price and status.", true);
                    return;
                }
                await api("/api/admin/courses/" + id, {
                    method: "PUT",
                    body: JSON.stringify({ title: courseTitle, price: coursePrice, status: courseStatus })
                });
                await loadCourses();
                showAlert("Course updated.");
            } else if (action === "archive-course") {
                if (!window.confirm("Archive or delete this course? Existing student records are retained.")) return;
                await api("/api/admin/courses/" + id, { method: "DELETE" });
                await loadCourses();
                showAlert("Course archived or deleted.");
            } else if (action === "edit-category") {
                var categoryName = window.prompt("Category name:");
                if (!categoryName) return;
                var categoryDescription = window.prompt("Category description:", "");
                await api("/api/admin/categories/" + id, {
                    method: "PUT",
                    body: JSON.stringify({ name: categoryName, description: categoryDescription || "" })
                });
                await loadCategories();
            } else if (action === "delete-category") {
                if (!window.confirm("Delete this unused category?")) return;
                await api("/api/admin/categories/" + id, { method: "DELETE" });
                await loadCategories();
            } else if (action === "upload-lesson-video") {
                var videoInput = target.closest("tr").querySelector("[data-video-input]");
                if (!videoInput.files[0]) {
                    showAlert("Choose a video file first.", true);
                    return;
                }
                var videoForm = new FormData();
                videoForm.append("file", videoInput.files[0]);
                await KCAPI.upload("/api/admin/lessons/" + id + "/video", videoForm);
                await loadLessons();
                showAlert("Lesson video uploaded.");
            } else if (action === "delete-lesson") {
                if (!window.confirm("Delete this lesson? Lessons with student progress cannot be deleted.")) return;
                await api("/api/admin/lessons/" + id, { method: "DELETE" });
                await loadLessons();
            } else if (action === "delete-note") {
                if (!window.confirm("Delete this study note and its uploaded file?")) return;
                await api("/api/admin/notes/" + id, { method: "DELETE" });
                await loadNotes();
            } else if (action === "revoke-certificate") {
                var revokeReason = window.prompt("Reason for revoking this certificate:");
                if (!revokeReason) return;
                await api("/api/admin/certificates/" + id + "/revoke", {
                    method: "POST", body: JSON.stringify({ reason: revokeReason })
                });
                await loadCertificates();
            } else if (action === "reissue-certificate") {
                await api("/api/admin/certificates/" + id + "/reissue", {
                    method: "POST", body: JSON.stringify({})
                });
                await loadCertificates();
            } else if (action === "toggle-student") {
                var currentStudent = await api("/api/admin/users/" + id);
                await api("/api/admin/users/" + id, {
                    method: "PUT",
                    body: JSON.stringify({ account_status: currentStudent.student.account_status === "active" ? "inactive" : "active" })
                });
                await loadStudents();
            } else if (action === "toggle-enrollment") {
                var currentStatus = target.textContent === "Suspend" ? "suspended" : "active";
                var reasonText = window.prompt("Enter a reason for changing course access:");
                if (!reasonText) return;
                await api("/api/admin/enrollments/" + id, {
                    method: "PATCH",
                    body: JSON.stringify({ access_status: currentStatus, reason: reasonText })
                });
                await loadEnrollments();
            } else if (action === "moderate-review") {
                var nextStatus = target.textContent === "Hide" ? "hidden" : "published";
                await api("/api/admin/reviews/" + id, {
                    method: "PATCH", body: JSON.stringify({ status: nextStatus })
                });
                await loadReviews();
            } else if (action === "toggle-announcement") {
                var announcements = await api("/api/admin/announcements");
                var selected = announcements.announcements.find(function (item) { return item.id === Number(id); });
                await api("/api/admin/announcements/" + id, {
                    method: "PATCH", body: JSON.stringify({ is_published: !selected.is_published })
                });
                await loadAnnouncements();
            } else if (action === "toggle-admin") {
                var active = target.textContent === "Deactivate";
                await api("/api/admin/admins/" + id, {
                    method: "PATCH", body: JSON.stringify({ account_status: active ? "inactive" : "active" })
                });
                await loadAdmins();
            } else if (action === "assign-admin-role") {
                var roleSelect = target.closest("tr").querySelector("[data-admin-role-select]");
                await api("/api/admin/admins/" + id, {
                    method: "PATCH", body: JSON.stringify({ admin_role_id: Number(roleSelect.value) })
                });
                await loadAdmins();
                showAlert("Administrator role updated.");
            } else if (action === "save-role-permissions") {
                var permissionSelect = target.closest("tr").querySelector("[data-role-permissions]");
                await api("/api/admin/roles/" + id, {
                    method: "PUT",
                    body: JSON.stringify({
                        permissions: Array.from(permissionSelect.selectedOptions).map(function (option) {
                            return option.value;
                        })
                    })
                });
                await loadAdmins();
                showAlert("Role permissions updated.");
            }
        } catch (error) { showAlert(error.message, true); }
    });

    document.getElementById("create-course-button").addEventListener("click", async function () {
        var title = window.prompt("Course title:");
        if (!title) return;
        var description = window.prompt("Course description:");
        if (!description) return;
        var category = window.prompt("Course category:");
        var rawPrice = window.prompt("Course price (0 for free):", "0");
        var price = Number(rawPrice);
        if (!Number.isFinite(price) || price < 0) {
            showAlert("Enter a valid non-negative course price.", true);
            return;
        }
        try {
            await api("/api/admin/courses", {
                method: "POST",
                body: JSON.stringify({ title: title, description: description, category: category || "",
                    price: price, status: "draft" })
            });
            await loadCourses();
            showAlert("Draft course created.");
        } catch (error) { showAlert(error.message, true); }
    });

    document.getElementById("category-form").addEventListener("submit", async function (event) {
        event.preventDefault();
        var data = Object.fromEntries(new FormData(this).entries());
        try {
            await api("/api/admin/categories", { method: "POST", body: JSON.stringify(data) });
            this.reset();
            await loadCategories();
            showAlert("Course category created.");
        } catch (error) { showAlert(error.message, true); }
    });

    document.getElementById("lesson-course-load").addEventListener("click", loadLessons);
    document.getElementById("lesson-form").addEventListener("submit", async function (event) {
        event.preventDefault();
        var data = Object.fromEntries(new FormData(this).entries());
        data.is_preview = this.querySelector("[name=is_preview]").checked;
        if (!data.lesson_order) delete data.lesson_order;
        try {
            await api("/api/admin/courses/" + document.getElementById("lesson-course").value + "/lessons", {
                method: "POST", body: JSON.stringify(data)
            });
            this.reset();
            await loadLessons();
            showAlert("Lesson created.");
        } catch (error) { showAlert(error.message, true); }
    });

    document.getElementById("note-form").addEventListener("submit", async function (event) {
        event.preventDefault();
        var data = new FormData(this);
        data.set("is_published", this.querySelector("[name=is_published]").checked ? "true" : "false");
        try {
            await KCAPI.upload("/api/admin/notes", data);
            this.reset();
            await loadNotes();
            showAlert("Study note uploaded.");
        } catch (error) { showAlert(error.message, true); }
    });

    document.getElementById("grant-enrollment").addEventListener("click", async function () {
        var studentId = Number(window.prompt("Student account ID:"));
        var courseId = Number(window.prompt("Course ID:"));
        var reason = window.prompt("Reason for complimentary access:");
        if (!studentId || !courseId || !reason) return;
        try {
            await api("/api/admin/enrollments", {
                method: "POST", body: JSON.stringify({
                    student_id: studentId, course_id: courseId, reason: reason
                })
            });
            await loadEnrollments();
            showAlert("Course access granted.");
        } catch (error) { showAlert(error.message, true); }
    });

    document.getElementById("announcement-form").addEventListener("submit", async function (event) {
        event.preventDefault();
        try {
            await api("/api/admin/announcements", {
                method: "POST", body: JSON.stringify({
                    title: document.getElementById("announcement-title").value,
                    content: document.getElementById("announcement-content").value,
                    is_published: document.getElementById("announcement-published").checked
                })
            });
            this.reset();
            await loadAnnouncements();
            showAlert("Announcement created.");
        } catch (error) { showAlert(error.message, true); }
    });

    document.getElementById("admin-create-form").addEventListener("submit", async function (event) {
        event.preventDefault();
        var data = Object.fromEntries(new FormData(this).entries());
        data.admin_role_id = Number(data.admin_role_id);
        try {
            await api("/api/admin/admins", { method: "POST", body: JSON.stringify(data) });
            this.reset();
            await loadAdmins();
            showAlert("Administrator account created.");
        } catch (error) { showAlert(error.message, true); }
    });

    document.getElementById("role-create-form").addEventListener("submit", async function (event) {
        event.preventDefault();
        var form = new FormData(this);
        var selected = Array.from(document.getElementById("role-permissions").selectedOptions)
            .map(function (option) { return option.value; });
        try {
            await api("/api/admin/roles", {
                method: "POST", body: JSON.stringify({
                    name: form.get("name"), description: form.get("description"), permissions: selected
                })
            });
            this.reset();
            await loadAdmins();
            showAlert("Administrator role created.");
        } catch (error) { showAlert(error.message, true); }
    });

    document.getElementById("admin-logout").addEventListener("click", async function () {
        try {
            await api("/api/auth/logout", { method: "POST", body: JSON.stringify({}) });
            window.location.replace("/admin-login.html");
        } catch (error) { showAlert(error.message, true); }
    });

    api("/api/admin/auth/me").then(function (result) {
        permissions = result.permissions || [];
        adminUserId = result.user.id;
        document.getElementById("admin-user").textContent =
            result.user.full_name + (result.is_super_admin ? " · Super Admin" : " · Admin");
        document.querySelectorAll("[data-permission]").forEach(function (item) {
            if (!permissions.includes(item.dataset.permission)) item.classList.add("d-none");
        });
        document.querySelectorAll("[data-super-admin]").forEach(function (item) {
            if (!result.is_super_admin) item.classList.add("d-none");
        });
        if (window.io) {
            supportSocket = window.io(KCAPI.base || undefined, { withCredentials: true });
            supportSocket.on("connect", function () {
                joinedTicket = null;
                if (activeTicket !== null) loadTicket(activeTicket);
            });
            supportSocket.on("support_message", function (message) {
                if (message.ticket_id === activeTicket) loadTicket(activeTicket);
                loadSupport();
            });
            supportSocket.on("support_new_ticket", function () { loadSupport(); });
            supportSocket.on("support_ticket_updated", function () { loadSupport(); });
        }
        openView("dashboard");
    }).catch(function () {
        window.location.replace("/admin-login.html");
    });
})();
