import os

import bleach
import markdown
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from groq import Groq, GroqError

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1_000_000
app.config["TEMPLATES_AUTO_RELOAD"] = True


@app.get("/")
def index():
    return render_template("index.html", model=os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"))


@app.post("/api/chat")
def chat():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or api_key == "your_groq_api_key_here":
        return jsonify(error="Set GROQ_API_KEY in the .env file before chatting."), 503

    data = request.get_json(silent=True)
    messages = data.get("messages") if isinstance(data, dict) else None
    if not isinstance(messages, list) or not messages or len(messages) > 40:
        return jsonify(error="Send between 1 and 40 conversation messages."), 400

    validated_messages = []
    for message in messages:
        if not isinstance(message, dict):
            return jsonify(error="Each message must contain a role and text content."), 400
        role = message.get("role")
        content = message.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            return jsonify(error="Messages must have a user or assistant role and text content."), 400
        if not content.strip() or len(content) > 12_000:
            return jsonify(error="Messages must contain 1 to 12,000 characters."), 400
        validated_messages.append({"role": role, "content": content})

    if validated_messages[-1]["role"] != "user":
        return jsonify(error="The latest conversation message must be from you."), 400

    system_prompt = os.getenv(
        "SYSTEM_PROMPT",
        "You are a helpful assistant. Answer clearly and accurately.",
    )
    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
    try:
        response = Groq(api_key=api_key).chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_prompt}, *validated_messages],
        )
    except GroqError as exc:
        app.logger.exception("Groq API request failed")
        return jsonify(error=f"Groq API request failed: {exc}"), 502

    answer = response.choices[0].message.content or ""
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
    return jsonify(reply=answer, reply_html=safe_answer)


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify(error="The conversation request is too large."), 413


if __name__ == "__main__":
    app.run(
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "5000")),
        debug=False,
    )
