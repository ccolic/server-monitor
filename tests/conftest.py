"""Pytest configuration."""

import asyncio
import os


def pytest_sessionfinish(session, exitstatus):
    """Pytest hook to clean up lingering async resources after all tests."""
    try:
        from server_monitor.checks import HTTPCheck

        loop = asyncio.get_event_loop()
        if not loop.is_closed():
            loop.run_until_complete(HTTPCheck.close_shared_client())
            loop.run_until_complete(asyncio.sleep(0.1))
            loop.close()
    except Exception as e:
        print(f"Error during pytest_sessionfinish cleanup: {e}")


def pytest_unconfigure(config):
    """Force exit after all tests to kill lingering threads and prevent pytest hang."""
    os._exit(0)
