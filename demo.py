import os
import sys

from dotenv import load_dotenv
from groq import Groq, GroqError


def main() -> int:
    load_dotenv()

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or api_key == "your_groq_api_key_here":
        print(
            "Set GROQ_API_KEY in the .env file before running this script.",
            file=sys.stderr,
        )
        return 1

    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
    system_prompt = os.getenv(
        "SYSTEM_PROMPT",
        "You are a helpful assistant. Answer clearly and accurately.",
    )
    client = Groq(api_key=api_key)
    messages = [{"role": "system", "content": system_prompt}]

    print(f"Chatting with {model}. Type /quit to exit.")
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if user_input.lower() in {"/quit", "/exit"}:
            return 0
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
            )
        except GroqError as exc:
            print(f"Groq API request failed: {exc}", file=sys.stderr)
            return 1

        answer = response.choices[0].message.content or ""
        messages.append({"role": "assistant", "content": answer})
        print(f"Assistant: {answer}")


if __name__ == "__main__":
    raise SystemExit(main())
