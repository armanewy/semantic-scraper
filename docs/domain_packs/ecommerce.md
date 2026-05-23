# Ecommerce Domain Pack

The ecommerce pack is the first local domain-pack release path for product extraction.

Supported first-pass fields:

- product title
- current product price
- rating/review score
- availability or stock status
- listing title/price/rating/coupon fields in replay canaries

The pack is conservative by design. It favors abstention over false positives for common ecommerce traps:

- current price vs old/list price
- shipping, tax, financing, installment, and bundle prices
- coupon/discount amounts
- sponsored or recommended product cards
- hidden duplicate values
- rating vs review count

Run the current baseline pack:

```bash
semscrape extract examples/product.yml examples/product_v2.html --pack ecommerce --values-only
```

Run the first release candidate pack:

```bash
semscrape extract examples/product.yml examples/product_v2.html --pack packs/ecommerce-v1 --values-only
```

Release-check command:

```bash
semscrape pack release-check packs/ecommerce-v1 \
  --baseline packs/ecommerce \
  --holdout corpus/base_holdout/manifest.yml \
  --adversarial corpus/adversarial_holdout/manifest.yml \
  --out runs/m12/ecommerce-v1-release-check.json
```

The current release candidate matched baseline holdout coverage, kept false-positive rate at zero, used no model calls, and kept adversarial false-positive rate at zero on the current sealed replay suites.
