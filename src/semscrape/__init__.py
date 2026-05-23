"""semscrape: local-first semantic scraping primitives."""

from .extract import extract_html
from .spec import load_spec

__all__ = ["extract_html", "load_spec"]
__version__ = "0.1.0"
