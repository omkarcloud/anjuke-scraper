"""Marshmallow request schemas for every /anjuke/* route.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair):

    city        pinyin host label ("beijing"), short alias ("bj") or Chinese
                name ("北京") — resolved to the pinyin label (anjuke/refs.py)
    listing     a resale listing id OR any anjuke.com resale link
    rental      a rental id OR any anjuke.com rental link
    community   a community id OR any anjuke.com community link
    project     a new-home project id OR any anjuke.com project link
    district    the site's district slug ("chaoyang") OR its Chinese name
    area        the site's business-area slug ("cbd") OR its Chinese name

Choice values map to the site's own filter marks (anjuke/refs.py tables,
read from the filter blocks of the Beijing list pages on 2026-10-30/31).
"""
from marshmallow import ValidationError, validates_schema

from schema_fields import (BaseSchema, ChoiceField, CommaListField, PageField, PositiveInt, QueryField, RefField,
                           StrippedString)
from anjuke import refs


class CityField(RefField):
    resolver = staticmethod(refs.resolve_city)

    def __init__(self, **kwargs):
        kwargs.setdefault("metadata", {"description": "city: pinyin host label (beijing), short alias (bj) or Chinese name (北京)"})
        super().__init__(**kwargs)


class ListingRefField(RefField):
    resolver = staticmethod(refs.resolve_listing)


class RentalRefField(RefField):
    resolver = staticmethod(refs.resolve_rental)


class CommunityRefField(RefField):
    resolver = staticmethod(refs.resolve_community)


class ProjectRefField(RefField):
    resolver = staticmethod(refs.resolve_project)


class PlaceField(StrippedString):
    """A district or business-area slug ("chaoyang", "cbd") or its Chinese name."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        if value is None:
            return None
        if value.isascii() and not refs.SLUG_RE.match(value.lower()):
            raise ValidationError("Must be the site's slug (chaoyang, cbd) or the Chinese name (朝阳, CBD).")
        return value


def _range_check(data, low_key, high_key, label):
    low, high = data.get(low_key), data.get(high_key)
    if low is not None and high is not None and low > high:
        raise ValidationError(f"{low_key} must not exceed {high_key}.", high_key)


# ---- cities -----------------------------------------------------------------------------

class CitiesListSchema(BaseSchema):
    q = StrippedString(required=False, load_default=None,
                       metadata={"description": "filter cities by Chinese name, pinyin or alias (substring)"})


class CitySchema(BaseSchema):
    city = CityField()


# ---- sale -------------------------------------------------------------------------------

class SaleSearchSchema(BaseSchema):
    city = CityField()
    q = StrippedString(required=False, load_default=None,
                       metadata={"description": "keyword (community, business area or metro station name) for the site's own search"})
    district = PlaceField(metadata={"description": "district slug or Chinese name (chaoyang / 朝阳); see cities/details"})
    area = PlaceField(metadata={"description": "business-area slug or Chinese name (cbd / CBD) inside the district"})
    price_min = PositiveInt(metadata={"description": "minimum total price in 万 (10,000 CNY), e.g. 200"})
    price_max = PositiveInt(metadata={"description": "maximum total price in 万 (10,000 CNY), e.g. 500"})
    size_min = PositiveInt(metadata={"description": "minimum floor area in m²"})
    size_max = PositiveInt(metadata={"description": "maximum floor area in m²"})
    rooms = ChoiceField(list(refs.SALE_ROOMS), metadata={"description": "bedrooms: 1-5, or 6 for six and more"})
    type = ChoiceField(list(refs.SALE_TYPES), metadata={"description": "use type: residential, apartment, villa, bungalow, other"})
    age = ChoiceField(list(refs.SALE_AGES), metadata={"description": "building age: under_2, 2_5, 5_10, over_10 (years)"})
    fitment = ChoiceField(list(refs.SALE_FITMENTS), metadata={"description": "interior finish: rough, simple, fine, luxury"})
    orientation = ChoiceField(list(refs.SALE_ORIENTATIONS),
                              metadata={"description": "facing: east, south, west, north, southeast, northeast, southwest, northwest, north_south, east_west"})
    floor_level = ChoiceField(list(refs.SALE_FLOOR_LEVELS), metadata={"description": "floor band: ground, low, middle, high, top"})
    property_type = ChoiceField(list(refs.SALE_PROPERTY_TYPES),
                                metadata={"description": "ownership type: commercial_housing, mixed_use, affordable, public, relocation, other"})
    features = CommaListField(allowed=list(refs.SALE_FEATURES), upper=False, max_items=6,
                              metadata={"description": "comma list: near_metro, over_5_years, over_2_years, verified, vr, owner_urgent"})
    ring = ChoiceField(list(refs.SALE_RINGS), metadata={"description": "ring-road band (Beijing): inside_2nd, 2nd_3rd, 3rd_4th, 4th_5th, 5th_6th, outside_6th"})
    sort = ChoiceField(list(refs.SALE_SORTS), metadata={"description": "default, price_asc, price_desc, area_desc"})
    page = PageField(max_page=refs.SALE_MAX_PAGE, metadata={"description": "page of 60 listings (the site serves at most 50 pages per query)"})

    @validates_schema
    def _ranges(self, data, **kwargs):
        _range_check(data, "price_min", "price_max", "price")
        _range_check(data, "size_min", "size_max", "size")


class ListingSchema(BaseSchema):
    listing = ListingRefField(metadata={"description": "resale listing id (3048414802945025) or an anjuke.com resale link"})


class SaleSuggestSchema(BaseSchema):
    city = CityField()
    q = QueryField(max_length=50, metadata={"description": "partial community, business-area or metro-station name (Chinese)"})


# ---- rent -------------------------------------------------------------------------------

class RentSearchSchema(BaseSchema):
    city = CityField()
    q = StrippedString(required=False, load_default=None,
                       metadata={"description": "place name (business area or community); resolved through the site's autocomplete to a business area"})
    district = PlaceField(metadata={"description": "district slug or Chinese name (chaoyang / 朝阳)"})
    area = PlaceField(metadata={"description": "business-area slug or Chinese name (cbd / CBD)"})
    rent_min = PositiveInt(metadata={"description": "minimum monthly rent in CNY"})
    rent_max = PositiveInt(metadata={"description": "maximum monthly rent in CNY"})
    rooms = ChoiceField(["1", "2", "3", "4", "5"], metadata={"description": "bedrooms: 1-4, or 5 for five and more"})
    rental_type = ChoiceField(list(refs.RENT_TYPES), metadata={"description": "whole (整租) or shared (合租)"})
    fitment = ChoiceField(list(refs.RENT_FITMENTS), metadata={"description": "interior finish: rough, simple, fine, luxury"})
    listed_by = ChoiceField(list(refs.RENT_SOURCES), metadata={"description": "agent or owner listings"})
    page = PageField(max_page=refs.RENT_MAX_PAGE, metadata={"description": "page of 30 rentals (the site serves up to 116 pages per query)"})

    @validates_schema
    def _ranges(self, data, **kwargs):
        _range_check(data, "rent_min", "rent_max", "rent")


class RentalSchema(BaseSchema):
    rental = RentalRefField(metadata={"description": "rental id (4732633159429128) or an anjuke.com rental link"})


# ---- communities ------------------------------------------------------------------------

class CommunitiesSearchSchema(BaseSchema):
    city = CityField()
    q = StrippedString(required=False, load_default=None, metadata={"description": "community name keyword"})
    district = PlaceField(metadata={"description": "district slug or Chinese name (chaoyang / 朝阳)"})
    area = PlaceField(metadata={"description": "business-area slug or Chinese name (cbd / CBD)"})
    age = ChoiceField(list(refs.COMMUNITY_AGES), metadata={"description": "community age: under_5, 5_10, 10_15, 15_20, 20_30, over_30 (years)"})
    features = CommaListField(allowed=list(refs.COMMUNITY_FEATURES), upper=False, max_items=2,
                              metadata={"description": "comma list: near_metro, video"})
    sort = ChoiceField(list(refs.COMMUNITY_SORTS),
                       metadata={"description": "default, price_asc, price_desc, popularity_asc, popularity_desc, score_desc, score_asc"})
    page = PageField(max_page=refs.COMMUNITY_MAX_PAGE, metadata={"description": "page of 25 communities (the site serves up to 50 pages per query)"})


class CommunitySchema(BaseSchema):
    community = CommunityRefField(metadata={"description": "community id (53195) or an anjuke.com community link"})


class CommunityListingsSchema(CommunitySchema):
    page = PageField(max_page=refs.SALE_MAX_PAGE, metadata={"description": "page of 60 resale listings"})


# ---- new homes --------------------------------------------------------------------------

class NewHomesSearchSchema(BaseSchema):
    city = CityField()
    district = PlaceField(metadata={"description": "district slug or Chinese name; the new-home slugs come from the city's new-home page (daxing / 大兴区)"})
    status = ChoiceField(list(refs.LOUPAN_STATUSES), metadata={"description": "on_sale, upcoming, sold_out, tail, new_permit"})
    rooms = ChoiceField(list(refs.LOUPAN_ROOMS), metadata={"description": "bedrooms: 1-4, or 5 for five and more"})
    size = ChoiceField(list(refs.LOUPAN_SIZES), metadata={"description": "unit size band in m²: under_70, 70_90, 90_120, 120_140, 140_160, 160_200, over_200"})
    property_type = ChoiceField(list(refs.LOUPAN_PROPERTY_TYPES), metadata={"description": "residential, low_density, commercial, shop, office"})
    opening = ChoiceField(list(refs.LOUPAN_OPENINGS), metadata={"description": "opening date: this_month, next_month, next_3_months, last_month, opened"})
    delivery = ChoiceField(list(refs.LOUPAN_DELIVERIES), metadata={"description": "delivery: ready, within_1_month, within_3_months, within_6_months"})
    fitment = ChoiceField(list(refs.LOUPAN_FITMENTS), metadata={"description": "rough, simple, furnished"})
    features = CommaListField(allowed=list(refs.LOUPAN_FEATURES), upper=False, max_items=7,
                              metadata={"description": "comma list, projects with ANY of them: brand_developer, near_metro, parking, near_school, state_owned, popular, vr"})
    sort = ChoiceField(list(refs.LOUPAN_SORTS), metadata={"description": "default, price_asc, price_desc (the site ranks per-m² and per-unit prices on one scale), opening_desc"})
    page = PageField(max_page=200, metadata={"description": "page of 20 projects"})


class ProjectSchema(BaseSchema):
    project = ProjectRefField(metadata={"description": "new-home project id (523824) or an anjuke.com project link"})
