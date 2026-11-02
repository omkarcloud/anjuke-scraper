"""The /anjuke/* endpoint functions (route_glue's route_table calls them
with the schema's loaded kwargs).

Every endpoint caches inside (cache.cached_call, tofler-style) because the
same upstream page serves several endpoints and every page costs one fresh
datacenter exit: a city's resale list page is the vocabulary behind
cities/details, the numeric city id behind sale/suggest and the district /
business-area slugs behind every search; the mobile community page +
valuation page are ONE cached community record behind communities/details;
the four mobile project pages are ONE cached project record.

Place inputs (district / area) accept the site's slug ("chaoyang", "cbd")
or the Chinese name ("朝阳", "CBD"); names resolve through the cached city
vocabulary. Free-text `q` on sale/search goes to the site's own keyword
search; on rent/search it resolves through the autocomplete to a business
area (the mobile rental list ignores keywords).
"""
import math

from cache import cached_call
from upwork.nuxt import NuxtStateError
from anjuke import cache_config as ttl
from anjuke import fetch, parsers, refs
from anjuke.fetch import AnjukeBlocked, AnjukeNotFound, AnjukeUpstreamError


def _nuxt(fn, *args, label):
    """Run a parser; a page that decodes to nothing is an upstream failure
    (a layout change or a half-served page), never an empty record."""
    try:
        return fn(*args)
    except NuxtStateError as e:
        raise AnjukeUpstreamError(f"{label}: {e}")


# ---- cities -------------------------------------------------------------------------------

def cities_list(q=None):
    """Every city the site serves, from refs.CITY_ROWS (the site's own table,
    frozen 2026-10-31): no upstream call."""
    needle = (q or "").lower()
    rows = []
    for name, pinyin, alias, extra, _new_only in refs.CITY_ROWS:
        if needle and not any(needle in (v or "").lower() for v in (name, pinyin, alias, *extra)):
            continue
        rows.append(refs.city_record(pinyin))
    rows.sort(key=lambda r: (not r["is_hot"], r["pinyin"]))
    return {"query": q, "count": len(rows), "cities": rows}


def _city_details(city):
    html = fetch.fetch_sale_list(refs.sale_path(city), city)
    return _nuxt(parsers.parse_city_details, html, city, label="city page")


def _city_vocabulary(city):
    return cached_call("anjuke.city", {"city": city}, _city_details, ttl.CITY_CACHE)


def cities_details(city):
    record = refs.city_record(city)
    if not record["has_resale"]:
        # a new-homes-only city has no resale site and so no vocabulary
        record.update({"id": None, "province": None, "lat": None, "lng": None, "resale_listings_total": None,
                       "districts": [], "metro_lines": [], "filters": None})
        return record
    return _city_vocabulary(city)


# ---- place resolution ----------------------------------------------------------------------

def _is_slug(value):
    return bool(value) and refs.SLUG_RE.match(value.lower()) is not None


def _resolve_place(city, district=None, area=None):
    """(district slug, area slug) from slugs or Chinese names; a bare area
    name is looked up across every district. ValueError (-> 400) when a name
    is not in the city's vocabulary."""
    if not district and not area:
        return None, None
    vocab = _city_vocabulary(city)
    districts = vocab.get("districts") or []

    def norm(value):
        return (value or "").strip().lower().replace("区", "").replace("县", "")

    d_slug = a_slug = None
    chosen = None
    if district:
        if _is_slug(district):
            d_slug = district.lower()
            chosen = next((d for d in districts if d["slug"] == d_slug), None)
        else:
            chosen = next((d for d in districts if norm(d["name"]) == norm(district)), None)
            if chosen is None:
                raise ValueError(f"Unknown district {district!r} for {city}: see /anjuke/cities/details?city={city}.")
            d_slug = chosen["slug"]
    if area:
        pool = [chosen] if chosen else districts
        if _is_slug(area):
            a_slug = area.lower()
            hit = next((d for d in pool if any(a["slug"] == a_slug for a in d["business_areas"])), None)
        else:
            hit = next((d for d in pool if any(norm(a["name"]) == norm(area) for a in d["business_areas"])), None)
            if hit is None:
                raise ValueError(f"Unknown business area {area!r} for {city}: see /anjuke/cities/details?city={city}.")
            a_slug = next(a["slug"] for a in hit["business_areas"] if norm(a["name"]) == norm(area))
        if hit is not None and not d_slug:
            d_slug = hit["slug"]
        if hit is None and not d_slug:
            raise ValueError(f"Unknown business area {area!r} for {city}: see /anjuke/cities/details?city={city}.")
    return d_slug, a_slug


def _marks(*pairs):
    """[(public value or list, table), ...] -> the site's url marks."""
    out = []
    for value, table in pairs:
        if value is None:
            continue
        values = value if isinstance(value, list) else [value]
        for v in values:
            mark = table.get(str(v).lower()) if isinstance(table, dict) else None
            if mark:
                out.append(mark)
    return out


def _pagination(page, per_page, total, max_pages=None):
    total_pages = math.ceil(total / per_page) if total else 0
    if max_pages:
        total_pages = min(total_pages, max_pages)
    return {"page": page, "items_per_page": per_page, "total_pages": total_pages, "total_count": total}


# ---- sale ---------------------------------------------------------------------------------

def _sale_search(city, q=None, district=None, area=None, community=None, price_min=None, price_max=None,
                 size_min=None, size_max=None, rooms=None, type=None, age=None, fitment=None,
                 orientation=None, floor_level=None, property_type=None, features=None, ring=None,
                 sort=None, page=1):
    d_slug, a_slug = _resolve_place(city, district, area)
    marks = _marks((rooms, refs.SALE_ROOMS), (type, refs.SALE_TYPES), (age, refs.SALE_AGES),
                   (fitment, refs.SALE_FITMENTS), (orientation, refs.SALE_ORIENTATIONS),
                   (floor_level, refs.SALE_FLOOR_LEVELS), (property_type, refs.SALE_PROPERTY_TYPES),
                   (features, refs.SALE_FEATURES), (ring, refs.SALE_RINGS), (sort, refs.SALE_SORTS))
    query = {"prices": refs.range_param(price_min, price_max), "areas": refs.range_param(size_min, size_max),
             "kw": q, "comm_id": community}
    url = refs.sale_path(city, d_slug, a_slug, marks, page, query)
    parsed = _nuxt(parsers.parse_sale_list, fetch.fetch_sale_list(url, city), city, label="resale list")
    listings = parsed["listings"]
    if parsed["page"] != page:
        listings = []      # the server clamps pages past the end back to page 1
    return {
        "city": refs.city_record(city)["name"],
        "query": q,
        "district": d_slug,
        "business_area": a_slug,
        "keyword_match": parsed["keyword_match"],
        "source_link": url,
        "results": listings,
        "pagination": _pagination(page, refs.SALE_PAGE_SIZE, parsed["total"], refs.SALE_MAX_PAGE),
    }


def sale_search(**data):
    return cached_call("anjuke.sale_search", data, _sale_search, ttl.SEARCH_CACHE)


def _sale_details(listing):
    html = fetch.fetch_sale_detail(listing["city"], listing["id"])
    return _nuxt(parsers.parse_sale_detail, html, listing["id"], listing["city"], label="resale detail")


def sale_details(listing):
    return cached_call("anjuke.sale_details", {"listing": listing}, _sale_details, ttl.LISTING_CACHE)


def _sale_suggest(city, q):
    vocab = _city_vocabulary(city)
    if not vocab.get("id"):
        raise AnjukeUpstreamError(f"no numeric city id for {city}")
    payload = fetch.fetch_autocomplete(city, q, vocab["id"])
    results = parsers.parse_autocomplete(payload, city)
    return {"city": vocab["name"], "query": q, "count": len(results), "results": results}


def sale_suggest(**data):
    return cached_call("anjuke.sale_suggest", data, _sale_suggest, ttl.SUGGEST_CACHE)


# ---- rent ---------------------------------------------------------------------------------

def _resolve_rent_place(city, q, district, area):
    """The mobile rental list has no keyword search: `q` resolves through the
    autocomplete to a business area (a community hit falls back to its own
    business area)."""
    if not q:
        return _resolve_place(city, district, area) + (None,)
    suggest = sale_suggest(city=city, q=q)["results"]
    vocab = _city_vocabulary(city)
    hit = next((s for s in suggest if s["type"] == "business_area"), None)
    if hit is not None:
        for d in vocab["districts"]:
            for a in d["business_areas"]:
                if a["id"] == int(hit["id"]):
                    return d["slug"], a["slug"], {"type": "business_area", "name": a["name"], "district": d["name"]}
    hit = next((s for s in suggest if s["type"] == "community" and s.get("address")), None)
    if hit is not None:
        parts = [p for p in hit["address"].split("-") if p]
        if len(parts) >= 2:
            try:
                d_slug, a_slug = _resolve_place(city, parts[0], parts[1])
                return d_slug, a_slug, {"type": "community", "name": hit["name"], "business_area": parts[1], "district": parts[0]}
            except ValueError:
                pass
    raise ValueError(f"{q!r} did not match a business area or community in {city}; "
                     f"try /anjuke/sale/suggest?city={city}&q=... or pass district / area.")


def _rent_query(url, city):
    """The search_param of one rendered rental list page (its path = the filters)."""
    return {"search_param": _nuxt(parsers.parse_rent_search_param, fetch.fetch_rent_list(url, city), label="rental list page")}


def _rent_search(city, q=None, district=None, area=None, rent_min=None, rent_max=None, rooms=None,
                 rental_type=None, fitment=None, listed_by=None, page=1):
    d_slug, a_slug, matched = _resolve_rent_place(city, q, district, area)
    url = refs.rent_list_path(city, d_slug, a_slug, rent_min, rent_max, rooms,
                              refs.RENT_TYPES.get(rental_type) if rental_type else None,
                              refs.RENT_FITMENTS.get(fitment) if fitment else None,
                              refs.RENT_SOURCES.get(listed_by) if listed_by else None)
    query = cached_call("anjuke.rent_query", {"url": url, "city": city}, _rent_query, ttl.LIST_QUERY_CACHE)
    parsed = parsers.parse_rent_api(fetch.fetch_rent_api(city, query["search_param"], page), city)
    return {
        "city": refs.city_record(city)["name"],
        "query": q,
        "matched": matched,
        "district": d_slug,
        "business_area": a_slug,
        "source_link": url,
        "results": parsed["rentals"],
        # the site serves 116 pages per query, whatever the total says
        "pagination": _pagination(page, refs.RENT_PAGE_SIZE, parsed["total"], refs.RENT_MAX_PAGE),
    }


def rent_search(**data):
    return cached_call("anjuke.rent_search", data, _rent_search, ttl.RENT_SEARCH_CACHE)


def _rent_details(rental):
    """Mobile page first (every photo, metro walking distances, amenities by
    room; passes on every fresh exit), then the desktop page for what only it
    carries (the broker card: service score, ratings, licence, store; the
    verified badge; the missing-amenities list). The desktop zu host answers
    the geetest wall to about half of the datacenter exits, so when its retry
    ladder ends Blocked the record is served from the mobile page alone and
    says so in `sources`."""
    city, rental_id = rental["city"], rental["id"]
    record = parsers.parse_rent_detail_mobile(fetch.fetch_rent_detail_mobile(city, rental_id), rental_id, city)
    if not record.get("title") and not record.get("rent", {}).get("monthly"):
        raise AnjukeUpstreamError("rental page carries no listing")
    record["sources"] = ["mobile"]
    try:
        desktop = parsers.parse_rent_detail(fetch.fetch_rent_detail(city, rental_id), rental_id, city)
    except AnjukeBlocked:
        return record
    if desktop.get("broker"):
        record["broker"] = desktop["broker"]
    for key in ("is_verified", "amenities_missing", "video_link"):
        if desktop.get(key) not in (None, []):
            record[key] = desktop[key]
    record["tags"] = _dedupe(record.get("tags", []) + desktop.get("tags", []))
    record["photos"] = _dedupe(record.get("photos", []) + desktop.get("photos", []))
    if (desktop.get("community") or {}).get("id") and not (record.get("community") or {}).get("id"):
        record["community"] = desktop["community"]
    record["sources"] = ["mobile", "desktop"]
    return record


def _dedupe(items):
    out = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out


def rent_details(rental):
    return cached_call("anjuke.rent_details", {"rental": rental}, _rent_details, ttl.RENTAL_CACHE)


# ---- communities --------------------------------------------------------------------------

def _communities_search(city, q=None, district=None, area=None, age=None, sort=None, features=None, page=1):
    d_slug, a_slug = _resolve_place(city, district, area)
    marks = _marks((age, refs.COMMUNITY_AGES), (features, refs.COMMUNITY_FEATURES), (sort, refs.COMMUNITY_SORTS))
    url = refs.community_list_path(city, d_slug, a_slug, marks, page, {"kw": q})
    parsed = _nuxt(parsers.parse_community_list, fetch.fetch_community_list(url, city), city, label="community list")
    communities = parsed["communities"] if parsed["page"] == page else []
    return {
        "city": refs.city_record(city)["name"],
        "query": q,
        "district": d_slug,
        "business_area": a_slug,
        "source_link": url,
        "results": communities,
        "pagination": _pagination(page, refs.COMMUNITY_PAGE_SIZE, parsed["total"], refs.COMMUNITY_MAX_PAGE),
    }


def communities_search(**data):
    return cached_call("anjuke.communities_search", data, _communities_search, ttl.SEARCH_CACHE)


def _community_record(community):
    """Mobile community page + desktop valuation page, merged once."""
    city, community_id = community["city"], community["id"]
    view = _nuxt(parsers.parse_community_view, fetch.fetch_community_view(city, community_id), community_id, city,
                 label="community page")
    city = (view.get("city") or {}).get("pinyin") or city or "beijing"
    try:
        prices = _nuxt(parsers.parse_community_price, fetch.fetch_community_price(city, community_id), community_id, city,
                       label="community valuation page")
    except AnjukeNotFound:
        prices = None
    view["price_history"] = (prices or {}).get("price_history") or []
    view["business_area_price"] = (prices or {}).get("business_area_price")
    view["business_area_price_history"] = (prices or {}).get("business_area_price_history") or []
    view["valuations"] = (prices or {}).get("valuations") or []
    view["recent_transactions"] = (prices or {}).get("recent_transactions") or []
    view["featured_agents"] = (prices or {}).get("featured_agents") or []
    if prices and prices.get("price") and view.get("price"):
        view["price"]["year_change_pct"] = prices["price"].get("year_change_pct")
        view["price"]["last_month_per_sqm"] = prices["price"].get("last_month_per_sqm")
    view["valuation_link"] = refs.community_price_link(city, community_id)
    return view


def _community(community):
    return cached_call("anjuke.community", {"community": community}, _community_record, ttl.COMMUNITY_CACHE)


def communities_details(community):
    return _community(community)


def _communities_listings(community, page=1):
    record = _community(community)
    city = (record.get("city") or {}).get("pinyin") or community["city"] or "beijing"
    result = sale_search(city=city, community=record["id"], page=page)
    return {
        "community": {"id": record["id"], "name": record["name"], "link": record["link"]},
        "results": result["results"],
        "pagination": result["pagination"],
    }


def communities_listings(**data):
    return cached_call("anjuke.communities_listings", data, _communities_listings, ttl.SEARCH_CACHE)


# ---- new homes ----------------------------------------------------------------------------

def _loupan_city(city):
    """The new-home city id (the XHR's `cid`) and district slugs, from the
    rendered list page of the whole city."""
    html = fetch.fetch_loupan_list(refs.loupan_list_path(city), city)
    parsed = _nuxt(parsers.parse_loupan_list, html, city, label="new-home list page")
    return {"cid": parsed["cid"], "districts": parsers.parse_loupan_districts(html)}


def _loupan_city_cached(city):
    return cached_call("anjuke.loupan_city", {"city": city}, _loupan_city, ttl.LOUPAN_CITY_CACHE)


def _resolve_loupan_district(city, district, table):
    if not district:
        return None
    if _is_slug(district):
        return district.lower()
    wanted = district.strip().replace("区", "").replace("县", "")
    for row in table["districts"]:
        if row["name"].replace("区", "").replace("县", "") == wanted or row["name"] == district.strip():
            return row["slug"]
    raise ValueError(f"Unknown district {district!r} for new homes in {city}: "
                     f"{', '.join(r['name'] + ' (' + r['slug'] + ')' for r in table['districts'][:30])}.")


def _new_homes_search(city, district=None, status=None, rooms=None, size=None, property_type=None,
                      opening=None, delivery=None, fitment=None, features=None, sort=None, page=1):
    table = _loupan_city_cached(city)
    d_slug = _resolve_loupan_district(city, district, table)
    marks = _marks((status, refs.LOUPAN_STATUSES), (rooms, refs.LOUPAN_ROOMS), (size, refs.LOUPAN_SIZES),
                   (property_type, refs.LOUPAN_PROPERTY_TYPES), (opening, refs.LOUPAN_OPENINGS),
                   (delivery, refs.LOUPAN_DELIVERIES), (fitment, refs.LOUPAN_FITMENTS),
                   (features, refs.LOUPAN_FEATURES), (sort, refs.LOUPAN_SORTS))
    url = refs.loupan_list_path(city, d_slug, marks)
    query = refs.loupan_query(table["cid"], refs.loupan_args(d_slug, marks), page)
    parsed = parsers.parse_loupan_api(fetch.fetch_loupan_api(city, query, url), city)
    return {
        "city": refs.city_record(city)["name"],
        "district": d_slug,
        "list_name": parsed["list_name"],
        "source_link": url,
        "results": parsed["projects"],
        "pagination": _pagination(page, refs.LOUPAN_PAGE_SIZE, parsed["total"]),
    }


def new_homes_search(**data):
    return cached_call("anjuke.new_homes_search", data, _new_homes_search, ttl.SEARCH_CACHE)


def _project_record(project):
    city, project_id = project["city"], project["id"]
    main = _nuxt(parsers.parse_loupan_main, fetch.fetch_loupan_page(city, project_id), project_id, city,
                 label="project page")
    # a bare id carries no city; the page's canonical link does
    city = refs.city_from_link(main.get("link")) or city
    params = _nuxt(parsers.parse_loupan_params, fetch.fetch_loupan_page(city, project_id, "params/"), project_id,
                   label="project parameters")
    plans = parsers.parse_loupan_huxing(fetch.fetch_loupan_page(city, project_id, "huxing/"), project_id)
    prices = parsers.parse_loupan_price(fetch.fetch_loupan_page(city, project_id, "jiage/"), project_id)
    record = dict(main)
    record["sale_status"] = params.get("sale_status") or main.get("status")
    for key in ("ring_road", "developer", "developer_brand", "mortgage_note", "delivery", "sales_office_address",
                "land_area_sqm", "building_area_sqm", "plot_ratio", "green_ratio_pct", "planned_households",
                "fitment", "property_type", "building_type", "land_tenure", "property_company", "property_fee",
                "parking_spaces", "parking_ratio", "electricity", "water", "property_features", "presale_permits"):
        record[key] = params.get(key)
    record["full_address"] = params.get("address")
    record["opening"] = main.get("opening") or params.get("opening")
    record["tags"] = main.get("tags") or params.get("tags")
    record["floor_plans"] = plans["floor_plans"]
    record["floor_plan_filters"] = plans["filters"]
    record["market_prices"] = {"area_averages": prices["area_averages"], "nearby_rising": prices["nearby_rising"],
                               "nearby_falling": prices["nearby_falling"]}
    record["parameter_sections"] = params.get("sections")
    record["links"] = {"params": refs.loupan_page_link(city, project_id, "params/"),
                       "floor_plans": refs.loupan_page_link(city, project_id, "huxing/"),
                       "prices": refs.loupan_page_link(city, project_id, "jiage/"),
                       "reviews": refs.loupan_page_link(city, project_id, "ugclist/"),
                       "questions": refs.loupan_page_link(city, project_id, "wenda/wenlist/")}
    return record


def new_homes_details(project):
    return cached_call("anjuke.project", {"project": project}, _project_record, ttl.PROJECT_CACHE)


def _new_homes_reviews(project):
    city, project_id = project["city"], project["id"]
    reviews = parsers.parse_loupan_reviews(fetch.fetch_loupan_reviews(city, project_id))
    questions = _nuxt(parsers.parse_loupan_questions, fetch.fetch_loupan_page(city, project_id, "wenda/wenlist/"),
                      project_id, label="project Q&A")
    if reviews["total"] in (None, 0) and not questions["questions"] and not questions.get("project_name"):
        raise AnjukeNotFound(f"project {project_id} not found")
    # a bare id carries no city; the review / question links carry the project's own
    city = next((refs.city_from_link(link) for link in
                 [r.get("link") for r in reviews["reviews"]] + [q.get("link") for q in questions["questions"]]
                 if link and refs.city_from_link(link)), city)
    return {
        "id": project_id,
        "name": questions.get("project_name"),
        "link": refs.project_link(city, project_id),
        "reviews_total": reviews["total"],
        "reviews": reviews["reviews"],
        "review_tags": reviews["tags"],
        "questions_total": questions["total"],
        "questions": questions["questions"],
    }


def new_homes_reviews(project):
    return cached_call("anjuke.project_reviews", {"project": project}, _new_homes_reviews, ttl.REVIEWS_CACHE)
