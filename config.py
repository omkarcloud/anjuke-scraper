"""Configuration for the Anjuke Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT          port the API listens on (default 8000)
    ANJUKE_PROXY  proxy URL for every request, e.g. http://user:pass@host:port
                  (default: none — your own IP). Anjuke's anti-bot answers a
                  CAPTCHA once one IP sends more than about one request a
                  minute, so for anything beyond a few calls set a rotating
                  proxy: one that hands out a fresh IP per connection.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request rides a fresh
# connection, so a rotating proxy gives every retry a fresh IP).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

ANJUKE_PROXY = os.environ.get("ANJUKE_PROXY") or None


def anjuke_proxy():
    """The proxy for one request (None = direct)."""
    return os.environ.get("ANJUKE_PROXY") or None
