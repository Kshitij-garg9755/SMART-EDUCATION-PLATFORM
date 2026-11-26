(function () {
    "use strict";

    var courseId = new URLSearchParams(window.location.search).get("course_id");
    var course = null;
    var currentLesson = null;
    var completedLessonIds = new Set();
    var video = document.getElementById("course-video");
    var videoMessage = document.getElementById("video-message");
    var lessonNotes = document.getElementById("lesson-notes");
    var lessonStatus = document.getElementById("lesson-status");

    function showError(message, offerLogin) {
        var element = document.getElementById("player-error");
        element.textContent = message;
        if (offerLogin) {
            var link = document.createElement("a");
            link.href = "/login.html";
            link.textContent = " Log in";
            element.appendChild(link);
        }
        element.classList.remove("d-none");
    }

    function showAccessMessage(message, price) {
        var element = document.getElementById("course-access");
        element.textContent = message + " ";
        var button = document.createElement("button");
        button.type = "button";
        button.className = "btn btn-sm btn-primary ms-2";
        button.textContent = Number(price) > 0 ? "Buy with UPI" : "Enroll free";
        button.addEventListener("click", startEnrollmentOrCheckout);
        element.appendChild(button);
        element.classList.remove("d-none");
    }

    function notesKey(lessonId) {
        return "kc-course-" + course.id + "-lesson-" + lessonId + "-notes";
    }

    function saveNotes() {
        if (!currentLesson) return;
        localStorage.setItem(notesKey(currentLesson.id), lessonNotes.value);
        lessonStatus.textContent = "Notes saved on this device.";
    }

    function exportNotes() {
        if (!currentLesson) return;
        var blob = new Blob([lessonNotes.value], { type: "text/plain;charset=utf-8" });
        var link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = "course-" + course.id + "-lesson-" + currentLesson.id + "-notes.txt";
        link.click();
        URL.revokeObjectURL(link.href);
    }

    function safeVideoUrl(value) {
        if (typeof value !== "string" || !value.trim()) return "";
        try {
            var url = new URL(value, window.location.origin);
            return url.protocol === "https:" || url.protocol === "http:" ? url.href : "";
        } catch (error) {
            return "";
        }
    }

    function selectLesson(lesson, button) {
        currentLesson = lesson;
        document.querySelectorAll(".lesson-button").forEach(function (item) {
            item.classList.toggle("active", item === button);
        });
        document.getElementById("lesson-title").textContent = lesson.title;
        lessonNotes.value = localStorage.getItem(notesKey(lesson.id)) || "";
        lessonStatus.textContent = lesson.is_preview && !course.enrolled ?
            "Preview lesson" : "Lesson " + lesson.lesson_order;

        var source = safeVideoUrl(lesson.video_url);
        video.pause();
        video.removeAttribute("src");
        video.load();
        if (source) {
            video.src = source;
            videoMessage.classList.add("d-none");
        } else {
            videoMessage.textContent = "The video for this lesson has not been uploaded yet.";
            videoMessage.classList.remove("d-none");
        }
    }

    function renderLessons(lessons) {
        var list = document.getElementById("lesson-list");
        var count = document.getElementById("lesson-count");
        var visibleLessons = Array.isArray(lessons) ? lessons : [];
        count.textContent = visibleLessons.length +
            (visibleLessons.length === 1 ? " lesson available" : " lessons available");
        list.replaceChildren();

        if (!visibleLessons.length) {
            var empty = document.createElement("p");
            empty.className = "small text-muted";
            empty.textContent = "No lessons are available for this course yet.";
            list.appendChild(empty);
            return;
        }

        visibleLessons.forEach(function (lesson) {
            var button = document.createElement("button");
            button.type = "button";
            button.className = "lesson-button";
            button.textContent = lesson.title +
                (lesson.is_preview && !course.enrolled ? " (Preview)" : "");
            if (completedLessonIds.has(lesson.id)) button.classList.add("done");
            button.addEventListener("click", function () {
                selectLesson(lesson, button);
            });
            list.appendChild(button);
        });

        var firstButton = list.querySelector(".lesson-button");
        if (firstButton) firstButton.click();
    }

    async function startEnrollmentOrCheckout() {
        var button = document.querySelector("#course-access button");
        if (button) {
            button.disabled = true;
            button.textContent = Number(course.price) > 0 ? "Opening checkout…" : "Enrolling…";
        }
        try {
            if (Number(course.price) > 0) {
                var order = await KCAPI.api("/api/payments/upi/orders", {
                    method: "POST",
                    body: JSON.stringify({ course_id: Number(course.id) })
                });
                window.location.href = "/upi-payment.html?id=" +
                    encodeURIComponent(order.payment.id);
                return;
            }
            await KCAPI.api("/api/courses/" + encodeURIComponent(course.id) + "/enroll", {
                method: "POST",
                body: JSON.stringify({})
            });
            window.location.reload();
        } catch (error) {
            var needsLogin = /authentication required|student account required/i.test(error.message);
            showError(
                needsLogin ? "Sign in with a student account to continue." : error.message,
                needsLogin
            );
            if (button) {
                button.disabled = false;
                button.textContent = Number(course.price) > 0 ? "Buy with UPI" : "Enroll free";
            }
        }
    }

    async function completeLesson() {
        if (!course || !course.enrolled || !currentLesson) return;
        try {
            await KCAPI.api("/api/lessons/" + encodeURIComponent(currentLesson.id) + "/complete", {
                method: "POST",
                body: JSON.stringify({})
            });
            completedLessonIds.add(currentLesson.id);
            var activeButton = document.querySelector(".lesson-button.active");
            if (activeButton) activeButton.classList.add("done");
            lessonStatus.textContent = "Lesson completed and progress saved.";
        } catch (error) {
            lessonStatus.textContent = "Could not save lesson progress: " + error.message;
        }
    }

    async function loadCourse() {
        if (!courseId || !/^\d+$/.test(courseId)) {
            showError("Choose a course from the course catalog to open its lessons.");
            document.getElementById("course-title").textContent = "Course not selected";
            return;
        }
        try {
            var result = await KCAPI.api("/api/courses/" + encodeURIComponent(courseId));
            course = result.course;
            document.title = course.title + " | Kshitij Coder";
            document.getElementById("course-title").textContent = course.title;
            document.getElementById("course-description").textContent = course.description || "";
            if (!course.enrolled) {
                showAccessMessage(
                    Number(course.price) > 0 ?
                        "Preview access only. Complete payment to unlock the full course." :
                        "Preview access only. Enroll to unlock all published lessons.",
                    course.price
                );
            }
            renderLessons(course.lessons);
        } catch (error) {
            document.getElementById("course-title").textContent = "Course unavailable";
            showError(error.message);
        }
    }

    video.addEventListener("ended", completeLesson);
    document.getElementById("save-notes").addEventListener("click", saveNotes);
    document.getElementById("export-notes").addEventListener("click", exportNotes);
    loadCourse();
})();
