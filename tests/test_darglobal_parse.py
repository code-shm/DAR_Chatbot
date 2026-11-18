from scraper.darglobal import classify, guess_location, guess_name


# --- classification ----------------------------------------------------
def test_root_development_is_project():
    assert classify("https://darglobal.co.uk/marea") == "project"
    assert classify("https://darglobal.co.uk/les-vagues") == "project"


def test_collection_prefix_is_project():
    assert classify("https://darglobal.co.uk/one-of-one/project-pagani") == "project"
    assert classify("https://darglobal.co.uk/rayana/trump-mansions") == "project"


def test_known_static_pages_are_not_projects():
    for path in ("faq", "about", "why-invest", "terms-conditions",
                 "privacy-policy", "tokenization", ""):
        assert classify(f"https://darglobal.co.uk/{path}") != "project", path


def test_section_types():
    assert classify("https://darglobal.co.uk/press/some-news") == "press-release"
    assert classify("https://darglobal.co.uk/blog/a-post") == "article"
    assert classify("https://darglobal.co.uk/partners/pagani") == "brand-partnership"
    assert classify("https://darglobal.co.uk/investor") == "investor-info"


# --- name recovery -----------------------------------------------------
def test_name_from_heading_matching_slug():
    # generic SEO title; the real name lives in a heading
    name = guess_name("https://darglobal.co.uk/one-of-one/top-of-the-astera",
                      "Buy Branded Homes | Million Dollar Houses for Sale",
                      ["Top of the Astera", "Register Interest"])
    assert name == "Top of the Astera"


def test_name_from_title_when_it_matches_slug():
    name = guess_name("https://darglobal.co.uk/marea",
                      "Marea, Interiors by Missoni | Costa Del Sol, Spain",
                      ["Register Interest"])
    assert name.startswith("Marea")


def test_name_falls_back_to_title_without_headings():
    assert guess_name("https://darglobal.co.uk/xyz", "Some Page | DarGlobal", []) \
        == "Some Page"


# --- location ----------------------------------------------------------
def test_location_city_country_pair():
    assert guess_location("DUBAI, UAE\nTRUMP INTERNATIONAL") == "Dubai, UAE"


def test_location_accented_city():
    assert guess_location("BENAHAVÍS, SPAIN\nTIERRA VIVA") == "Benahavís, Spain"


def test_location_country_only_fallback():
    assert guess_location("Located in beautiful Oman near the coast") == "Oman"


def test_location_absent():
    assert guess_location("No place names here at all.") == ""
