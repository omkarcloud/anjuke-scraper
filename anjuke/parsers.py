"""Raw anjuke pages / JSON -> clean dicts for every /anjuke/* endpoint.
Pure functions, no I/O.

Where the data sits (research 2026-10-30/31; fixtures captured the same
days, anjuke/fixtures/):

  * Resale (二手房) list, resale detail, community list, community valuation
    page and the mobile community page are Nuxt 2 apps: everything is in
    `window.__NUXT__ = (function(a,b,…){…}(…))`, decoded with the shared
    upwork/nuxt.py interpreter (no node in the scrapers image).
  * The mobile rental list carries a schema.org ItemList plus HTML cards;
    the desktop rental detail is server-rendered HTML with one JSON-LD
    block (price, geo, amenities, description).
  * The mobile new-home (楼盘) list is Nuxt too (state.loupan.loupan.twLoupans);
    the mobile new-home pages (main, params, huxing, jiage) are
    server-rendered HTML; reviews come as JSON (ajaxdianpin), Q&A as Nuxt.
  * The city table is www.anjuke.com/sy-city.html's Nuxt `allData`.

Value conventions (shared with the other scraper packages):
  * money   numbers in CNY, with `currency: "CNY"`; the site's 万 (10,000)
            totals are kept beside the yuan amount as `*_wan`
  * dates   ISO: "2026年10月30日" -> "2026-10-30"; epoch seconds -> ISO 8601 UTC
  * keys    snake_case; `link` not `url`; booleans as questions; absent -> null
  * strings "" / "0" placeholders -> null where the site uses them as "none"
"""
import fastjson
import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from upwork.nuxt import NuxtStateError, decode_nuxt2, ld_json
from anjuke import refs
from scraper_utils.values import num as _float, number as _num, to_int as _int
from scraper_utils.text import squashed_any as _str

CURRENCY = "CNY"

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_CN_DATE_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月(?:\s*(\d{1,2})\s*日)?")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


# ---- value helpers ---------------------------------------------------------------------


def _nonzero(value):
    """Numeric value, with the site's 0 / "0" placeholder as None."""
    n = _num(value)
    return None if n in (None, 0) else n


def _flag(value):
    """"1" / 1 / true -> True, "0" / 0 / false -> False, else None."""
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip() in ("1", "true", "True")


def _wan_to_yuan(value):
    f = _float(value)
    return None if f is None else int(round(f * 10000))


def _epoch_iso(value):
    n = _int(value)
    if not n:
        return None
    return datetime.fromtimestamp(n, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cn_date(value):
    """"2026年10月30日" -> "2026-10-30"; "2026年4月" -> "2026-04"; else the text."""
    text = _str(value)
    if not text:
        return None
    match = _CN_DATE_RE.search(text)
    if not match:
        return text
    year, month, day = match.groups()
    return f"{year}-{int(month):02d}" + (f"-{int(day):02d}" if day else "")


def _first_number(text):
    match = _NUMBER_RE.search(text or "")
    return _num(match.group(0)) if match else None


def _dedupe(items):
    out = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out


def _photo(url):
    url = _str(url)
    if not url:
        return None
    return "https:" + url if url.startswith("//") else url


def _lat_lng(lat, lng):
    lat, lng = _float(lat), _float(lng)
    if not lat or not lng:
        return None, None
    # the site sometimes serves them swapped (lng 39.9, lat 116.4 for Beijing)
    if lat > 90 and lng <= 90:
        lat, lng = lng, lat
    return lat, lng


def page_title(html):
    match = _TITLE_RE.search(html or "")
    return " ".join(match.group(1).split()) if match else ""


def is_gateway_page(html):
    """58's anti-bot gateway stub (a 700-byte page that redirects to
    callback.58.com/antibot/verifycode) or the ershoufang captcha shell."""
    head = (html or "")[:4000]
    return ("xxzlGatewayUrl" in head or "antibot/verifycode" in head
            or "esfcommon-captcha" in head or "captchaxf-verify" in head
            or ("<title>验证码</title>" in head))


def nuxt_data(html):
    """The first `data` block of a Nuxt 2 page (NuxtStateError when absent)."""
    state = decode_nuxt2(html)
    data = state.get("data") or []
    return (data[0] if data and isinstance(data[0], dict) else {}), state


def _layout(rooms, halls, baths):
    rooms, halls, baths = _int(rooms), _int(halls), _int(baths)
    if rooms is None and halls is None and baths is None:
        return None
    text = "".join(f"{n}{unit}" for n, unit in ((rooms, "室"), (halls, "厅"), (baths, "卫")) if n is not None)
    return {"rooms": rooms, "halls": halls, "bathrooms": baths, "text": text or None}


_FLOOR_RE = re.compile(r"^(?P<level>[一-鿿]+)?\s*(?:层)?\s*\(?\s*(?:共\s*(?P<total>\d+)\s*层)?\)?$")


def _floor(level, total, text=None):
    """"低层(共18层)" / ("", "0", "") -> {level, total, text} or None."""
    level = _str(level) or None
    total = _nonzero(total)
    text = _str(text)
    if level and "(" in level and not text:
        text, level = level, None
    if text and (level is None or total is None):
        match = _FLOOR_RE.match(text)
        if match:
            level = level or _str(match.group("level"))
            total = total or _int(match.group("total"))
    if level is None and total is None and text is None:
        return None
    return {"level": level, "total_floors": total, "text": text or (f"{level}(共{total}层)" if level and total else level)}


# ---- cities -----------------------------------------------------------------------------

def parse_city_table(html):
    """www.anjuke.com/sy-city.html -> the site's own city rows (name, pinyin
    host label, short alias, other spellings) in the page's letter order.
    refs.CITY_ROWS is this output frozen on 2026-10-31."""
    data, _ = nuxt_data(html)
    rows = []
    for group in data.get("allData") or []:
        for city in group.get("children") or []:
            if not isinstance(city, dict):
                continue
            rows.append({
                "name": _str(city.get("name")),
                "pinyin": _str(city.get("ajk_list_name")) or (city.get("pinyin") or [None])[0],
                "alias": _str(city.get("ajk_short_list_name")),
                "other_pinyin": [p for p in (city.get("pinyin") or []) if p != city.get("ajk_list_name")],
                "link": _str(city.get("link")),
                "letter": _str(group.get("key")),
            })
    return rows


def _filter_options(options, with_range=False):
    out = []
    for option in options or []:
        if not isinstance(option, dict) or option.get("name") in (None, "不限", "全部"):
            continue
        row = {"name": _str(option.get("name")), "mark": (f"{option.get('url_mark')}{option.get('url_value')}"
                                                           if option.get("url_mark") and option.get("url_value") not in (None, "") else None)}
        if with_range:
            value = option.get("value")
            if isinstance(value, dict):
                low, high = _num(value.get("min")), _num(value.get("max"))
                row["min"] = low or None
                row["max"] = None if high in (None, 0) or high >= refs.OPEN_BOUND else high
        out.append(row)
    return out


def parse_city_details(html, city):
    """The city's filter vocabulary from its resale list page: districts with
    business areas, metro lines with stations, the site's own price / area /
    age buckets, ring roads, plus the live resale listing count."""
    data, _ = nuxt_data(html)
    filt = data.get("filter") or {}
    districts = []
    for region in filt.get("regions") or []:
        info = region.get("info") or {}
        lat, lng = _lat_lng(info.get("mapx"), info.get("mapy"))
        areas = []
        for sub in region.get("sub_data_list") or []:
            slat, slng = _lat_lng(sub.get("mapx"), sub.get("mapy"))
            areas.append({"id": _int(sub.get("id")), "name": _str(sub.get("name")), "slug": _str(sub.get("url_mark")),
                          "lat": slat, "lng": slng})
        districts.append({"id": _int(info.get("id")), "name": _str(info.get("name")), "slug": _str(info.get("url_mark")),
                          "lat": lat, "lng": lng, "business_areas": areas,
                          "link": refs.sale_path(city, info.get("url_mark")) if info.get("url_mark") else None})
    metro_lines = []
    for line in filt.get("metros") or []:
        info = line.get("info") or {}
        metro_lines.append({"id": _int(info.get("id")), "name": _str(info.get("name")),
                            "stations": [{"id": _int(s.get("id")), "name": _str(s.get("name"))}
                                         for s in line.get("sub_data_list") or []]})
    city_info = data.get("city_info_vo") or {}
    lat, lng = _lat_lng(city_info.get("lat"), city_info.get("lng"))
    listings = ((data.get("list") or {}).get("list") or [])
    city_id = None
    for item in listings:
        prop = ((item.get("info") or {}).get("property") or {})
        if prop.get("city_id"):
            city_id = _int(prop["city_id"])
            break
    if city_id is None:
        for group in (data.get("cityGroup") or {}).get("cityList") or []:
            for info in group.get("cityInfo") or []:
                if f"//{city}.anjuke.com" in (info.get("jumpAction") or ""):
                    city_id = _int(info.get("id"))
    record = refs.city_record(city)
    record.update({
        "id": city_id,
        "province": _str(data.get("province")),
        "lat": lat, "lng": lng,
        "resale_listings_total": _int((data.get("list") or {}).get("total")),
        "districts": districts,
        "metro_lines": metro_lines,
        "filters": {
            "price_buckets_wan": _filter_options(filt.get("sprice"), with_range=True),
            "area_buckets_sqm": _filter_options(filt.get("area"), with_range=True),
            "rooms": _filter_options(filt.get("model")),
            "use_types": _filter_options(filt.get("use_type")),
            "ages": _filter_options(filt.get("house_age"), with_range=True),
            "fitments": _filter_options(filt.get("fitment")),
            "orientations": _filter_options(filt.get("orientation")),
            "floor_levels": _filter_options(filt.get("floor_type")),
            "property_types": _filter_options(filt.get("property_types")),
            "features": _filter_options(filt.get("features")),
            "shortcuts": _filter_options(filt.get("shortcut")),
            "ring_roads": _filter_options(filt.get("circles")),
            "sorts": _filter_options(filt.get("sorttype")),
        },
    })
    return record


# ---- resale listings (二手房) ------------------------------------------------------------

def _tag_names(items):
    out = []
    for item in items or []:
        name = item.get("label") or item.get("name") if isinstance(item, dict) else item
        name = _str(name)
        if name and name not in out:
            out.append(name)
    return out


def _price_block(attr):
    total_wan = _num(attr.get("price"))
    return {
        "total": _wan_to_yuan(attr.get("price")),
        "total_wan": total_wan,
        "per_sqm": _nonzero(attr.get("avg_price")),
        "currency": CURRENCY,
    }


def _list_community(comm):
    if not comm or not comm.get("id"):
        return None
    lat, lng = _lat_lng(comm.get("lat"), comm.get("lng"))
    glat, glng = _lat_lng(comm.get("gLat"), comm.get("gLng"))
    flag = comm.get("flag") or {}
    city = refs.CITIES.get(_pinyin_for_city_id(comm.get("city_id")), {})
    return {
        "id": _str(comm.get("id")),
        "name": _str(comm.get("name")),
        "link": refs.community_link(city.get("pinyin"), comm.get("id")),
        "address": _str(comm.get("address")),
        "district": {"id": _int(comm.get("area_id")), "name": _str(comm.get("area_name"))},
        "business_area": {"id": _int(comm.get("shangquan_id")), "name": _str(comm.get("shangquan_name"))} if comm.get("shangquan_id") else None,
        "block": {"id": _int(comm.get("block_id")), "name": _str(comm.get("block_name"))} if comm.get("block_id") else None,
        "lat": lat, "lng": lng,
        "gcj_lat": glat, "gcj_lng": glng,
        "year_built": _str(comm.get("completion_time")),
        "building_type": _str(comm.get("build_type_str")),
        "ownership_type": _str(comm.get("ship_type_str")),
        "score": _nonzero(comm.get("score")),
        "tags": _tag_names(comm.get("tags")),
        "is_near_metro": _flag(flag.get("closeSubway")),
        "is_near_school": _flag(flag.get("closeSchool")),
        "photo": _photo(comm.get("default_photo")),
    }


_CITY_ID_CACHE = {}


def _pinyin_for_city_id(city_id):
    """Best-effort pinyin for a numeric city id seen in a payload (filled by
    the list parsers as they meet host + id pairs); None when unknown."""
    return _CITY_ID_CACHE.get(_str(city_id))


def remember_city_id(city, city_id):
    if city and city_id:
        _CITY_ID_CACHE[_str(city_id)] = city


def _list_broker(broker):
    if not broker or _str(broker.get("broker_id")) in (None, "0"):
        return None
    return {
        "id": _str(broker.get("broker_id")),
        "name": _str(broker.get("name")),
        "photo": _photo(broker.get("photo")),
        "company": _str(broker.get("company_name")),
        "company_full_name": _str(broker.get("company_full_name")),
        "store": _str(broker.get("store_name")),
        "rating": _nonzero(broker.get("star_score")),
        "is_verified": _flag(broker.get("is_verify")),
        "is_owner": broker.get("user_is_owner") if isinstance(broker.get("user_is_owner"), bool) else None,
    }


def _sale_auction(prop):
    """The card's placement code from its `isauction` JSON: "201" organic
    (and the "广告" ad), "221" a paid 热推 promoted slot."""
    try:
        return _str((fastjson.loads(prop.get("isauction") or "{}") or {}).get("auction"))
    except (ValueError, TypeError, AttributeError):
        return None


def _sale_item(item, city):
    info = item.get("info") or {}
    prop = info.get("property") or {}
    attr = prop.get("attribute") or {}
    flag = prop.get("flag") or {}
    other = info.get("other") or {}
    # `id` is the routable listing id (/prop/view/<id>, the S<id> / A<id>
    # forms); house_id is the same on the list cards but an internal id on
    # the detail page
    listing_id = _str(prop.get("id")) or _str(prop.get("house_id"))
    remember_city_id(city, prop.get("city_id"))
    pc_url = _str(prop.get("pc_url"))
    tw_url = _str(prop.get("tw_url"))
    return {
        "id": listing_id,
        "title": _str(prop.get("title")),
        "link": pc_url.split("?")[0] if pc_url else refs.listing_link(city, listing_id),
        "mobile_link": tw_url.split("?")[0] if tw_url else refs.listing_mobile_link(city, listing_id),
        "status": "active" if _str(prop.get("status")) == "1" else _str(prop.get("status")),
        "listed_at": _epoch_iso(prop.get("post_date")),
        "price": _price_block(attr),
        "layout": _layout(attr.get("room_num"), attr.get("hall_num"), attr.get("toilet_num")),
        "area_sqm": _num(attr.get("area_num")),
        "floor": _floor(attr.get("floor_level") or attr.get("floor"), attr.get("total_floor")),
        "orientation": _str(attr.get("orient")),
        "fitment": _str(attr.get("fitment_name")),
        "use_type": _str(attr.get("use_type")),
        "year_built": _nonzero(attr.get("house_age")),
        "has_elevator": _flag(prop.get("has_lift")) if _str(prop.get("has_lift")) in ("0", "1") else None,
        "has_heating": _flag(attr.get("heating")) if _str(attr.get("heating")) in ("0", "1") else None,
        "is_unique_property": _flag(attr.get("unique_prop")) if _str(attr.get("unique_prop")) in ("0", "1") else None,
        "is_verified": _flag(flag.get("is_guarantee")),
        "is_owner_listed": _flag(flag.get("is_landlord_listed")),
        "is_new_home": _flag(flag.get("is_xinfang")),
        "is_ad": _str(other.get("ads_tag")) == "广告",
        # paid "热推" slots (auction code 221, every sixth card) ride on top of
        # the 60 organic results of a page and can repeat across pages
        "is_promoted": _sale_auction(prop) == "221",
        "badge": _str(other.get("ads_tag")),
        "has_video": _flag(flag.get("has_video")),
        "has_vr": bool(_str(flag.get("pano_id")) and _str(flag.get("pano_type"))) or (_flag(flag.get("is_new_3d_vr")) or None),
        "vr_type": _str(flag.get("pano_type")) if _str(flag.get("pano_id")) else None,
        "photo": _photo(prop.get("default_photo")),
        "tags": _tag_names(prop.get("tags")) or _tag_names(prop.get("labels")),
        "highlights": _dedupe([_str(h) for h in prop.get("highlights") or []]),
        "metro": _str(other.get("metro_desc")),
        "school": _str(other.get("school_desc")),
        "community": _list_community(info.get("community")),
        "broker": _list_broker(info.get("broker")),
    }


def parse_sale_list(html, city):
    """A resale list page -> (listings, total, page, keyword_match_type).
    Sponsored blocks (list_type 1006 "推荐新楼盘") are dropped: only the
    site's own listing cards (list_type "1") are returned."""
    data, _ = nuxt_data(html)
    block = data.get("list") or {}
    items = [_sale_item(item, city) for item in block.get("list") or [] if _str(item.get("list_type")) == "1"]
    listing_params = data.get("listParams") or {}
    page = _int(data.get("page")) or _int(listing_params.get("page")) or 1
    other = block.get("other") or {}
    return {
        "listings": items,
        "total": _int(block.get("total")),
        "page": page,
        "has_more": _flag(block.get("has_more")),
        "keyword_match": _str(other.get("keyword_search_type")),
        "community": _top_community(data.get("community")) if isinstance(data.get("community"), dict) and data["community"].get("base") else None,
    }


def _photos(items):
    out = []
    for item in items or []:
        if isinstance(item, dict):
            url = _photo(item.get("original_url") or item.get("url"))
            if url:
                out.append({"link": url, "caption": _str(item.get("desc"))})
        elif _str(item):
            out.append({"link": _photo(item), "caption": None})
    return out


def _desc_sections(items):
    out = []
    for item in items or []:
        if isinstance(item, dict) and _str(item.get("content")):
            out.append({"title": _str(item.get("name")), "text": item["content"].strip()})
    return out


def _detail_broker(broker):
    if not broker or _str(broker.get("broker_id")) in (None, "0"):
        return None
    license_ = broker.get("license") or {}
    medal = broker.get("broker_medal") or {}
    verifications = [{"title": _str(v.get("title")), "value": _str(v.get("desc"))}
                     for v in broker.get("unified_broker_verification") or broker.get("unified_broker_info") or []
                     if isinstance(v, dict)]
    return {
        "id": _str(broker.get("broker_id")),
        "name": _str(broker.get("name")),
        "photo": _photo(broker.get("photo")),
        "link": _str(broker.get("broker_url")),
        "company": _str(broker.get("company_name")),
        "company_full_name": _str(broker.get("company_full_name")),
        "company_link": _str(broker.get("company_url")),
        "company_license": _str(license_.get("code")),
        "store": _str(broker.get("store_name")),
        "rating": _nonzero(broker.get("score")),
        "service_score": _nonzero(medal.get("andromedaScore")),
        "medal_level": _int(medal.get("medalType")),
        "is_verified": _flag((broker.get("flag") or {}).get("is_verified")),
        "verifications": verifications,
        "tags": _tag_names(broker.get("tags")) + _tag_names(broker.get("unified_broker_tags")),
        "phone": None,   # 58's virtual numbers need a logged-in captcha flow
    }


def _top_community(comm):
    """The resale-detail / list `community` block (base + extend + priceInfo + propInfo)."""
    base = comm.get("base") or {}
    extend = comm.get("extend") or {}
    price = comm.get("priceInfo") or {}
    props = comm.get("propInfo") or {}
    lat, lng = _lat_lng(base.get("lat"), base.get("lng"))
    blat, blng = _lat_lng(base.get("blat"), base.get("blng"))
    return {
        "id": _str(base.get("id")),
        "name": _str(base.get("name")),
        "link": _str(comm.get("communityUrl")) or (refs.community_link(refs.CITIES.get(_pinyin_for_city_id(base.get("cityId")), {}).get("pinyin"), base.get("id")) if base.get("id") else None),
        "address": _str(base.get("address")),
        "district": {"id": _int(base.get("areaId")), "name": _str(base.get("areaName"))},
        "business_area": {"id": _int(base.get("tradingAreaId")), "name": _str(base.get("tradingAreaName"))} if base.get("tradingAreaId") else None,
        "lat": lat, "lng": lng, "baidu_lat": blat, "baidu_lng": blng,
        "year_built": _str(base.get("completionTime")),
        "building_type": _str(base.get("buildTypeStr")),
        "ownership_type": _str(base.get("shipTypeStr")),
        "property_types": [_str(p) for p in base.get("propertyTypes") or [] if _str(p)],
        "developer": _str(extend.get("developer")),
        "property_company": _str(extend.get("propertyCompany")),
        "property_fee": _str(extend.get("propertyMoney")),
        "plot_ratio": _num(extend.get("plotRatio")),
        "green_ratio_pct": _num(extend.get("landscapingRatio")),
        "households": _nonzero(extend.get("totalHouseHoldNum")),
        "parking": _str(extend.get("parking")),
        "photo": _photo(base.get("defaultPhoto")),
        "price": {"per_sqm": _nonzero(price.get("price")), "month_change_pct": _num(price.get("monthChange")),
                  "year_change_pct": _num(price.get("yearChange")), "label": _str(price.get("title")),
                  "currency": CURRENCY} if price else None,
        "counts": {"for_sale": _int(props.get("saleNum")), "for_rent": _int(props.get("rentNum"))} if props else None,
    }


def parse_sale_detail(html, listing_id, city):
    """A desktop resale page (/prop/view/<id>) -> the full listing record."""
    data, _ = nuxt_data(html)
    view = data.get("viewData") or {}
    prop = view.get("property") or {}
    if not prop.get("id"):
        raise NuxtStateError("resale page carries no property block")
    attr = prop.get("attribute") or {}
    flag = prop.get("flag") or {}
    budget = attr.get("budget") or {}
    comm = view.get("community") or {}
    lat, lng = _lat_lng(comm.get("lat"), comm.get("lng"))
    top_comm = data.get("community") if isinstance(data.get("community"), dict) and (data.get("community") or {}).get("base") else None
    # a bare id carries no city (and a caller's city may be the wrong one: any
    # city host serves any id); the page's own links carry the listing's city.
    # Resolve it before the city-id cache learns the pair.
    tw_url = _str((view.get("other") or {}).get("tw_url"))
    city = (refs.city_from_link(tw_url) or refs.city_from_link(_str((top_comm or {}).get("communityUrl")))
            or refs.city_from_link(_str(comm.get("area_url"))) or city)
    remember_city_id(city, prop.get("city_id"))
    community = _top_community(top_comm) if top_comm else {}
    community.update({k: v for k, v in {
        "id": _str(comm.get("id")) or community.get("id"),
        "name": _str(comm.get("name")) or community.get("name"),
        "address": _str(comm.get("address")) or community.get("address"),
        "lat": lat or community.get("lat"), "lng": lng or community.get("lng"),
        "district": {"id": _int(comm.get("area_id")), "name": _str(comm.get("area_name")), "slug": _str(comm.get("area")),
                     "link": _str(comm.get("area_url"))},
        "business_area": {"id": _int(comm.get("shangquan_id")), "name": _str(comm.get("shangquan_name")),
                          "slug": _str(comm.get("shangquan")), "link": _str(comm.get("shangquan_url"))} if comm.get("shangquan_id") else community.get("business_area"),
        "block": {"id": _int(comm.get("block_id")), "name": _str(comm.get("block_name"))} if comm.get("block_id") else None,
        "link": community.get("link") or (refs.community_link(city, comm.get("id")) if comm.get("id") else None),
    }.items() if v is not None} if comm else {})
    history = [{"month": _str(p.get("date")), "per_sqm": _nonzero(p.get("price"))}
               for p in (data.get("priceTrend") or {}).get("community") or [] if isinstance(p, dict)]
    stores = data.get("storeBrokers") or {}
    stats = stores.get("statistics") or {}
    qa = data.get("qaCom") or {}
    status = _str(prop.get("status"))
    return {
        # the routable id (what the list cards, the link and the `listing`
        # param use); the page's house_id is a different, internal number
        "id": _str(prop.get("id")) or listing_id,
        "house_id": _str(prop.get("house_id")),
        "title": _str(prop.get("title")),
        "link": refs.listing_link(city, _str(prop.get("id")) or listing_id),
        "mobile_link": tw_url.split("?")[0] if tw_url else refs.listing_mobile_link(city, listing_id),
        "status": "active" if status == "1" else status,
        "source": "new_home_agency" if _str(prop.get("source_type")) == "19" else ("broker" if _str(prop.get("source_type")) in ("1", "2") else _str(prop.get("source_type"))),
        "listed_at": _epoch_iso(prop.get("post_date")),
        "updated_at": _epoch_iso(prop.get("update_date")),
        "price": _price_block(attr),
        "mortgage": {"down_payment": _wan_to_yuan(budget.get("down_payment")), "down_payment_wan": _num(budget.get("down_payment")),
                     "monthly": _nonzero(budget.get("monthly_payment") or budget.get("per_month_price")), "currency": CURRENCY} if budget else None,
        "layout": _layout(attr.get("room_num"), attr.get("hall_num"), attr.get("toilet_num")),
        "area_sqm": _num(attr.get("area_num")),
        "floor": _floor(attr.get("floor_level") or attr.get("floor"), attr.get("total_floor")),
        "orientation": _str(attr.get("orient")),
        "fitment": _str(attr.get("fitment_name")),
        "use_type": _str(attr.get("use_type")),
        "property_rights": _str(attr.get("right_type") or attr.get("rights_type")),
        "property_rights_years": _str(attr.get("right_age") or attr.get("rights_age")),
        "year_built": _nonzero(attr.get("house_age")),
        "has_elevator": _flag(attr.get("has_lift")) if _str(attr.get("has_lift")) in ("0", "1") else None,
        "has_heating": _flag(attr.get("heating")) if _str(attr.get("heating")) in ("0", "1") else None,
        "is_unique_property": _flag(attr.get("unique_prop")) if _str(attr.get("unique_prop")) in ("0", "1") else None,
        "is_verified": _flag(flag.get("is_guarantee")),
        "is_owner_listed": _flag(flag.get("is_landlord_listed")),
        "is_new_home": _flag(flag.get("is_new_house")) or _flag(flag.get("is_xinfang")),
        "has_property_certificate": _flag(flag.get("is_property_certificate")),
        "has_video": _flag(flag.get("has_video")),
        "video_link": _str(prop.get("video_url")),
        "vr": {"link": _str(prop.get("pano_url")), "id": _str(prop.get("pano_id")), "type": _str(prop.get("pano_type"))} if _str(prop.get("pano_url")) else None,
        "quality_label": {"title": _str((prop.get("premier_tag") or {}).get("title")), "subtitle": _str((prop.get("premier_tag") or {}).get("sub_title")),
                          "description": _str((prop.get("premier_tag") or {}).get("desc"))} if _str((prop.get("premier_tag") or {}).get("title")) else None,
        "tags": _tag_names(prop.get("tags")),
        "features": _dedupe([_str(t) for t in prop.get("feature_tags") or []]),
        "description": _desc_sections(prop.get("desc_structure")),
        "photos": {"indoor": _photos(prop.get("indoor_photos") or prop.get("room_photos")),
                   "floor_plan": _photos(prop.get("model_photos")),
                   "outdoor": _photos(prop.get("outdoor_photos"))},
        "government_verification": [{"title": _str(g.get("title")), "code": _str(g.get("desc")), "image": _photo(g.get("imageUrl")),
                                     "link": _str(g.get("href"))} if isinstance(g, dict) else {"title": None, "code": _str(g), "image": None, "link": None}
                                    for g in prop.get("government_verification") or []],
        "community": community or None,
        "community_price_history": history,
        "broker": _detail_broker(view.get("broker")),
        "agency_coverage": {"stores": _int(stats.get("storeNum")), "brokers": _int(stats.get("brokerNum")),
                            "total": _int(stores.get("total"))} if stats else None,
        "questions": {"total": _int(qa.get("total")), "items": [_qa_item(q) for q in qa.get("list") or [] if isinstance(q, dict)]} if qa else None,
    }


def _qa_item(q):
    best = q.get("best_answer") or {}
    user = best.get("answer_user") or {}
    return {
        "id": _str(q.get("id")),
        "question": _str(q.get("title")),
        "asked_at": _str(q.get("ask_time") or q.get("askTime")),
        "answers_count": _int(q.get("answer_num") if q.get("answer_num") is not None else q.get("answerAmount")),
        "link": _str(q.get("detail_url") or q.get("jumpAction")),
        "best_answer": {"text": _str(best.get("content")), "answered_at": _str(best.get("answer_time")),
                        "author": _str(user.get("user_name")), "author_link": _str(user.get("personal_zone_url"))} if _str(best.get("content")) else None,
    }


# ---- autocomplete (sale/suggest) ---------------------------------------------------------

_SUGGEST_TYPES = {2: "business_area", 3: "metro_station", 4: "community"}


def parse_autocomplete(payload, city):
    """esf-ajax/community/pc/autocomplete -> typed suggestions."""
    out = []
    for item in (payload or {}).get("data") or []:
        kind = _SUGGEST_TYPES.get(_int(item.get("type")), _str(item.get("type")))
        row = {
            "type": kind,
            "id": _str(item.get("id")),
            "name": _str(item.get("name")),
            "address": _str(item.get("address")),
            "district": {"id": _int(item.get("areaId")), "name": _str(item.get("areaName"))} if item.get("areaId") else None,
            "avg_price_per_sqm": _nonzero(item.get("price")),
            "currency": CURRENCY if _nonzero(item.get("price")) else None,
            "slug": _str(item.get("listName")),
            "link": refs.community_link(city, item.get("id")) if kind == "community" else None,
        }
        out.append(row)
    return out


# ---- rentals (租房) ------------------------------------------------------------------------

def _ld_props(block):
    props = {}
    for prop in block.get("additionalProperty") or []:
        if isinstance(prop, dict) and prop.get("name"):
            props[prop["name"]] = _str(prop.get("value"))
    return props


_LAYOUT_RE = re.compile(r"(\d+)\s*室\s*(?:(\d+)\s*厅)?\s*(?:(\d+)\s*卫)?")


def _layout_text(text):
    match = _LAYOUT_RE.search(text or "")
    if not match:
        return None
    return _layout(match.group(1), match.group(2), match.group(3))


_SEARCH_PARAM_RE = re.compile(r"search_param\s*:\s*(\{.*?\})\s*,", re.S)


def parse_rent_search_param(html):
    """The `search_param` object a mobile rental list page hands its own
    "load more" XHR (__json4fe.search_param): the 58 city id, the district /
    business-area ids, rent band, rooms, type, fitment and source the path
    encodes. Raises NuxtStateError when the page carries none (a shell page)."""
    match = _SEARCH_PARAM_RE.search(html or "")
    if not match:
        raise NuxtStateError("rental list page carries no search_param")
    try:
        value = fastjson.loads(match.group(1))
    except ValueError as e:
        raise NuxtStateError(f"rental search_param is not JSON: {e}")
    if not isinstance(value, dict) or not value.get("city_id"):
        raise NuxtStateError("rental search_param has no city_id")
    return value


def _rent_row(row, city):
    prop = (row.get("property") or {}).get("base") or {}
    attr = prop.get("attribute") or {}
    flag = prop.get("flag") or {}
    comm = (row.get("community") or {}).get("base") or {}
    other = row.get("other") or {}
    rental_id = _str(prop.get("house_id"))
    detail = _str((row.get("front_message") or {}).get("detail_url")) or ""
    alias = detail.split("m.anjuke.com/")[1].split("/")[0] if "m.anjuke.com/" in detail else refs.city_alias(city)
    lat, lng = _lat_lng(comm.get("lat"), comm.get("lng"))
    floor = _nonzero(attr.get("floor"))
    total = _nonzero(attr.get("total_floor"))
    level = _str(attr.get("floor_level"))
    return {
        "id": rental_id,
        "title": _str(prop.get("title")),
        "link": f"https://{alias}.zu.anjuke.com/fangyuan/{rental_id}",
        "mobile_link": f"{refs.MOBILE}/{alias}/rent/{rental_id}-3/",
        "rental_type": _str(prop.get("rent_type")),
        "rent": {"monthly": _num(attr.get("price")), "currency": CURRENCY, "unit": _str(attr.get("priceUnit"))},
        "layout": _layout(attr.get("room_num"), attr.get("hall_num"), attr.get("toilet_num")),
        "area_sqm": _nonzero(attr.get("area_num")),
        "floor": {"floor": floor, "total_floors": total, "level": level,
                  "text": f"{floor}/{total}层" if floor and total else level} if (floor or total or level) else None,
        "orientation": _str(attr.get("orient")),
        "fitment": _str(attr.get("fitment_name")),
        "use_type": _str(attr.get("use_type")),
        "heating": _str(attr.get("heat_type")),
        "is_verified": _flag(flag.get("is_guarantee")),
        "has_elevator": _flag(flag.get("has_elevator")),
        "has_video": _flag(flag.get("has_video")),
        "apartment_brand": _str(flag.get("apartment_brand")),
        "tags": _dedupe([_str(t) for t in prop.get("tags") or []]),
        "metro": _str(prop.get("metro_info")) or _str(other.get("metro_desc")),
        "school": _str(other.get("school_desc")),
        "posted_ago": _str(prop.get("post_date")),
        "photo": _photo(prop.get("default_photo")),
        "community": {
            "id": _str(comm.get("id")),
            "name": _str(comm.get("name")),
            "link": refs.community_link(city, comm.get("id")) if _str(comm.get("id")) else None,
            "address": _str(comm.get("address")),
            "district": {"id": _int(comm.get("areaId")), "name": _str(comm.get("areaName"))} if comm.get("areaId") else None,
            "block": {"id": _int(comm.get("blockId")), "name": _str(comm.get("blockName"))} if comm.get("blockId") else None,
            "lat": lat, "lng": lng,
        } if comm.get("id") or comm.get("name") else None,
    }


def parse_rent_api(payload, city):
    """The rental list XHR (zufang/m/house/api_houselist_data_Jgs) ->
    (rentals, total, has_more). 30 rows a page; the total is the site's live
    count of rentals matching the query."""
    data = (payload or {}).get("data") or {}
    rows = [r for r in data.get("list") or [] if isinstance(r, dict) and ((r.get("property") or {}).get("base") or {}).get("house_id")]
    return {
        "rentals": [_rent_row(r, city) for r in rows],
        "total": _int(data.get("total")),
        "has_more": _flag(data.get("has_more")),
    }


_RENT_AMENITY_RE = re.compile(r'<li class="peitao-item\s*(has|no)?[^"]*"[^>]*>.*?<div class="peitao-info">([^<]+)</div>', re.S)


def parse_rent_detail(html, rental_id, city):
    """The desktop rental page (<alias>.zu.anjuke.com/fangyuan/<id>) ->
    the full rental record (JSON-LD block + the page's info table, broker
    card, amenities grid, gallery and description)."""
    soup = BeautifulSoup(html, "lxml")
    listing = next((b for b in ld_json(html) if "RealEstateListing" in (b.get("@type") or [])), {})
    props = _ld_props(listing)
    offer = listing.get("offers") or {}
    geo = listing.get("geo") or {}
    title = soup.select_one("h1.house-title .tit-rest") or soup.select_one("h1.house-title")

    info = {}
    for li in soup.select(".house-info-zufang .house-info-item"):
        label = _str((li.select_one(".type") or li).get_text()).rstrip("：:") if li.select_one(".type") else None
        value_node = li.select_one(".info")
        if label and value_node is not None:
            info[label] = _str(value_node.get_text(" "))
    community_link = soup.select_one(".house-info-zufang .house-info-item a.link[href*='community/view']")
    area_links = [a for a in soup.select(".house-info-zufang .house-info-item a.link[href*='/fangyuan/']")]
    full_line = soup.select_one(".house-info-zufang .full-line")
    terms = [_str(s.get_text(" ")) for s in full_line.select(".type")] if full_line else []
    payment = next((t for t in terms if t and "付" in t and "押" in t), None)
    fees = {}
    for t in terms:
        if t and "：" in t:
            k, v = t.split("：", 1)
            fees[k] = _first_number(v)

    amenities, missing = [], []
    for state, name in _RENT_AMENITY_RE.findall(html):
        (missing if state == "no" else amenities).append(_str(name))
    if not amenities and props.get("房屋配套"):
        amenities = props["房屋配套"].split()

    broker_card = soup.select_one(".broker-card")
    broker = None
    if broker_card is not None:
        lines = [_str(x.get_text(" ")) for x in broker_card.select(".broker-line")]
        company_span = broker_card.select_one(".broker-line span[title]")
        company = _str(company_span["title"]) if company_span is not None else next(
            (l.split("：", 1)[-1] for l in lines if l and l.startswith("公司")), None)
        store = next((l.split("：", 1)[-1] for l in lines if l and l.startswith("门店")), None)
        scores = {_str(i.select_one(".score-title").get_text()): _str(i.select_one(".score-result").get_text())
                  for i in broker_card.select(".agent-score .score-item") if i.select_one(".score-title") and i.select_one(".score-result")}
        card_texts = [_str(a.get_text(" ")) for a in broker_card.select(".card-info .card-text")]
        identity_card = next((_first_number(t.split("身份信息卡号")[-1]) for t in card_texts if t and "身份信息卡号" in t), None)
        license_code = next((t.split("公司执照编码")[-1].strip() for t in card_texts if t and "公司执照编码" in t), None)
        complaints = broker_card.select_one(".complaints-phone")
        broker = {
            "name": _str(broker_card.select_one(".broker-name").get_text()) if broker_card.select_one(".broker-name") else None,
            "photo": _photo((broker_card.select_one("img.broker-photo-main") or {}).get("src")),
            "company": company,
            "company_license": license_code,
            "company_complaints_phone": _str(complaints.get_text()).split("：")[-1] if complaints else None,
            "store": store,
            "service_score": _first_number(broker_card.select_one(".agent-score-total .score").get_text()) if broker_card.select_one(".agent-score-total .score") else None,
            "service_score_note": _str(broker_card.select_one(".agent-score-total .beatOthers").get_text()) if broker_card.select_one(".agent-score-total .beatOthers") else None,
            "ratings": scores or None,
            "identity_card_number": str(identity_card) if identity_card is not None else None,
            "phone": None,
        }

    labels = [_str(li.get_text()) for li in soup.select(".title-label .title-label-item")]
    rental_type = next((l for l in labels if l in ("合租", "整租")), None)
    photos = _dedupe([_photo(src) for src in (img.get("data-src") or img.get("lazy_src") or img.get("src") or ""
                                              for img in soup.select(".lbox .switch_list img"))
                      if src.startswith(("http", "//")) and "ajkimg" in src])
    video = re.search(r'https?://[^"\']+\.mp4[^"\']*', html)
    lat = re.search(r"\blat\s*:\s*['\"]?(\d{1,2}\.\d+)", html)
    lng = re.search(r"\blng\s*:\s*['\"]?(\d{2,3}\.\d+)", html)
    comm_id = None
    if community_link is not None:
        match = re.search(r"community/view/(\d+)", community_link["href"])
        comm_id = match.group(1) if match else None
    description = soup.select_one(".auto-general")
    description_text = None
    if description is not None:
        description_text = "\n".join(t for t in (line.strip() for line in description.get_text("\n").split("\n")) if t) or None
        description_text = description_text.replace("显示全部", "").strip() if description_text else None
    final_url = _str(listing.get("url")) or refs.rental_link(city, rental_id)
    alias = final_url.split("//")[1].split(".")[0] if "//" in final_url else refs.city_alias(city)
    return {
        "id": rental_id,
        "title": _str(title.get_text()) if title is not None else _str(listing.get("name")),
        "link": final_url,
        "mobile_link": f"{refs.MOBILE}/{alias}/rent/{rental_id}-3/",
        "rental_type": rental_type,
        "rent": {"monthly": _first_number(offer.get("price")) if offer else _first_number((full_line.select_one(".price") or full_line).get_text() if full_line else None),
                 "currency": CURRENCY, "payment_terms": payment,
                 "agency_fee": fees.get("中介费"), "service_fee": fees.get("服务费")},
        "layout": _layout_text(info.get("户型")) or _layout_text(listing.get("keywords")),
        "area_sqm": _first_number(info.get("面积")),
        "orientation": _str(props.get("朝向") or info.get("朝向")),
        "floor": _floor(None, None, props.get("楼层") or info.get("楼层")),
        "fitment": _str(props.get("装修") or info.get("装修")),
        "use_type": _str(props.get("类型") or info.get("类型")),
        "is_verified": any(l == "安选" for l in [_str(x.get_text()) for x in soup.select(".house-title .anxvan-ico")]) or None,
        "tags": [l for l in labels if l],
        "amenities": _dedupe(amenities),
        "amenities_missing": _dedupe(missing),
        "description": description_text,
        "updated_at": _cn_date(props.get("更新时间")),
        "address": _str((listing.get("address") or {}).get("streetAddress")),
        "lat": _float(geo.get("latitude")) or (_float(lat.group(1)) if lat else None),
        "lng": _float(geo.get("longitude")) or (_float(lng.group(1)) if lng else None),
        "community": {
            "id": comm_id,
            "name": _str(community_link.get_text()) if community_link is not None else _str(props.get("小区")),
            "link": community_link["href"] if community_link is not None else None,
            "district": _str(area_links[0].get_text()) if area_links else None,
            "business_area": _str(area_links[1].get_text()) if len(area_links) > 1 else None,
        } if (community_link is not None or props.get("小区")) else None,
        "photos": photos,
        "video_link": video.group(0) if video else None,
        "broker": broker,
    }


# ---- communities (小区) --------------------------------------------------------------------

def _grade(grade):
    if not grade or not isinstance(grade, dict):
        return None
    return {
        "overall": _num(grade.get("score")),
        "categories": [{"name": _str(c.get("name")), "score": _num(c.get("score")), "note": _str(c.get("tips"))}
                       for c in grade.get("list") or [] if isinstance(c, dict)],
        "aspects": [{"name": _str(c.get("name")), "score": _num(c.get("score"))}
                    for c in grade.get("items") or [] if isinstance(c, dict)],
    }


def _community_base(base, city):
    lat, lng = _lat_lng(base.get("lat"), base.get("lng"))
    blat, blng = _lat_lng(base.get("blat"), base.get("blng"))
    flag = base.get("flag") or {}
    comm_id = _str(base.get("id"))
    pinyin = _str(base.get("longCityListName")) or city
    return {
        "id": comm_id,
        "name": _str(base.get("name")),
        "slug": _str(base.get("listName")),
        "link": refs.community_link(pinyin, comm_id),
        "mobile_link": f"{refs.MOBILE}/{_str(base.get('cityListName')) or refs.city_alias(pinyin)}/community/{comm_id}/",
        "address": _str(base.get("address")),
        "city": {"id": _int(base.get("cityId")), "name": _str(base.get("cityName")), "pinyin": pinyin},
        "district": {"id": _int(base.get("areaId")), "name": _str(base.get("areaName")), "slug": _str(base.get("districtListName"))},
        "business_area": {"id": _int(base.get("tradingAreaId")), "name": _str(base.get("tradingAreaName")),
                          "slug": _str(base.get("shangquanListName"))} if base.get("tradingAreaId") else None,
        "lat": lat, "lng": lng, "baidu_lat": blat, "baidu_lng": blng,
        "year_built": _str(base.get("completionTime")),
        "building_type": _str(base.get("buildTypeStr")),
        "ownership_type": _str(base.get("shipTypeStr")),
        "property_types": [_str(p) for p in base.get("propertyTypes") or [] if _str(p)],
        "land_tenure": _str(base.get("landUsagePeriod")),
        "tags": _tag_names(base.get("tags")),
        "is_near_metro": _flag(flag.get("closeSubway")),
        "is_near_school": _flag(flag.get("closeSchool")),
        "has_panorama": _flag(flag.get("hasPanoPhoto")),
        "photo": _photo(base.get("defaultPhoto")),
    }


def _community_extend(extend):
    if not extend:
        return {}
    return {
        "developer": _str(extend.get("developer")),
        "property_company": _str(extend.get("propertyCompany")),
        "property_brand": _str(extend.get("propertyBrand")),
        "property_fee": _str(extend.get("propertyMoney")),
        "property_phone": _str(extend.get("propertyTelephone")),
        "plot_ratio": _num(extend.get("plotRatio")),
        "green_ratio_pct": _num(extend.get("landscapingRatio")),
        "households": _nonzero(extend.get("totalHouseHoldNum")),
        "total_area_sqm": _nonzero(extend.get("totalArea")),
        "parking": _str(extend.get("parking")),
        "parking_fee": _str(extend.get("parkingFee")),
        "parking_management_fee": _str(extend.get("manageParkingFee")),
        "has_elevator": _flag(extend.get("hasElevator")) if extend.get("hasElevator") not in (None, "") else None,
        "has_heating": _flag(extend.get("heatSupply")) if extend.get("heatSupply") not in (None, "") else None,
        "utilities": _str(extend.get("waterPowerSupply")),
        "property_features": _str(extend.get("propertyFeatures")),
        "merits": _str(extend.get("merits")),
        "demerits": _str(extend.get("demerits")),
        "completion_years": _dedupe([_str(c.get("year")) for c in extend.get("completionTimes") or [] if isinstance(c, dict)]),
        "introduction": _str(extend.get("introduction") or extend.get("introductionSeo")),
        "media_counts": {"photos": _int(extend.get("photoNum")), "videos": _int(extend.get("videoNum")),
                         "panoramas": _int(extend.get("panoNum"))},
    }


def _community_price(price):
    if not price:
        return None
    return {
        "per_sqm": _nonzero(price.get("price")),
        "month_change_pct": _num(price.get("monthChange")),
        "year_change_pct": _num(price.get("yearChange")),
        "sentiment": _str(price.get("marketSentiment")),
        "month": _int(price.get("month")),
        "label": _str(price.get("title")),
        "currency": CURRENCY,
    }


def _community_counts(props):
    if not props:
        return None
    return {"for_sale": _int(props.get("saleNum")), "for_rent": _int(props.get("rentNum")),
            "new_home_units": _int(props.get("xinfangNum")), "recent_transactions": _int(props.get("tradeNum"))}


def parse_community_list(html, city):
    """A community list page (desktop or mobile, same Nuxt payload) ->
    (communities, total, page, has_next)."""
    data, _ = nuxt_data(html)
    block = data.get("communityListData") or {}
    out = []
    for comm in block.get("communities") or []:
        base = comm.get("base") or {}
        if not base.get("id"):
            continue
        row = _community_base(base, city)
        row.update(_community_extend(comm.get("extend")))
        row["price"] = _community_price(comm.get("priceInfo"))
        row["counts"] = _community_counts(comm.get("propInfo"))
        row["score"] = _grade(comm.get("grade"))
        row["metro"] = _str(comm.get("metroDesc")) or None
        row["school"] = _str(comm.get("schoolDesc")) or None
        out.append(row)
    params = data.get("pathParams") or {}
    search = data.get("searchParams") or {}
    return {
        "communities": out,
        "total": _int(block.get("total")),
        "page": _int(params.get("pageNo")) or _int(search.get("page")) or 1,
        "has_next": _flag(block.get("hasNext")) or None,
        "keyword": _str(search.get("q")),
    }


def parse_community_view(html, community_id, city):
    """The mobile community page (m.anjuke.com/<alias>/community/<id>/) -> the
    community record: base + extended facts, current price, counts, score
    card, map, gallery counts, Q&A and the user-comment total."""
    data, _ = nuxt_data(html)
    comm = data.get("community") or {}
    base = comm.get("base") or {}
    if not base.get("id"):
        raise NuxtStateError("community page carries no base block")
    record = _community_base(base, city)
    record.update(_community_extend(comm.get("extend")))
    record["price"] = _community_price(comm.get("priceInfo") or data.get("priceInfo"))
    price_data = (data.get("priceInfo") or {}).get("priceData") or []
    record["price_history_6m"] = [{"month": _str(p.get("date")), "per_sqm": _nonzero(p.get("price"))} for p in price_data if isinstance(p, dict)]
    record["counts"] = _community_counts(comm.get("propInfo"))
    record["score"] = _grade(comm.get("grade") or (data.get("scoreInfo") or {}).get("score"))
    evaluation = comm.get("evaluationInfo") or {}
    sections = {_str(d.get("type")): _str(d.get("content")) for d in evaluation.get("detail") or [] if isinstance(d, dict) and _str(d.get("type"))}
    record["evaluation"] = {
        "summary": _str(evaluation.get("summaryContent")),
        "advantages": sections.get("优点"),
        "disadvantages": sections.get("缺点"),
        "living_experience": sections.get("居住感受"),
        "transport": sections.get("周边交通"),
        "other_sections": {k: v for k, v in sections.items() if k not in ("优点", "缺点", "居住感受", "周边交通")} or None,
    } if evaluation else None
    gallery = data.get("galleryData") or {}
    totals = gallery.get("total") or {}
    record["gallery"] = {
        "counts": {"photos": _int(totals.get("photo")), "videos": _int(totals.get("video")), "panoramas": _int(totals.get("pano"))},
        "photos": _dedupe([_photo(p.get("imageUrl") or p.get("image")) for p in gallery.get("room_photos") or [] if isinstance(p, dict)]),
        "videos": [{"link": _str(v.get("resource")), "cover": _photo(v.get("coverImage") or v.get("image"))}
                   for v in gallery.get("video_photos") or [] if isinstance(v, dict) and _str(v.get("resource"))],
    }
    map_info = data.get("mapInfo") or {}
    if map_info.get("lat") and not record.get("lat"):
        record["lat"], record["lng"] = _lat_lng(map_info.get("lat"), map_info.get("lng"))
    record["map_image"] = _photo(map_info.get("picUrl"))
    qa = data.get("qaInfo") or {}
    record["questions"] = {"total": _int(qa.get("total")), "items": [_mobile_qa(q) for q in qa.get("list") or [] if isinstance(q, dict)]} if qa else None
    comments = data.get("commentInfo") or {}
    record["comments_total"] = _int(comments.get("total")) if comments else None
    brokers = (data.get("brokerList") or {}).get("data") or []
    record["featured_brokers"] = [_mobile_broker(b) for b in brokers if isinstance(b, dict)]
    return record


def _mobile_qa(q):
    best = q.get("best_answer") or {}
    return {"id": _str(q.get("id")), "question": _str(q.get("title")), "answers_count": _int(q.get("answer_count")),
            "link": _str(q.get("url")), "best_answer": _str(best.get("content"))}


def _mobile_broker(b):
    other = b.get("otherBrokerVo") or {}
    return {"id": _str(b.get("brokerId")), "name": _str(b.get("brokerName")), "link": _str(b.get("url")),
            "photo": _photo(b.get("photo")), "company": _str(other.get("companyFullName") or other.get("companyName")),
            "store": _str(other.get("storeName")), "avg_response_time": _str(b.get("avgRespondTime")),
            "note": _str(b.get("rcmdText"))}


def parse_community_price(html, community_id, city):
    """The desktop valuation page (/gufangjia/xiaoqu-<id>/) -> 36-month price
    history of the community and its business area, per-layout valuations,
    recent transactions and the page's featured agents."""
    data, _ = nuxt_data(html)
    trend = data.get("priceTrend") or {}
    nav = (data.get("navData") or {}).get("community") or {}
    if not (trend or nav):
        raise NuxtStateError("valuation page carries no price block")
    comm_info = trend.get("commInfo") or {}
    sq_info = trend.get("shangquanInfo") or {}

    def series(points):
        return [{"month": _str(p.get("date")), "per_sqm": _nonzero(p.get("price"))} for p in points or [] if isinstance(p, dict)]

    valuations = []
    for row in data.get("evaluate_list") or []:
        if not isinstance(row, dict):
            continue
        valuations.append({
            "layout": _layout(row.get("roomNum"), row.get("hallNum"), row.get("toiletNum")),
            "area_sqm": _num(row.get("area")),
            "floor_level": _str(row.get("floorDesc")),
            "orientation": _str(row.get("orientDesc")),
            "valuation": _wan_to_yuan(row.get("assessTotal")) if _str(row.get("assessTotalUnit")) == "万" else _num(row.get("assessTotal")),
            "valuation_wan": _num(row.get("assessTotal")) if _str(row.get("assessTotalUnit")) == "万" else None,
            "valued_at": _str(row.get("assessTime")).replace(".", "-") if _str(row.get("assessTime")) else None,
            "currency": CURRENCY,
        })
    agents = []
    for b in data.get("broker_list") or []:
        if isinstance(b, dict):
            base = b.get("base") or b
            agents.append({"id": _str(base.get("brokerId") or base.get("broker_id")), "name": _str(base.get("name")),
                           "company": _str(base.get("companyName") or base.get("company_name")),
                           "store": _str(base.get("storeName") or base.get("store_name")),
                           "note": _str(b.get("reason")), "link": _str(b.get("jumpAction"))})
    return {
        "id": _str(nav.get("id")) or community_id,
        "name": _str(nav.get("name")) or _str(comm_info.get("name")),
        "price": {"per_sqm": _nonzero(comm_info.get("price")), "last_month_per_sqm": _nonzero(comm_info.get("lastMonthPrice")),
                  "month_change_pct": _num(comm_info.get("monthChange")), "year_change_pct": _num(comm_info.get("yearChange")),
                  "label": _str(comm_info.get("title")), "currency": CURRENCY} if comm_info else None,
        "business_area_price": {"name": _str(sq_info.get("name")), "per_sqm": _nonzero(sq_info.get("price")),
                                "month_change_pct": _num(sq_info.get("monthChange")), "year_change_pct": _num(sq_info.get("yearChange")),
                                "link": _str(sq_info.get("url")), "currency": CURRENCY} if sq_info else None,
        "price_history": series(trend.get("community")),
        "business_area_price_history": series(trend.get("shangquan")),
        "valuations": valuations,
        "recent_transactions": [t for t in data.get("trade_list") or [] if isinstance(t, dict)],
        "featured_agents": agents,
        "price_history_link": _str(trend.get("historyJumpAction")),
    }


# ---- new homes (新房 / 楼盘) -----------------------------------------------------------------

_SALE_STATUS = {"1": "upcoming", "2": "upcoming", "3": "upcoming", "4": "on_sale", "5": "sold_out", "6": "tail", "7": "sold_out"}


def _loupan_price(value, unit, note=None):
    """A project's headline price: "元/m²" is a price per m²; "万元/套起" is a
    from-price per unit in 万 (10,000 CNY), e.g. 汤臣君品 5656 万元/套起 =
    56,560,000 CNY. The site sorts both kinds together on one scale."""
    per_unit = bool(unit) and "套" in unit
    return {
        "per_sqm": None if per_unit else value,
        "total_from": _wan_to_yuan(value) if per_unit and value else None,
        "total_from_wan": value if per_unit else None,
        "unit": unit,
        "currency": CURRENCY if value else None,
        "note": note or None,
    }


def _loupan_row(row, city):
    status = row.get("status") or {}
    phone = row.get("400phone") or {}
    lat, lng = _lat_lng(row.get("baidu_lat"), row.get("baidu_lng"))
    loupan_id = _str(row.get("loupan_id"))
    metro = [{"line": _str(g.get("subway_name")), "station": _str(g.get("station_name")),
              "distance_m": _int(g.get("distance_raw"))} for g in row.get("guijiao") or [] if isinstance(g, dict)]
    price = _nonzero(row.get("new_price_value"))
    jump = _str(row.get("jump_url"))
    alias = jump.split("m.anjuke.com/")[1].split("/")[0] if jump and "m.anjuke.com/" in jump else refs.city_alias(city)
    return {
        "id": loupan_id,
        "name": _str(row.get("loupan_name")),
        "link": f"https://{alias}.fang.anjuke.com/loupan/{loupan_id}.html",
        "mobile_link": jump.split("?")[0] if jump else refs.project_mobile_link(city, loupan_id),
        "status": _str(status.get("complex_title") or status.get("sale_title") or row.get("sale_title")),
        "sale_status": _str(status.get("sale_title") or row.get("sale_title")),
        "rent_status": _str(status.get("rent_title")) if _flag(status.get("is_show_rent")) else None,
        "property_type": _str(row.get("property_type")),
        "building_types": [_str(b) for b in row.get("building_types") or [] if _str(b)],
        "city": {"id": _int(row.get("city_id")), "name": _str(row.get("city_name"))},
        "district": {"id": _int(row.get("region_id")), "name": _str(row.get("region_title"))},
        "block": {"id": _int(row.get("sub_region_id")), "name": _str(row.get("sub_region_title"))} if row.get("sub_region_id") else None,
        "address": _str(row.get("address")),
        "baidu_lat": lat, "baidu_lng": lng,
        "price": _loupan_price(price, _str(row.get("new_price_back")), _str((row.get("recommend_price") or {}).get("value"))),
        "area_range": _str(row.get("area_range")),
        "layouts": _str(row.get("housetype_text")),
        "rooms": _dedupe([_int(r.get("rooms")) for r in row.get("rooms_area") or [] if isinstance(r, dict)]),
        "opening_date": _str(row.get("kaipan_date")),
        "opening_note": _str(row.get("kaipan_date_note")),
        "tags": _dedupe([_str(t) for t in row.get("tags_list") or []]),
        "brand_tags": _dedupe([_str(t.get("name")) for t in row.get("tags_title") or [] if isinstance(t, dict)]),
        "activity": _dedupe([_str(a.get("title")) for a in row.get("activity") or [] if isinstance(a, dict)]),
        "metro": metro,
        "sales_phone": f"{phone.get('service_num')}转{phone.get('num')}" if phone.get("service_num") and phone.get("num") else _str(phone.get("service_num")),
        "has_video": _flag(row.get("has_video")),
        "has_vr": _flag(row.get("has_quanjing")),
        "has_aerial_photo": _flag(row.get("has_aerial_photo")),
        "has_sunlight_simulation": _flag(row.get("has_sunshine")),
        "is_unlicensed": _flag(row.get("is_unlicensed")),
        "is_developer_direct": bool((row.get("flagship_service") or {}).get("titles")) or None,
        "unit_counts": {k: _int(v) for k, v in (row.get("counts") or {}).items()} or None,
        "photo": _photo(row.get("default_image")),
    }


def parse_loupan_list(html, city):
    """The mobile new-home list page -> its first page of projects plus the
    query its own "load more" XHR replays: `cid` (the new-home city id) and
    `args` (the filters the path encodes). The page's `params.page` is the
    NEXT page that XHR will load, so the rendered page is params.page - 1."""
    _, state = nuxt_data(html)
    block = ((state.get("state") or {}).get("loupan") or {}).get("loupan") or {}
    params = block.get("params") or {}
    if not params.get("cid"):
        raise NuxtStateError("new-home list page carries no city id")
    rows = block.get("twLoupans") or []
    return {
        "cid": _int(params.get("cid")),
        "args": params.get("args") if isinstance(params.get("args"), dict) else {},
        "projects": [_loupan_row(r, city) for r in rows if isinstance(r, dict) and r.get("loupan_id")],
        "total": _int(block.get("totalTwLoupan")),
        "page": max((_int(params.get("page")) or 2) - 1, 1),
        "has_more": _flag(block.get("hasMore")),
        "list_name": _str(block.get("listName")),
    }


def parse_loupan_api(payload, city):
    """The new-home list XHR (xinfang/api/loupan/list/) -> (projects, total,
    has_more). 20 rows a page, same row shape as the rendered page."""
    result = (payload or {}).get("result") or {}
    rows = result.get("rows") or []
    return {
        "projects": [_loupan_row(r, city) for r in rows if isinstance(r, dict) and r.get("loupan_id")],
        "total": _int(result.get("total")),
        "has_more": _flag(result.get("has_more")),
        "list_name": _str(result.get("list_name")),
    }


def parse_loupan_districts(html):
    """The district links of a mobile new-home list page -> [{name, slug}]
    (the new-home district slugs differ from the resale ones: pinggu vs
    pinggua, dongcheng vs dongchenga)."""
    out = []
    for slug, name in re.findall(r'<a[^>]+href="https?://m\.anjuke\.com/[a-z0-9]+/loupan/([a-z0-9]+)/"[^>]*>\s*([^<]{1,20}?)\s*<', html or ""):
        if slug in ("all",) or slug.isdigit():
            continue
        name = _str(name)
        if name and slug not in [o["slug"] for o in out]:
            out.append({"name": name, "slug": slug})
    return out


def _text(node, sep=" "):
    return _str(node.get_text(sep)) if node is not None else None


def parse_loupan_main(html, project_id, city):
    """The mobile project page (m.anjuke.com/<alias>/loupan/<id>/) -> the
    headline record: name, status tags, reference price, total-price and
    area ranges, layouts, opening, address + coordinates, rankings, hotline,
    album and the on-page floor-plan summary."""
    soup = BeautifulSoup(html, "lxml")
    name = soup.select_one("h1.loupan-name")
    if name is None or not _text(name):
        raise NuxtStateError("project page carries no name")
    tags = [_text(em) for em in soup.select(".lptags .default-tag")]
    avg = soup.select_one(".avg-price em")
    total = soup.select_one(".total-price em")
    area = soup.select_one(".area-range em")
    rooms = soup.select_one(".huxing-wrap .value-tip")
    opening = None
    for line in soup.select(".date .common-line"):
        label = _text(line.select_one("label"))
        if label and "开盘" in label:
            opening = _text(line.select_one(".common-value"))
    address_node = soup.select_one("a.address")
    address = _text(address_node.select_one(".common-value-overflow")) if address_node is not None else None
    lat = lng = None
    if address_node is not None and address_node.get("href"):
        mlat = re.search(r"[?&]lat=([\d.]+)", address_node["href"])
        mlng = re.search(r"[?&]lng=([\d.]+)", address_node["href"])
        lat, lng = (_float(mlat.group(1)) if mlat else None), (_float(mlng.group(1)) if mlng else None)
    if lat is None:
        mlat = re.search(r"\blat=(\d{1,2}\.\d+)", html)
        mlng = re.search(r"\blng=(\d{2,3}\.\d+)", html)
        lat, lng = (_float(mlat.group(1)) if mlat else None), (_float(mlng.group(1)) if mlng else None)
    rankings = _dedupe([_text(s) for s in soup.select(".rank-bang-detail span")])
    # JSON-LD "telephone" carries the project's extension ("4000919290,874565"); the
    # bare 400 number alone is the site-wide hotline every project shares.
    hotline = re.search(r'"telephone"\s*:\s*"(400\d{7})(?:,(\d+))?"', html) or re.search(r"\b(400\d{7})\b", html)
    album = _dedupe([_photo(img.get("src")) for img in soup.select(".loupan-album img.album-img")])
    album_tabs = [_text(t) for t in soup.select(".loupan-album .tab-item em")]
    floor_plans = []
    for item in soup.select(".huxing-block .huxing-item"):
        names = [_text(n) for n in item.select(".hxname")]
        price_node = item.select_one(".hxprice")
        floor_plans.append({
            "status": _text(item.select_one(".hx-status_sale_rent")),
            "area_text": next((n for n in names if n and "m²" in n), None),
            "is_featured": item.select_one(".hx-fashion") is not None,
            "has_vr": item.select_one(".icon-panorama") is not None,
            "image": _photo((item.select_one("img.huxing-image") or {}).get("src")),
            "price_from_wan": _first_number(price_node.get_text()) if price_node is not None and _first_number(price_node.get_text()) else None,
        })
    total_text = _text(total)
    total_range = re.match(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", total_text or "")
    area_text = _text(area)
    area_range = re.match(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", area_text or "")
    status = tags[0] if tags and tags[0] in ("在售", "待售", "售罄", "尾盘") else None
    canonical_node = soup.select_one('link[rel="canonical"][href*=".fang.anjuke.com/loupan/"]')
    canonical = _str(canonical_node.get("href")) if canonical_node is not None else None
    return {
        "id": project_id,
        "name": _text(name),
        "link": canonical or refs.project_link(city, project_id),
        "mobile_link": refs.project_mobile_link(refs.city_from_link(canonical) or city, project_id),
        "status": status,
        "tags": [t for t in tags if t and t != status],
        "price": {"per_sqm": _first_number(_text(avg)), "currency": CURRENCY if _first_number(_text(avg)) else None,
                  "note": _text(soup.select_one(".avg-price-box .value-tip"))},
        "total_price": {"min_wan": _num(total_range.group(1)) if total_range else _first_number(total_text),
                        "max_wan": _num(total_range.group(2)) if total_range else None,
                        "min": _wan_to_yuan(total_range.group(1)) if total_range else _wan_to_yuan(_first_number(total_text)),
                        "max": _wan_to_yuan(total_range.group(2)) if total_range else None,
                        "text": total_text, "currency": CURRENCY} if total_text else None,
        "area_range_sqm": {"min": _num(area_range.group(1)) if area_range else _first_number(area_text),
                           "max": _num(area_range.group(2)) if area_range else None, "text": area_text} if area_text else None,
        "layouts": _text(rooms),
        "opening": _cn_date(opening),
        "address": address,
        "lat": lat, "lng": lng,
        "rankings": rankings,
        "sales_phone": (f"{hotline.group(1)}转{hotline.group(2)}" if hotline.lastindex == 2 and hotline.group(2)
                        else hotline.group(1)) if hotline else None,
        "album": {"tabs": [t for t in album_tabs if t], "photos": album},
        "floor_plans_summary": floor_plans,
    }


def parse_loupan_params(html, project_id):
    """The parameters page (/loupan/<id>/params/) -> every label/value row
    grouped by its section, plus the presale permits as a list."""
    soup = BeautifulSoup(html, "lxml")
    sections = {}
    permits, current = [], {}
    for wrap in soup.select(".content-wrap"):
        title = _text(wrap.select_one(".content-wrap-title"))
        if not title:
            continue
        rows = {}
        for li in wrap.select("li.content-item, li.content-item_empty"):
            if "content-item_empty" in (li.get("class") or []):
                if current:
                    permits.append(current)
                    current = {}
                continue
            label = _text(li.select_one(".content-item-title"))
            value_node = li.select_one(".content-item-content")
            value = _text(value_node) if value_node is not None else None
            if value_node is not None and value_node.select_one(".tooltip-wrap") is not None and not value:
                value = None   # a tooltip image where the value should be
            if not label:
                continue
            if title == "预售许可证":
                current[label] = value
            else:
                rows[label] = value
        if title == "预售许可证":
            if current:
                permits.append(current)
                current = {}
        else:
            sections[title] = rows
    tags = [_text(t) for t in soup.select(".tag-wrap .tag")]
    if not sections and not permits:
        raise NuxtStateError("parameters page carries no sections")
    basic = sections.get("基础信息", {})
    sales = sections.get("销售信息", {})
    plan = sections.get("建筑规划", {})
    prop = sections.get("物业信息", {})
    return {
        "id": project_id,
        "tags": [t for t in tags if t],
        "sale_status": basic.get("销售状态"),
        "ring_road": basic.get("环线位置"),
        "address": basic.get("楼盘地址"),
        "developer": basic.get("开发商"),
        "developer_brand": basic.get("开发商品牌"),
        "reference_price_text": sales.get("参考价格"),
        "reference_price_per_sqm": _first_number(sales.get("参考价格")),
        "mortgage_note": sales.get("房贷计算"),
        "layouts": sales.get("全部户型"),
        "opening": _cn_date(sales.get("开盘时间")),
        "delivery": _cn_date(sales.get("交房时间")) if sales.get("交房时间") else None,
        "sales_office_address": sales.get("售楼处地址"),
        "land_area_sqm": _first_number(plan.get("占地面积")),
        "building_area_sqm": _first_number(plan.get("建筑面积")),
        "plot_ratio": _num(plan.get("容积率")) if plan.get("容积率") else None,
        "green_ratio_pct": _first_number(plan.get("绿化率")),
        "planned_households": _int(plan.get("规划户数")),
        "fitment": plan.get("装修情况"),
        "property_type": plan.get("物业类型") or basic.get("物业类型"),
        "building_type": plan.get("建筑类型"),
        "land_tenure": plan.get("产权年限") or basic.get("产权年限"),
        "property_company": prop.get("物业公司"),
        "property_fee": prop.get("物业管理费"),
        "parking_spaces": _int(prop.get("车位数")),
        "parking_ratio": prop.get("车位比"),
        "electricity": prop.get("供电"),
        "water": prop.get("供水"),
        "property_features": prop.get("物业特色"),
        "presale_permits": [{"number": p.get("预售证号"), "issued_on": p.get("发证时间"), "buildings": p.get("绑定楼栋")} for p in permits],
        "sections": sections,
    }


def parse_loupan_huxing(html, project_id):
    """The floor-plan page (/loupan/<id>/huxing/) -> every layout with its
    status, rooms, area, name, bonus area and from-price."""
    soup = BeautifulSoup(html, "lxml")
    plans = []
    for item in soup.select(".hx-item-wrap"):
        alias = _text(item.select_one(".alias-area"))
        price = item.select_one(".hx-price .price")
        suffix = _text(item.select_one(".hx-price .suffix"))
        plans.append({
            "name": _text(item.select_one(".hx-name")),
            "status": _text(item.select_one(".sale-status")),
            "layout": _layout_text(alias),
            "area_sqm": _first_number(alias.split("卫")[-1] if alias and "卫" in alias else alias),
            "bonus_area": _text(item.select_one(".hx-area")),
            "price_from_wan": _first_number(_text(price)) if price is not None and suffix and "万" in suffix else None,
            "price_from": _wan_to_yuan(_first_number(_text(price))) if price is not None and suffix and "万" in suffix else None,
            "price_text": (_text(price) or "") + (suffix or "") if price is not None and _text(price) else None,
            "is_featured": item.select_one(".recom-tag") is not None,
            "has_vr": item.select_one(".icon-quanjing") is not None,
            "image": _photo((item.select_one("img") or {}).get("src")),
            "currency": CURRENCY,
        })
    filters = {}
    for line in soup.select(".filter-line"):
        title = _text(line.select_one(".filter-title"))
        if title:
            filters[title] = [_text(s) for s in line.select(".filter-items span") if _text(s)]
    return {"id": project_id, "floor_plans": plans, "filters": filters or None}


def parse_loupan_price(html, project_id):
    """The price page (/loupan/<id>/jiage/) -> city / district / block average
    prices and the block's rising / falling projects. The trend chart itself
    is drawn from a separate XHR and is not on the page."""
    soup = BeautifulSoup(html, "lxml")
    averages = []
    for anchor in soup.select(".house_price_table a"):
        label = _text(anchor.select_one("span")) or _text(anchor)
        price = anchor.select_one(".house_price")
        if price is not None:
            scope = _str(re.sub(r"\d.*$", "", label or "")) or None
            averages.append({"scope": (scope or "").replace("房价：", "").replace("房价", "") or None,
                             "per_sqm": _first_number(_text(price)), "link": anchor.get("href"), "currency": CURRENCY})
    movers = {}
    for block in soup.select(".house_price_list"):
        title = _text(block.select_one("h4"))
        rows = []
        for anchor in block.select("a.g-next"):
            name = _text(anchor.select_one(".name"))
            rows.append({"name": re.sub(r"^\d+\.\s*", "", name) if name else None,
                         "per_sqm": _first_number(_text(anchor.select_one(".price"))),
                         "change_text": _text(anchor.select_one("[class^=percent]")),
                         "link": anchor.get("href")})
        if title:
            key = "rising" if "上升" in title else ("falling" if "下降" in title else title)
            movers[key] = rows
    name = soup.select_one(".loupan-tlt span")
    return {"id": project_id, "name": _text(name), "area_averages": averages,
            "nearby_rising": movers.get("rising", []), "nearby_falling": movers.get("falling", [])}


def parse_loupan_reviews(payload):
    """ajaxdianpin JSON -> (total, reviews, tags). The route ignores paging
    and serves the latest ten."""
    payload = payload or {}
    reviews = []
    for r in payload.get("dianpin") or []:
        if not isinstance(r, dict):
            continue
        reviews.append({
            "id": _str(r.get("id")),
            "author": _str(r.get("author_name")),
            "author_link": _str(r.get("author_url")),
            "author_photo": _photo(r.get("Avatar")),
            "is_verified_author": _flag(r.get("is_v")),
            "text": _str(r.get("content")),
            "posted_at": _str(r.get("create_time")) or _epoch_iso(r.get("created")),
            "rating": _nonzero(r.get("service_score")),
            "likes": _int(r.get("total_love")),
            "replies": _int(r.get("reply_num")),
            "photos": [_photo(p) for p in r.get("images") or [] if _photo(p)],
            "visit_status": _int(r.get("visit_loupan_status")),
            "link": _str(r.get("view_url")),
        })
    tags = [_review_tag(t) for t in payload.get("tagsInfo") or [] if isinstance(t, dict)]
    return {"total": _int(payload.get("dianp_total_count")), "reviews": reviews, "tags": [t for t in tags if t["name"]]}


_TAG_COUNT_RE = re.compile(r"^(.*?)\s*[(（]\s*(\d+)\s*[)）]\s*$")


def _review_tag(t):
    """{"tag_id": 8, "tag_title": "环境不错(63)", "tag_url": ...} -> name + count."""
    title = _str(t.get("tag_title") or t.get("tag_name") or t.get("name"))
    count = _int(t.get("count") if t.get("count") is not None else t.get("cnt"))
    match = _TAG_COUNT_RE.match(title or "")
    if match:
        title = _str(match.group(1)) or title
        count = _int(match.group(2)) if count is None else count
    return {"id": _str(t.get("tag_id")), "name": title, "count": count, "link": _str(t.get("tag_url"))}


def parse_loupan_questions(html, project_id):
    """The Q&A list page (/loupan/<id>/wenda/wenlist/) -> questions with
    their best answer and the project's question total."""
    _, state = nuxt_data(html)
    wenda = (((state.get("state") or {}).get("loupan") or {}).get("wenda") or {})
    block = wenda.get("questionlist") or {}
    rows = block.get("rows") or wenda.get("questionlists") or []
    out = []
    for q in rows:
        if not isinstance(q, dict):
            continue
        best = q.get("best_answer") or {}
        author = best.get("author") or {}
        out.append({
            "id": _str(q.get("question_id")),
            "question": _str(q.get("title")),
            "asked_at": _str(q.get("create_time")),
            "answers_count": _int(q.get("answer_count")),
            "link": _str(q.get("jump_url")),
            "best_answer": {"text": _str(best.get("content")), "answered_at": _str(best.get("create_time")),
                            "author": _str(author.get("name")), "author_role": ", ".join(_str(t) for t in author.get("tags") or [] if _str(t)) or None,
                            "author_link": _str(author.get("consultant_url"))} if _str(best.get("content")) else None,
        })
    return {"id": project_id, "project_name": _str(block.get("title")), "total": _int(block.get("total")),
            "has_more": _flag(block.get("has_more")), "questions": out}


_MOBILE_METRO_RE = re.compile(r"^(?P<line>.+?号线)(?P<station>.+)$")


def parse_rent_detail_mobile(html, rental_id, city):
    """The mobile rental page (m.anjuke.com/<alias>/rent/<id>-3/) -> the same
    record shape as parse_rent_detail. It carries what the desktop page
    lacks (the full photo set, metro stations with walking distances, the
    amenities split by room) and lacks the desktop broker card (score,
    ratings, licence)."""
    soup = BeautifulSoup(html, "lxml")
    listing = next((b for b in ld_json(html) if "RealEstateListing" in (b.get("@type") or [])), {})
    props = _ld_props(listing)
    offer = listing.get("offers") or {}
    geo = listing.get("geo") or {}
    info = {}
    for li in soup.select(".prop-info-list li"):
        text = _text(li)
        if text and "：" in text:
            key, value = text.split("：", 1)
            info[key.strip()] = _str(value)
    title = soup.select_one("h1.prop-title")
    tags = [_text(s) for s in soup.select(".prop-tags span")]
    price_block = soup.select_one(".prop-price")
    price_text = _text(price_block) or ""
    fees = {k: _first_number(v) for k, v in re.findall(r"(中介费|服务费)\s*[:：]\s*([^\s]+)", price_text)}
    payment = next((p for p in re.findall(r"押[一二三\d]付[一二三\d]|付\d押\d", price_text)), None)
    amenities = {}
    for dl in soup.select(".hezu-config-detail dl.conf-cate"):
        cat = _text(dl.select_one("dt"))
        amenities[cat or "其他"] = [t for t in (_text(li) for li in dl.select("li")) if t]
    metro = []
    for li in soup.select(".comm-intro .stat-list li"):
        stat, dist = _text(li.select_one(".stat")), _text(li.select_one(".distance"))
        match = _MOBILE_METRO_RE.match(stat or "")
        metro.append({"line": match.group("line") if match else None, "station": match.group("station") if match else stat,
                      "walk_text": dist, "walk_m": _first_number(dist)})
    comm_link = soup.select_one(".comm-intro a.comm-link[href]")
    comm_text = _text(comm_link) or ""
    comm_match = re.match(r"(?:小区：\s*)?(.+?)\s*\(\s*(\S+)\s+(\S+)\s*\)", comm_text)
    comm_id = None
    if comm_link is not None:
        m = re.search(r"/community/(\d+)/", comm_link["href"])
        comm_id = m.group(1) if m else None
    agent = soup.select_one(".main-agent")
    complaints = soup.select_one(".agent-company .complaints-tel .phone")
    broker = {
        "name": _text(agent.select_one(".name")) if agent else None,
        "photo": None,
        "company": _text(agent.select_one(".agent-icon")) if agent else None,
        "company_license": None,
        "company_complaints_phone": _text(complaints) if complaints is not None else None,
        "store": None, "service_score": None, "service_score_note": None, "ratings": None,
        "identity_card_number": None, "phone": None,
    } if agent is not None and _text(agent.select_one(".name")) else None
    photos = _dedupe([_photo(img.get("src")) for img in soup.select(".view-photo .swiper-slide")
                      if img.get("src") and "ajkimg" in img.get("src")])
    video = re.search(r'https?://[^"\']+\.mp4[^"\']*', html)
    date = soup.select_one(".prop-publis-date")
    description = soup.select_one(".prop-desc-content")
    url = _str(listing.get("url")) or refs.rental_link(city, rental_id)
    city = refs.city_from_link(url) or city        # a bare id carries no city; the page's own link does
    alias = url.split("//")[1].split(".")[0] if "//" in url else refs.city_alias(city)
    all_amenities = _dedupe([a for items in amenities.values() for a in items]) or (props.get("房屋配套") or "").split()
    return {
        "id": rental_id,
        "title": _text(title) or _str(listing.get("name")),
        "link": url.rstrip("/"),
        "mobile_link": f"{refs.MOBILE}/{alias}/rent/{rental_id}-3/",
        "rental_type": next((t for t in tags if t in ("合租", "整租")), None),
        "rent": {"monthly": _first_number(offer.get("price")) or _first_number(price_text), "currency": CURRENCY,
                 "payment_terms": payment, "agency_fee": fees.get("中介费"), "service_fee": fees.get("服务费")},
        "layout": _layout_text(info.get("户型")),
        "area_sqm": _first_number(info.get("面积")),
        "orientation": _str(props.get("朝向") or info.get("朝向")),
        "floor": _floor(None, None, props.get("楼层") or info.get("楼层")),
        "fitment": _str(props.get("装修") or info.get("装修")),
        "use_type": _str(props.get("类型") or info.get("类型")),
        "is_verified": None,
        "tags": [t for t in tags if t],
        "amenities": all_amenities,
        "amenities_by_room": amenities or None,
        "amenities_missing": [],
        "description": "\n".join(t for t in (l.strip() for l in description.get_text("\n").split("\n")) if t) if description is not None else _str(props.get("房源概况")),
        "updated_at": _cn_date(props.get("更新时间")) or (_str(date.get_text()).replace("更新", "") if date is not None else None),
        "address": _str((listing.get("address") or {}).get("streetAddress")),
        "lat": _float(geo.get("latitude")),
        "lng": _float(geo.get("longitude")),
        "community": {
            "id": comm_id,
            "name": _str(comm_match.group(1)) if comm_match else _str(props.get("小区")),
            "link": refs.community_link(city, comm_id) if comm_id else None,
            "district": _str(comm_match.group(2)) if comm_match else None,
            "business_area": _str(comm_match.group(3)) if comm_match else None,
        } if (comm_id or props.get("小区")) else None,
        "metro": metro,
        "photos": photos,
        "video_link": video.group(0) if video else None,
        "broker": broker,
    }
