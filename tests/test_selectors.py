from semscrape.dom import parse_html
from semscrape.selectors import unique_selector


def test_unique_selector_by_data_attr():
    soup = parse_html('<main><h1 data-qa="name-primary">Thing</h1><h1>Other</h1></main>')
    h1 = soup.find("h1")
    selector = unique_selector(soup, h1)
    assert selector == 'h1[data-qa="name-primary"]'
    assert soup.select_one(selector).get_text(strip=True) == "Thing"
