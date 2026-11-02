"""Anjuke transport: plain curl_cffi with browser-impersonated TLS. No
browser, no cookies, no login.

Why one fresh exit PER REQUEST (research 2026-10-30/31 through datacenter
proxy exits, confirmed per surface 6/6 on 2026-10-31):
58.com's "xxzl" gateway fronts every anjuke host and decides per exit IP
and frequency. The FIRST page request from a fresh datacenter exit passes
with nothing but a Referer (no cookies, any TLS profile: chrome / safari /
edge / iOS Safari). A SECOND request on the same exit within ~60 s answers
the gateway stub (a 700-byte page that redirects to
callback.58.com/antibot/verifycode, a geetest slider) or the ershoufang
captcha shell (www.anjuke.com/esfcommon-captcha-wy), and the exit stays
burnt for a minute or more. A headed Chrome on the same exit is challenged
identically and its cookies (sessid, aQQ_ajkguid, ctid, id58, xxzl*) replay
nothing, so there is no identity to mint: the recipe is one sticky
datacenter port per request, which is why this module creates and closes a
session per request instead of the usual thread-lifetime session
(config.anjuke_proxy() picks a random sticky port per call). Chinese
residential exits are not needed and fail the CONNECT a third of the time.

Surfaces and what they need:

  * DESKTOP (chrome TLS) — <pinyin>.anjuke.com resale list / detail,
    community list / valuation page, esf-ajax autocomplete, the desktop
    rental detail on <pinyin>.zu.anjuke.com (301 to the alias host),
    www.anjuke.com/sy-city.html. Open on the first hit of a fresh exit.
  * MOBILE (iOS Safari TLS + UA) — m.anjuke.com rental list with filters /
    paging, community page, new-home list / detail / params / floor plans /
    price / Q&A / reviews JSON. The desktop twins of these (rental paging and
    filters, every *.fang.anjuke.com page) are challenged on the first hit of
    every exit; the mobile site is not.

Not found: an unknown resale / rental / project id is a real HTTP 404
(404-安居客 / 对不起 pages); an unknown community id answers a 9 KB mobile
shell without the Nuxt state (and the desktop valuation page 404s); the
project parameters page answers 200 with an "undefinedundefined…" title.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  AnjukeUpstreamError  transport failure / 5xx / payload shape          — retryable
  AnjukeBlocked        gateway stub, captcha redirect, 401/403/429      — retryable on a fresh exit
  AnjukeBadRequest     upstream 400                                     — never retried
  AnjukeNotFound       unknown id / page                                — never retried
"""
import json
import os
import re
import sys
import time
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import egress
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from anjuke import refs
from anjuke.parsers import is_gateway_page, page_title

# Explicit profiles, never the generic "chrome" alias: with curl_cffi 0.17.0
# the alias's TLS fingerprint draws the gateway stub on every exit while
# chrome131 / chrome136 / safari17_0 / edge101 pass, and the iOS Safari
# profile passes on m.anjuke.com (server-side matrix 2026-11-01).
PC_IMPERSONATE = "chrome136"
MOBILE_IMPERSONATE = "safari184_ios"
MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
PAGE_TIMEOUT = 40      # resale list pages are 1.1-1.4 MB
JSON_TIMEOUT = 20

_NOT_FOUND_TITLES = ("对不起", "404-安居客", "对不起，没有找到这个页面", "Not Found")


class AnjukeUpstreamError(UpstreamError):
    """Transport failure, 5xx or an unexpected payload — retryable."""


class AnjukeBlocked(AnjukeUpstreamError, Blocked):
    """58's gateway stub / captcha redirect / 401-403-429 — retryable on a fresh exit."""


class AnjukeBadRequest(BadRequest):
    """Upstream 400 — never retried."""


class AnjukeNotFound(NotFound):
    """Listing / rental / community / project does not exist — never retried."""


def _session(mobile=False):
    """A fresh session on a fresh sticky exit (see the module docstring)."""
    from curl_cffi import requests as curl_requests
    proxy = config.anjuke_proxy()
    sess = curl_requests.Session(impersonate=MOBILE_IMPERSONATE if mobile else PC_IMPERSONATE)
    if proxy:
        sess.proxies = {"http": proxy, "https": proxy}
    headers = {
        "accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                   "image/avif,image/webp,*/*;q=0.8"),
        "accept-language": egress.accept_language(proxy),
        "upgrade-insecure-requests": "1",
    }
    if mobile:
        headers["user-agent"] = MOBILE_UA
    sess.headers.update(headers)
    return sess


def _retrying(fn):
    """Run fn() under the shared retry policy; every retry is a new session
    and so a new exit (AnjukeUpstreamError only; NotFound / BadRequest
    surface immediately)."""
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except AnjukeUpstreamError as e:
            last = e
            if attempt < config.MAX_RETRIES:
                time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


def _classify(resp, label):
    if resp.status_code == 404:
        raise AnjukeNotFound(f"{label} not found")
    if resp.status_code == 400:
        raise AnjukeBadRequest(resp.text[:200])
    if resp.status_code in (401, 403, 429):
        raise AnjukeBlocked(f"HTTP {resp.status_code} for {label}")
    if resp.status_code != 200:
        raise AnjukeUpstreamError(f"HTTP {resp.status_code} for {label}")
    final = str(resp.url or "")
    if "captcha" in final or "verifycode" in final or "/404" in final.split("?")[0]:
        if "/404" in final.split("?")[0] and "captcha" not in final and "verifycode" not in final:
            raise AnjukeNotFound(f"{label} not found")
        raise AnjukeBlocked(f"anti-bot challenge for {label}")
    text = resp.text
    if is_gateway_page(text):
        raise AnjukeBlocked(f"58 gateway challenge for {label}")
    return text


def _get(url, label, mobile=False, referer=None, xhr=False, timeout=PAGE_TIMEOUT):
    """GET one page on a fresh exit; the body text (callers parse)."""
    def once():
        sess = _session(mobile=mobile)
        headers = {}
        if referer:
            headers["referer"] = referer
        if xhr:
            headers["x-requested-with"] = "XMLHttpRequest"
            headers["accept"] = "application/json, text/javascript, */*; q=0.01"
        try:
            try:
                resp = sess.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            finally:
                sess.close()
        except Exception as e:
            raise AnjukeUpstreamError(f"request failed: {type(e).__name__}: {e}")
        text = _classify(resp, label)
        title = page_title(text)
        if title and title.startswith(_NOT_FOUND_TITLES):
            raise AnjukeNotFound(f"{label} not found")
        return text
    return _retrying(once)


def _json(url, label, mobile=False, referer=None):
    text = _get(url, label, mobile=mobile, referer=referer, xhr=True, timeout=JSON_TIMEOUT)
    try:
        return json.loads(text)
    except ValueError:
        raise AnjukeBlocked(f"non-JSON reply for {label}: {text[:120]}")


# ---- cities ------------------------------------------------------------------------------

def fetch_city_table():
    """www.anjuke.com/sy-city.html (Nuxt page with every city)."""
    return _get(refs.CITY_TABLE_LINK, "city table", referer=refs.WWW + "/")


# ---- resale ------------------------------------------------------------------------------

def fetch_sale_list(url, city):
    """One desktop resale list page (built by refs.sale_path)."""
    return _get(url, "resale list", referer=refs.pc_host(city) + "/")


def fetch_sale_detail(city, listing_id):
    """The desktop resale page /prop/view/<id> (any city host serves any id)."""
    city = city or "beijing"
    return _get(refs.listing_link(city, listing_id), f"listing {listing_id}",
                referer=refs.pc_host(city) + "/sale/")


def fetch_autocomplete(city, keyword, city_id):
    """esf-ajax/community/pc/autocomplete -> JSON (needs the numeric city id;
    without it the route answers 400)."""
    url = (f"{refs.pc_host(city)}/esf-ajax/community/pc/autocomplete/"
           f"?kw={quote(keyword)}&city_id={city_id}")
    payload = _json(url, "autocomplete", referer=refs.pc_host(city) + "/sale/")
    if not isinstance(payload, dict):
        raise AnjukeUpstreamError("unexpected autocomplete payload")
    return payload


# ---- rentals -----------------------------------------------------------------------------

def fetch_rent_api(city, search_param, page):
    """One page of the rental list XHR (refs.RENT_API) for the search_param a
    rendered list page carries; JSON."""
    url = (f"{refs.RENT_API}?page={page}&search_firstpage=1"
           f"&search_param={quote(json.dumps(search_param, separators=(',', ':'), ensure_ascii=False))}&font_encrypt=")
    payload = _json(url, "rental list", mobile=True, referer=f"{refs.MOBILE}/{refs.city_alias(city)}/rent/")
    if not isinstance(payload, dict) or str(payload.get("code")) != "0":
        raise AnjukeUpstreamError(f"unexpected rental list payload: {str(payload)[:160]}")
    return payload


def fetch_rent_list(url, city):
    """One rendered mobile rental list page (built by refs.rent_list_path):
    the source of the search_param fetch_rent_api replays."""
    return _get(url, "rental list", mobile=True, referer=f"{refs.MOBILE}/{refs.city_alias(city)}/")


def fetch_rent_detail(city, rental_id):
    """The desktop rental page <city>.zu.anjuke.com/fangyuan/<id>."""
    city = city or "beijing"
    return _get(refs.rental_link(city, rental_id), f"rental {rental_id}",
                referer=refs.rent_host(city) + "/")


def fetch_rent_detail_mobile(city, rental_id):
    """The mobile rental page m.anjuke.com/<alias>/rent/<id>-3/ (passes on
    every fresh exit where the desktop twin is a coin flip: 2026-11-01,
    desktop 4/8 across chrome136 / chrome131 / edge101 / safari17_0, mobile 2/2)."""
    city = city or "beijing"
    return _get(refs.rental_mobile_link(city, rental_id), f"rental {rental_id}", mobile=True,
                referer=f"{refs.MOBILE}/{refs.city_alias(city)}/rent/")


# ---- communities -------------------------------------------------------------------------

def fetch_community_list(url, city):
    """One desktop community list page (built by refs.community_list_path)."""
    return _get(url, "community list", referer=refs.pc_host(city) + "/")


def fetch_community_view(city, community_id):
    """The mobile community page m.anjuke.com/<alias>/community/<id>/. An
    unknown id answers a 9 KB shell without Nuxt state -> NotFound."""
    city = city or "beijing"
    html = _get(refs.community_mobile_link(city, community_id), f"community {community_id}",
                mobile=True, referer=f"{refs.MOBILE}/{refs.city_alias(city)}/")
    if "__NUXT__" not in html:
        raise AnjukeNotFound(f"community {community_id} not found")
    return html


def fetch_community_price(city, community_id):
    """The desktop valuation page /gufangjia/xiaoqu-<id>/ (404 for an unknown id)."""
    city = city or "beijing"
    return _get(refs.community_price_link(city, community_id), f"community {community_id} prices",
                referer=refs.community_link(city, community_id))


# ---- new homes ---------------------------------------------------------------------------

def fetch_loupan_api(city, query, location_url):
    """One page of the new-home list XHR (refs.LOUPAN_API); `query` is
    refs.loupan_query(...). JSON."""
    url = (f"{refs.LOUPAN_API}?args={quote(json.dumps(query, separators=(',', ':'), ensure_ascii=False))}"
           f"&location_url={quote(location_url, safe='')}")
    payload = _json(url, "new-home list", mobile=True, referer=location_url)
    if not isinstance(payload, dict) or not isinstance(payload.get("result"), dict):
        raise AnjukeUpstreamError(f"unexpected new-home list payload: {str(payload)[:160]}")
    return payload


def fetch_loupan_list(url, city):
    """One rendered mobile new-home list page (built by refs.loupan_list_path):
    the source of the city id and district slugs fetch_loupan_api needs."""
    return _get(url, "new-home list", mobile=True, referer=f"{refs.MOBILE}/{refs.city_alias(city)}/xinfang/")


def fetch_loupan_page(city, project_id, sub=""):
    """A mobile project page: "" (main), "params/", "huxing/", "jiage/",
    "wenda/wenlist/". The params page of an unknown project answers 200 with
    an "undefinedundefined…" title -> NotFound."""
    city = city or "beijing"
    html = _get(refs.loupan_page_link(city, project_id, sub), f"project {project_id} {sub or 'page'}",
                mobile=True, referer=refs.project_mobile_link(city, project_id))
    if page_title(html).startswith("undefined"):
        raise AnjukeNotFound(f"project {project_id} not found")
    return html


def fetch_loupan_reviews(city, project_id):
    """ajaxdianpin JSON: the latest ten reviews + total + tag counts (the
    route ignores every paging parameter)."""
    city = city or "beijing"
    url = refs.loupan_page_link(city, project_id, "ajaxdianpin/?from=loupan_view")
    payload = _json(url, f"project {project_id} reviews", mobile=True,
                    referer=refs.project_mobile_link(city, project_id))
    if not isinstance(payload, dict):
        raise AnjukeUpstreamError("unexpected reviews payload")
    return payload
