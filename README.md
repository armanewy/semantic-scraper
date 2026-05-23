# semscrape

A local-first prototype for the smallest useful part of a robust scraper: semantic selector repair.

The model is **not** used to scrape every page. The normal path is deterministic selectors. The local model only runs when a selector is missing or fails validation.

```text
cached selector -> validate -> done
                    |
                    v
              candidate DOM list
                    |
          heuristic ranking + local LLM
                    |
              repaired selector
                    |
              validate + persist
```

## Why this prototype exists

Traditional scrapers bind to brittle structure. This prototype tries to bind to meaning:

```yaml
fields:
  price:
    description: Current sale price shown to the shopper
    type: price
```

Then it finds a stable selector such as:

```css
strong[itemprop="price"]
```

instead of relying on whatever CSS class happened to exist during recording.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Install Ollama and pull a small local model:

```bash
ollama pull qwen3:1.7b
```

Other reasonable first models:

```bash
ollama pull gemma3:1b
ollama pull llama3.2:1b
```

## Try it without a model

The deterministic ranker should already survive the included layout/class mutation:

```bash
semscrape extract examples/product.yml examples/product_v1.html --no-llm --values-only
semscrape extract examples/product.yml examples/product_v2.html --no-llm --values-only
```

Benchmark both fixtures:

```bash
semscrape benchmark examples/product.yml examples/product_v1.html examples/product_v2.html --no-llm
```

## Try it with local model repair

```bash
semscrape extract examples/product.yml examples/product_v2.html --model qwen3:1.7b --learn
```

This writes:

```text
examples/product.yml.lock.json
```

The lock file stores repaired selectors. Subsequent runs try those selectors first and skip the model when validation passes.

## Inspect candidate DOM elements

```bash
semscrape candidates examples/product_v2.html \
  --field price \
  --description "Current sale price shown to the shopper" \
  --type price
```

This is the main debugging interface. If the correct element is not in the top candidate list, the local model cannot fix the scraper. Candidate generation quality matters more than prompt wording.

## Extraction spec

```yaml
fields:
  title:
    description: Product title or product name shown to the shopper
    type: title
    expected: "Acme Noise-Canceling Headphones"
  price:
    description: Current sale price shown to the shopper
    type: price
    expected: "$129.99"
  rating:
    description: Customer rating value for this product
    type: rating
    expected: "4.7 out of 5 stars"
```

Supported first-pass types:

- `text`
- `title`
- `price`
- `date`
- `url`
- `image`
- `rating`
- `email`
- `phone`
- `number`

You can add a custom regex:

```yaml
fields:
  sku:
    description: Product SKU
    type: text
    regex: "SKU-[0-9]+"
```

## Local model contract

The local model receives only a compact candidate list, not the full page. It must return strict JSON:

```json
{
  "chosen_candidate_id": 12,
  "alternate_candidate_ids": [9, 14],
  "confidence": 0.88,
  "expected_value": "$129.99",
  "needs_browser": false,
  "reason": "Candidate 12 has itemprop=price and price-shaped text."
}
```

The runtime validates the chosen selector before trusting it. If the model returns a bad candidate, the result is rejected or downgraded.

## What this does not do yet

This is not a complete scraper product. It deliberately avoids these larger product surfaces for now:

- JavaScript rendering through Playwright
- login/session workflows
- pagination
- anti-bot/proxy behavior
- visual layout reasoning
- fine-tuned local model training
- remote orchestration

Those can be added after the semantic locator is measurable.

## Next robustness tests

1. Generate 100+ mutated DOM variants per fixture.
2. Measure candidate recall: is the correct element in the top 40?
3. Measure model choice accuracy among top candidates.
4. Measure repaired selector survival across future variants.
5. Only then add browser rendering and a real crawl loop.
