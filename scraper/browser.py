"""Browser lifecycle management with automatic context rotation."""

import asyncio
import random
import logging
from typing import Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright

logger = logging.getLogger(__name__)

USER_AGENTS = [
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
]


class BrowserManager:
    """Manages browser lifecycle with automatic context rotation to prevent crashes."""

    def __init__(self, headless: bool = True, context_ttl: int = 15):
        """
        Args:
            headless: Run browser in headless mode (True for CI, False for debugging)
            context_ttl: Max page navigations before rotating to a fresh context
        """
        self.headless = headless
        self.context_ttl = context_ttl
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._nav_count = 0

    async def start(self):
        """Launch browser.

        Uses Chrome's "new headless" mode which is much harder for sites to
        detect as automated (passes most bot-detection checks that old headless fails).
        """
        self._playwright = await async_playwright().start()

        launch_args = [
            '--disable-blink-features=AutomationControlled',
            '--disable-dev-shm-usage',
            '--no-sandbox',
            '--disable-http2',
        ]
        # New headless mode: behaves like a real headed browser but without a window.
        # Much harder for United to fingerprint vs old headless.
        if self.headless:
            launch_args.append('--headless=new')

        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=launch_args,
        )
        logger.info(f"Browser launched (headless={self.headless}, new-headless={'yes' if self.headless else 'n/a'})")

    async def get_page(self) -> Page:
        """Get a working page, rotating context if needed."""
        if self._page is None or self._nav_count >= self.context_ttl:
            await self._rotate_context()
        return self._page

    async def _rotate_context(self):
        """Close old context and create a fresh one."""
        if self._context:
            try:
                await self._context.close()
                logger.info("Rotated browser context (old context closed)")
            except Exception:
                pass

        self._context = await self._browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent=random.choice(USER_AGENTS),
            locale='en-US',
            timezone_id='America/New_York',
        )
        self._page = await self._context.new_page()
        self._nav_count = 0

        # Hide webdriver flag that bot detectors check
        await self._page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        # Warm up: quick visit to establish cookies (short timeout — not critical)
        try:
            await self._page.goto(
                "https://www.united.com/en/us/flightstatus",
                timeout=20000,
                wait_until="domcontentloaded",
            )
            await asyncio.sleep(random.uniform(1, 3))
            logger.info("New browser context initialized")
        except Exception as e:
            logger.info(f"Warmup skipped (non-fatal): {type(e).__name__}")

    async def navigate(self, url: str, timeout: int = 90000) -> Page:
        """Navigate to URL with automatic crash recovery.

        Returns the page object (useful for setting up response listeners).
        """
        page = await self.get_page()
        try:
            await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            self._nav_count += 1
            return page
        except Exception as e:
            if 'Target page, context or browser has been closed' in str(e):
                logger.warning("Context crashed, rotating and retrying...")
                self._page = None  # Force rotation
                page = await self.get_page()
                await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
                self._nav_count += 1
                return page
            raise

    async def stop(self):
        """Shut down browser and playwright."""
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        logger.info("Browser shut down")
