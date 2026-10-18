import os
import secrets
from io import BytesIO
from datetime import timedelta

import bleach
import markdown
from cachelib.file import FileSystemCache
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_file, session
from flask_session import Session
from groq import APIStatusError, Groq, GroqError

load_dotenv()

app = Flask(__name__)
MAX_AUDIO_FILE_BYTES = 24_000_000
app.config["MAX_CONTENT_LENGTH"] = 25_000_000
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config.update(
    SECRET_KEY=os.getenv("SESSION_SECRET") or secrets.token_hex(32),
    SESSION_TYPE="cachelib",
    SESSION_CACHELIB=FileSystemCache(
        cache_dir=os.getenv(
            "SESSION_FILE_DIR",
            os.path.join(app.instance_path, "sessions"),
        ),
        threshold=1000,
        default_timeout=24 * 60 * 60,
    ),
    SESSION_PERMANENT=True,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=24),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
)
Session(app)

PREFERRED_MODELS = (
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-20b",
)
MAX_MODEL_ATTEMPTS = 5
MAX_HISTORY_MESSAGES = 20
TRANSCRIPTION_MODELS = {"whisper-large-v3", "whisper-large-v3-turbo"}
SPEECH_VOICES = {
    "canopylabs/orpheus-v1-english": {
        "autumn", "diana", "hannah", "austin", "daniel", "troy",
    },
    "canopylabs/orpheus-arabic-saudi": {
        "abdullah", "fahad", "sultan", "lulwa", "noura", "aisha",
    },
}
SUPPORTED_AUDIO_EXTENSIONS = {
    ".flac", ".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".ogg", ".wav", ".webm",
}


def get_session_history():
    history = session.get("chat_history", [])
    if not isinstance(history, list):
        app.logger.warning("Discarding malformed chat history in server-side session")
        return []
    return [
        message
        for message in history
        if isinstance(message, dict)
        and message.get("role") in {"user", "assistant"}
        and isinstance(message.get("content"), str)
    ][-MAX_HISTORY_MESSAGES:]


def get_api_key():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or api_key == "your_groq_api_key_here":
        return None
    return api_key


def get_active_models(client):
    return [
        model
        for model in client.models.list().data
        if isinstance(getattr(model, "id", None), str)
        and getattr(model, "active", True) is not False
    ]


def is_chat_model(model):
    model_id = model.id.lower()
    if model_id.startswith(("whisper-", "canopylabs/")):
        return False
    if model_id.startswith("meta-llama/llama-prompt-guard-"):
        return False
    return getattr(model, "context_window", 1024) > 512


def get_model_catalog(active_models):
    preferred_model = os.getenv("GROQ_MODEL", PREFERRED_MODELS[0])
    preferred_order = tuple(dict.fromkeys((preferred_model, *PREFERRED_MODELS)))
    chat_models = sorted(
        (
            model.id
            for model in active_models
            if is_chat_model(model)
        ),
        key=lambda model_id: (
            (0, preferred_order.index(model_id))
            if model_id in preferred_order
            else (1, model_id.lower())
        ),
    )
    transcription_models = sorted(
        model.id for model in active_models if model.id in TRANSCRIPTION_MODELS
    )
    speech_models = sorted(
        model.id for model in active_models if model.id in SPEECH_VOICES
    )
    default_chat = next(
        (
            model_id
            for model_id in (preferred_model, *PREFERRED_MODELS)
            if model_id in chat_models
        ),
        chat_models[0] if chat_models else None,
    )
    return {
        "chat": chat_models,
        "transcription": transcription_models,
        "speech": speech_models,
        "default_chat": default_chat,
    }


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/models")
def models():
    api_key = get_api_key()
    if not api_key:
        return jsonify(error="Set GROQ_API_KEY before loading Groq models."), 503

    try:
        active_models = get_active_models(Groq(api_key=api_key))
    except GroqError as exc:
        app.logger.exception("Could not load active Groq models")
        return jsonify(error=f"Could not load Groq models: {exc}"), 502

    return jsonify(get_model_catalog(active_models))


def get_model_candidates(available_models, preferred_model):
    models_by_id = {
        model.id: model
        for model in available_models
        if is_chat_model(model)
    }
    candidates = []

    if preferred_model in models_by_id:
        candidates.append(preferred_model)
    elif preferred_model:
        app.logger.warning(
            "Configured Groq model %s is not currently available; selecting an active model.",
            preferred_model,
        )

    for model_id in PREFERRED_MODELS:
        if model_id in models_by_id and model_id not in candidates:
            candidates.append(model_id)

    discovered_models = sorted(
        (
            model
            for model_id, model in models_by_id.items()
            if model_id not in candidates
        ),
        key=lambda model: getattr(model, "created", 0),
        reverse=True,
    )
    candidates.extend(model.id for model in discovered_models)
    return candidates[:MAX_MODEL_ATTEMPTS]


def is_model_unavailable_error(error):
    if error.status_code in {404, 429}:
        return True
    if error.status_code != 400:
        return False

    body = error.body
    if isinstance(body, dict):
        detail = body.get("error", body)
        message = detail.get("message", "") if isinstance(detail, dict) else str(detail)
    else:
        message = str(body or error)
    message = message.lower()
    return any(
        phrase in message
        for phrase in ("deprecated", "decommissioned", "model not found", "model is not supported")
    )


def create_completion_with_fallback(client, available_models, model, messages):
    candidates = get_model_candidates(available_models, model)
    if not candidates:
        raise RuntimeError("Groq did not return any active chat models.")

    for index, candidate in enumerate(candidates):
        try:
            response = client.chat.completions.create(
                model=candidate,
                messages=messages,
            )
        except APIStatusError as exc:
            if not is_model_unavailable_error(exc) or index == len(candidates) - 1:
                raise
            app.logger.warning(
                "Groq model %s is unavailable (HTTP %s); trying the next active model.",
                candidate,
                exc.status_code,
            )
        else:
            if candidate != model:
                app.logger.info("Groq chat completed using fallback model %s.", candidate)
            return response

    raise RuntimeError("No active Groq model could handle the request.")


@app.get("/api/history")
def get_history():
    return jsonify(messages=get_session_history())


@app.delete("/api/history")
def clear_history():
    session.pop("chat_history", None)
    return jsonify(messages=[])


def validate_selected_model(model_id, available_models, supported_models):
    if not isinstance(model_id, str) or model_id not in supported_models:
        return False
    return any(model.id == model_id for model in available_models)


@app.post("/api/chat")
def chat():
    api_key = get_api_key()
    if not api_key:
        return jsonify(error="Set GROQ_API_KEY in the .env file before chatting."), 503

    data = request.get_json(silent=True)
    content = data.get("message") if isinstance(data, dict) else None
    if not isinstance(content, str) or not content.strip() or len(content) > 12_000:
        return jsonify(error="Message must contain 1 to 12,000 characters."), 400

    client = Groq(api_key=api_key)
    try:
        available_models = get_active_models(client)
    except GroqError as exc:
        app.logger.exception("Could not load active Groq models for chat")
        return jsonify(error=f"Could not load Groq models: {exc}"), 502

    catalog = get_model_catalog(available_models)
    requested_model = data.get("model") if isinstance(data, dict) else None
    model = requested_model or session.get("chat_model") or catalog["default_chat"]
    if not validate_selected_model(model, available_models, catalog["chat"]):
        return jsonify(error="Choose an active Groq chat model and try again."), 400

    history = get_session_history()[-MAX_HISTORY_MESSAGES + 1 :]
    messages = [*history, {"role": "user", "content": content}]

    system_prompt = os.getenv(
        "SYSTEM_PROMPT",
        "You are a helpful assistant. Answer clearly and accurately.",
    )
    try:
        response = create_completion_with_fallback(
            client,
            available_models,
            model,
            [{"role": "system", "content": system_prompt}, *messages],
        )
    except APIStatusError as exc:
        app.logger.exception("Groq chat request failed after model fallback")
        if exc.status_code == 429:
            return jsonify(
                error="Groq rate limits were reached for the available models. Please wait and try again."
            ), 429
        return jsonify(error=f"Groq API request failed: {exc}"), 502
    except GroqError as exc:
        app.logger.exception("Groq API request failed while checking available models")
        return jsonify(error=f"Groq API request failed: {exc}"), 502
    except RuntimeError as exc:
        app.logger.exception("No active Groq model could handle the request")
        return jsonify(error=str(exc)), 502

    answer = response.choices[0].message.content or ""
    history = [*messages, {"role": "assistant", "content": answer}]
    session["chat_history"] = history[-MAX_HISTORY_MESSAGES:]
    session["chat_model"] = model
    session.permanent = True
    formatted_answer = markdown.markdown(
        answer,
        extensions=["fenced_code", "sane_lists", "tables"],
    )
    safe_answer = bleach.clean(
        formatted_answer,
        tags={
            "a", "blockquote", "br", "code", "del", "em", "h1", "h2", "h3",
            "h4", "h5", "h6", "hr", "li", "ol", "p", "pre", "strong",
            "table", "tbody", "td", "th", "thead", "tr", "ul",
        },
        attributes={"a": ["href", "title"]},
        protocols={"http", "https", "mailto"},
        strip=True,
    )
    return jsonify(
        reply=answer,
        reply_html=safe_answer,
        messages=session["chat_history"],
    )


@app.post("/api/transcribe")
def transcribe_audio():
    api_key = get_api_key()
    if not api_key:
        return jsonify(error="Set GROQ_API_KEY before transcribing audio."), 503

    audio_file = request.files.get("audio")
    model = request.form.get("model")
    language = request.form.get("language", "").strip()
    if audio_file is None or not audio_file.filename:
        return jsonify(error="Choose an audio file to transcribe."), 400

    extension = os.path.splitext(audio_file.filename)[1].lower()
    if extension not in SUPPORTED_AUDIO_EXTENSIONS:
        return jsonify(error="Use a supported audio file such as MP3, WAV, M4A, OGG, or WEBM."), 400
    if language and (len(language) != 2 or not language.isalpha()):
        return jsonify(error="Language must be a two-letter language code."), 400

    audio_file.stream.seek(0, os.SEEK_END)
    file_size = audio_file.stream.tell()
    audio_file.stream.seek(0)
    if file_size == 0:
        return jsonify(error="The selected audio file is empty."), 400
    if file_size > MAX_AUDIO_FILE_BYTES:
        return jsonify(error="Audio files must be 24 MB or smaller."), 413

    client = Groq(api_key=api_key)
    try:
        active_models = get_active_models(client)
        catalog = get_model_catalog(active_models)
        if not validate_selected_model(model, active_models, catalog["transcription"]):
            return jsonify(error="Choose an active Groq transcription model and try again."), 400

        arguments = {
            "model": model,
            "file": (
                audio_file.filename,
                audio_file.stream,
                audio_file.mimetype or "application/octet-stream",
            ),
            "response_format": "json",
        }
        if language:
            arguments["language"] = language
        transcription = client.audio.transcriptions.create(**arguments)
    except APIStatusError as exc:
        app.logger.exception("Groq audio transcription failed")
        status = 429 if exc.status_code == 429 else 502
        return jsonify(error=f"Groq audio transcription failed: {exc}"), status
    except GroqError as exc:
        app.logger.exception("Groq audio transcription request failed")
        return jsonify(error=f"Groq audio transcription failed: {exc}"), 502

    return jsonify(text=transcription.text)


@app.post("/api/speech")
def generate_speech():
    api_key = get_api_key()
    if not api_key:
        return jsonify(error="Set GROQ_API_KEY before generating speech."), 503

    data = request.get_json(silent=True)
    text = data.get("text") if isinstance(data, dict) else None
    model = data.get("model") if isinstance(data, dict) else None
    voice = data.get("voice") if isinstance(data, dict) else None
    if not isinstance(text, str) or not text.strip() or len(text) > 200:
        return jsonify(error="Enter 1 to 200 characters of text to speak."), 400

    client = Groq(api_key=api_key)
    try:
        active_models = get_active_models(client)
        catalog = get_model_catalog(active_models)
        if not validate_selected_model(model, active_models, catalog["speech"]):
            return jsonify(error="Choose an active Groq speech model and try again."), 400
        if not isinstance(voice, str) or voice not in SPEECH_VOICES[model]:
            return jsonify(error="Choose a voice supported by the selected speech model."), 400

        audio = client.audio.speech.create(
            model=model,
            voice=voice,
            input=text.strip(),
            response_format="wav",
        )
    except APIStatusError as exc:
        app.logger.exception("Groq speech generation failed")
        status = 429 if exc.status_code == 429 else 502
        return jsonify(error=f"Groq speech generation failed: {exc}"), status
    except GroqError as exc:
        app.logger.exception("Groq speech generation request failed")
        return jsonify(error=f"Groq speech generation failed: {exc}"), 502

    response = send_file(
        BytesIO(audio.read()),
        mimetype="audio/wav",
        as_attachment=False,
        download_name="nano-assistant.wav",
        max_age=0,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify(error="The upload is too large. Audio files must be 24 MB or smaller."), 413


if __name__ == "__main__":
    app.run(
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "5000")),
        debug=False,
    )
