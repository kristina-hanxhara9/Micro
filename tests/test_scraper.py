from src.plugins.scraper import _extract_visible_text


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
