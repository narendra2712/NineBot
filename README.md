# Nano Assistant

A small Groq-powered chat web app built with Flask.

## Run locally

1. Create and activate a virtual environment:

   ```powershell
   py -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

2. Install dependencies and configure the environment:

   ```powershell
   pip install -r requirements.txt
   Copy-Item .env.example .env
   ```

3. Put your Groq API key and a unique `SESSION_SECRET` in `.env`, then start the app. Generate a secret with `python -c "import secrets; print(secrets.token_hex(32))"`:

   ```powershell
   python app.py
   ```

   Open <http://127.0.0.1:5000>.

## Deploy to Render

1. Push this project to a GitHub repository.
2. In Render, create a Blueprint from that repository. Render will read `render.yaml`.
3. Enter `GROQ_API_KEY` in Render when prompted. Set it as a secret in Render only; never commit `.env` or paste the key into source code.
4. Deploy the `ninebot` web service. Render provides its public URL after the deploy succeeds.

The Groq API key is read on the server and is not sent to the browser. This app uses Groq-hosted inference and prompt-based behavior; it does not fine-tune model weights.

Chat history is stored in a server-side session for up to 24 hours and restored after a page refresh. The rolling memory sends at most the latest 20 user/assistant messages to Groq. Use **New chat** to clear the session. The selected chat model and light/dark theme are remembered in the browser. On Render's free service, session data is temporary and can be lost when the service restarts or redeploys; persistent cross-deploy history requires a database-backed session store.

Use **Translate chat to Telugu** to show a Telugu translation under each original message without changing the saved conversation. Enable **Telugu replies** to have future assistant responses written in Telugu; this preference is stored in the current server-side browser session. Both features use the selected Groq chat model, and translation is limited to conversations with up to 30,000 characters.

Each assistant response also has **Translate & play Telugu audio**. The Telugu translation is generated with the selected Groq chat model, then spoken using a Telugu voice installed in the user's browser/device. Groq's hosted voices do not currently include Telugu; if no Telugu browser voice is installed, the translated text is still shown with setup guidance and can be played after adding a device voice.

## Model selection and fallback

The chat model selector is populated from Groq's active models API. By default, Nano Assistant prefers `openai/gpt-oss-120b`; set `GROQ_MODEL` to choose a different default. If the selected model is unavailable, deprecated, or rate-limited, chat tries other active models. Rate limits can apply across your Groq organization, so switching models may not avoid an organization-wide limit.

## Audio tools

- **Audio to text** uploads audio to Groq's transcription endpoint. Active Whisper Large V3 and Whisper Large V3 Turbo models are offered when available. Supported file types include FLAC, MP3, MP4, MPEG, MPGA, M4A, OGG, WAV, and WEBM; files are limited to 24 MB.
- **Text to audio** uses active Groq Orpheus models with English or Saudi Arabic voices. Speech input is limited to 200 characters, matching Groq's current speech endpoint limit.
- The app does not generate images: Groq currently documents image understanding (vision), not an image-generation API. Image features were skipped as selected.

The Groq API key remains server-side. Audio files are sent directly to Groq for processing and are not stored by this app.
