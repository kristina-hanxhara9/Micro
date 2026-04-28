from src.models import ExtractedRetailer, PriceSample
from src.plugins.validator import normalize_phone, score_record


def test_normalize_phone_us_valid():
    norm, ok = normalize_phone("(212) 555-1212")
    assert ok is True
    assert norm == "+12125551212"


def test_normalize_phone_garbage():
    norm, ok = normalize_phone("not a number")
    assert ok is False
    assert norm == "not a number"


def test_normalize_phone_none():
    assert normalize_phone(None) == (None, False)


def test_score_full_record_high_confidence():
    extracted = ExtractedRetailer(
        about="Best Buy is a leading retailer of consumer electronics in the United States.",
        categories=["electronics", "appliances"],
        brands=["Sony", "Apple", "Samsung"],
        sample_prices=[PriceSample(item="iPhone 15", price=799.0)],
        phone="(612) 291-1000",
        address="7601 Penn Ave S, Richfield, MN 55423",
    )
    rec = score_record(
        name="Best Buy",
        website="https://www.bestbuy.com",
        extracted=extracted,
        sources=["https://www.bestbuy.com/", "https://www.bestbuy.com/about"],
    )
    assert rec.confidence >= 0.9
    assert "no_website_found" not in rec.flags
    assert "domain_mismatch" not in rec.flags
    assert rec.phone == "+16122911000"


def test_score_no_website():
    rec = score_record("Asdfqwer Mart", None, ExtractedRetailer(), [])
    assert rec.confidence < 0.5
    assert "no_website_found" in rec.flags
    assert "no_sources_scraped" in rec.flags


def test_score_domain_mismatch_flagged():
    rec = score_record(
        "Joe's Hardware",
        "https://yelp.com/biz/joes-hardware",
        ExtractedRetailer(categories=["hardware"]),
        ["https://yelp.com/biz/joes-hardware"],
    )
    assert "domain_mismatch" in rec.flags


def test_score_invalid_phone_flagged():
    rec = score_record(
        "Test Co",
        "https://test-co.com",
        ExtractedRetailer(phone="123", categories=["x"]),
        ["https://test-co.com"],
    )
    assert "phone_invalid" in rec.flags
