"""
Run LinkedIn saved searches, summarize new jobs with Groq, and send Telegram.

This script is designed for GitHub Actions, but it also runs locally when the
required environment variables are set.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from linkedin_cron import (
    SEEN_JOBS_FILE,
    add_profile,
    generate_profile_id,
    get_defaults,
    load_profiles,
    load_seen_jobs,
    mark_jobs_seen,
    run_profiles,
    save_profiles,
    save_seen_jobs,
)


BASE_DIR = Path(__file__).resolve().parent
PROFILES_FILE = BASE_DIR / "search_profiles.json"
TELEGRAM_LIMIT = 4096
SAFE_MESSAGE_LIMIT = 3900


class MissingConfigError(RuntimeError):
    """Raised when a required secret or variable is missing."""


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        print(f"[Digest] Ignoring invalid integer for {name}: {value}", file=sys.stderr)
        return default


def compact_text(value: Any, limit: int = 500) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def normalize_profile(profile: dict[str, Any]) -> dict[str, Any]:
    defaults = get_defaults()
    keywords = compact_text(profile.get("keywords"))
    location = compact_text(profile.get("location"))

    if not keywords:
        raise ValueError("Each profile must include keywords")

    normalized = {
        "id": profile.get("id") or generate_profile_id(keywords, location),
        "keywords": keywords,
        "location": location,
        "experience": str(profile.get("experience") or defaults.get("experience", "")),
        "remote": str(profile.get("remote") or defaults.get("remote", "")),
        "job_type": str(profile.get("job_type") or defaults.get("job_type", "")),
        "date_posted": str(profile.get("date_posted") or defaults.get("date_posted", "r86400")),
        "max_pages": int(profile.get("max_pages") or defaults.get("max_pages", 2)),
        "enabled": bool(profile.get("enabled", True)),
        "created_at": profile.get("created_at") or utc_now_iso(),
        "last_run": profile.get("last_run"),
        "total_jobs_found": int(profile.get("total_jobs_found", 0)),
    }

    # Optional experience cap (None means no cap)
    max_exp = profile.get("max_experience_years")
    if max_exp is None:
        max_exp = defaults.get("max_experience_years")
    normalized["max_experience_years"] = int(max_exp) if max_exp is not None else None

    return normalized


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_state_files() -> None:
    if not PROFILES_FILE.exists():
        save_profiles({"profiles": [], "defaults": get_defaults()})
    if not SEEN_JOBS_FILE.exists():
        save_seen_jobs(load_seen_jobs())


def sync_profiles_from_json_env() -> bool:
    raw = os.getenv("LINKEDIN_SEARCH_PROFILES_JSON", "").strip()
    if not raw:
        return False

    parsed = json.loads(raw)
    if isinstance(parsed, list):
        data = {"profiles": parsed, "defaults": get_defaults()}
    elif isinstance(parsed, dict):
        data = {
            "profiles": parsed.get("profiles", []),
            "defaults": parsed.get("defaults", get_defaults()),
        }
    else:
        raise ValueError("LINKEDIN_SEARCH_PROFILES_JSON must be a JSON object or array")

    data["profiles"] = [normalize_profile(profile) for profile in data["profiles"]]
    save_profiles(data)
    print(f"[Digest] Synced {len(data['profiles'])} profile(s) from JSON env")
    return True


def bootstrap_profile_from_env() -> bool:
    keywords = os.getenv("LINKEDIN_KEYWORDS", "").strip()
    if not keywords:
        return False

    max_pages = None
    if os.getenv("LINKEDIN_MAX_PAGES", "").strip():
        max_pages = env_int("LINKEDIN_MAX_PAGES", get_defaults().get("max_pages", 2))

    result = add_profile(
        keywords=keywords,
        location=os.getenv("LINKEDIN_LOCATION", "").strip(),
        experience=os.getenv("LINKEDIN_EXPERIENCE", "").strip(),
        remote=os.getenv("LINKEDIN_REMOTE", "").strip(),
        job_type=os.getenv("LINKEDIN_JOB_TYPE", "").strip(),
        date_posted=os.getenv("LINKEDIN_DATE_POSTED", "").strip(),
        max_pages=max_pages,
    )

    if not result.get("success"):
        raise RuntimeError(result.get("error", "Failed to add LinkedIn search profile"))

    total_added = result.get("total_added")
    if total_added is None:
        total_added = 1
    print(f"[Digest] Bootstrapped {total_added} profile(s) from env")
    return True


def ensure_profiles() -> None:
    data = load_profiles()
    force_sync = env_bool("FORCE_PROFILE_SYNC", False)

    if force_sync:
        if sync_profiles_from_json_env():
            return
        if bootstrap_profile_from_env():
            return

    if data.get("profiles"):
        print(f"[Digest] Loaded {len(data['profiles'])} saved profile(s)")
        return

    if sync_profiles_from_json_env():
        return
    if bootstrap_profile_from_env():
        return

    print("[Digest] No search profiles configured")


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise MissingConfigError(f"Missing required environment variable: {name}")
    return value


def job_payload(jobs: list[dict[str, Any]]) -> list[dict[str, str]]:
    fields = [
        "title",
        "company",
        "job_id",
        "location",
        "search_keywords",
        "employment_type",
        "experience_level",
        "requirements",
        "tech_stack",
        "role_summary",
        "description",
        "posted_date",
        "url",
    ]

    payload = []
    for job in jobs:
        item = {}
        for field in fields:
            limit = 900 if field in {"role_summary", "description"} else 240
            value = compact_text(job.get(field), limit=limit)
            if value:
                item[field] = value
        payload.append(item)
    return payload


def summarize_jobs_with_groq(result: dict[str, Any], jobs: list[dict[str, Any]]) -> dict[str, str]:
    from groq import Groq

    api_key = require_env("GROQ_API_KEY")
    model = os.getenv("GROQ_MODEL", "").strip() or "llama-3.3-70b-versatile"
    max_tokens = env_int("GROQ_MAX_TOKENS", 1800)

    client = Groq(api_key=api_key)
    digest_input = {
        "run": {
            "utc_time": utc_now_iso(),
            "profiles_run": result.get("profiles_run"),
            "total_scraped": result.get("total_scraped"),
            "total_unique": result.get("total_unique"),
            "total_new": result.get("total_new"),
            "truncated": result.get("truncated"),
            "showing": result.get("showing"),
        },
        "jobs": job_payload(jobs),
    }

    response = client.chat.completions.create(
        model=model,
        temperature=0.2,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You summarize job descriptions for a Telegram digest. Return JSON only. "
                    "For each job, write one concise profile summary under 35 words. Do not "
                    "invent experience, tech stack, links, companies, or dates."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Return JSON in this shape: "
                    '{"summaries":[{"job_id":"...","summary":"..."}]}. '
                    "Use the supplied job_id values exactly.\n\n"
                    + json.dumps(digest_input, ensure_ascii=False)
                ),
            },
        ],
    )
    content = response.choices[0].message.content or "{}"
    data = json.loads(content)
    summaries = data.get("summaries", [])
    if not isinstance(summaries, list):
        raise ValueError("Groq response did not include a summaries list")

    by_id = {}
    for item in summaries:
        if not isinstance(item, dict):
            continue
        job_id = compact_text(item.get("job_id"), 120)
        summary = compact_text(item.get("summary"), 320)
        if job_id and summary:
            by_id[job_id] = summary
    return by_id


def fallback_job_summaries(jobs: list[dict[str, Any]]) -> dict[str, str]:
    summaries = {}
    for job in jobs:
        job_id = str(job.get("job_id") or "")
        summary = (
            compact_text(job.get("role_summary"), 320)
            or compact_text(job.get("description"), 320)
            or "Summary not listed."
        )
        if job_id:
            summaries[job_id] = summary
    return summaries


def field_or_default(value: Any, default: str = "Not listed") -> str:
    return compact_text(value, 500) or default


def posted_date_label(job: dict[str, Any]) -> str:
    posted = compact_text(job.get("posted_date"), 120)
    return posted or "Not listed"


def minimum_experience_label(job: dict[str, Any]) -> str:
    return (
        compact_text(job.get("requirements"), 160)
        or compact_text(job.get("experience_level"), 160)
        or "Not listed"
    )


def job_summary_label(job: dict[str, Any], summaries_by_id: dict[str, str]) -> str:
    job_id = str(job.get("job_id") or "")
    return (
        compact_text(summaries_by_id.get(job_id), 320)
        or compact_text(job.get("role_summary"), 320)
        or compact_text(job.get("description"), 320)
        or "Summary not listed."
    )


def format_job_card(index: int, job: dict[str, Any], summaries_by_id: dict[str, str]) -> str:
    company = field_or_default(job.get("company"))
    title = field_or_default(job.get("title"))
    location = field_or_default(job.get("location"))
    experience = minimum_experience_label(job)
    tech_stack = field_or_default(job.get("tech_stack"))
    summary = job_summary_label(job, summaries_by_id)
    url = field_or_default(job.get("url"))

    return "\n".join(
        [
            f"{index}. {company} | Posted: {posted_date_label(job)}",
            f"Role: {title}",
            f"Location: {location}",
            f"Minimum experience required: {experience}",
            f"Tech stack required: {tech_stack}",
            f"Summary of job profile: {summary}",
            f"LinkedIn: {url}",
        ]
    )


def build_digest_message(
    summaries_by_id: dict[str, str],
    result: dict[str, Any],
    jobs: list[dict[str, Any]],
) -> str:
    run_time = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d %H:%M IST")
    header = [
        "LinkedIn job digest",
        f"Run: {run_time}",
        f"New jobs: {result.get('total_new', len(jobs))}",
    ]
    if result.get("truncated"):
        header.append(f"Showing: {result.get('showing')} of {result.get('total_new')}")

    cards = [
        format_job_card(index, job, summaries_by_id)
        for index, job in enumerate(jobs, start=1)
    ]
    parts = ["\n".join(header), *cards]
    return "\n\n".join(part for part in parts if part).strip()


def build_empty_message(result: dict[str, Any]) -> str:
    run_time = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d %H:%M IST")
    return (
        "LinkedIn job digest\n"
        f"Run: {run_time}\n"
        "No new jobs found.\n"
        f"Profiles run: {result.get('profiles_run', 0)}\n"
        f"Scraped jobs: {result.get('total_scraped', 0)}"
    )


def chunk_message(text: str, limit: int = SAFE_MESSAGE_LIMIT) -> list[str]:
    text = text.strip()
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for line in text.splitlines():
        addition = line if not current else "\n" + line
        if len(current) + len(addition) <= limit:
            current += addition
            continue

        if current:
            chunks.append(current)
        current = ""

        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        current = line

    if current:
        chunks.append(current)
    return chunks


def send_telegram_message(text: str) -> None:
    token = require_env("TELEGRAM_BOT_TOKEN")
    chat_id = require_env("TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    for chunk in chunk_message(text, limit=min(SAFE_MESSAGE_LIMIT, TELEGRAM_LIMIT)):
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "link_preview_options": {"is_disabled": True},
        }
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram sendMessage failed: {data}")


def deliver_message(text: str) -> None:
    if env_bool("DRY_RUN", False):
        print("[Digest] DRY_RUN=true, Telegram message follows:")
        print(text)
        return
    send_telegram_message(text)


def mark_delivered_jobs_seen(jobs: list[dict[str, Any]]) -> None:
    job_ids = [str(job.get("job_id")) for job in jobs if job.get("job_id")]
    if job_ids:
        mark_jobs_seen(job_ids)


def main() -> int:
    ensure_state_files()
    ensure_profiles()

    profile_id = os.getenv("LINKEDIN_PROFILE", "").strip() or None
    result = run_profiles(profile_id=profile_id, mark_seen=False)
    if not result.get("success"):
        raise RuntimeError(result.get("error", "LinkedIn profile run failed"))

    jobs = result.get("new_jobs", [])
    if not jobs:
        print("[Digest] No new jobs found")
        if env_bool("NOTIFY_ON_EMPTY", False):
            deliver_message(build_empty_message(result))
        return 0

    try:
        summaries_by_id = summarize_jobs_with_groq(result, jobs)
    except MissingConfigError:
        raise
    except Exception as exc:  # Keep notifications flowing if Groq has a transient issue.
        print(f"[Digest] Groq summary failed: {exc}", file=sys.stderr)
        summaries_by_id = fallback_job_summaries(jobs)

    message = build_digest_message(summaries_by_id, result, jobs)
    deliver_message(message)
    if not env_bool("DRY_RUN", False):
        mark_delivered_jobs_seen(jobs)
    print(
        json.dumps(
            {
                "sent": True,
                "total_new": result.get("total_new"),
                "showing": result.get("showing"),
                "truncated": result.get("truncated"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except MissingConfigError as exc:
        print(f"[Digest] {exc}", file=sys.stderr)
        raise SystemExit(2)
