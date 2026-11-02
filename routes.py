"""The 13 Anjuke endpoints. Every path is served with and without the
`/anjuke` prefix, so code generated against the hosted API on RapidAPI (paths
like /sale/details) runs unchanged against this server.

Each request is validated by the module's own marshmallow schema
(anjuke/schemas.py), so param names, defaults and allowed values are the same
as the hosted API's; paged endpoints answer in the same flat shape
(count / per_page / current_page / total_pages / next / previous + results).
"""
import json
from urllib.parse import urlencode

from bottle import request, response, route

from anjuke import api, schemas
from scraper_errors import BadRequest, NotFound
from schema_fields import load_query


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The request query as unicode strings (bottle 0.12's .get() hands back
    latin-1 decoded bytes, so a UTF-8 "上海" would arrive mangled)."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _page_link(path, params, page):
    if not page:
        return None
    query = {k: v for k, v in params.items() if v not in (None, "", False)}
    query["page"] = page
    host = request.headers.get("Host") or "localhost"
    return f"{request.urlparts.scheme}://{host}{path}?{urlencode(query, doseq=True)}"


def paginate(result, path, raw):
    """Lift the scraper's `pagination` block into the flat shape with
    next/previous links built from the caller's own params."""
    pagination = result.pop("pagination", None) or {}
    page = _as_int(pagination.get("page")) or _as_int(raw.get("page")) or 1
    if "has_next" in pagination:
        has_next = bool(pagination["has_next"])
        total_pages = pagination.get("total_pages")
    else:
        total_pages = max(_as_int(pagination.get("total_pages")), 0)
        has_next = page < total_pages
    out = {
        "count": pagination.get("total_count"),
        "per_page": pagination.get("items_per_page"),
        "current_page": page,
        "total_pages": total_pages,
        "next": _page_link(path, raw, page + 1 if has_next else None),
        "previous": _page_link(path, raw, page - 1 if page > 1 else None),
    }
    out.update(result)
    return out


def call(label, schema, impl, paginated=False):
    """Validate with the schema, run the endpoint, map failures to HTTP:
    bad params -> 400, unknown id -> 404, blocked / retries exhausted -> 500."""
    raw = query_dict()
    data, error = load_query(schema, raw)
    if error:
        return json_response(error, 400)
    try:
        result = impl(**data)
    except ValueError as e:                       # e.g. an unknown district name
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:
        return json_response({"error": f"anjuke rejected the request: {e}"}, 400)
    except NotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Exception as e:                        # blocked / retries exhausted
        return json_response({"error": f"anjuke {label} failed: {type(e).__name__}: {e}"}, 500)
    if paginated:
        result = paginate(result, request.path, raw)
    return json_response(result)


ENDPOINTS = [
    ("/sale/details", schemas.ListingSchema, api.sale_details, False),
    ("/sale/suggest", schemas.SaleSuggestSchema, api.sale_suggest, False),
    ("/sale/search", schemas.SaleSearchSchema, api.sale_search, True),
    ("/rent/search", schemas.RentSearchSchema, api.rent_search, True),
    ("/rent/details", schemas.RentalSchema, api.rent_details, False),
    ("/communities/search", schemas.CommunitiesSearchSchema, api.communities_search, True),
    ("/communities/details", schemas.CommunitySchema, api.communities_details, False),
    ("/communities/listings", schemas.CommunityListingsSchema, api.communities_listings, True),
    ("/new_homes/search", schemas.NewHomesSearchSchema, api.new_homes_search, True),
    ("/new_homes/details", schemas.ProjectSchema, api.new_homes_details, False),
    ("/new_homes/reviews", schemas.ProjectSchema, api.new_homes_reviews, False),
    ("/cities/list", schemas.CitiesListSchema, api.cities_list, False),
    ("/cities/details", schemas.CitySchema, api.cities_details, False),
]


def mount(path, schema, impl, paginated):
    """Serve one endpoint at /path and /anjuke/path."""
    def handler():
        return call(path.strip("/"), schema, impl, paginated)
    handler.__name__ = "anjuke_" + path.strip("/").replace("/", "_")
    route(path, method="GET")(handler)
    route("/anjuke" + path, method="GET")(handler)


for _path, _schema, _impl, _paginated in ENDPOINTS:
    mount(_path, _schema, _impl, _paginated)


@route("/", method="GET")
@route("/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [p for p, *_ in ENDPOINTS]})
