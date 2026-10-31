from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections.abc import AsyncIterator
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from playwright.async_api import BrowserContext, Page

from ..config import HiristFiltersConfig
from ..cookies import slugify
from ..page_load import goto_settled, scroll_lazy_page, wait_for_page_settled
from ..utils import JobListing
from .auth import HIRIST_ORIGIN

logger = logging.getLogger("job_apply")

_JOB_HREF = re.compile(r"/j/[a-z0-9-]+", re.I)

# Hirist's JSON API (the site calls it "gladiator"). Search pages render no employer
# name, so the detail endpoint is the only cheap source of company + declared salary.
HIRIST_API = "https://gladiator.hirist.tech"
_JOB_CODE = re.compile(r"-(\d+)$")

# One evaluate() per card instead of a locator round-trip per field.
_CARD_FIELDS_JS = r"""
(a) => {
  const card = a.closest('.joblist-card-v2')
    || a.closest('[class*="joblist-card"]')
    || a.parentElement;
  const pick = (id) => {
    const el = card && card.querySelector('[data-testid="' + id + '"]');
    return el ? (el.innerText || '').trim() : '';
  };
  return {
    title: pick('job_title'),
    salary: pick('job_salary'),
    experience: pick('job_experience'),
    location: pick('job_location'),
    text: (a.innerText || '').trim(),
  };
}
"""


def _paginated_url(base_url: str, page_num: int) -> str:
    """Hirist uses ?page=N (page 1 omits the param)."""
    if page_num <= 1:
        return base_url
    parsed = urlparse(base_url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    qs["page"] = [str(page_num)]
    query = urlencode(qs, doseq=True)
    return urlunparse(parsed._replace(query=query))


def _with_experience_params(url: str, filters: HiristFiltersConfig) -> str:
    if filters.experience_min is None and filters.experience_max is None:
        return url
    parsed = urlparse(url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    if filters.experience_min is not None:
        qs["minexp"] = [str(filters.experience_min)]
    if filters.experience_max is not None:
        qs["maxexp"] = [str(filters.experience_max)]
    query = urlencode(qs, doseq=True)
    return urlunparse(parsed._replace(query=query))


def _search_url(filters: HiristFiltersConfig) -> str:
    keyword = slugify(filters.keywords[0] if filters.keywords else "backend")
    if filters.cities:
        city = slugify(filters.cities[0])
        url = f"{HIRIST_ORIGIN}/k/{keyword}-jobs-in-{city}"
    else:
        url = f"{HIRIST_ORIGIN}/k/{keyword}-jobs"
    return _with_experience_params(url, filters)


def feed_urls(filters: HiristFiltersConfig) -> list[str]:
    if filters.search_urls:
        return [_with_experience_params(u, filters) for u in filters.search_urls]
    return [_search_url(filters)]


async def apply_filters(page: Page, filters: HiristFiltersConfig) -> None:
    if filters.search_urls:
        logger.info("Hirist using %d configured search URL(s)", len(filters.search_urls))
        return

    url = _search_url(filters)
    await goto_settled(page, url)

    if filters.experience:
        try:
            exp = page.get_by_text(re.compile(filters.experience.replace("-", r"[-–]"), re.I))
            if await exp.count() > 0:
                await exp.first.click()
                await page.wait_for_timeout(500)
        except Exception:
            logger.warning("Could not set Hirist experience filter")

    await page.wait_for_timeout(600)
    logger.info("Hirist filters applied: %s", page.url)


def _job_id(href: str, title: str) -> str:
    return hashlib.sha1(f"{href}|{title}".encode()).hexdigest()[:16]


async def _merge_jobs_on_page(page: Page, jobs: dict[str, JobListing], limit: int) -> int:
    before = len(jobs)
    links = page.locator('a[href*="/j/"]')
    count = await links.count()
    for i in range(count):
        if len(jobs) >= limit:
            break
        link = links.nth(i)
        href = await link.get_attribute("href") or ""
        if not _JOB_HREF.search(href):
            continue
        full_url = urljoin(HIRIST_ORIGIN, href.split("?")[0])
        try:
            info = await link.evaluate(_CARD_FIELDS_JS) or {}
        except Exception:
            info = {}
        text = str(info.get("text") or "").strip()
        if len(text) < 3:
            continue
        title = str(info.get("title") or "").strip() or text.split("\n")[0].strip()
        if len(title) < 3:
            continue
        job_id = _job_id(full_url, title)
        salary = str(info.get("salary") or "").strip()
        meta: dict = {}
        if salary:
            meta["salary"] = salary
            meta["salary_display"] = salary
        experience = str(info.get("experience") or "").strip()
        if experience:
            meta["experience"] = experience
        location = str(info.get("location") or "").strip()
        if location:
            meta["location"] = location
        jobs.setdefault(
            job_id,
            JobListing(
                job_id=job_id,
                title=title,
                company="",
                url=full_url,
                source="hirist",
                easy_apply=True,
                meta=meta,
            ),
        )
    return len(jobs) - before


async def iter_job_listings(page: Page, limit: int) -> AsyncIterator[JobListing]:
    jobs: dict[str, JobListing] = {}
    await _merge_jobs_on_page(page, jobs, limit)
    for listing in list(jobs.values()):
        yield listing

    stable = 0
    for round_num in range(40):
        if len(jobs) >= limit:
            break
        before = set(jobs.keys())
        await page.mouse.wheel(0, 2500)
        await scroll_lazy_page(page, rounds=2, pause_ms=200)
        await wait_for_page_settled(page, extra_ms=200)
        await _merge_jobs_on_page(page, jobs, limit)
        added = len(jobs) - len(before)
        if added == 0:
            stable += 1
            if stable >= 3:
                break
        else:
            stable = 0
            if round_num % 8 == 7:
                logger.info("Hirist scrolling… %d listings so far", len(jobs))
            for job_id in jobs:
                if job_id not in before:
                    yield jobs[job_id]


async def collect_srp_page(page: Page, limit: int = 500) -> list[JobListing]:
    """Collect jobs on the current SRP page only (no multi-page infinite scroll)."""
    jobs: dict[str, JobListing] = {}
    await _merge_jobs_on_page(page, jobs, limit)
    await scroll_lazy_page(page, rounds=2, pause_ms=200)
    await wait_for_page_settled(page, extra_ms=200)
    await _merge_jobs_on_page(page, jobs, limit)
    return list(jobs.values())


async def iter_paginated_feed_pages(
    page: Page,
    filters: HiristFiltersConfig,
    *,
    max_pages: int | None = None,
) -> AsyncIterator[tuple[str, int, list[JobListing]]]:
    """Yield (feed_url, page_num, jobs) — apply after each page before continuing."""
    pages_cap = max_pages if max_pages is not None else filters.max_pages
    if pages_cap < 1:
        pages_cap = 1

    for feed_url in feed_urls(filters):
        for page_num in range(1, pages_cap + 1):
            url = _paginated_url(feed_url, page_num)
            logger.info("Hirist feed page %d: %s", page_num, url)
            await goto_settled(page, url, timeout_ms=90_000, quick=page_num > 1)
            jobs = await collect_srp_page(page)
            if not jobs:
                if page_num > 1:
                    logger.info("Hirist feed ended at page %d (no listings)", page_num)
                break
            yield feed_url, page_num, jobs


async def collect_job_listings(page: Page, limit: int) -> list[JobListing]:
    """Collect all listings on current page with infinite scroll (legacy single-page scrape)."""
    seen: set[str] = set()
    listings: list[JobListing] = []
    async for job in iter_job_listings(page, limit):
        if job.job_id in seen:
            continue
        seen.add(job.job_id)
        listings.append(job)
        if len(listings) >= limit:
            break
    logger.info("Found %d Hirist listings on page", len(listings))
    return listings[:limit]


async def collect_from_search_urls(page: Page, urls: list[str], limit: int) -> list[JobListing]:
    merged: dict[str, JobListing] = {}
    per_feed = limit if limit > 0 else 2000
    for feed_idx, url in enumerate(urls):
        logger.info("Hirist feed: %s", url)
        await goto_settled(page, url, timeout_ms=90_000, quick=feed_idx > 0)
        for job in await collect_srp_page(page, per_feed):
            merged[job.job_id] = job
        if limit > 0 and len(merged) >= limit:
            break
    result = list(merged.values())[:limit] if limit > 0 else list(merged.values())
    logger.info("Found %d Hirist listings across %d feed(s)", len(result), len(urls))
    return result


def _job_code(url: str) -> str:
    """Hirist job URLs end in the numeric job code ("...-1680135")."""
    match = _JOB_CODE.search(url.split("?")[0].rstrip("/"))
    return match.group(1) if match else ""


def _salary_from_detail(data: dict) -> str:
    if data.get("hideSal"):
        return ""
    low = data.get("minSal") or 0
    high = data.get("maxSal") or 0
    try:
        low, high = float(low), float(high)
    except (TypeError, ValueError):
        return ""
    if high > 0 and low > 0 and high != low:
        return f"{low:g}-{high:g} LPA"
    single = high or low
    return f"{single:g} LPA" if single > 0 else ""


async def enrich_hirist_jobs(
    context: BrowserContext,
    jobs: list[JobListing],
    *,
    concurrency: int = 8,
) -> None:
    """Fill company (and salary when the card hid it) from Hirist's detail API.

    Search-result cards never render the employer name, so one-job-per-company and
    the salary floor have nothing to work with until the detail endpoint is read.
    Failures are non-fatal: the listing is kept with whatever the card provided.
    """
    targets = [job for job in jobs if not job.company]
    if not targets:
        return

    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def enrich(job: JobListing) -> None:
        code = _job_code(job.url)
        if not code:
            return
        async with semaphore:
            try:
                response = await context.request.get(
                    f"{HIRIST_API}/job/detail?jobcode={code}", timeout=15_000
                )
                if not response.ok:
                    return
                payload = await response.json()
            except Exception as exc:  # network hiccup / non-JSON error page
                logger.debug("Hirist detail lookup failed for %s: %s", job.url, exc)
                return
        data = (payload or {}).get("data") or {}
        company = str(((data.get("companyData") or {}).get("companyName")) or "").strip()
        if company:
            job.company = company
        if not job.meta.get("salary"):
            salary = _salary_from_detail(data)
            if salary:
                job.meta["salary"] = salary
                job.meta["salary_display"] = salary

    await asyncio.gather(*(enrich(job) for job in targets))
    logger.info(
        "Hirist: enriched %d/%d job(s) with company/salary detail",
        sum(1 for job in targets if job.company),
        len(targets),
    )

