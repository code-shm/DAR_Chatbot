from scraper.wasalt import parse_category, parse_listing, split_location


def test_parse_sale_villa():
    r = parse_listing(
        "https://wasalt.sa/en/property/sale/villa-333-sqm-facing-east-on-20m-width-street-5841671")
    assert r["deal"] == "sale" and r["type"] == "villa"
    assert r["sqm"] == 333 and r["facing"] == "east" and r["street_width_m"] == 20
    assert r["id"] == "5841671"


def test_parse_apartment_bedrooms():
    r = parse_listing("https://wasalt.sa/en/property/sale/apartment-with-3-bedrooms-5841667")
    assert r["type"] == "apartment" and r["bedrooms"] == 3


def test_parse_rejects_non_listing():
    assert parse_listing("https://wasalt.sa/en/s/privacy-policy") is None


# --- location splitting -------------------------------------------------
def test_split_plain_city():
    assert split_location("taif-al-malaab") == ("", "taif", "al malaab")


def test_split_article_city():
    assert split_location("al-khobar-corniche") == ("", "al khobar", "corniche")


def test_split_double_article_city():
    # 'hafar-al-batin' — the article chain carries the city to 3 tokens
    assert split_location("hafar-al-batin-industrial") == ("", "hafar al batin", "industrial")


def test_split_zone_prefix():
    assert split_location("east-riyadh-al-marjan") == ("east", "riyadh", "al marjan")


def test_split_city_only():
    assert split_location("jeddah") == ("", "jeddah", "")


# --- category URLs ------------------------------------------------------
def test_parse_category_properties():
    r = parse_category("https://wasalt.sa/en/properties-for-sale-in-taif-al-malaab")
    assert r["deal"] == "sale" and r["ptype"] == "property"
    assert r["city"] == "taif" and r["district"] == "al malaab"


def test_parse_category_typed():
    r = parse_category("https://wasalt.sa/en/villas-for-sale-in-east-riyadh-al-marjan")
    assert r["ptype"] == "villa" and r["zone"] == "east" and r["city"] == "riyadh"


def test_parse_category_hyphenated_type():
    r = parse_category("https://wasalt.sa/en/rest-houses-for-sale-in-buraidah-jbara")
    assert r["ptype"] == "rest house" and r["city"] == "buraidah"


def test_parse_category_mixed_case_slug():
    r = parse_category("https://wasalt.sa/en/lands-for-sale-in-buraidah-khub-al-Jutaily")
    assert r["ptype"] == "land" and r["city"] == "buraidah"


def test_parse_category_rent():
    r = parse_category("https://wasalt.sa/en/apartments-for-rent-in-jeddah-al-hamra")
    assert r["deal"] == "rent" and r["ptype"] == "apartment" and r["city"] == "jeddah"


def test_parse_category_rejects_unknown_type():
    assert parse_category("https://wasalt.sa/en/widgets-for-sale-in-jeddah") is None
