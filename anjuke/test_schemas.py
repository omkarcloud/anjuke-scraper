"""Offline tests for the /anjuke/* request schemas.

    python -m pytest anjuke/test_schemas.py -q
"""
import os
import sys

import pytest
from marshmallow import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anjuke import schemas  # noqa: E402


def _error(schema, query):
    with pytest.raises(ValidationError) as info:
        schema().load(query)
    return info.value.normalized_messages()


def test_city_field_forms():
    for value in ("beijing", "bj", "北京", "Beijing ", "北京市"):
        assert schemas.CitySchema().load({"city": value}) == {"city": "beijing"}
    assert "Unknown city" in _error(schemas.CitySchema, {"city": "nowhere"})["city"][0]
    assert "city" in _error(schemas.CitySchema, {})
    assert "city" in _error(schemas.CitySchema, {"city": ""})


def test_cities_list_schema():
    assert schemas.CitiesListSchema().load({}) == {"q": None}
    assert schemas.CitiesListSchema().load({"q": " bei "}) == {"q": "bei"}


def test_sale_search_full():
    loaded = schemas.SaleSearchSchema().load({
        "city": "bj", "q": "望京", "district": "朝阳", "area": "cbd", "price_min": "200", "price_max": "500",
        "size_min": "70", "size_max": "90", "rooms": "2", "type": "Residential", "age": "2_5", "fitment": "fine",
        "orientation": "south", "floor_level": "high", "property_type": "commercial_housing",
        "features": "near_metro, vr", "ring": "3rd_4th", "sort": "price_asc", "page": "2"})
    assert loaded["city"] == "beijing" and loaded["district"] == "朝阳" and loaded["area"] == "cbd"
    assert loaded["price_min"] == 200 and loaded["size_max"] == 90 and loaded["rooms"] == "2"
    assert loaded["type"] == "residential" and loaded["features"] == ["near_metro", "vr"] and loaded["page"] == 2


def test_sale_search_defaults_and_rejections():
    loaded = schemas.SaleSearchSchema().load({"city": "beijing"})
    assert loaded["page"] == 1 and loaded["q"] is None and loaded["features"] is None and loaded["sort"] is None
    assert "price_max" in _error(schemas.SaleSearchSchema, {"city": "bj", "price_min": "500", "price_max": "200"})
    assert "size_max" in _error(schemas.SaleSearchSchema, {"city": "bj", "size_min": "90", "size_max": "70"})
    assert "Must be one of" in _error(schemas.SaleSearchSchema, {"city": "bj", "rooms": "9"})["rooms"][0]
    assert "features" in _error(schemas.SaleSearchSchema, {"city": "bj", "features": "pool"})
    assert "page" in _error(schemas.SaleSearchSchema, {"city": "bj", "page": "51"})     # the site serves 50 pages
    assert "district" in _error(schemas.SaleSearchSchema, {"city": "bj", "district": "cha oyang!"})
    assert "price_min" in _error(schemas.SaleSearchSchema, {"city": "bj", "price_min": "0"})


def test_ref_schemas_accept_ids_and_links_and_reject_siblings():
    assert schemas.ListingSchema().load({"listing": "S3048414802945025"}) == {"listing": {"id": "3048414802945025", "city": None}}
    assert schemas.ListingSchema().load({"listing": "https://m.anjuke.com/bj/sale/A7487050974/"}) == \
        {"listing": {"id": "7487050974", "city": "beijing"}}
    assert schemas.RentalSchema().load({"rental": "https://bj.zu.anjuke.com/fangyuan/4732633159429128"}) == \
        {"rental": {"id": "4732633159429128", "city": "beijing"}}
    assert schemas.CommunitySchema().load({"community": "53195"}) == {"community": {"id": "53195", "city": None}}
    assert schemas.CommunityListingsSchema().load({"community": "https://beijing.anjuke.com/community/view/53195", "page": "3"}) == \
        {"community": {"id": "53195", "city": "beijing"}, "page": 3}
    assert schemas.ProjectSchema().load({"project": "https://bj.fang.anjuke.com/loupan/523824.html"}) == \
        {"project": {"id": "523824", "city": "beijing"}}
    assert "Unknown field" in _error(schemas.CommunitySchema, {"community": "53195", "url": "x"})["url"][0]
    assert "Unknown field" in _error(schemas.ListingSchema, {"listing": "1", "id": "1"})["id"][0]
    assert "listing" in _error(schemas.ListingSchema, {"listing": "https://example.com/prop/view/1"})
    assert "project" in _error(schemas.ProjectSchema, {"project": "https://beijing.anjuke.com/community/view/53195"})
    assert "rental" in _error(schemas.RentalSchema, {})


def test_suggest_schema():
    assert schemas.SaleSuggestSchema().load({"city": "北京", "q": "望京"}) == {"city": "beijing", "q": "望京"}
    assert "q" in _error(schemas.SaleSuggestSchema, {"city": "bj"})
    assert "q" in _error(schemas.SaleSuggestSchema, {"city": "bj", "q": "x" * 51})


def test_rent_search_schema():
    loaded = schemas.RentSearchSchema().load({"city": "sh", "rent_min": "2000", "rent_max": "5000", "rooms": "2",
                                              "rental_type": "Whole", "fitment": "fine", "listed_by": "owner", "page": "2"})
    assert loaded["city"] == "shanghai" and loaded["rental_type"] == "whole" and loaded["listed_by"] == "owner"
    assert "rent_max" in _error(schemas.RentSearchSchema, {"city": "bj", "rent_min": "5000", "rent_max": "2000"})
    assert "rooms" in _error(schemas.RentSearchSchema, {"city": "bj", "rooms": "6"})
    assert "rental_type" in _error(schemas.RentSearchSchema, {"city": "bj", "rental_type": "sublet"})


def test_communities_search_schema():
    loaded = schemas.CommunitiesSearchSchema().load({"city": "bj", "age": "5_10", "sort": "score_desc", "features": "near_metro,video"})
    assert loaded["age"] == "5_10" and loaded["features"] == ["near_metro", "video"] and loaded["page"] == 1
    assert "age" in _error(schemas.CommunitiesSearchSchema, {"city": "bj", "age": "new"})
    assert "features" in _error(schemas.CommunitiesSearchSchema, {"city": "bj", "features": "pool"})


def test_new_homes_search_schema():
    loaded = schemas.NewHomesSearchSchema().load({"city": "bj", "district": "大兴区", "status": "on_sale", "rooms": "3", "size": "90_120",
                                                  "property_type": "residential", "opening": "next_3_months", "delivery": "ready",
                                                  "fitment": "furnished", "features": "near_metro,vr", "sort": "price_desc"})
    assert loaded["status"] == "on_sale" and loaded["size"] == "90_120" and loaded["features"] == ["near_metro", "vr"]
    assert "status" in _error(schemas.NewHomesSearchSchema, {"city": "bj", "status": "soon"})
    assert "size" in _error(schemas.NewHomesSearchSchema, {"city": "bj", "size": "huge"})
    assert "q" in _error(schemas.NewHomesSearchSchema, {"city": "bj", "q": "x"})     # the mobile list has no keyword search


def test_every_field_documents_itself():
    for schema in (schemas.CitiesListSchema, schemas.CitySchema, schemas.SaleSearchSchema, schemas.ListingSchema,
                   schemas.SaleSuggestSchema, schemas.RentSearchSchema, schemas.RentalSchema, schemas.CommunitiesSearchSchema,
                   schemas.CommunitySchema, schemas.CommunityListingsSchema, schemas.NewHomesSearchSchema, schemas.ProjectSchema):
        for name, field in schema().fields.items():
            assert field.metadata.get("description"), f"{schema.__name__}.{name} has no description"
