# Deployment guide — Streamlit Community Cloud

This walks through pushing the repo to GitHub and deploying to **Streamlit
Community Cloud** (Topic 8.4) with optional **password protection**
(Topic 8.2). Total time: **~30 minutes**.

> Pre-requisites: You'll need a free GitHub account and a free Streamlit
> account (the Streamlit one can be created via GitHub OAuth — no separate
> signup).

---

## Part 1 — Push the local repo to GitHub (Topic 8.3)

### Step 1.1 — Create the GitHub repo

1. Go to https://github.com/new
2. **Repository name**: e.g., `sao-co-pilot`
3. **Visibility**: Public is fine (no secrets in the repo — `.env` is gitignored)
4. **Do NOT** initialise with README, .gitignore, or licence — we have those already
5. Click **Create repository**

GitHub will show a quickstart page with commands. We want the **"…or push an existing repository from the command line"** section.

### Step 1.2 — Connect local → GitHub

Replace `<USER>` and `<REPO>` with your values:

```powershell
cd "D:\AI\1. MSF_AI_LLM_bootcamp_GovTech_SGPoly_May2026\Capstone assignment"

# Set your real identity (Capstone Owner placeholder was for local commits)
git config user.name  "Your Name"
git config user.email "your@email.com"

# Add GitHub as the "origin" remote
git remote add origin https://github.com/<USER>/<REPO>.git

# Push the main branch (and all commits)
git push -u origin main
```

You'll be prompted for credentials. GitHub no longer accepts password auth — use a **Personal Access Token** instead:
- Generate at https://github.com/settings/tokens (Classic, with `repo` scope)
- When git asks for password, paste the token

After push, refresh the GitHub repo page — you should see all files + commit history.

---

## Part 2 — Deploy to Streamlit Community Cloud (Topic 8.4)

### Step 2.1 — Sign in to Streamlit Cloud

1. Go to https://share.streamlit.io
2. Click **Sign in with GitHub** — authorise Streamlit to read your repos

### Step 2.2 — Create a new app

1. Click **Create app** → **Deploy a public app from GitHub**
2. **Repository**: `<USER>/<REPO>`
3. **Branch**: `main`
4. **Main file path**: `app.py`
5. **App URL**: pick something like `sao-co-pilot.streamlit.app`
6. Click **Advanced settings** ▸ — set Python version to **3.11** or **3.12** for best compatibility
7. Click **Deploy**

Streamlit will:
- Clone your repo
- `pip install -r requirements.txt`
- Run `streamlit run app.py`

First build takes ~3–5 minutes. Subsequent re-deploys (auto-triggered on `git push`) take ~1 min.

### Step 2.3 — Set the OpenAI key as a secret

The app needs `OPENAI_API_KEY` to work. Locally we use `.env`; on Streamlit Cloud we use the platform secrets manager.

1. In Streamlit Cloud, open your app → click **⋮ Settings** → **Secrets**
2. Paste (TOML format):

```toml
OPENAI_API_KEY = "sk-proj-..."
```

3. Click **Save** — the app reboots automatically.

That's it for a public deployment. Anyone with the URL can use the app.

---

## Part 3 — Password protection (Topic 8.2)

If you'd like to restrict access (e.g., during demos), the app supports an
optional password gate (`_require_password()` in `app.py`).

In Streamlit Cloud → **Settings** → **Secrets**, append:

```toml
OPENAI_API_KEY  = "sk-proj-..."
APP_PASSWORD    = "your-chosen-password"
```

Save. The next visit to the app shows a password screen before anything
else loads.

If `APP_PASSWORD` is **not set**, the app stays open (the right default
for local development — `.env` doesn't include it).

### Local testing of the password gate

Add to your local `.env`:

```bash
APP_PASSWORD=test123
```

Restart Streamlit. You'll get the password prompt locally too.

---

## Part 4 — Optional: CLOAK keys (future, Container B)

When you have the CLOAK training API key from the LMS, add to Streamlit
Cloud secrets:

```toml
OPENAI_API_KEY       = "sk-proj-..."
APP_PASSWORD         = "..."
CLOAK_PUBLIC_KEY     = "..."
CLOAK_PRIVATE_KEY    = "..."
```

The PII filter (`pii_filter.py`, not yet built) will read these via
`get_secret()` automatically.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Build fails on `playwright` | Streamlit Cloud can't install browser binaries | Move `playwright` to a separate `requirements-dev.txt`; main `requirements.txt` only needs `openai`, `python-dotenv`, `numpy`, `streamlit`, `tiktoken` for runtime |
| App loads but errors on first query | `OPENAI_API_KEY` not set in secrets | Add it in Streamlit Settings → Secrets |
| Build fails on `numpy` / `tiktoken` | Python version mismatch | Set Python 3.11 or 3.12 in Streamlit advanced settings |
| Password prompt loops on wrong password | `APP_PASSWORD` typo in secrets vs. what user types | Re-check secrets TOML — quotes matter |
| 50 MB warning on push | `data/embeddings/vectors.npy` (12.5 MB) is fine; check no large `*.mp4` slipped through `.gitignore` | `git rm --cached <big-file>`, commit |

---

## Quick deploy timeline

| Step | Effort | Cumulative |
|---|---|---|
| 1.1 — Create GitHub repo | 2 min | 0:02 |
| 1.2 — Push local → GitHub | 5 min | 0:07 |
| 2.1–2.2 — Connect Streamlit Cloud + deploy | 5 min interactive + 5 min build | 0:17 |
| 2.3 — Set OPENAI_API_KEY secret | 2 min | 0:19 |
| 3 — Set APP_PASSWORD (optional) | 2 min | 0:21 |
| Smoke test the live URL | 5 min | 0:26 |

About 30 minutes start to finish.
