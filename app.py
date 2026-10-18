import os
import secrets
from datetime import timedelta

import bleach
import markdown
from cachelib.file import FileSystemCache
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, session
from flask_session import Session
from groq import APIStatusError, Groq, GroqError

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1_000_000
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


@app.get("/")
def index():
    return render_template("index.html")


def get_model_candidates(available_models, preferred_model):
    models_by_id = {
        model.id: model
        for model in available_models
        if isinstance(getattr(model, "id", None), str)
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


def create_completion_with_fallback(client, model, messages):
    available_models = client.models.list().data
    candidates = get_model_candidates(available_models, model)
    if not candidates:
        raise RuntimeError("Groq did not return any active models.")

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


@app.post("/api/chat")
def chat():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or api_key == "your_groq_api_key_here":
        return jsonify(error="Set GROQ_API_KEY in the .env file before chatting."), 503

    data = request.get_json(silent=True)
    content = data.get("message") if isinstance(data, dict) else None
    if not isinstance(content, str) or not content.strip() or len(content) > 12_000:
        return jsonify(error="Message must contain 1 to 12,000 characters."), 400

    history = get_session_history()[-MAX_HISTORY_MESSAGES + 1 :]
    messages = [*history, {"role": "user", "content": content}]

    system_prompt = os.getenv(
        "SYSTEM_PROMPT",
        "You are a helpful assistant. Answer clearly and accurately.",
    )
    model = os.getenv("GROQ_MODEL", PREFERRED_MODELS[0])
    client = Groq(api_key=api_key)
    try:
        response = create_completion_with_fallback(
            client,
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


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify(error="The conversation request is too large."), 413


if __name__ == "__main__":
    app.run(
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "5000")),
        debug=False,
    )
