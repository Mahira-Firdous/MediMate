
// Display today's date on the dashboard.
const todayElement = document.getElementById("today");

if (todayElement) {
    todayElement.textContent = new Date().toLocaleDateString(
        undefined,
        {
            weekday: "long",
            year: "numeric",
            month: "long",
            day: "numeric"
        }
    );
}

// Handle questions submitted to the MediMate assistant.
const chatForm = document.getElementById("chat-form");

if (chatForm) {
    chatForm.addEventListener("submit", async function (event) {
        event.preventDefault();

        const questionInput = document.getElementById("user-question");
        const chatBox = document.getElementById("chat-box");
        const status = document.getElementById("chat-status");
        const sendButton = document.getElementById("send-button");

        const question = questionInput.value.trim();

        if (!question) return;

        // Display the user's question.
        const userMessage = document.createElement("div");
        userMessage.className = "chat-message user-message";
        userMessage.textContent = question;
        chatBox.appendChild(userMessage);

        questionInput.value = "";
        sendButton.disabled = true;
        status.textContent = "Preparing a response...";

        try {
            // Send the question to our Flask backend.
            const response = await fetch("/assistant", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ question: question })
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.answer || "Request failed.");
            }

            // Display the assistant's response safely as text.
            const botMessage = document.createElement("div");
            botMessage.className = "chat-message bot-message";
            botMessage.textContent = data.answer;
            chatBox.appendChild(botMessage);

            status.textContent = "Response received.";
        } catch (error) {
            status.textContent =
                "Unable to get a response. Please try again.";
        } finally {
            sendButton.disabled = false;
            chatBox.scrollTop = chatBox.scrollHeight;
            questionInput.focus();
        }
    });
}
