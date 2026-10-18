const form = document.querySelector("#chat-form");
const promptInput = document.querySelector("#prompt");
const sendButton = document.querySelector("#send");
const clearButton = document.querySelector("#clear");
const messagesElement = document.querySelector("#messages");
const welcome = document.querySelector("#welcome");
const errorBanner = document.querySelector("#error");
const conversation = [];

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

promptInput.addEventListener("input", resizePrompt);

document.querySelectorAll(".suggestion").forEach((button) => {
  button.addEventListener("click", () => {
    promptInput.value = button.textContent;
    resizePrompt();
    promptInput.focus();
  });
});

clearButton.addEventListener("click", () => {
  conversation.length = 0;
  messagesElement.replaceChildren();
  welcome.hidden = false;
  errorBanner.hidden = true;
  promptInput.focus();
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
      body: JSON.stringify({ messages: conversation }),
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
