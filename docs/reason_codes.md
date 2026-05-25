# Reason Codes

Reason codes explain why semscrape abstained, rejected a cached selector, suppressed fallback, or marked evidence as failed. They are safety signals. In public-alpha workflows, an abstention with a clear reason is usually preferable to a silent wrong value.

This document covers common codes emitted by the current extraction, ranker, cache, fallback, safety-veto, and evidence paths. Field-specific ranker gates are numerous; related codes use consistent prefixes and are grouped below.

## Where To Look

- Extraction JSON: each field has `status`, `source`, `decision.reason`, `validation_errors`, `reasons`, and `trace`.
- Field diagnosis: `semscrape diagnose SPEC INPUT --field FIELD` prints the final decision, primary reasons, top candidates, and suggested next steps. Add `--json` for structured output.
- Evidence review: `semscrape evidence review .semscrape/evidence.db --status abstained`.
- Candidate inspection: `semscrape inspect SPEC INPUT FIELD --top-k 20`.
- Failure summaries: `semscrape failures summarize RUN_OR_FAILURE_DIR`.

## Validator Reasons

| Code | Meaning | Try next |
| --- | --- | --- |
| `no_candidate` | The strict gate received no chosen candidate. | Inspect candidate generation. If the desired value is absent, improve rendering, field hints, or candidate generation. |
| `no_candidates` | No DOM candidates were available. | Confirm the input HTML contains the value, use `--render` for JavaScript pages, and inspect candidates. |
| `validator_disqualified` | A hard disqualifier fired. | Check `decision.hard_disqualifiers`; fix field intent, validators, or the candidate source. |
| `validator_rejected` | The candidate did not pass validation. | Check `validation_errors` such as `not price-like`, `currency missing`, `not date-like`, or custom regex failures. |
| `low_validator_confidence` | Validation passed but confidence was below policy threshold. | Add precise hints or validators, or check whether the candidate is too broad. |
| `low_confidence` | Heuristic confidence was below policy threshold. | Inspect top candidates and add field hints/examples that match nearby labels. |
| `ambiguous_candidates` | The best candidate did not beat competitors by enough margin. | Clarify field descriptions, add hints, add validators, or accept abstention. |
| `strict_gate_failed` | Generic strict-mode abstention when no more specific reason was available. | Read earlier trace events for the concrete validator or ranker reason. |

Common validator error text includes `empty required value`, `length < N`, `length > N`, `not price-like`, `currency missing`, `not number-like`, `not date-like`, `not url-like`, `not email-like`, `not bool-like`, `regex did not match: ...`, `regex_not matched: ...`, `missing required text: ...`, `contains rejected text: ...`, and `not in choices`.

## Ranker Reasons

| Code | Meaning | Try next |
| --- | --- | --- |
| `ranker_error` | The ranker could not run, usually because the model file was missing or malformed. | Run `semscrape ranker info`; check `--ranker` or reinstall so the packaged ranker is available. |
| `ranker_abstained` | A ranker-only policy received no safe ranker choice. | Inspect the `ranker` trace event for the underlying reason. |
| `low_ranker_confidence` | Ranker positive confidence was below threshold. | If the correct candidate is present, collect/review evidence rather than lowering thresholds for public-alpha runs. |
| `low_ranker_margin` | The ranker saw multiple close candidates. | Add hints or validators that separate the intended value from neighbors. |
| `no_safe_ranker_candidate` | Every scored candidate was blocked by a ranker gate. | Review individual candidate reasons; this usually needs better spec context or trusted evidence. |
| `ranker_hard_negative` | The candidate matched a known hard-negative pattern. | Inspect context; if actually correct, create reviewed evidence for the exception. |
| `ranker_hidden_candidate` | The candidate was hidden or not visible. | Use rendered inspection and relearn visible selectors. |
| `ranker_validator_disqualified` | The candidate had validator hard disqualifiers. | Check `hard_disqualifiers`; fix field type, validators, or candidate context. |
| `ranker_validator_rejected` | The candidate failed validation. | Inspect value shape and field type. |
| `ranker_penalty_limit` | The candidate had more soft penalties than the policy allows. | Improve hints/candidates instead of loosening this for public-alpha runs. |
| `ranker_chose_wrong_candidate` | Evaluation found the ranker selected a validated candidate that did not match expected truth. | Treat as a safety incident; add reviewed hard-negative evidence or a regression fixture. |
| `validator_rejected_choice` | Evaluation found the ranker's chosen candidate did not validate. | Check ranker data and validator thresholds. |

## Field-Specific Ranker Gates

These codes block candidates that may look valid in isolation but are unsafe for the requested field.

| Code or family | Meaning | Try next |
| --- | --- | --- |
| `ranker_title_*` | Title/headline traps such as price-shaped titles, date-shaped titles, non-primary regions, tag clouds, or missing heading context. | Clarify whether you want page title, product title, article headline, recent item, or tag/category text. |
| `ranker_listing_*` | Listing/card traps such as wrong ordinal, non-first item, or missing card/result context. | Make ordinals explicit and inspect repeated-card candidates. |
| `ranker_recent_title_*` | Recent-item title traps such as featured/page title, non-heading, non-primary region, or section label. | Clarify whether you want the page title, featured item, or first recent item. |
| `ranker_table_*` | Table traps such as non-cell context, header instead of value, pagination controls, wrong row, or missing percentage context. | Add row/column hints and verify the desired cell is in candidates. |
| `ranker_section_*` | Section traps such as navigation/footer/sidebar/TOC regions, page title, non-heading, or non-first section. | Add main/article/content hints and separate page-title fields from section-heading fields. |
| `ranker_author_*` | Author traps such as section labels, non-person values, bio text, or missing byline context. | Add byline hints or use a broader text field for organizations. |
| `ranker_summary_too_short` | A summary/description matched a heading or short fragment. | Add minimum length or paragraph/description hints. |
| `ranker_generic_text_*` | Generic text lacked intent evidence or came from unsafe regions. | Make the field description more specific. |
| `ranker_monthly_annual_conflict` | A monthly price request matched an annual/yearly price. | Add monthly, `/mo`, or plan-specific hints. |
| `ranker_price_*` | Price traps such as ad/add-on regions, missing plan context, or wrong plan context. | Add product/current/plan hints and inspect nearby price labels. |
| `ranker_coupon_*` | Coupon/promo traps such as no-coupon context or missing promo/code evidence. | Accept abstention or add coupon-specific hints. |
| `ranker_availability_*` | Availability traps such as price candidates or missing stock/shipping context. | Use availability-specific hints and validators. |
| `ranker_link_*` | Link traps such as non-anchor candidates or wrong link ordinal. | Use `url` fields and inspect link order. |
| `ranker_metadata_*` | Metadata traps such as labels, containers, code samples, body links, inline body text, wrong fields, or non-metadata regions. | Verify the value is a scalar metadata value, not a label/container. |
| `ranker_document_title_required` | A document title field did not use the `title` element in `head`. | Use a page title field for visible H1 text. |
| `ranker_main_heading_required` | A main-heading field did not match an H1. | Inspect rendering and heading markup. |
| `ranker_updated_date_candidate` | A published-date field matched an updated/modified date. | Add published/original date hints. |
| `ranker_date_negative_context` | A date was near negative context such as updated, joined, copyright, comments, or related article. | Add stronger publication-date context. |
| `ranker_broad_container` | The candidate was a broad container rather than a scalar value. | Improve candidate specificity with hints or validators. |

## Cache Reasons

| Code | Meaning | Try next |
| --- | --- | --- |
| `selector_invalid` | The cached selector could not be parsed. | Clear or regenerate the cache with `semscrape cache-clear CACHE_PATH` and rerun with `--learn`. |
| `selector_no_match` | The cached selector matched nothing on this page version. | Normal drift; let extraction repair and relearn if the value is present. |
| `selector_many_matches` | The cached selector matched multiple elements. | Relearn from a more specific accepted candidate. |
| `selector_not_validated` | Cache entries existed but none produced a validated value. | Review cache trace and let normal ranking run. |
| `hidden_candidate` | A cached selector found a hidden candidate. | Use rendered inspection and relearn visible selectors. |
| `value_hard_disqualified` | The cached value hit validator hard disqualifiers. | Check whether the page changed semantics; do not force reuse. |
| `value_failed_validator` | The cached value failed validation. | Adjust validators only if they are wrong; otherwise relearn. |
| `value_low_confidence` | The cached value did not clear confidence checks. | Add hints/validators or rely on normal ranking. |
| `cache_rejected` | A cached candidate was rejected by strict gating. | Inspect `decision.reason`; cache entries are advisory. |

## Fallback Suppression Reasons

| Code | Meaning | Try next |
| --- | --- | --- |
| `policy_all` | LLM fallback is allowed by policy. | No action; this is an eligibility reason. |
| `recoverable_candidate_available` | A visible candidate can plausibly pass strict gates if selected. | No action; the model may be called. |
| `unknown_fallback_policy` | The fallback policy name is not recognized. | Use `all`, `recoverable-only`, or `budgeted`. |
| `ranker_reason_not_recoverable` | The ranker abstention reason was unsafe for model recovery. | Fix candidates/spec/evidence instead of asking the model to override safety. |
| `no_strict_eligible_candidates` | No visible candidate could pass strict validation even with zero margin. | Improve candidate generation, rendering, or validators. |
| `fallback_ad_region` | All eligible candidates were in sponsored/recommended/ad context. | Add main content hints or accept abstention. |
| `fallback_monthly_annual_conflict` | A monthly price field only had annual-looking eligible candidates. | Add monthly price hints or adjust the field intent. |
| `fallback_budget_floor` | Budgeted fallback suppressed a low-confidence text candidate. | Improve field specificity or use `recoverable-only` for experiments. |
| `coupon_absent_context` | Coupon fallback found only absent-coupon context. | Accept abstention unless absence is the desired value. |
| `model_error` | The local model call failed. | Check Ollama daemon, model name, and host. |
| `model_abstained` | The local model returned abstain/no choice. | Inspect candidates; model abstention is expected on ambiguity. |
| `low_model_confidence` | The model chose below minimum model confidence. | Do not lower this for high-precision runs without review data. |

## Safety Veto Reasons

| Code | Meaning | Try next |
| --- | --- | --- |
| `veto_ranker_required` | `ranker-local-safe-veto` was selected without a veto ranker. | Supply `--veto-ranker` or use `ranker-local-safe`. |
| `safety_veto_low_positive_confidence` | The veto ranker scored an accepted candidate below threshold. | Treat as abstention and review evidence before changing thresholds. |
| `safety_veto_candidate_row_missing` | Veto evaluation could not find the candidate row. | Check evaluation artifacts and candidate ids. |
| `trap_first_content_link_ordinal` | A first-content-link candidate was not the first link. | Clarify ordinal or inspect content links. |
| `trap_first_content_link_low_positive_confidence` | Learned trap veto was uncertain about a first content link. | Review manually; this policy is internal/diagnostic. |
| `trap_updated_date_for_published_date` | A published-date field matched an updated/modified date. | Add published/original date hints. |
| `trap_tag_cloud_title` | A title field matched tag-cloud/category text. | Add main title hints or create a tag field. |
| `trap_related_or_recommended_title` | A title field matched related/recommended/ad content. | Add main content hints. |
| `trap_shipping_or_addon_price` | A price field matched shipping, tax, add-on, workshop, or delivery context. | Add product/current price hints. |
| `trap_table_context_mismatch` | A table field matched outside accepted table cell/link context. | Add row/column hints and inspect candidates. |
| `trap_only_low_positive_confidence` | Generic learned trap-only veto confidence was too low. | Review manually; do not treat as a positive training label. |
| `trap_only_no_learned_veto_for_field` | Trap-only mode found no learned veto for this field and passed the candidate. | No action; informational pass reason. |
| `trap_only_veto_passed` | Trap-only veto evaluated and did not block. | No action. |

## Evidence Failure Reasons

| Code | Meaning | Try next |
| --- | --- | --- |
| `candidate_missing` | Expected value was known but no top-K candidate matched it. | Improve candidate generation, rendering, or spec. Do not tune ranker thresholds first. |
| `false_positive_missing_field` | Expected value was absent, but extraction returned a validated value. | Treat as a safety incident and add reviewed hard-negative evidence or a regression fixture. |
| `wrong_candidate` | Expected value was present, but extraction returned a different validated value. | Inspect whether the correct candidate was in top-K and add regression/evidence for the wrong pattern. |
| `abstained` | The final result abstained and no more specific decision reason was recorded. | Inspect field trace for earlier gate details. |
