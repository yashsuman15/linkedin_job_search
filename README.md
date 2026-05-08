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

This folder is ready to be used as the root of a GitHub repository. The workflow file must be present on your default branch at:

```text
.github/workflows/linkedin-job-digest.yml
```

Recommended setup: create a GitHub repository from the contents of `linkedin_cron_jobs`, so `.github/workflows/linkedin-job-digest.yml`, `run_linkedin_digest.py`, `pyproject.toml`, and `uv.lock` are all at the repository root.

If you keep `linkedin_cron_jobs` inside a larger repository, move/copy the workflow file to the larger repository's root `.github/workflows/` directory and adjust the workflow commands to run from `linkedin_cron_jobs`.

### 1. Push the Project

Commit and push these files to GitHub:

```text
.github/workflows/linkedin-job-digest.yml
.python-version
.gitignore
pyproject.toml
uv.lock
run_linkedin_digest.py
linkedin_cron.py
linkedin_scraper.py
geo_ids.json
config.example.json
search_profiles.example.json
README.md
```

Do not commit `.venv`, `.uv-cache`, `.env`, or `config.json`.

### 2. Enable Workflow Write Permission

The cron stores sent job IDs in `seen_jobs.json` so you only get unique jobs. GitHub Actions must be allowed to commit that file back to the repository.

In GitHub:

```text
Repository -> Settings -> Actions -> General -> Workflow permissions
```

Select:

```text
Read and write permissions
```

Keep the workflow-level permission in the YAML:

```yaml
permissions:
  contents: write
```

### 3. Add Repository Secrets

Go to:

```text
Repository -> Settings -> Secrets and variables -> Actions -> Secrets
```

Add these repository secrets for the current multi-profile setup:

| Secret | Value |
| --- | --- |
| `GROQ_API_KEY` | Your Groq API key |
| `TELEGRAM_BOT_TOKEN` | Token(s) from BotFather (comma-separated for multiple) |
| `TELEGRAM_CHAT_ID` | Channel username(s) like `@your_channel` or numeric chat ID (comma-separated for multiple) |
| `LINKEDIN_SEARCH_PROFILES_JSON` | Full JSON copied from `search_profiles.example.json` |

Make the Telegram bot an admin in the channel so it can post.

`LINKEDIN_SEARCH_PROFILES_JSON` is a secret because it is a large structured value and can contain your personal search preferences. The workflow reads it and creates/updates `search_profiles.json` during each run when `FORCE_PROFILE_SYNC=true`.

For your current setup it contains six searches:

| Keyword | Location |
| --- | --- |
| `AI Engineer` | `Noida, India` |
| `AI Engineer` | `Bengaluru, India` |
| `AI Developer` | `Noida, India` |
| `AI Developer` | `Bengaluru, India` |
| `RAG AI Engineer` | `Noida, India` |
| `RAG AI Engineer` | `Bengaluru, India` |

All six profiles use:

| Field | Value | Meaning |
| --- | --- | --- |
| `experience` | `2` | LinkedIn entry-level filter, closest to roughly 1 year |
| `remote` | `1,3` | On-site + hybrid |
| `job_type` | `F` | Full-time |
| `date_posted` | `r86400` | Last 24 hours |
| `max_pages` | `2` | Scrape about 50 jobs per profile |

### 4. Add Repository Variables

Go to:

```text
Repository -> Settings -> Secrets and variables -> Actions -> Variables
```

Add this required variable:

| Variable | Example |
| --- | --- |
| `FORCE_PROFILE_SYNC` | `true` |

Add these optional variables if you want to override defaults:

| Variable | Example |
| --- | --- |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` |
| `GROQ_MAX_TOKENS` | `3000` |
| `NOTIFY_ON_EMPTY` | `false` |

GitHub stores variables as strings. Use lowercase `true` and `false` for booleans. The runner also accepts `TRUE`, `yes`, `1`, and `on` as true values.

You do not need these single-profile variables when `LINKEDIN_SEARCH_PROFILES_JSON` is set:

```text
LINKEDIN_KEYWORDS
LINKEDIN_LOCATION
LINKEDIN_EXPERIENCE
LINKEDIN_REMOTE
LINKEDIN_JOB_TYPE
LINKEDIN_DATE_POSTED
LINKEDIN_MAX_PAGES
```

Those are only for a simpler one-search setup.

### 5. Start the Cron Job

The workflow already contains both triggers:

```yaml
on:
  schedule:
    - cron: "0 */3 * * *"
  workflow_dispatch:
```

The schedule runs every 3 hours in UTC from the latest commit on the default branch.

To start immediately:

1. Open the GitHub repository.
2. Go to the `Actions` tab.
3. Select `LinkedIn Job Digest`.
4. Click `Run workflow`.
5. Choose the default branch.
6. Click `Run workflow`.

After the first successful run, GitHub creates/updates:

```text
search_profiles.json
seen_jobs.json
```

`seen_jobs.json` is the dedupe store. It contains job IDs already sent to Telegram.

### 6. Confirm It Is Working

Open the workflow run logs and check for:

```text
Run LinkedIn digest
Persist scraper state
```

A successful run should:

1. Install `uv`.
2. Run `uv sync --locked`.
3. Scrape LinkedIn.
4. Summarize new jobs with Groq.
5. Send the Telegram message.
6. Commit `seen_jobs.json` and `search_profiles.json` if they changed.

If the workflow says there are no new jobs, that can be correct if the job IDs are already present in `seen_jobs.json`.

### Troubleshooting

If the workflow does not appear in GitHub Actions, confirm the file is on the default branch at `.github/workflows/linkedin-job-digest.yml`.

If jobs repeat every run, confirm workflow write permission is enabled and the `Persist scraper state` step can push commits.

If Telegram does not receive messages, confirm the bot is an admin in the channel(s) and `TELEGRAM_CHAT_ID` contains valid channel username(s) like `@your_channel` or numeric chat ID(s). Also ensure the number of bot tokens matches the number of chat IDs if using multiple channels (or provide just one token/chat ID to apply to all).

If Groq fails, confirm `GROQ_API_KEY` is set as a secret and `GROQ_MODEL` is a valid Groq chat model.

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

## Search Profiles JSON

Use [search_profiles.example.json](search_profiles.example.json) as the source for your `LINKEDIN_SEARCH_PROFILES_JSON` secret.

The secret may be either:

1. The full object from `search_profiles.example.json`, including `profiles` and `defaults`.
2. Just a JSON array of profile objects.

The full object is recommended because it keeps defaults beside the profiles.

When `FORCE_PROFILE_SYNC=true`, GitHub Actions copies the secret value into `search_profiles.json` at the start of the run. That keeps your GitHub secret as the source of truth.

## Local Test

Install `uv`, then run:

```bash
cd linkedin_cron_jobs
uv sync
cp search_profiles.example.json search_profiles.json
uv run --frozen python linkedin_cron.py run --no-mark-seen
```

That checks scraping and dedupe without Groq or Telegram.

To test scraping with Groq formatting but without Telegram delivery:

```bash
GROQ_API_KEY="your_groq_key" DRY_RUN=true uv run --frozen python run_linkedin_digest.py
```

`DRY_RUN=true` prints the Telegram message instead of sending it and does not mark jobs as seen.

To test the real Groq + Telegram flow:

```bash
GROQ_API_KEY="your_groq_key" TELEGRAM_BOT_TOKEN="token1,token2" TELEGRAM_CHAT_ID="@channel1,@channel2" uv run --frozen python run_linkedin_digest.py
```

### Windows Git Bash Notes

If `uv sync` fails with `failed to remove file ... .venv\lib64: Access is denied`, delete `.venv` and rerun `uv sync`. That usually means `.venv` was created from WSL/Linux and Windows cannot clean up the Linux symlink.

If you see `warning: Ignoring invalid SSL_CERT_FILE` while Conda is active, leave Conda first or unset the variable:

```bash
conda deactivate
unset SSL_CERT_FILE
uv sync
```
