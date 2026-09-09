from common import parse_source_line, read_urls


def test_non_english_and_mixed_language_blogs_are_not_configured():
    configured = {parse_source_line(line)["url"] for line in read_urls()}
    assert configured.isdisjoint(
        {
            "https://beta.hackndo.com/",
            "https://blog.orange.tw/",
            "https://devco.re/blog/",
        }
    )
