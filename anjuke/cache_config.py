"""Cache TTL per /anjuke/* endpoint (cache.py, keyed on the validated
params). Every anjuke page costs one fresh proxy exit (58's
gateway allows one request per exit per minute, anjuke/fetch.py), so the
TTLs lean long wherever the data moves slowly.
"""
from datetime import timedelta

# A city's filter vocabulary (districts, business areas, metro, buckets) and
# its numeric id: changes a few times a year.
CITY_CACHE = timedelta(days=7)
# Resale / community / new-home list pages: listings come and go daily; a
# few hours keeps paging clients consistent without serving stale counts.
SEARCH_CACHE = timedelta(hours=3)
# Mobile rental list: rentals churn fastest.
RENT_SEARCH_CACHE = timedelta(hours=2)
# The query object a rendered rental list page hands its own paging XHR
# (search_param: 58 city / district ids for the path): ids never move.
LIST_QUERY_CACHE = timedelta(days=7)
# One resale / rental record: price edits are rare within a day.
LISTING_CACHE = timedelta(hours=6)
RENTAL_CACHE = timedelta(hours=6)
# Autocomplete: communities and business areas are static.
SUGGEST_CACHE = timedelta(hours=24)
# Community record (mobile page + valuation page): monthly price data.
COMMUNITY_CACHE = timedelta(hours=24)
# A new-home project (four mobile pages): prices and permits move weekly.
PROJECT_CACHE = timedelta(hours=12)
# Reviews + Q&A of a project.
REVIEWS_CACHE = timedelta(hours=6)
# The per-city new-home city id + district slugs (parsed from the list page).
LOUPAN_CITY_CACHE = timedelta(days=7)
