"""Adaptive rate limiting to avoid detection."""

import asyncio
import random
import logging

logger = logging.getLogger(__name__)


class AdaptiveRateLimiter:
    """Manages delays between requests with adaptive backoff on failures."""

    def __init__(self, base_min: float = 3.0, base_max: float = 7.0):
        self.base_min = base_min
        self.base_max = base_max
        self.consecutive_failures = 0
        self.total_requests = 0

    async def wait(self):
        """Apply delay before next request."""
        delay = random.uniform(self.base_min, self.base_max)

        # Exponential backoff on consecutive failures
        if self.consecutive_failures > 0:
            backoff = min(self.consecutive_failures * 5, 60)
            delay += backoff
            logger.debug(f"Backoff: +{backoff}s (failures={self.consecutive_failures})")

        # Take a longer break every 50 requests
        if self.total_requests > 0 and self.total_requests % 50 == 0:
            pause = random.uniform(15, 30)
            delay += pause
            logger.info(f"Periodic pause after {self.total_requests} requests: +{pause:.0f}s")

        await asyncio.sleep(delay)
        self.total_requests += 1

    def record_success(self):
        self.consecutive_failures = 0

    def record_failure(self):
        self.consecutive_failures += 1
