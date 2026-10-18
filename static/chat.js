const form = document.querySelector("#chat-form");
const promptInput = document.querySelector("#prompt");
const sendButton = document.querySelector("#send");
const clearButton = document.querySelector("#clear");
const messagesElement = document.querySelector("#messages");
const welcome = document.querySelector("#welcome");
const errorBanner = document.querySelector("#error");
const chatModel = document.querySelector("#chat-model");
const transcriptionModel = document.querySelector("#transcription-model");
const speechModel = document.querySelector("#speech-model");
const speechVoice = document.querySelector("#speech-voice");
const conversation = [];

function showError(message) {
  errorBanner.textContent = message;
  errorBanner.hidden = false;
}

function hideError() {
  errorBanner.hidden = true;
  errorBanner.textContent = "";
}

async function readJson(response) {
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error("The server returned an unreadable response.");
  }
  if (!response.ok) throw new Error(data.error || "The request failed.");
  return data;
}

function getSavedValue(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function saveValue(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    return;
  }
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const dark = theme === "dark";
  const label = document.querySelector("#theme-label");
  const button = document.querySelector("#theme-toggle");
  label.textContent = dark ? "Light mode" : "Dark mode";
  button.setAttribute("aria-label", `Switch to ${dark ? "light" : "dark"} mode`);
  document.querySelector('meta[name="theme-color"]').content = dark ? "#141713" : "#f5f5f2";
  saveValue("nano-theme", theme);
}

document.querySelector("#theme-toggle").addEventListener("click", () => {
  const nextTheme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  setTheme(nextTheme);
});
setTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");

function addMessage(role, content) {
  const message = document.createElement("article");
  message.className = `message ${role}`;

  const label = document.createElement("div");
  label.className = "message-label";
  label.textContent = role === "user" ? "You" : "Nano";

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

function fillModelSelect(select, models, savedModel, defaultModel) {
  select.replaceChildren();
  for (const model of models) {
    const option = document.createElement("option");
    option.value = model;
    option.textContent = model;
    select.append(option);
  }
  const selected = models.includes(savedModel) ? savedModel : defaultModel;
  if (selected && models.includes(selected)) select.value = selected;
  select.disabled = models.length === 0;
  return Boolean(selected && models.includes(selected));
}

const speechVoices = {
  "canopylabs/orpheus-v1-english": [
    ["autumn", "Autumn"], ["diana", "Diana"], ["hannah", "Hannah"],
    ["austin", "Austin"], ["daniel", "Daniel"], ["troy", "Troy"],
  ],
  "canopylabs/orpheus-arabic-saudi": [
    ["abdullah", "Abdullah"], ["fahad", "Fahad"], ["sultan", "Sultan"],
    ["lulwa", "Lulwa"], ["noura", "Noura"], ["aisha", "Aisha"],
  ],
};

function updateSpeechVoices() {
  const previousVoice = speechVoice.value;
  const voices = speechVoices[speechModel.value] || [];
  speechVoice.replaceChildren();
  for (const [id, name] of voices) {
    const option = document.createElement("option");
    option.value = id;
    option.textContent = name;
    speechVoice.append(option);
  }
  if (voices.some(([id]) => id === previousVoice)) speechVoice.value = previousVoice;
  speechVoice.disabled = voices.length === 0;
}

async function loadModels() {
  try {
    const catalog = await readJson(await fetch("/api/models"));
    const chatAvailable = fillModelSelect(
      chatModel,
      catalog.chat,
      getSavedValue("nano-chat-model"),
      catalog.default_chat,
    );
    fillModelSelect(
      transcriptionModel,
      catalog.transcription,
      getSavedValue("nano-transcription-model"),
      catalog.transcription[0],
    );
    const speechAvailable = fillModelSelect(
      speechModel,
      catalog.speech,
      getSavedValue("nano-speech-model"),
      catalog.speech[0],
    );
    updateSpeechVoices();
    sendButton.disabled = !chatAvailable;
    document.querySelector("#transcribe-button").disabled = catalog.transcription.length === 0;
    document.querySelector("#speech-button").disabled = !speechAvailable;
    if (!chatAvailable) showError("No active Groq chat models are available for this API key.");
  } catch (error) {
    showError(error.message || "Could not load the active Groq models.");
  }
}

async function restoreHistory() {
  try {
    const data = await readJson(await fetch("/api/history"));
    if (!Array.isArray(data.messages)) throw new Error("The server returned invalid chat history.");
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
    showError(error.message || "Could not restore this chat.");
  } finally {
    clearButton.disabled = false;
  }
}

document.querySelectorAll(".mode-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".mode-tab").forEach((candidate) => {
      const selected = candidate === tab;
      candidate.classList.toggle("active", selected);
      candidate.setAttribute("aria-selected", String(selected));
      candidate.tabIndex = selected ? 0 : -1;
    });
    document.querySelectorAll(".tool-view").forEach((view) => {
      const selected = view.id === tab.dataset.view;
      view.classList.toggle("active", selected);
      view.hidden = !selected;
    });
    hideError();
  });
  tab.addEventListener("keydown", (event) => {
    const tabs = [...document.querySelectorAll(".mode-tab")];
    const currentIndex = tabs.indexOf(tab);
    let nextIndex;
    if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % tabs.length;
    if (event.key === "ArrowLeft") nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = tabs.length - 1;
    if (nextIndex === undefined) return;
    event.preventDefault();
    tabs[nextIndex].click();
    tabs[nextIndex].focus();
  });
});

document.querySelectorAll(".suggestion").forEach((button) => {
  button.addEventListener("click", () => {
    promptInput.value = button.textContent;
    resizePrompt();
    promptInput.focus();
  });
});

chatModel.addEventListener("change", () => saveValue("nano-chat-model", chatModel.value));
transcriptionModel.addEventListener("change", () =>
  saveValue("nano-transcription-model", transcriptionModel.value));
speechModel.addEventListener("change", () => {
  saveValue("nano-speech-model", speechModel.value);
  updateSpeechVoices();
});

promptInput.addEventListener("input", resizePrompt);

clearButton.addEventListener("click", async () => {
  if (clearButton.disabled) return;
  clearButton.disabled = true;
  hideError();
  try {
    await readJson(await fetch("/api/history", { method: "DELETE" }));
    conversation.length = 0;
    messagesElement.replaceChildren();
    welcome.hidden = false;
    promptInput.focus();
  } catch (error) {
    showError(error.message || "Could not clear this chat.");
  } finally {
    clearButton.disabled = false;
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const content = promptInput.value.trim();
  if (!content || sendButton.disabled) return;

  welcome.hidden = true;
  hideError();
  conversation.push({ role: "user", content });
  addMessage("user", content);
  promptInput.value = "";
  resizePrompt();
  sendButton.disabled = true;
  clearButton.disabled = true;

  const pending = addMessage("assistant", "Thinking...");
  try {
    const data = await readJson(await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: content, model: chatModel.value }),
    }));

    if (typeof data.reply !== "string") {
      throw new Error("The server returned no reply. Please try again.");
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
    showError(error.message || "Could not reach the server.");
  } finally {
    sendButton.disabled = chatModel.options.length === 0;
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

const audioFile = document.querySelector("#audio-file");
const transcribeForm = document.querySelector("#transcribe-form");
const transcribeButton = document.querySelector("#transcribe-button");
audioFile.addEventListener("change", () => {
  document.querySelector("#file-name").textContent =
    audioFile.files[0]?.name || "Choose an audio file";
});

transcribeForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = audioFile.files[0];
  if (!file) {
    showError("Choose an audio file to transcribe.");
    return;
  }
  if (file.size > 24_000_000) {
    showError("Audio files must be 24 MB or smaller.");
    return;
  }

  hideError();
  transcribeButton.disabled = true;
  transcribeButton.textContent = "Transcribing...";
  const body = new FormData();
  body.append("audio", file);
  body.append("model", transcriptionModel.value);
  body.append("language", document.querySelector("#audio-language").value);
  try {
    const data = await readJson(await fetch("/api/transcribe", { method: "POST", body }));
    document.querySelector("#transcription-text").value = data.text;
    document.querySelector("#transcription-result").hidden = false;
  } catch (error) {
    showError(error.message || "Could not transcribe this audio file.");
  } finally {
    transcribeButton.disabled = transcriptionModel.options.length === 0;
    transcribeButton.textContent = "Transcribe audio";
  }
});

document.querySelector("#send-transcript").addEventListener("click", () => {
  const text = document.querySelector("#transcription-text").value;
  if (!text) return;
  document.querySelector("#chat-tab").click();
  promptInput.value = text;
  resizePrompt();
  promptInput.focus();
});

const speechText = document.querySelector("#speech-text");
const speechButton = document.querySelector("#speech-button");
const speechPlayer = document.querySelector("#speech-player");
let speechObjectUrl = null;

speechText.addEventListener("input", () => {
  document.querySelector("#character-count").textContent = `${speechText.value.length} / 200`;
});

document.querySelector("#speech-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!speechText.value.trim() || speechButton.disabled) return;
  hideError();
  speechButton.disabled = true;
  speechButton.textContent = "Generating...";
  try {
    const response = await fetch("/api/speech", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: speechText.value,
        model: speechModel.value,
        voice: speechVoice.value,
      }),
    });
    if (!response.ok) {
      const data = await readJson(response);
      throw new Error(data.error || "Could not generate speech.");
    }
    if (speechObjectUrl) URL.revokeObjectURL(speechObjectUrl);
    speechObjectUrl = URL.createObjectURL(await response.blob());
    speechPlayer.src = speechObjectUrl;
    speechPlayer.hidden = false;
    await speechPlayer.play();
  } catch (error) {
    showError(error.message || "Could not generate speech.");
  } finally {
    speechButton.disabled = speechModel.options.length === 0;
    speechButton.textContent = "Generate speech";
  }
});

loadModels();
restoreHistory();
