from __future__ import annotations

import logging
import re

from playwright.async_api import BrowserContext, Page
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeout

from ..apply_runner import run_apply_batch
from ..config import AppConfig
from ..limits import apply_cap
from ..role_filter import role_filter_kwargs, should_skip_role
from ..utils import JobListing, job_key, save_applied_job
from .auth import INSTAHYRE_OPPORTUNITIES
from .feeds import (
    InstahyreFeedSpec,
    _dismiss_apply_modal,
    _wait_for_opportunities,
    activate_feed,
    feeds_from_config,
)
from .search import (
    EMPLOYER_ROW,
    _scroll_load_more,
    click_view_at,
    employer_rows,
    job_id_from_card,
    parse_company_title,
    view_buttons,
)

logger = logging.getLogger("job_apply")

APPLY_MODAL = ".application-modal.candidate-apply-modal"


def _instahyre_delay_ms(config: AppConfig) -> int:
    return config.application.platform_delays.instahyre_ms


def _instahyre_advance_ms(config: AppConfig) -> int:
    return config.application.platform_delays.instahyre_advance_ms


async def _delay(page: Page, config: AppConfig) -> None:
    try:
        await page.wait_for_timeout(_instahyre_delay_ms(config))
    except PlaywrightError as exc:
        if "Target page, context or browser has been closed" in str(exc):
            raise
        logger.debug("Delay interrupted: %s", exc)


async def _read_job_panel(page: Page) -> tuple[str, str]:
    modal = page.locator(APPLY_MODAL)
    scope = modal.last if await modal.count() > 0 else page.locator(EMPLOYER_ROW).first
    if await modal.count() == 0 and await employer_rows(page).count() == 0:
        scope = page.locator("body")

    name_el = scope.locator(".employer-job-name .company-name, .employer-details .company-name, .modal-title, h1, h2")
    if await name_el.count() > 0:
        full = (await name_el.first.inner_text()).strip()
        if full:
            company, title = parse_company_title(full)
            return title, company

    text = await scope.inner_text()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    skip = {"view »", "view", "applied", "apply", "save", "hide", "share", "not interested"}
    filtered = [ln for ln in lines if ln.lower() not in skip]
    if not filtered:
        return "Unknown", ""
    company, title = parse_company_title(filtered[0])
    return title, company


_ADVANCE_NEXT_JOB_JS = """
() => {
  const wrap = document.querySelector(
    ".application-modal.candidate-apply-modal .application-modal-wrap"
  );
  if (!wrap) return { ok: false, reason: "no modal" };
  const scope = angular.element(wrap).scope();
  if (scope?.swipeOpp && scope?.opp) {
    scope.$apply(() => scope.swipeOpp(scope.opp, "next"));
    return { ok: true, via: "swipeOpp" };
  }
  return { ok: false, reason: "no swipeOpp" };
}
"""


async def _advance_to_next_job(page: Page, config: AppConfig) -> bool:
    """Move to next job in Instahyre's apply modal queue."""
    modal = page.locator(".application-modal.candidate-apply-modal")
    if await modal.count() == 0:
        return False

    before = await _read_job_panel(page)
    try:
        result = await page.evaluate(_ADVANCE_NEXT_JOB_JS)
        if isinstance(result, dict) and result.get("ok"):
            await page.wait_for_timeout(_instahyre_delay_ms(config))
            after = await _read_job_panel(page)
            return after != before
    except Exception:
        pass

    try:
        await page.keyboard.press("ArrowRight")
        await page.wait_for_timeout(_instahyre_advance_ms(config))
        after = await _read_job_panel(page)
        if after != before:
            return True
    except Exception:
        pass

    return False


async def _dismiss_modal(page: Page) -> None:
    await _dismiss_apply_modal(page)


async def _visible_apply_button(page: Page):
    """First visible Apply control inside Instahyre's job modal."""
    scope = page.locator(APPLY_MODAL)
    if await scope.count() == 0:
        return None

    for pattern in (r"^apply$", r"apply now", r"quick apply"):
        buttons = scope.get_by_role("button", name=re.compile(pattern, re.I))
        for i in range(await buttons.count()):
            button = buttons.nth(i)
            try:
                if await button.is_visible():
                    return button
            except Exception:
                continue

    fallback = scope.locator("button.btn-primary.new-btn")
    for i in range(await fallback.count()):
        button = fallback.nth(i)
        try:
            if await button.is_visible() and "company site" not in (await button.inner_text()).lower():
                return button
        except Exception:
            continue
    return None


async def _has_apply_button(page: Page) -> bool:
    return await _visible_apply_button(page) is not None


async def _click_apply(page: Page) -> bool:
    button = await _visible_apply_button(page)
    if button is None:
        return False
    try:
        await button.click(timeout=5000)
        return True
    except PlaywrightTimeout:
        return False


async def _try_apply_current(page: Page, config: AppConfig, feed_key: str) -> bool:
    """Click Apply on the open job modal when the button is visible."""
    title, company = await _read_job_panel(page)
    if config.application.dry_run:
        if await _has_apply_button(page):
            logger.info("[DRY RUN] Would apply on Instahyre: %s @ %s", title, company or "?")
        return False
    if not await _has_apply_button(page):
        return False
    if not await _click_apply(page):
        return False
    jid = job_id_from_card(title, company, feed_key)
    key = job_key("instahyre", jid)
    save_applied_job(
        config.applied_jobs_path,
        key,
        {"source": "instahyre", "title": title, "company": company, "url": feed_key},
    )
    logger.info("Applied on Instahyre: %s @ %s", title, company or "?")
    return True


async def _apply_chain_from_view(
    page: Page,
    config: AppConfig,
    feed_key: str,
    *,
    cap: int | None,
    already_applied: int,
) -> int:
    """Apply through Instahyre's modal queue — advance when Apply is missing."""
    applied = 0
    stuck = 0

    for _ in range(500):
        if cap is not None and already_applied + applied >= cap:
            break

        if config.application.dry_run:
            if await _has_apply_button(page):
                title, company = await _read_job_panel(page)
                logger.info("[DRY RUN] Would apply on Instahyre: %s @ %s", title, company or "?")
            elif not await _advance_to_next_job(page, config):
                stuck += 1
            else:
                stuck = 0
            if stuck >= 8:
                break
            continue

        if await _has_apply_button(page):
            if await _try_apply_current(page, config, feed_key):
                applied += 1
                stuck = 0
                if await _advance_to_next_job(page, config):
                    continue
            else:
                stuck += 1
        elif await _advance_to_next_job(page, config):
            stuck = 0
            continue
        else:
            stuck += 1

        if stuck >= 8:
            logger.info("Modal apply chain ended after %d applies on this feed segment", applied)
            break

        await _delay(page, config)

    return applied


_ROWS_JS = """
() => [...document.querySelectorAll('div.employer-row')].map((row) => ({
  name: (row.querySelector('.employer-job-name')?.innerText || '').trim(),
  has_view: !!row.querySelector('.btn-interested, #interested-btn, button.button-interested'),
}))
"""


async def _first_acceptable_row(
    page: Page,
    config: AppConfig,
    handled: set[str],
) -> tuple[int, str] | None:
    """First visible row whose title passes the role/company filters."""
    rows = await page.evaluate(_ROWS_JS)
    kwargs = role_filter_kwargs(config.profile)
    skip_companies = [c.lower() for c in config.profile.skip_companies]
    for index, row in enumerate(rows or []):
        name = str(row.get("name") or "").strip()
        if not name or not row.get("has_view") or name in handled:
            continue
        if any(company in name.lower() for company in skip_companies):
            continue
        _company, title = parse_company_title(name)
        if should_skip_role(title, **kwargs)[0]:
            logger.info("Skipping role: %s", name)
            handled.add(name)
            continue
        return index, name
    return None


async def apply_feed(page: Page, spec: InstahyreFeedSpec, config: AppConfig, applied_ids: set[str]) -> int:
    feed_key = await activate_feed(page, spec)

    applied = 0
    cap = apply_cap(config.application.max_jobs_per_run)
    handled: set[str] = set()

    for _ in range(20):
        if cap is not None and applied >= cap:
            break

        picked = await _first_acceptable_row(page, config, handled)
        if picked is None:
            logger.info("No acceptable rows left on feed %s", spec.name)
            break

        index, full_name = picked
        handled.add(full_name)
        if not await click_view_at(page, index):
            logger.warning("Could not click View on feed: %s", spec.name)
            break

        await page.wait_for_timeout(_instahyre_delay_ms(config))
        company, title = parse_company_title(full_name)

        if config.application.dry_run:
            if await _has_apply_button(page):
                logger.info("[DRY RUN] Would apply on Instahyre: %s @ %s", title, company)
            else:
                logger.info("[DRY RUN] No apply button for Instahyre job: %s", full_name)
            await _dismiss_modal(page)
            continue

        if not await _has_apply_button(page):
            logger.info("No apply button for Instahyre job: %s", full_name)
            await _dismiss_modal(page)
            continue

        if not await _click_apply(page):
            logger.warning("Could not click Apply for Instahyre job: %s", full_name)
            await _dismiss_modal(page)
            continue

        await page.wait_for_timeout(2500)
        jid = job_id_from_card(title, company, feed_key)
        save_applied_job(
            config.applied_jobs_path,
            job_key("instahyre", jid),
            {"source": "instahyre", "title": title, "company": company, "url": feed_key},
        )
        applied += 1
        logger.info("Applied on Instahyre: %s @ %s", title, company or "?")

        await _dismiss_modal(page)
        await _scroll_load_more(page, rounds=1)

    return applied


async def apply_from_feeds(
    page: Page,
    config: AppConfig,
    applied_ids: set[str],
    *,
    search_urls: list[str] | None = None,
    feed_dicts: list[dict] | None = None,
    default_job_functions: list[str] | None = None,
    job_function_aliases: dict[str, str] | None = None,
    default_skills: str | None = None,
    skill_chip_values: dict[str, str] | None = None,
    skill_type_queries: dict[str, str] | None = None,
) -> int:
    total = 0
    for spec in feeds_from_config(
        search_urls=search_urls,
        feed_dicts=feed_dicts,
        default_job_functions=default_job_functions,
        job_function_aliases=job_function_aliases,
        default_skills=default_skills,
        skill_chip_values=skill_chip_values,
        skill_type_queries=skill_type_queries,
    ):
        total += await apply_feed(page, spec, config, applied_ids)
        cap = apply_cap(config.application.max_jobs_per_run)
        if cap is not None and total >= cap:
            break
    return total


async def apply_to_job(
    page: Page,
    _context: BrowserContext | None,
    job: JobListing,
    config: AppConfig,
) -> bool | None:
    feed_url = str(job.meta.get("feed_url", job.url or "")).strip()
    card_index = int(job.meta.get("card_index", 0))

    if not feed_url:
        logger.warning("No Instahyre feed URL for: %s", job.title)
        return False

    if feed_url not in page.url:
        await page.goto(f"{INSTAHYRE_OPPORTUNITIES}?matching=true", wait_until="domcontentloaded", timeout=90000)
        await _delay(page, config)
        await _wait_for_opportunities(page)

    if not await click_view_at(page, card_index):
        logger.warning("Could not click View for: %s", job.title)
        return False
    await _delay(page, config)

    if config.application.dry_run:
        logger.info("[DRY RUN] Would apply on Instahyre: %s", job.title)
        return None

    if not await _click_apply(page):
        logger.warning("No apply button for Instahyre job: %s", job.title)
        return False

    save_applied_job(
        config.applied_jobs_path,
        job_key("instahyre", job.job_id),
        {"source": "instahyre", "title": job.title, "company": job.company, "url": feed_url},
    )
    logger.info("Applied on Instahyre: %s @ %s", job.title, job.company or "?")
    return True


async def apply_batch(
    page: Page,
    context: BrowserContext | None,
    jobs: list[JobListing],
    config: AppConfig,
) -> int:
    # Instahyre applies sequentially (one job at a time); parallel tabs caused
    # feed/modal races, so it intentionally ignores instahyre_apply_workers.
    return await run_apply_batch(
        jobs,
        config,
        page,
        context,
        apply_to_job,
        workers=1,
    )
