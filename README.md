# LinkedIn Job Digest Cron

GitHub Actions job that runs every 3 hours, scrapes LinkedIn jobs, summarizes new listings with Groq, and sends the digest to a Telegram bot channel.

## Files

| File | Purpose |
| --- | --- |
| `.github/workflows/linkedin-job-digest.yml` | GitHub Actions schedule, manual trigger, and state commit |
| `pyproject.toml` | `uv` project metadata and dependencies |
| `run_linkedin_digest.py` | Runs saved searches, calls Groq, sends Telegram |
| `linkedin_scraper.py` | Scraper copied from the LinkedIn jobs skill |
| `linkedin_cron.py` | Search profile and dedupe runner copied from the skill |
| `search_profiles.example.json` | Optional committed profile template |
| `seen_jobs.json` | Auto-created state file used to avoid duplicate alerts |

## GitHub Setup

This folder is ready to be used as the root of a GitHub repository. If you put it inside a larger repo, the workflow file must still live at that repo root under `.github/workflows/`.

Add these repository secrets:

| Secret | Value |
| --- | --- |
| `GROQ_API_KEY` | Your Groq API key |
| `TELEGRAM_BOT_TOKEN` | Token from BotFather |
| `TELEGRAM_CHAT_ID` | Channel username like `@your_channel` or numeric chat ID |

Make the Telegram bot an admin in the channel so it can post.

Add these repository variables for a simple single-location setup:

| Variable | Example |
| --- | --- |
| `LINKEDIN_KEYWORDS` | `AI Engineer, ML Engineer, Data Scientist` |
| `LINKEDIN_LOCATION` | `Bengaluru, India` |
| `LINKEDIN_EXPERIENCE` | `2,3` |
| `LINKEDIN_REMOTE` | `2,3` |
| `LINKEDIN_JOB_TYPE` | `F` |
| `LINKEDIN_MAX_PAGES` | `2` |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` |

The workflow runs at `0 */3 * * *`, which is every 3 hours in UTC. You can also run it manually from the Actions tab with `workflow_dispatch`.

## Telegram Message Format

Each job is sent as a plain-text card:

```text
1. Company Name | Posted: YYYY-MM-DD
Role: Job title
Location: Job location
Minimum experience required: Experience from the post
Tech stack required: Technologies found in the post
Summary of job profile: Short Groq summary
LinkedIn: https://www.linkedin.com/jobs/view/...
```

## Multiple Profiles

For several independent searches, set the secret `LINKEDIN_SEARCH_PROFILES_JSON` to either:

```json
[
  {
    "keywords": "AI Engineer",
    "location": "Bengaluru, India",
    "experience": "2,3",
    "remote": "2,3",
    "max_pages": 2
  },
  {
    "keywords": "Backend Engineer",
    "location": "Remote",
    "remote": "2",
    "max_pages": 2
  }
]
```

Set `FORCE_PROFILE_SYNC=true` if you want GitHub variables or `LINKEDIN_SEARCH_PROFILES_JSON` to overwrite the committed `search_profiles.json` on each run.

## Local Test

Install `uv`, then run:

```bash
cd linkedin_cron_jobs
uv sync
DRY_RUN=true LINKEDIN_KEYWORDS="AI Engineer" LINKEDIN_LOCATION="Bengaluru, India" uv run --frozen python run_linkedin_digest.py
```

`DRY_RUN=true` prints the Telegram message instead of sending it.

For normal local runs after the first sync:

```bash
uv run --frozen python run_linkedin_digest.py
```

### Windows Git Bash Notes

If `uv sync` fails with `failed to remove file ... .venv\lib64: Access is denied`, delete `.venv` and rerun `uv sync`. That usually means `.venv` was created from WSL/Linux and Windows cannot clean up the Linux symlink.

If you see `warning: Ignoring invalid SSL_CERT_FILE` while Conda is active, leave Conda first or unset the variable:

```bash
conda deactivate
unset SSL_CERT_FILE
uv sync
```
