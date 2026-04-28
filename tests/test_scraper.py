from src.plugins.scraper import _extract_json_ld, _extract_visible_text


def test_extract_strips_scripts_and_chrome():
    html = """
    <html>
      <head><title>x</title><script>alert(1)</script><style>body{}</style></head>
      <body>
        <nav>nav links</nav>
        <header>top</header>
        <main>
          <h1>Best Buy</h1>
          <p>We sell electronics including Sony and Apple products.</p>
        </main>
        <footer>footer junk</footer>
      </body>
    </html>
    """
    text = _extract_visible_text(html)
    assert "Best Buy" in text
    assert "electronics" in text
    assert "alert" not in text
    assert "nav links" not in text
    assert "footer junk" not in text


def test_extract_collapses_whitespace():
    html = "<html><body>  hello   \n\n   world  </body></html>"
    assert _extract_visible_text(html) == "hello world"


def test_json_ld_single_product():
    html = """
    <html><head>
      <script type="application/ld+json">
      {"@context":"https://schema.org","@type":"Product","name":"iPhone 15",
       "brand":{"@type":"Brand","name":"Apple"},
       "offers":{"@type":"Offer","price":"799.00","priceCurrency":"USD"}}
      </script>
    </head><body></body></html>
    """
    blobs = _extract_json_ld(html)
    assert len(blobs) == 1
    assert blobs[0]["@type"] == "Product"
    assert blobs[0]["name"] == "iPhone 15"


def test_json_ld_graph_unwraps():
    html = """
    <html><head>
      <script type="application/ld+json">
      {"@graph":[
        {"@type":"Organization","name":"Best Buy"},
        {"@type":"Product","name":"Sony TV","offers":{"price":"499","priceCurrency":"USD"}}
      ]}
      </script>
    </head><body></body></html>
    """
    blobs = _extract_json_ld(html)
    types = [b.get("@type") for b in blobs]
    assert "Organization" in types
    assert "Product" in types


def test_json_ld_skips_invalid():
    html = '<script type="application/ld+json">{ this is not json }</script>'
    assert _extract_json_ld(html) == []
