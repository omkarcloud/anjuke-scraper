"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does (same params, validated by
the same schemas); results are written to output/*.json.
"""
import json
import os

from anjuke import api, schemas

os.makedirs("output", exist_ok=True)


def run(schema, endpoint, **params):
    """Validate params exactly like the API and call the endpoint."""
    return endpoint(**schema().load(params))


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # a resale listing id or any anjuke.com listing link
    save("listing_3993742615191556.json", run(schemas.ListingSchema, api.sale_details, listing="3993742615191556"))

    # 60 resale homes per page: filter by district, price (万), size, rooms and more
    save("sale_search_shanghai.json", run(schemas.SaleSearchSchema, api.sale_search, city="shanghai", district="pudong"))

    # a community: price history, valuations, scores, gallery, Q&A
    save("community_51241.json", run(schemas.CommunitySchema, api.communities_details, community="51241"))
