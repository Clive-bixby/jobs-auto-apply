from __future__ import annotations

import logging
import random
import re
from datetime import datetime

from playwright.async_api import BrowserContext, Page
from playwright.async_api import TimeoutError as PlaywrightTimeout

from ..config import AppConfig
from ..utils import JobListing, job_key, save_applied_job
from .auth import UPLERS_JOBS_URLS

logger = logging.getLogger("job_apply")

APPLY_FORM = "form#apply-form"
APPLY_SUBMIT = f'{APPLY_FORM} input[type="submit"][value="Apply Now"]'


async def _close_drawer(page: Page) -> None:
    for selector in (".modalCloseBtn", ".drawerCloseBtn", ".closeBtn"):
        btn = page.locator(selector)
        if await btn.count():
            try:
                await btn.first.click(timeout=2000)
                await page.wait_for_timeout(800)
                return
            except PlaywrightTimeout:
                pass
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(600)


async def _find_card(page: Page, job_id: str):
    """Locate the job card for a listing id, scrolling the feed if needed."""
    selectors = (
        f'.jobCard:has(#skills_{job_id})',
        f'.jobCard:has(.uplersPartnerBadge#partner{job_id})',
    )
    for selector in selectors:
        card = page.locator(selector).first
        if await card.count():
            return card

    for _ in range(6):
        await page.mouse.wheel(0, 2500)
        await page.wait_for_timeout(1200)
        for selector in selectors:
            card = page.locator(selector).first
            if await card.count():
                return card
    return None


async def _open_job_drawer(page: Page, job: JobListing) -> bool:
    await _close_drawer(page)
    card = await _find_card(page, job.job_id)
    if card is None:
        # The filtered feed may have been replaced: reload and try once more.
        await page.goto(UPLERS_JOBS_URLS[0], wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        card = await _find_card(page, job.job_id)
    if card is None:
        logger.warning("Uplers card not found for %s (%s)", job.title, job.job_id)
        return False

    try:
        await card.scroll_into_view_if_needed()
        await card.click()
    except Exception as exc:  # noqa: BLE001 - card can detach while scrolling
        logger.warning("Could not open Uplers job %s: %s", job.job_id, exc)
        return False
    await page.wait_for_timeout(3500)
    return True


async def _open_apply_form(page: Page) -> bool:
    if await page.locator(APPLY_FORM).count():
        return True

    apply_now = page.locator("button.applyBtn")
    if await apply_now.count():
        await apply_now.first.click()
    else:
        fallback = page.get_by_role("button", name=re.compile(r"^apply$", re.I))
        if await fallback.count() == 0:
            logger.warning("No apply control on the Uplers job drawer")
            return False
        await fallback.first.click()

    try:
        await page.wait_for_selector(APPLY_FORM, timeout=20000)
    except PlaywrightTimeout:
        logger.warning("Uplers apply form did not open")
        return False
    return True


async def _fill_apply_form(page: Page, config: AppConfig) -> None:
    form = page.locator(APPLY_FORM).first

    years = max(0, int(getattr(config.profile, "years_experience", 1) or 0))
    experience = form.locator('input[name="total_experience"]')
    if await experience.count() >= 2:
        await experience.nth(0).fill(str(years))
        await experience.nth(1).fill("0")

    current = getattr(config.compensation, "current_ctc_lpa", None)
    current_input = form.locator("#current_ctc")
    if current is not None and await current_input.count():
        await current_input.fill(str(current))

    expected = getattr(config.compensation, "expected_ctc_lpa", None)
    expected_input = form.locator("#expected_ctc")
    if expected is not None and await expected_input.count():
        await expected_input.fill(str(expected))

    # Uplers requires a last working day even when the notice period is
    # "Immediately"; today's date is the truthful answer for a 0-day notice.
    date_input = form.locator('input.date-input, input[placeholder*="Ex: 20/11"]')
    if await date_input.count():
        today = datetime.now().strftime("%d/%m/%Y")
        await date_input.first.click()
        await date_input.first.fill(today)
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(400)

    modes = form.locator("#preferred_modes")
    if await modes.count() and not (await modes.input_value()).strip():
        try:
            await modes.click()
            await page.wait_for_timeout(700)
            option = page.locator('.react-select__option:has-text("Remote")').first
            if await option.count():
                await option.click()
                await page.wait_for_timeout(400)
                await page.keyboard.press("Escape")
        except PlaywrightTimeout:
            logger.warning("Could not set preferred mode of work")

    shift = form.locator('#talent_shift label.radioInput:has-text("Yes")')
    if await shift.count():
        await shift.first.click()
        await page.wait_for_timeout(300)


async def _submit_apply_form(page: Page) -> bool:
    submit = page.locator(APPLY_SUBMIT).first
    if await submit.count() == 0:
        logger.warning("Uplers apply form has no submit button")
        return False

    await submit.click()
    try:
        await page.wait_for_selector(APPLY_FORM, state="detached", timeout=25000)
    except PlaywrightTimeout:
        if await page.locator(APPLY_FORM).count():
            error_text = ""
            for selector in (
                ".error-message",
                ".invalid-feedback",
                ".toast",
                ".Toastify__toast",
                ".alert",
            ):
                loc = page.locator(selector)
                if await loc.count():
                    error_text = (await loc.first.inner_text()).strip()
                    if error_text:
                        break
            logger.warning("Uplers apply form did not close (validation?): %s", error_text[:200])
            return False
        return True

    await page.wait_for_timeout(1500)
    return True


async def apply_to_uplers_job(
    page: Page,
    context: BrowserContext,
    job: JobListing,
    config: AppConfig,
) -> bool | None:
    if not await _open_job_drawer(page, job):
        return False

    if not await _open_apply_form(page):
        body = (await page.locator("body").inner_text()).lower()
        if "applied" in body:
            logger.info("Already applied on Uplers: %s", job.title)
            return None
        return False

    if config.application.dry_run:
        logger.info("[DRY RUN] Would apply on Uplers: %s @ %s", job.title, job.company)
        await _close_drawer(page)
        return False

    await _fill_apply_form(page, config)
    if not await _submit_apply_form(page):
        return False

    await _close_drawer(page)
    save_applied_job(
        config.applied_jobs_path,
        job_key("uplers", job.job_id),
        {
            "source": "uplers",
            "title": job.title,
            "company": job.company,
            "url": job.url,
        },
    )
    logger.info("Applied on Uplers: %s @ %s", job.title, job.company)
    return True


async def apply_batch(
    page: Page,
    context: BrowserContext,
    jobs: list[JobListing],
    config: AppConfig,
) -> int:
    applied = 0
    for job in jobs:
        try:
            if await apply_to_uplers_job(page, context, job, config):
                applied += 1
        except Exception:
            logger.exception("Failed Uplers apply for %s", job.url)

        delay = random.randint(
            config.application.delay_seconds_min,
            config.application.delay_seconds_max,
        )
        logger.info("Waiting %ds before next application...", delay)
        await page.wait_for_timeout(delay * 1000)
    return applied
