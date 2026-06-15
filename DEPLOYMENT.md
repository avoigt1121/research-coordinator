# Deployment & Dev-Branch Workflow

How code reaches the live Hugging Face Spaces, and how to test safely **without
touching production**. Read this before pushing anything.

> **Golden rule:** Do all work on `dev`. **Never push to a production target
> unless you explicitly mean to release.** For this repo, production = pushing
> `main` to `origin`. Default to dev; promote to prod only on request.

---

## The one thing that can deploy to prod by accident

For **research-coordinator**, `main` *is* production:

```
push to origin/main ──> GitHub Action (.github/workflows/sync-to-hf-space.yml)
                        force-pushes origin/main ──> hf Space (anne-voigt/research_coordinator)  [LIVE]
```

The Action triggers on `push` to **`main` only** (`branches: [main]`). Therefore:

- Pushing **`dev`** (or any non-main branch) to `origin` does **NOT** deploy. Safe.
- Pushing **`main`** to `origin` **DOES** deploy to the live Space. Treat every
  `main` push as a production release.
- Do **not** push directly to the `hf` remote — the next `main` push force-overwrites it.

---

## Per-repo deploy map

| Repo | `origin` is… | What deploys to PROD | Dev target |
|------|-------------|----------------------|------------|
| **research-coordinator** | GitHub (source of truth) | push `main` → Action syncs to `hf` Space | `dev` branch (no auto-deploy); see "Dev Space" below |
| **DecoupleRpy_Agent** | the **PROD** HF Space (`Paper2Agent_decoupleRpy`) | push `main` to `origin` | `dev` branch → push to `hf-dev` Space (`..._dev`) |
| **biodata-registry** | GitHub (pip-only, no Space) | nothing auto-deploys; consumers pin a commit | push `main` freely; "deploy" = bump the pin in a consumer repo |

Key asymmetry: in **DecoupleRpy_Agent**, `origin` itself is the prod Space, so
`git push origin main` deploys directly. In **research-coordinator**, `origin` is
GitHub and a CI Action does the deploy. Either way, **pushing `main` = going live.**

---

## Standard workflow (research-coordinator)

```bash
# 1. Always start from dev
git checkout dev
git pull origin dev          # if collaborating

# 2. Work, commit on dev
git add -p && git commit -m "…"

# 3. Push dev — this does NOT deploy; it just backs up / shares your work
git push origin dev

# 4. Test (see "Testing" below)

# 5. ONLY when you intend to release to production:
git checkout main
git merge --ff-only dev      # or a reviewed merge
git push origin main         # <-- this deploys to the live Space
git checkout dev             # go back to dev for the next change
```

If a release misbehaves, roll back by pushing the previous good `main`:
`git push origin main --force-with-lease` after resetting `main` to the last good commit.

---

## Testing without hitting prod

There are two levels of "dev":

**A. Code-level (always available).** Work on `dev`, run the app locally:

```bash
python app.py        # or: gradio gradio_ui.py
```

Local runs never touch any Space. This is enough for most logic/router changes.

**B. A live dev Space (recommended before launch).** research-coordinator has no
dev Space yet (DecoupleRpy_Agent does: `Paper2Agent_decoupleRpy_dev`). To get one,
mirroring the Agent's setup:

1. Create a Space `anne-voigt/research_coordinator_dev` (Gradio SDK) on HF.
2. Set its `ANTHROPIC_API_KEY` secret (same as prod).
3. Add a remote and push `dev` to it:
   ```bash
   git remote add hf-dev https://huggingface.co/spaces/anne-voigt/research_coordinator_dev
   git push hf-dev dev:main      # Spaces build from their own `main` branch
   ```
4. Test against the dev Space URL. Promote to prod only via the step-5 flow above.

Until that Space exists, treat **local runs** as the dev environment and keep all
in-progress work on `dev`.

> Note: pointing the dev coordinator at a dev specialist — set the specialist
> Space in `agents.yaml` to `Paper2Agent_decoupleRpy_dev` on the `dev` branch — lets
> you test the full chain (coordinator + specialist) without touching either prod Space.

---

## Quick reference — "am I about to deploy to prod?"

You are deploying to **production** if and only if you run one of:

- `git push origin main`  (research-coordinator → triggers the sync Action)
- `git push origin main`  (DecoupleRpy_Agent → origin IS the prod Space)

Anything else — `git push origin dev`, `git push hf-dev …`, local runs — is safe.
When in doubt, check your branch (`git branch --show-current`) before pushing.
