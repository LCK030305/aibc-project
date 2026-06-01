# Docker — containerised deployment

Containerising the app turns it into a single portable artefact that
runs **identically** on any machine with Docker — your laptop, a
colleague's, a server, or GovTech's CStack Kubernetes platform.

Maps to bootcamp **Xtra Topic 1 — *"Deploying Prototype as a Containerized
App"***.

> Prerequisite: Docker Desktop on Windows/Mac OR Docker Engine on Linux.
> Install from https://www.docker.com/products/docker-desktop/

---

## Build the image

From the project root:

```powershell
cd "D:\AI\1. MSF_AI_LLM_bootcamp_GovTech_SGPoly_May2026\Capstone assignment"
docker build -t sao-co-pilot:latest .
```

First build downloads the Python base image (~120 MB) and installs
deps — takes ~3–5 minutes. Re-builds after code changes are ~10 seconds
(thanks to layer caching).

Final image size: **~600 MB** (Python 3.11-slim + deps + corpus +
embeddings). Tight enough for most container registries.

---

## Run locally (with your `.env`)

```powershell
docker run -p 8501:8501 --env-file .env sao-co-pilot:latest
```

Open http://localhost:8501.

The `-p 8501:8501` maps the container's port 8501 to your host's 8501.
The `--env-file .env` loads `OPENAI_API_KEY` (and any other secrets)
from your local `.env` into the container's environment.

To stop: `Ctrl+C`.

---

## Run with explicit secrets (production pattern)

For deployment, you don't want `.env` files lying around — pass secrets
explicitly at run time:

```powershell
docker run -p 8501:8501 `
  -e OPENAI_API_KEY="sk-proj-..." `
  -e APP_PASSWORD="..." `
  sao-co-pilot:latest
```

When the CLOAK PII layer ships, also add:

```powershell
  -e CLOAK_PUBLIC_KEY="..." `
  -e CLOAK_PRIVATE_KEY="..." `
```

The `get_secret()` helper in `llm.py` reads from `os.environ` (or
`st.secrets` if running on Streamlit Cloud), so the same secret name
works everywhere.

---

## Run detached (background) — useful for a long-running demo

```powershell
docker run -d -p 8501:8501 --env-file .env --name sao-co-pilot sao-co-pilot:latest
```

- `-d` runs detached (returns a container ID, frees your terminal)
- `--name sao-co-pilot` names the container for easy reference

Manage it:

```powershell
docker logs -f sao-co-pilot       # tail logs
docker stop sao-co-pilot          # graceful stop
docker rm   sao-co-pilot          # remove stopped container
```

---

## Healthcheck

The image declares a healthcheck (`/_stcore/health` every 30s). Orchestrators
(Kubernetes, CStack, Docker Swarm) use this to detect a wedged container
and restart it automatically. View the current status:

```powershell
docker inspect --format='{{.State.Health.Status}}' sao-co-pilot
```

Outputs `healthy`, `starting`, or `unhealthy`.

---

## Deploying to GovTech CStack (Xtra Topic 1)

CStack is GovTech's internal Kubernetes platform. High-level path:

1. **Tag** the image for the CStack container registry:
   ```
   docker tag sao-co-pilot:latest <cstack-registry>/<namespace>/sao-co-pilot:v1.0
   ```
2. **Push** to the registry (requires CStack auth):
   ```
   docker push <cstack-registry>/<namespace>/sao-co-pilot:v1.0
   ```
3. **Deploy** via the CStack UI or `kubectl apply -f deployment.yaml`,
   referencing the image tag and setting secrets via Kubernetes
   `Secret` objects.

Detailed CStack deployment is covered in the bootcamp Xtra notes — this
file just gets you to a containerised image ready for that path.

---

## Image-size optimisation (optional, future work)

The current image bundles `playwright` (Python package) which the runtime
doesn't actually use — only the offline scraper does. To trim ~5–10 MB:

```dockerfile
# In requirements.txt, split into:
#   requirements.txt          (runtime: openai, python-dotenv, numpy,
#                              streamlit, tiktoken)
#   requirements-dev.txt      (dev only: playwright, python-pptx)
```

…and `pip install -r requirements.txt` in the Dockerfile. Skipped for
now — the marginal savings aren't worth the added complexity for a
capstone demo.

---

## Quick reference

| What | Command |
|---|---|
| Build | `docker build -t sao-co-pilot:latest .` |
| Run (foreground) | `docker run -p 8501:8501 --env-file .env sao-co-pilot:latest` |
| Run (background) | `docker run -d -p 8501:8501 --env-file .env --name sao-co-pilot sao-co-pilot:latest` |
| Stop | `docker stop sao-co-pilot` |
| Remove | `docker rm sao-co-pilot` |
| Inspect health | `docker inspect --format='{{.State.Health.Status}}' sao-co-pilot` |
| View logs | `docker logs -f sao-co-pilot` |
| Open shell inside | `docker exec -it sao-co-pilot /bin/bash` |
