# Safety Rule Registry

The rule registry gives deterministic safety gates stable IDs, scopes, severities, and reason codes. It does not replace validators or ranker gates. It names the rules that are already emitted so incident reports, tests, and user-facing explanations can refer to the same thing.

The initial registry is intentionally small. Future remediation work should add rules here as gates are introduced or migrated.

| Rule ID | Severity | Reason Code | Applies To | Notes |
| --- | --- | --- | --- | --- |
| `price.shipping_tax_installment` | `hard_disqualifier` | `shipping/tax/installment price cue` | price fields | Rejects shipping, tax, delivery, installment, or monthly-price context unless requested. |
| `price.old_list_price` | `penalty` | `old/list price cue` | price fields | Penalizes old/list/MSRP/compare-at prices unless requested. |
| `title.price_shaped_candidate` | `hard_disqualifier` | `price-shaped title candidate` | title-like text fields | Rejects price-shaped text when the field asks for a title. |
| `listing.non_first_listing_item` | `hard_disqualifier` | `non-first listing item` | listing fields | Rejects later repeated cards when the field asks for the first listing item. |
| `listing.non_first_listing_item_price` | `hard_disqualifier` | `non-first listing item price` | listing price fields | Rejects later repeated-card prices when the field asks for the first listing item price. |
| `docs.chrome_action_label` | `hard_disqualifier` | `docs chrome action label` | documentation fields | Rejects UI chrome labels such as show source, report a bug, or improve this page. |
| `docs.section_non_content_region` | `hard_disqualifier` | `section heading outside main content` | docs section fields | Rejects section headings from navigation, footer, sidebar, or other non-content regions. |

## Adding Rules

Each rule should include:

- stable `id`
- user-facing `description`
- `applies_to` metadata
- `severity`
- emitted `reason_code`
- optional `introduced_by` incident or milestone
- optional `pack_scope`

Keep reason codes stable unless there is a compatibility plan. Tests should prove migrated rules still emit the same reason code and reject or penalize the same candidates.
