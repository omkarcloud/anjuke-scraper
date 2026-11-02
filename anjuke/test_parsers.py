"""Offline tests for the anjuke parsers and reference resolvers.

    python -m pytest anjuke/test_parsers.py -q

Fixtures are real anjuke.com pages captured 2026-10-30/31 (anjuke/fixtures/):
the Beijing resale list (page 1, a keyword page and a one-listing community
page 2), a resale detail, the autocomplete JSON, the mobile rental list, a
desktop rental detail, the Beijing community list, a mobile community page
and its valuation page, the mobile new-home list, one project's five pages
and its reviews JSON, the city table, plus the not-found and anti-bot pages.
No network.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from upwork.nuxt import NuxtStateError  # noqa: E402
from anjuke import parsers as P, refs  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return json.load(f) if name.endswith(".json") else f.read()


# ---- refs ---------------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("beijing", "beijing"), ("bj", "beijing"), ("北京", "beijing"), ("北京市", "beijing"), ("Shanghai", "shanghai"),
    ("sh", "shanghai"), ("chengdou", "chengdu"), ("大邑", "chengdu"), ("emeishan", "emeishan"),
])
def test_resolve_city(value, expected):
    assert refs.resolve_city(value) == expected


@pytest.mark.parametrize("value", ["", "nowhere", "https://beijing.anjuke.com/"])
def test_resolve_city_invalid(value):
    with pytest.raises(ValueError):
        refs.resolve_city(value)


def test_city_table_is_the_sites_own():
    rows = P.parse_city_table(fixture("cities.html"))
    assert len(rows) > 700
    names = {r["pinyin"] for r in rows if r["pinyin"]}
    assert {"beijing", "shanghai", "guangzhou"} <= names
    # every host label / county spelling on the page resolves through the frozen table
    assert all(refs.resolve_city(n) for n in names)
    assert refs.city_record("beijing")["link"] == "https://beijing.anjuke.com/"
    assert refs.city_record("emeishan")["has_resale"] is False


@pytest.mark.parametrize("value,expected", [
    ("3048414802945025", {"id": "3048414802945025", "city": None}),
    ("S3048414802945025", {"id": "3048414802945025", "city": None}),
    ("A7487050974", {"id": "7487050974", "city": None}),
    ("https://beijing.anjuke.com/prop/view/S3048414802945025?auction=201", {"id": "3048414802945025", "city": "beijing"}),
    ("https://m.anjuke.com/sh/sale/A7487050974/", {"id": "7487050974", "city": "shanghai"}),
])
def test_resolve_listing(value, expected):
    assert refs.resolve_listing(value) == expected


@pytest.mark.parametrize("value", ["", "abc", "https://example.com/prop/view/1", "https://beijing.anjuke.com/community/view/53195"])
def test_resolve_listing_invalid(value):
    with pytest.raises(ValueError):
        refs.resolve_listing(value)


def test_resolve_other_refs():
    assert refs.resolve_rental("https://m.anjuke.com/bj/rent/4732633159429128-3/") == {"id": "4732633159429128", "city": "beijing"}
    assert refs.resolve_rental("https://beijing.zu.anjuke.com/fangyuan/4503423129639944x.html") == {"id": "4503423129639944", "city": "beijing"}
    assert refs.resolve_community("https://beijing.anjuke.com/gufangjia/xiaoqu-53195/") == {"id": "53195", "city": "beijing"}
    assert refs.resolve_community("https://m.anjuke.com/sh/community/1588/") == {"id": "1588", "city": "shanghai"}
    assert refs.resolve_community("53195") == {"id": "53195", "city": None}
    assert refs.resolve_project("https://bj.fang.anjuke.com/loupan/523824.html") == {"id": "523824", "city": "beijing"}
    assert refs.resolve_project("https://m.anjuke.com/bj/loupan/523824/huxing/") == {"id": "523824", "city": "beijing"}
    with pytest.raises(ValueError):
        refs.resolve_project("https://beijing.anjuke.com/prop/view/1")


def test_path_grammar():
    assert refs.sale_path("beijing", "chaoyang", "cbd", ["b17", "o4"], 2, {"prices": "200_300"}) == \
        "https://beijing.anjuke.com/sale/chaoyang-q-cbd/b17-o4-p2/?prices=200_300"
    assert refs.sale_path("beijing") == "https://beijing.anjuke.com/sale/"
    assert refs.sale_path("beijing", page=3) == "https://beijing.anjuke.com/sale/p3/"
    assert refs.range_param(200, None) == "200_2147483640"
    assert refs.range_param(None, 300) == "0_300"
    assert refs.range_param(None, None) is None
    assert refs.rent_list_path("beijing", "chaoyang", "cbd", 1000, 3000, "2", "1", None, "2") == \
        "https://m.anjuke.com/bj/rent/chaoyang-q-cbd/a1000_3000-b2-1-0-f2/"
    assert refs.rent_list_path("shanghai") == "https://m.anjuke.com/sh/rent/all/a0_0-b0-0-0-f0/"
    assert refs.loupan_list_path("beijing", "daxing", ["a1", "h3"]) == "https://m.anjuke.com/bj/loupan/daxing/a1-h3/"
    assert refs.loupan_list_path("shanghai") == "https://m.anjuke.com/sh/loupan/all/"
    assert refs.community_list_path("beijing", None, None, ["f2"], 1, {"kw": "望京"}) == \
        "https://beijing.anjuke.com/community/f2/?kw=%E6%9C%9B%E4%BA%AC"


def test_loupan_xhr_query():
    # the args object the new-home list page's own "load more" XHR sends (Shanghai pudong page state, 2026-11-02)
    assert refs.loupan_args("pudong", ["a1", "h3", "m564", "w1", "z3", "q9", "s1"]) == \
        {"regions": {"pudong": ""}, "a": "1", "h": "3", "m": "564", "w": "1", "z": "3", "q": "9", "s": "1"}
    assert refs.loupan_args(None, ["q9", "q56"]) == {"q": "9,56"}      # repeated letters: ANY of
    assert refs.loupan_args() == {}
    assert refs.loupan_query(11, {"a": "1"}, 3) == {"cid": 11, "kw": "", "page": 3, "pageSize": 20, "args": {"a": "1"},
                                                    "commerce": 0, "commerce_type": 0, "school_id": None, "seoPage": None}


# ---- anti-bot / not-found detection ---------------------------------------------------------

def test_gateway_and_captcha_pages_are_detected():
    assert P.is_gateway_page(fixture("gateway_page.html"))
    assert P.is_gateway_page(fixture("captcha_redirect.html"))
    assert not P.is_gateway_page(fixture("sale_list_beijing.html"))
    assert not P.is_gateway_page(fixture("rent_list_beijing_mobile.html"))


def test_not_found_titles():
    assert P.page_title(fixture("sale_detail_notfound.html")).startswith("对不起")
    assert P.page_title(fixture("rent_detail_notfound.html")) == "404-安居客"
    assert P.page_title(fixture("loupan_notfound_params.html")).startswith("undefined")


# ---- cities -------------------------------------------------------------------------------

def test_city_details():
    city = P.parse_city_details(fixture("sale_list_beijing.html"), "beijing")
    assert city["id"] == 14 and city["name"] == "北京" and city["province"] == "北京市"
    assert city["resale_listings_total"] == 269021
    chaoyang = next(d for d in city["districts"] if d["slug"] == "chaoyang")
    assert chaoyang["id"] == 642 and chaoyang["name"] == "朝阳" and chaoyang["lat"] == pytest.approx(39.92, abs=0.01)
    assert any(a["slug"] == "cbd" and a["id"] == 6834 for a in chaoyang["business_areas"])
    assert len(city["metro_lines"]) == 30
    assert city["metro_lines"][0]["stations"][0]["name"]
    assert city["filters"]["price_buckets_wan"][0] == {"name": "150万以下", "mark": "m11292", "min": None, "max": 150}
    assert city["filters"]["rooms"][0] == {"name": "一室", "mark": "b15"}
    assert city["filters"]["price_buckets_wan"][-1]["max"] is None   # 1000万以上


# ---- resale -------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sale_list():
    return P.parse_sale_list(fixture("sale_list_beijing.html"), "beijing")


def test_sale_list_shape(sale_list):
    assert sale_list["total"] == 269021 and sale_list["page"] == 1 and sale_list["keyword_match"] == "filter"
    assert len(sale_list["listings"]) == 71          # 76 blocks minus 5 sponsored "推荐新楼盘" rows
    first = sale_list["listings"][0]
    assert first["id"] == "3048414802945025"
    assert first["link"] == "https://beijing.anjuke.com/prop/view/S3048414802945025"
    assert first["price"] == {"total": 2400000, "total_wan": 240, "per_sqm": 30770, "currency": "CNY"}
    assert first["layout"] == {"rooms": 3, "halls": 2, "bathrooms": 1, "text": "3室2厅1卫"}
    assert first["area_sqm"] == 78 and first["is_ad"] is True and first["is_verified"] is True
    assert first["badge"] == "广告" and first["is_promoted"] is False
    promoted = [i for i, r in enumerate(sale_list["listings"]) if r["is_promoted"]]
    assert len(promoted) == 11 and promoted[:3] == [7, 13, 19]      # 60 organic + 11 paid 热推 slots
    assert sum(1 for r in sale_list["listings"] if r["badge"] == "法拍房") == 5   # court-auction homes
    assert first["has_vr"] is True and first["vr_type"] == "VR3D"
    assert first["listed_at"] == "2023-05-30T10:35:00Z"
    assert first["community"]["id"] == "1664414" and first["community"]["district"] == {"id": 843, "name": "昌平"}
    assert first["community"]["lat"] == pytest.approx(40.1648, abs=0.001)
    assert first["broker"] is None                    # the list card's broker block is all zeros


def test_sale_list_floor_text_is_split(sale_list):
    second = sale_list["listings"][1]
    assert second["floor"] == {"level": "高层", "total_floors": 17, "text": "高层(共17层)"}
    assert second["is_ad"] is False and second["has_vr"] is None


def test_sale_list_keyword_and_community_pages():
    kw = P.parse_sale_list(fixture("sale_list_keyword_wangjing.html"), "beijing")
    assert kw["keyword_match"] == "shangquan" and kw["total"] == 1122 and len(kw["listings"]) == 60
    comm = P.parse_sale_list(fixture("sale_list_community_53195_p2.html"), "beijing")
    assert comm["total"] == 61 and comm["page"] == 2 and len(comm["listings"]) == 1
    assert comm["keyword_match"] == "comm_one"


def test_sale_detail():
    rec = P.parse_sale_detail(fixture("sale_detail_S3048414802945025.html"), "3048414802945025", "beijing")
    assert rec["id"] == "3048414802945025" and rec["house_id"] == "3633945514681355"   # id round-trips to /prop/view/<id>
    assert rec["link"] == "https://beijing.anjuke.com/prop/view/3048414802945025"
    assert rec["title"] == "170！！！优惠有 看房车接车"
    assert rec["price"]["total"] == 2400000 and rec["mortgage"] == {"down_payment": 360000, "down_payment_wan": 36, "monthly": 7362, "currency": "CNY"}
    assert rec["source"] == "new_home_agency" and rec["is_new_home"] is True
    assert rec["vr"]["link"].startswith("https://www.anjuke.com/panorama")
    assert rec["quality_label"]["title"] == "品质好房"
    assert rec["description"][0]["title"] == "核心卖点" and len(rec["description"]) == 2
    assert len(rec["photos"]["indoor"]) >= 10 and rec["photos"]["floor_plan"]
    assert rec["broker"]["name"] == "付海侠" and rec["broker"]["company"] == "我爱我家"
    assert rec["broker"]["company_license"] == "911101157001735358" and rec["broker"]["phone"] is None
    assert rec["link"] == "https://beijing.anjuke.com/prop/view/3048414802945025"
    assert rec["community"]["id"] == "1664414" and rec["community"]["name"] == "北京城建·国誉燕园"
    assert rec["community"]["district"]["slug"] == "changping" and rec["community"]["developer"] == "北京城建兴荣房地产开发有限公司"
    assert rec["community"]["lat"] == pytest.approx(40.1648, abs=0.001)
    assert len(rec["community_price_history"]) == 36 and rec["community_price_history"][0] == {"month": "2023-11", "per_sqm": 39000}
    assert rec["community_price_history"][7]["per_sqm"] is None     # months without a figure stay null
    assert rec["agency_coverage"] == {"stores": 20, "brokers": 37, "total": 37}
    assert rec["questions"]["items"][0]["best_answer"]["text"] == "小区是市政供暖，集中供暖"


def test_sale_detail_takes_its_city_from_the_page():
    # fetched by a bare id (no city): the record's links follow the listing's own city, Shanghai
    rec = P.parse_sale_detail(fixture("sale_detail_3993742615191556_shanghai.html"), "3993742615191556", None)
    assert rec["link"] == "https://shanghai.anjuke.com/prop/view/3993742615191556"
    assert rec["mobile_link"].startswith("https://m.anjuke.com/sh/sale/")
    assert rec["community"]["link"] == "https://shanghai.anjuke.com/community/view/8"
    assert rec["price"]["total"] == 100000000 and rec["area_sqm"] == 433.87
    assert rec["government_verification"] and set(rec["government_verification"][0]) == {"title", "code", "image", "link"}


def test_sale_detail_without_property_block_raises():
    with pytest.raises(NuxtStateError):
        P.parse_sale_detail(fixture("sale_list_beijing.html"), "x", "beijing")


def test_autocomplete():
    rows = P.parse_autocomplete(fixture("autocomplete_wangjing.json"), "beijing")
    assert rows[0] == {"type": "business_area", "id": "1203", "name": "望京", "address": None, "district": {"id": 642, "name": None},
                       "avg_price_per_sqm": 60493, "currency": "CNY", "slug": None, "link": None}
    assert rows[1]["type"] == "community" and rows[1]["link"] == "https://beijing.anjuke.com/community/view/847935"
    assert {r["type"] for r in rows} == {"business_area", "community", "metro_station"}
    assert P.parse_autocomplete({"status": "ok", "data": []}, "beijing") == []


# ---- rentals ------------------------------------------------------------------------------

def test_rent_search_param():
    plain = P.parse_rent_search_param(fixture("rent_list_beijing_mobile.html"))
    assert plain["city_id"] == 1 and plain["page_size"] == 30 and plain["cityDomain"] == "bj"
    filtered = P.parse_rent_search_param(fixture("rent_list_shanghai_pudong_filtered_mobile.html"))
    assert filtered["city_id"] == 2 and filtered["area_id"] == "1411" and filtered["prices"] == "3000_8000"
    assert filtered["room_nums"] == 2 and filtered["house_type"] == 1
    with pytest.raises(NuxtStateError):
        P.parse_rent_search_param(fixture("gateway_page.html"))


def test_rent_api_page():
    out = P.parse_rent_api(fixture("rent_list_api_shanghai_p2.json"), "shanghai")
    assert out["total"] == 427668 and out["has_more"] is True and len(out["rentals"]) == 30
    first = out["rentals"][0]
    assert first["id"] == "4804853935057924"
    assert first["link"] == "https://sh.zu.anjuke.com/fangyuan/4804853935057924"
    assert first["mobile_link"] == "https://m.anjuke.com/sh/rent/4804853935057924-3/"
    assert first["title"] == "红梅小区，精装一房一厅，近安亭老街，民用水电燃气可办居住证"
    assert first["rental_type"] == "整租"
    assert first["rent"] == {"monthly": 1800, "currency": "CNY", "unit": "元/月"}
    assert first["layout"]["text"] == "1室1厅1卫" and first["area_sqm"] == 50
    assert first["floor"] == {"floor": 3, "total_floors": 6, "level": None, "text": "3/6层"}
    assert first["orientation"] == "朝南" and first["fitment"] == "精装修"
    assert first["is_verified"] is True and first["has_elevator"] is True and first["has_video"] is True
    assert first["metro"] == "距11号线-安亭站922m" and first["posted_ago"] == "19分钟前"
    assert first["community"] == {"id": "1026084", "name": "红梅小区(嘉定)", "link": "https://shanghai.anjuke.com/community/view/1026084",
                                  "address": "昌吉路203,215,231,237,253弄,昌吉路217-259号(单)",
                                  "district": {"id": 6961, "name": "嘉定"}, "block": {"id": 6996, "name": "安亭"},
                                  "lat": None, "lng": None}
    assert all(r["id"] and r["rent"]["monthly"] for r in out["rentals"])
    assert P.parse_rent_api({"code": "0", "data": {"total": "0", "has_more": "0", "list": []}}, "shanghai") == \
        {"rentals": [], "total": 0, "has_more": False}


def test_rent_detail():
    rec = P.parse_rent_detail(fixture("rent_detail_4732633159429128.html"), "4732633159429128", "beijing")
    assert rec["title"] == "13号线龙泽回龙观地铁站 豪华装修主卧独卫超大落地窗可随时住"
    assert rec["rental_type"] == "合租" and rec["is_verified"] is True
    assert rec["rent"] == {"monthly": 2800, "currency": "CNY", "payment_terms": "付1押1", "agency_fee": 0, "service_fee": 0}
    assert rec["layout"]["text"] == "3室1厅2卫" and rec["area_sqm"] == 10
    assert rec["floor"] == {"level": "低层", "total_floors": 18, "text": "低层(共18层)"}
    assert "空调" in rec["amenities"] and len(rec["amenities"]) >= 15
    assert rec["updated_at"] == "2026-10-30" and rec["address"] == "昌平路"
    assert rec["lat"] == pytest.approx(40.0748, abs=0.001) and rec["lng"] == pytest.approx(116.3307, abs=0.001)
    assert rec["community"] == {"id": "53121", "name": "新龙城", "link": "https://beijing.anjuke.com/community/view/53121",
                                "district": "昌平", "business_area": "回龙观"}
    assert rec["video_link"].endswith(".mp4") and len(rec["photos"]) >= 10     # data-src, not the lazy placeholder src
    broker = rec["broker"]
    assert broker["name"] == "高晓鑫" and broker["company"] == "北京晟信住房租赁有限公司"
    assert broker["store"] == "晟信住房回龙观店" and broker["service_score"] == 826
    assert broker["company_license"] == "91110114MAEWHBK529" and broker["phone"] is None
    assert broker["ratings"] == {"服务能力": "良好", "房源信息": "优秀", "专业能力": "良好"}
    assert rec["description"].startswith("本房源亮点")


def test_rent_detail_mobile():
    rec = P.parse_rent_detail_mobile(fixture("rent_detail_4732633159429128_mobile.html"), "4732633159429128", "beijing")
    assert rec["title"] == "13号线龙泽回龙观地铁站 豪华装修主卧独卫超大落地窗可随时住" and rec["rental_type"] == "合租"
    assert rec["link"] == "https://bj.zu.anjuke.com/fangyuan/4732633159429128"
    assert rec["rent"] == {"monthly": 2800, "currency": "CNY", "payment_terms": "押一付一", "agency_fee": 0, "service_fee": 0}
    assert rec["layout"]["text"] == "3室1厅2卫" and rec["area_sqm"] == 10 and rec["fitment"] == "精装修"
    assert rec["floor"] == {"level": "低层", "total_floors": 18, "text": "低层(共18层)"}
    assert rec["metro"][0] == {"line": "13号线", "station": "龙泽", "walk_text": "步行819米", "walk_m": 819} and len(rec["metro"]) == 3
    assert rec["amenities_by_room"]["卧室 设施"][0] == "电视" and len(rec["amenities"]) == 16
    assert rec["community"] == {"id": "53121", "name": "新龙城", "link": "https://beijing.anjuke.com/community/view/53121",
                                "district": "昌平", "business_area": "回龙观"}
    assert len(rec["photos"]) == 12 and rec["video_link"].endswith(".mp4")
    assert rec["broker"]["name"] == "高晓鑫" and rec["broker"]["company"] == "北京晟信住房租赁有限公司"
    assert rec["broker"]["company_complaints_phone"] == "13363078023" and rec["broker"]["service_score"] is None
    assert rec["updated_at"] == "2026-10-30" and rec["lat"] == pytest.approx(40.0748, abs=0.001)
    # a bare id (no city) still gets the rental's own city from its JSON-LD link
    assert P.parse_rent_detail_mobile(fixture("rent_detail_4732633159429128_mobile.html"), "4732633159429128", None)["community"]["link"] == \
        "https://beijing.anjuke.com/community/view/53121"
    assert set(rec) == set(P.parse_rent_detail(fixture("rent_detail_4732633159429128.html"), "4732633159429128", "beijing")) | {"metro", "amenities_by_room"}


def test_rent_detail_on_a_not_found_page_is_empty_not_a_crash():
    rec = P.parse_rent_detail(fixture("rent_detail_notfound.html"), "1234567890123456", "beijing")
    assert rec["rent"]["monthly"] is None and rec["broker"] is None
    rec = P.parse_rent_detail_mobile(fixture("rent_detail_notfound_mobile.html"), "1234567890123456", "beijing")
    assert rec["rent"]["monthly"] is None and rec["broker"] is None and rec["title"] is None


# ---- communities --------------------------------------------------------------------------

def test_community_list():
    out = P.parse_community_list(fixture("community_list_beijing.html"), "beijing")
    assert out["total"] == 40485 and out["page"] == 1 and len(out["communities"]) == 25
    first = out["communities"][0]
    assert first["id"] == "53195" and first["name"] == "美景东方" and first["slug"] == "meijingdongfang"
    assert first["link"] == "https://beijing.anjuke.com/community/view/53195"
    assert first["district"] == {"id": 642, "name": "朝阳", "slug": "chaoyang"}
    assert first["business_area"] == {"id": 15345, "name": "华威桥", "slug": "bjhuaweiqiao"}
    assert first["price"]["per_sqm"] == 52523 and first["price"]["month_change_pct"] == 0.45
    assert first["counts"] == {"for_sale": 62, "for_rent": 201, "new_home_units": None, "recent_transactions": None}
    assert first["score"]["overall"] == 8 and len(first["score"]["categories"]) == 7
    assert first["households"] == 3281 and first["green_ratio_pct"] == 38.66
    assert first["is_near_metro"] is True


def test_community_view():
    rec = P.parse_community_view(fixture("community_view_53195_mobile.html"), "53195", "beijing")
    assert rec["name"] == "美景东方" and rec["city"] == {"id": 14, "name": "北京", "pinyin": "beijing"}
    assert rec["lat"] == pytest.approx(39.8695, abs=0.001) and rec["baidu_lat"] == pytest.approx(39.8753, abs=0.001)
    assert rec["developer"] == "北京达义兴业房地产开发有限公司" and rec["property_fee"] == "2.50元/平米/月"
    assert rec["plot_ratio"] == 2.99 and rec["parking"] == "2232(1:0.7)" and rec["land_tenure"] == "70年"
    assert rec["has_elevator"] is True and rec["has_heating"] is True
    assert rec["price"]["per_sqm"] == 52523 and rec["price"]["sentiment"] == "看好"
    assert len(rec["price_history_6m"]) == 6 and rec["price_history_6m"][0] == {"month": "26/10", "per_sqm": 52523}
    assert rec["counts"]["for_rent"] == 201
    assert rec["evaluation"]["advantages"].startswith("小区绿化率") and rec["evaluation"]["disadvantages"].startswith("小区车位紧张")
    assert rec["gallery"]["counts"] == {"photos": 354, "videos": 610, "panoramas": 0}
    assert len(rec["gallery"]["photos"]) == 30 and rec["gallery"]["videos"][0]["link"].endswith(".mp4")
    assert rec["questions"]["total"] == 68 and rec["questions"]["items"][0]["answers_count"] == 308
    assert rec["comments_total"] == 1438
    assert rec["featured_brokers"][0]["name"] == "宋淑芬"


def test_community_view_without_state_raises():
    with pytest.raises(NuxtStateError):
        P.parse_community_view(fixture("gateway_page.html"), "1", "beijing")


def test_community_price():
    rec = P.parse_community_price(fixture("community_price_53195.html"), "53195", "beijing")
    assert rec["name"] == "美景东方"
    assert rec["price"] == {"per_sqm": 52523, "last_month_per_sqm": 52285, "month_change_pct": 0.45, "year_change_pct": -10.61,
                            "label": "10月挂牌均价", "currency": "CNY"}
    assert rec["business_area_price"]["name"] == "华威桥" and rec["business_area_price"]["per_sqm"] == 58879
    assert len(rec["price_history"]) == 36 and rec["price_history"][0] == {"month": "2023-11", "per_sqm": 72141}
    assert rec["price_history"][-1] == {"month": "2026-10", "per_sqm": 52523}
    assert len(rec["valuations"]) == 5
    assert rec["valuations"][0]["layout"]["text"] == "3室2厅3卫" and rec["valuations"][0]["valuation"] == 7430000
    assert rec["valuations"][0]["valued_at"] == "2026-08-10"
    assert len(rec["featured_agents"]) == 3


# ---- new homes ----------------------------------------------------------------------------

def test_loupan_list():
    out = P.parse_loupan_list(fixture("loupan_list_beijing.html"), "beijing")
    # the page is /loupan/all/ (page 1): state.params.page is the load-more cursor (2)
    assert out["total"] == 449 and out["page"] == 1 and out["has_more"] is True
    assert out["cid"] == 14 and out["args"] == {}
    assert len(out["projects"]) == 20
    first = out["projects"][0]
    assert first["id"] == "516665" and first["name"] == "御翠园"
    assert first["link"] == "https://bj.fang.anjuke.com/loupan/516665.html"
    assert first["status"] == "在售" and first["property_type"] == "住宅"
    assert first["district"] == {"id": 642, "name": "朝阳区"} and first["block"] == {"id": 671, "name": "朝青"}
    assert first["price"] == {"per_sqm": 75000, "total_from": None, "total_from_wan": None, "unit": "元/m²", "currency": "CNY", "note": None}
    assert first["opening_date"] == "2026-11-01" and first["rooms"] == [3]
    assert first["metro"] == [{"line": "3号线", "station": "姚家园", "distance_m": 548}]
    assert first["sales_phone"] == "4006708287转45326" and first["has_vr"] is True
    assert first["baidu_lat"] == pytest.approx(39.954, abs=0.001)


def test_loupan_api_page():
    out = P.parse_loupan_api(fixture("loupan_list_api_shanghai_p1.json"), "shanghai")
    assert out["total"] == 2248 and out["has_more"] is True and out["list_name"] == "全部楼盘" and len(out["projects"]) == 20
    first = out["projects"][0]
    assert first["id"] == "534431" and first["name"] == "保利·苏河珺"
    assert first["link"] == "https://sh.fang.anjuke.com/loupan/534431.html"
    assert first["district"] == {"id": 6, "name": "长宁区"} and first["block"] == {"id": 52, "name": "中山公园"}
    assert first["rooms"] == [3, 4] and first["area_range"] == "112-155㎡"
    assert first["price"]["per_sqm"] is None and first["price"]["currency"] is None    # price not announced yet (待售)
    assert P._loupan_price(5656, "万元/套起") == {"per_sqm": None, "total_from": 56560000, "total_from_wan": 5656,
                                                "unit": "万元/套起", "currency": "CNY", "note": None}
    assert P.parse_loupan_api({"result": {"rows": [], "total": "2248", "has_more": 0}}, "shanghai") == \
        {"projects": [], "total": 2248, "has_more": False, "list_name": None}


def test_loupan_districts():
    rows = P.parse_loupan_districts(fixture("loupan_list_beijing.html"))
    assert {"name": "大兴区", "slug": "daxing"} in rows
    assert {"name": "平谷区", "slug": "pinggu"} in rows        # differs from the resale slug "pinggua"
    assert all(not r["slug"].isdigit() and r["slug"] != "all" for r in rows)


def test_loupan_main():
    rec = P.parse_loupan_main(fixture("loupan_523824.html"), "523824", "beijing")
    assert rec["name"] == "壹品兴创·颐和公馆" and rec["status"] == "在售"
    # the canonical link carries the project's own city, whatever city the caller passed
    assert rec["link"] == "https://bj.fang.anjuke.com/loupan/523824.html"
    assert P.parse_loupan_main(fixture("loupan_523824.html"), "523824", "shanghai")["mobile_link"] == "https://m.anjuke.com/bj/loupan/523824/"
    assert rec["price"]["per_sqm"] == 55000
    assert rec["total_price"]["min_wan"] == 650 and rec["total_price"]["max"] == 12000000
    assert rec["area_range_sqm"] == {"min": 127, "max": 224, "text": "127-224"}
    assert rec["layouts"] == "4室" and rec["opening"] == "2026-04"
    assert rec["address"] == "大兴区-黄村 义忠路和义和庄南街交界处"
    assert rec["lat"] == pytest.approx(39.7163, abs=0.001) and rec["lng"] == pytest.approx(116.3314, abs=0.001)
    assert rec["sales_phone"] == "4006708258"
    assert len(rec["rankings"]) == 2 and len(rec["album"]["photos"]) >= 20
    assert len(rec["floor_plans_summary"]) == 6 and rec["floor_plans_summary"][0]["is_featured"] is True


def test_loupan_main_takes_its_city_from_the_canonical_link():
    rec = P.parse_loupan_main(fixture("loupan_517873_shanghai.html"), "517873", None)
    assert rec["link"] == "https://sh.fang.anjuke.com/loupan/517873.html"
    assert rec["mobile_link"] == "https://m.anjuke.com/sh/loupan/517873/"
    assert rec["name"] == "陆家嘴太古源 源邸"


def test_loupan_main_not_found_raises():
    with pytest.raises(NuxtStateError):
        P.parse_loupan_main(fixture("loupan_notfound.html"), "1", "beijing")


def test_loupan_params():
    rec = P.parse_loupan_params(fixture("loupan_523824_params.html"), "523824")
    assert rec["developer"] == "北京壹兴置业有限公司" and rec["developer_brand"] == "中建地产"
    assert rec["reference_price_per_sqm"] == 55000 and rec["opening"] == "2026-04"
    assert rec["land_area_sqm"] == 45954.22 and rec["building_area_sqm"] == 142178.44
    assert rec["plot_ratio"] == 2 and rec["green_ratio_pct"] == 30 and rec["planned_households"] == 752
    assert rec["property_fee"] == "5.5元/㎡/月" and rec["parking_spaces"] == 919 and rec["parking_ratio"] == "1:1.2"
    assert len(rec["presale_permits"]) == 4
    assert rec["presale_permits"][2] == {"number": "京房售证字(2024)17号", "issued_on": "2024-03-13",
                                         "buildings": "8号住宅楼、9号住宅楼、3号住宅楼、5号住宅楼、1号住宅楼、2号住宅楼"}
    assert "物业信息" in rec["sections"]
    with pytest.raises(NuxtStateError):
        P.parse_loupan_params(fixture("loupan_notfound_params.html"), "1")


def test_loupan_huxing():
    rec = P.parse_loupan_huxing(fixture("loupan_523824_huxing.html"), "523824")
    assert len(rec["floor_plans"]) == 6
    first = rec["floor_plans"][0]
    assert first["name"] == "C户型和御" and first["layout"]["text"] == "4室2厅2卫" and first["area_sqm"] == 132
    assert first["price_from_wan"] == 640 and first["price_from"] == 6400000 and first["bonus_area"] == "赠送6.0㎡"
    assert first["is_featured"] is True and first["has_vr"] is True
    assert rec["filters"]["户型"] == ["四室"]


def test_loupan_price():
    rec = P.parse_loupan_price(fixture("loupan_523824_price.html"), "523824")
    assert rec["name"] == "壹品兴创·颐和公馆"
    assert [a["scope"] for a in rec["area_averages"]] == ["北京", "大兴区", "黄村"]
    assert rec["area_averages"][0]["per_sqm"] == 63934
    assert rec["nearby_rising"][0]["name"] == "绿地海珀云翡" and rec["nearby_rising"][0]["change_text"] == "↑0%"
    assert rec["nearby_falling"][0]["change_text"] == "↓0%"


def test_loupan_reviews_and_questions():
    rev = P.parse_loupan_reviews(fixture("loupan_523824_reviews.json"))
    assert rev["total"] == 1165 and len(rev["reviews"]) == 2      # the route serves a short head only
    first = rev["reviews"][0]
    assert first["id"] == "16256152" and first["rating"] == 5 and first["likes"] == 124 and first["posted_at"] == "2024-06-13"
    assert len(first["photos"]) == 3
    assert rev["tags"][0] == {"id": "8", "name": "环境不错", "count": 63, "link": "https://m.anjuke.com/bj/loupan/523824/ugclist/?tid=8"}
    assert P.parse_loupan_reviews(fixture("loupan_notfound_reviews.json")) == {"total": 0, "reviews": [], "tags": []}
    qa = P.parse_loupan_questions(fixture("loupan_523824_questions.html"), "523824")
    assert qa["project_name"] == "壹品兴创·颐和公馆" and qa["total"] == 14 and len(qa["questions"]) == 13
    assert qa["questions"][0]["best_answer"]["author"] == "李政刚" and qa["questions"][0]["best_answer"]["author_role"] == "置业顾问"


# ---- value helpers -------------------------------------------------------------------------

def test_value_helpers():
    assert P._cn_date("2026年10月30日") == "2026-10-30" and P._cn_date("2026年4月") == "2026-04" and P._cn_date("") is None
    assert P._epoch_iso("1685442900") == "2023-05-30T10:35:00Z" and P._epoch_iso("") is None
    assert P._wan_to_yuan("240") == 2400000 and P._wan_to_yuan(None) is None
    assert P._floor("低层(共18层)", "0") == {"level": "低层", "total_floors": 18, "text": "低层(共18层)"}
    assert P._floor("", "0") is None
    assert P._lat_lng("116.4", "39.9") == (39.9, 116.4)         # swapped pairs are corrected
    assert P._layout_text("3室1厅2卫")["bathrooms"] == 2 and P._layout_text("no") is None
    assert P._nonzero("0.0") is None and P._nonzero("12") == 12
