"""The Accept-Language a request announces. The hosted API derives it from
the proxy exit's country; this standalone copy sends a plain US-English list,
which Anjuke serves the same pages to."""


def accept_language(proxy=None):
    return "en-US,en;q=0.9"
