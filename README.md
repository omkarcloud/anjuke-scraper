# 🏠 Anjuke Scraper

Anjuke Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Anjuke data for free.

## ✨ What Can I Get?

- 🏠 **Resale homes in 679 Chinese cities** — 398K+ in Shanghai alone: price, ¥/m², layout, photos, broker & mortgage estimate
- 🔑 **420K+ Shanghai rentals** — rent, payment terms, amenities, photos, metro walking distances & broker
- 🏘️ **Every residential community (小区)** — 54K+ in Shanghai: average price, price history, valuations, scores & Q&A
- 🏗️ **2,200+ new-home projects in Shanghai** — prices, floor plans, presale permits, developer & buyer reviews

## 🎥 Example: A Full Anjuke Listing

```json
{
  "id": "3993742615191556",
  "title": "汤臣一品高区一线江景，哪有什么意难平，你住汤臣你也行",
  "link": "https://shanghai.anjuke.com/prop/view/3993742615191556",
  "price": { "total": 100000000, "total_wan": 10000, "per_sqm": 230484, "currency": "CNY" },
  "mortgage": { "down_payment": 15000000, "down_payment_wan": 1500, "monthly": 306741, "currency": "CNY" },
  "layout": { "rooms": 4, "halls": 2, "bathrooms": 4, "text": "4室2厅4卫" },
  "area_sqm": 433.87,
  "floor": { "level": "高层", "total_floors": 37, "text": "高层(共37层)" },
  "year_built": 2007,
  "features": ["满五年", "唯一住房", "有电梯", "近地铁", "车位充足"],
  "photos": {
    "indoor": [{ "link": "https://pic1.ajkimg.com/display/anjuke/932826-%E5%A4%AA%E5%B9%B3%E6%B4%8B%E6%88%BF%E5%B1%8B/3b5c7d02b2511939fe967cf99069bc40-2500x2000.jpg?frame=1" }]
  },
  "community": {
    "id": "8",
    "name": "汤臣一品",
    "address": "花园石桥路28弄",
    "district": { "id": 7, "name": "浦东" },
    "business_area": { "id": 2643, "name": "陆家嘴" },
    "price": { "per_sqm": 229531, "currency": "CNY" }
  },
  "broker": { "name": "罗强", "company": "太平洋房屋", "store": "太平洋房屋瑞平路店", "service_score": 618 }
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Anjuke Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/anjuke-scraper
cd anjuke-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

Anjuke lets one IP make about one request a minute. For more, point the scraper at a rotating proxy (a fresh IP per connection) before you start it:
```bash
export ANJUKE_PROXY="http://user:pass@host:port"
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/sale/details?listing=3993742615191556"
```

```json
{
  "id": "3993742615191556",
  "title": "汤臣一品高区一线江景，哪有什么意难平，你住汤臣你也行",
  "link": "https://shanghai.anjuke.com/prop/view/3993742615191556",
  "price": { "total": 100000000, "total_wan": 10000, "per_sqm": 230484, "currency": "CNY" },
  "layout": { "rooms": 4, "halls": 2, "bathrooms": 4, "text": "4室2厅4卫" },
  "area_sqm": 433.87,
  "floor": { "level": "高层", "total_floors": 37, "text": "高层(共37层)" },
  "year_built": 2007,
  "features": ["满五年", "唯一住房", "有电梯", "近地铁", "车位充足"],
  "community": {
    "id": "8",
    "name": "汤臣一品",
    "district": { "id": 7, "name": "浦东" },
    "business_area": { "id": 2643, "name": "陆家嘴" }
  },
  "broker": { "name": "于伯骁", "company": "太平洋房屋" }
}
```

All 13 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

13 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Resale Listing Details | `/sale/details` | Price, mortgage, layout, photos, broker, community and price history |
| Autocomplete | `/sale/suggest` | Communities, business areas and metro stations with average prices |
| Search Resale Homes | `/sale/search` | 60 homes per page; filter by district, price, size, rooms |
| Search Rentals | `/rent/search` | 30 rentals per page; filter by place, rent, rooms, type |
| Rental Details | `/rent/details` | Rent, payment terms, amenities, photos, metro distances and broker |
| Search Communities | `/communities/search` | 25 communities per page with average price, households and score |
| Community Details | `/communities/details` | Developer, fees, parking, valuations, gallery and price history |
| Community Listings | `/communities/listings` | Every resale home for sale in one community |
| Search New Homes | `/new_homes/search` | 20 projects per page with price, status, metro and hotline |
| New Home Details | `/new_homes/details` | Prices, permits, floor plans, developer, fees and area prices |
| New Home Reviews | `/new_homes/reviews` | Buyer reviews and Q&A with sales-consultant answers |
| Cities | `/cities/list` | All 679 cities with pinyin, alias and links |
| City Details | `/cities/details` | Districts, business areas, metro lines and price buckets |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-anjuke-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-anjuke-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-anjuke-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/sale/search",
    params={"city": "shanghai", "district": "pudong", "price_min": 500, "rooms": "3", "sort": "price_desc"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Anjuke Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://www.omkar.cloud/l/anjuke-scraper-github-whatsapp)

[![Ask Us by Email about Anjuke Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](https://www.omkar.cloud/l/anjuke-scraper-github-email)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/anjuke-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/anjuke-scraper)
