# NineBot

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

3. Put your Groq API key in `.env`, then start the app:

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
