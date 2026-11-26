(function () {
    "use strict";

    var shell = document.getElementById("chatShell");
    var list = document.getElementById("chatPeople");
    var messageList = document.getElementById("chatMessages");
    var search = document.getElementById("chatSearch");
    var form = document.getElementById("chatForm");
    var input = document.getElementById("chatInput");
    var errorBox = document.getElementById("chatError");
    var activeUser = null;
    var activeConversation = null;
    var me = null;
    var students = [];
    var conversations = [];
    var socket = null;
    var typingTimer = null;
    var seenMessages = new Set();

    function escapeText(value) {
        return String(value || "");
    }

    function avatarMarkup(student, className) {
        var fallback = escapeText((student.full_name || "?").trim().charAt(0).toUpperCase());
        var avatar = document.createElement("div");
        avatar.className = className || "chat-avatar";
        avatar.textContent = fallback;
        if (student.profile_image) {
            var image = document.createElement("img");
            image.src = student.profile_image;
            image.alt = "";
            image.onerror = function () {
                image.remove();
                avatar.textContent = fallback;
            };
            avatar.textContent = "";
            avatar.appendChild(image);
        }
        return avatar;
    }

    function setError(message) {
        errorBox.textContent = message || "";
        errorBox.hidden = !message;
    }

    function conversationFor(studentId) {
        return conversations.find(function (item) { return item.student.id === studentId; });
    }

    function latestPreview(conversation) {
        if (!conversation.last_message) return "Start a conversation";
        return conversation.last_message;
    }

    function renderPeople() {
        var term = search.value.trim().toLocaleLowerCase();
        var filtered = students.filter(function (student) {
            return student.full_name.toLocaleLowerCase().includes(term);
        });
        list.replaceChildren();
        if (!filtered.length) {
            var empty = document.createElement("div");
            empty.className = "chat-empty-list";
            empty.textContent = term ? "No contacts found." : "No chat contacts are available yet.";
            list.appendChild(empty);
            return;
        }
        filtered.forEach(function (student) {
            var conversation = conversationFor(student.id);
            var button = document.createElement("button");
            button.type = "button";
            button.className = "chat-person" +
                (activeUser && activeUser.id === student.id ? " active" : "");
            button.addEventListener("click", function () { openStudent(student); });
            button.appendChild(avatarMarkup(student));

            var content = document.createElement("span");
            content.className = "chat-person-content";
            var name = document.createElement("span");
            name.className = "chat-person-name";
            name.textContent = student.full_name;
            var preview = document.createElement("span");
            preview.className = "chat-person-preview";
            preview.textContent = conversation ? latestPreview(conversation) : "Start a conversation";
            content.append(name, preview);
            button.appendChild(content);
            if (conversation && conversation.unread_count > 0) {
                var unread = document.createElement("span");
                unread.className = "chat-unread";
                unread.textContent = conversation.unread_count > 99 ? "99+" : String(conversation.unread_count);
                button.appendChild(unread);
            }
            list.appendChild(button);
        });
    }

    function formatTime(value) {
        return new Intl.DateTimeFormat(undefined, {hour: "numeric", minute: "2-digit"})
            .format(new Date(value));
    }

    function appendMessage(message) {
        if (seenMessages.has(message.id)) return;
        seenMessages.add(message.id);
        var mine = Number(message.sender_id) === Number(me.id);
        var bubble = document.createElement("div");
        bubble.className = "chat-bubble " + (mine ? "mine" : "theirs");
        var body = document.createElement("div");
        body.textContent = message.message;
        bubble.appendChild(body);
        var time = document.createElement("span");
        time.className = "chat-bubble-time";
        time.textContent = formatTime(message.created_at);
        if (mine) {
            var status = document.createElement("span");
            status.className = "chat-message-status" + (message.is_read ? " read" : "");
            status.dataset.messageId = message.id;
            status.textContent = message.is_read ? "✓✓" : "✓";
            time.appendChild(status);
        }
        bubble.appendChild(time);
        messageList.appendChild(bubble);
        messageList.scrollTop = messageList.scrollHeight;
    }

    async function refreshConversations() {
        var result = await KCAPI.api("/api/chat/conversations");
        conversations = result.conversations;
        renderPeople();
    }

    async function openStudent(student) {
        setError("");
        activeUser = student;
        renderPeople();
        var conversation = conversationFor(student.id);
        if (!conversation) {
            var created = await KCAPI.api("/api/chat/conversations", {
                method: "POST",
                body: JSON.stringify({student_id: student.id})
            });
            conversation = created.conversation;
            conversations.unshift(conversation);
        }
        activeConversation = conversation.id;
        document.getElementById("chatPeerName").textContent = student.full_name;
        var peerAvatar = document.getElementById("chatPeerAvatar");
        peerAvatar.replaceWith(avatarMarkup(student, "chat-avatar"));
        document.querySelector(".chat-header").querySelector(".chat-avatar").id = "chatPeerAvatar";
        shell.classList.add("conversation-open");
        messageList.replaceChildren();
        seenMessages.clear();
        if (socket && socket.connected) socket.emit("join_conversation", {conversation_id: activeConversation});
        var result = await KCAPI.api("/api/chat/conversations/" + activeConversation + "/messages");
        result.messages.forEach(appendMessage);
        var current = conversationFor(student.id);
        if (current) current.unread_count = 0;
        renderPeople();
        input.focus();
    }

    function updatePreview(message) {
        if (!activeUser) return;
        var conversation = conversationFor(activeUser.id);
        if (!conversation) return;
        conversation.last_message = message.message;
        conversation.last_message_at = message.created_at;
        if (Number(message.sender_id) !== Number(me.id) && activeConversation !== conversation.id) {
            conversation.unread_count += 1;
        }
        renderPeople();
    }

    function connectSocket() {
        if (!window.io) {
            setError("Chat connection library failed to load. Reload this page and try again.");
            return;
        }
        socket = io({withCredentials: true});
        socket.on("connect_error", function () { setError("Chat connection failed. Please sign in again."); });
        socket.on("receive_message", function (message) {
            var currentConversation = conversationFor(activeUser && activeUser.id);
            var incomingConversationId = Number(message.conversation_id || activeConversation);
            if (activeConversation && (!message.conversation_id || incomingConversationId === activeConversation)) {
                appendMessage(message);
                if (Number(message.sender_id) !== Number(me.id)) {
                    KCAPI.api("/api/chat/messages/" + message.id + "/read", {
                        method: "POST", body: "{}"
                    }).catch(function () {});
                }
            }
            if (currentConversation && Number(message.sender_id) !== Number(me.id)) {
                currentConversation.unread_count = activeConversation === currentConversation.id ?
                    currentConversation.unread_count : currentConversation.unread_count + 1;
            }
            if (activeUser) {
                var conversation = conversationFor(activeUser.id);
                if (conversation) {
                    conversation.last_message = message.message;
                    conversation.last_message_at = message.created_at;
                }
            }
            refreshConversations().catch(function () {});
        });
        socket.on("conversation_updated", function (conversation) {
            var existing = conversations.find(function (item) { return item.id === conversation.id; });
            if (existing) Object.assign(existing, conversation);
            else conversations.unshift(conversation);
            renderPeople();
        });
        socket.on("new_conversation", function (conversation) {
            if (!conversationFor(conversation.student.id)) {
                conversations.unshift(conversation);
            }
            refreshConversations().catch(function () {});
        });
        socket.on("message_read", function (receipt) {
            if (Number(receipt.conversation_id) !== Number(activeConversation)) return;
            receipt.message_ids.forEach(function (id) {
                var status = messageList.querySelector('[data-message-id="' + id + '"]');
                if (status) {
                    status.classList.add("read");
                    status.textContent = "✓✓";
                }
            });
        });
        socket.on("message_delivered", function (receipt) {
            if (Number(receipt.conversation_id) !== Number(activeConversation)) return;
            receipt.message_ids.forEach(function (id) {
                var status = messageList.querySelector('[data-message-id="' + id + '"]');
                if (status && !status.classList.contains("read")) status.textContent = "✓✓";
            });
        });
        socket.on("user_typing", function (event) {
            if (Number(event.conversation_id) === Number(activeConversation)) {
                document.getElementById("chatTyping").textContent = event.full_name + " is typing…";
            }
        });
        socket.on("user_stop_typing", function (event) {
            if (Number(event.conversation_id) === Number(activeConversation)) {
                document.getElementById("chatTyping").textContent = "";
            }
        });
    }

    form.addEventListener("submit", async function (event) {
        event.preventDefault();
        var message = input.value.trim();
        if (!message || !activeConversation) return;
        setError("");
        var conversationId = activeConversation;
        var sendButton = form.querySelector(".chat-send");
        sendButton.disabled = true;
        try {
            var result = await KCAPI.api("/api/chat/conversations/" + conversationId + "/messages", {
                method: "POST",
                body: JSON.stringify({message: message})
            });
            if (activeConversation === conversationId) appendMessage(result.message);
            input.value = "";
            refreshConversations().catch(function () {});
            if (socket && socket.connected) {
                socket.emit("user_stop_typing", {conversation_id: conversationId});
            }
        } catch (error) {
            setError(error.message || "Message could not be sent. Please try again.");
        } finally {
            sendButton.disabled = false;
        }
    });

    input.addEventListener("input", function () {
        if (!socket || !socket.connected || !activeConversation) return;
        socket.emit("user_typing", {conversation_id: activeConversation});
        window.clearTimeout(typingTimer);
        typingTimer = window.setTimeout(function () {
            socket.emit("user_stop_typing", {conversation_id: activeConversation});
        }, 1200);
    });

    input.addEventListener("keydown", function (event) {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            form.requestSubmit();
        }
    });

    var searchTimer = null;
    search.addEventListener("input", function () {
        window.clearTimeout(searchTimer);
        searchTimer = window.setTimeout(function () {
            KCAPI.api("/api/chat/students?search=" + encodeURIComponent(search.value.trim()))
                .then(function (result) {
                    students = result.students;
                    renderPeople();
                })
                .catch(function (error) { setError(error.message); });
        }, 180);
    });
    document.getElementById("chatBack").addEventListener("click", function () {
        shell.classList.remove("conversation-open");
        if (socket && socket.connected && activeConversation) {
            socket.emit("leave_conversation", {conversation_id: activeConversation});
        }
        activeConversation = null;
        activeUser = null;
        renderPeople();
    });

    Promise.all([KCAPI.api("/api/profile"), KCAPI.api("/api/chat/students"), KCAPI.api("/api/chat/conversations")])
        .then(function (results) {
            me = results[0].user;
            students = results[1].students;
            conversations = results[2].conversations;
            renderPeople();
            connectSocket();
        })
        .catch(function () {
            window.location.href = "login.html";
        });
})();
