const form = document.querySelector("#chat-form");
const promptInput = document.querySelector("#prompt");
const sendButton = document.querySelector("#send");
const clearButton = document.querySelector("#clear");
const messagesElement = document.querySelector("#messages");
const welcome = document.querySelector("#welcome");
const errorBanner = document.querySelector("#error");
const conversation = [];
sendButton.disabled = true;
clearButton.disabled = true;

function addMessage(role, content) {
  const message = document.createElement("article");
  message.className = `message ${role}`;

  const label = document.createElement("div");
  label.className = "message-label";
  label.textContent = role === "user" ? "You" : "Assistant";

  const text = document.createElement("div");
  text.className = "message-content";
  text.textContent = content;

  message.append(label, text);
  messagesElement.append(message);
  message.scrollIntoView({ behavior: "smooth", block: "end" });
  return text;
}

function resizePrompt() {
  promptInput.style.height = "auto";
  promptInput.style.height = `${Math.min(promptInput.scrollHeight, 180)}px`;
}

async function restoreHistory() {
  try {
    const response = await fetch("/api/history");
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not restore this chat.");
    if (!Array.isArray(data.messages)) {
      throw new Error("The server returned invalid chat history.");
    }

    for (const message of data.messages) {
      if (
        !message ||
        !["user", "assistant"].includes(message.role) ||
        typeof message.content !== "string"
      ) {
        throw new Error("The server returned invalid chat history.");
      }
      conversation.push(message);
      addMessage(message.role, message.content);
    }
    welcome.hidden = conversation.length > 0;
  } catch (error) {
    errorBanner.textContent = error.message || "Could not restore this chat.";
    errorBanner.hidden = false;
  } finally {
    sendButton.disabled = false;
    clearButton.disabled = false;
  }
}

restoreHistory();
promptInput.addEventListener("input", resizePrompt);

document.querySelectorAll(".suggestion").forEach((button) => {
  button.addEventListener("click", () => {
    promptInput.value = button.textContent;
    resizePrompt();
    promptInput.focus();
  });
});

clearButton.addEventListener("click", async () => {
  if (clearButton.disabled) return;
  clearButton.disabled = true;
  errorBanner.hidden = true;
  try {
    const response = await fetch("/api/history", { method: "DELETE" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not clear this chat.");

    conversation.length = 0;
    messagesElement.replaceChildren();
    welcome.hidden = false;
    promptInput.focus();
  } catch (error) {
    errorBanner.textContent = error.message || "Could not clear this chat.";
    errorBanner.hidden = false;
  } finally {
    clearButton.disabled = false;
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const content = promptInput.value.trim();
  if (!content || sendButton.disabled) return;

  welcome.hidden = true;
  errorBanner.hidden = true;
  conversation.push({ role: "user", content });
  addMessage("user", content);
  promptInput.value = "";
  resizePrompt();
  sendButton.disabled = true;
  clearButton.disabled = true;

  const pending = addMessage("assistant", "Thinking...");
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: content }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "The request failed.");

    if (typeof data.reply !== "string") {
      throw new Error("The server returned no reply. Restart the app and try again.");
    }
    if (typeof data.reply_html === "string") {
      pending.innerHTML = data.reply_html;
    } else {
      pending.textContent = data.reply;
    }
    conversation.push({ role: "assistant", content: data.reply });
    if (Array.isArray(data.messages)) {
      conversation.splice(0, conversation.length, ...data.messages);
    }
  } catch (error) {
    pending.closest(".message").remove();
    conversation.pop();
    errorBanner.textContent = error.message || "Could not reach the server.";
    errorBanner.hidden = false;
  } finally {
    sendButton.disabled = false;
    clearButton.disabled = false;
    promptInput.focus();
  }
});

promptInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});
