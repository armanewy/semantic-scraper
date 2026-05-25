# Architecture

semscrape is a local-first extraction pipeline. It tries to choose typed scalar values from HTML with deterministic candidate generation, validators, strict gates, and optional local repair steps. The current alpha posture favors abstention over silent wrong values.

## Runtime Flow

```text
spec.yml
  |
  v
load spec
  |
  v
load local HTML / fetch URL / optional Playwright render
  |
  v
generate compact DOM candidates
  |
  +-------------------------+
  | optional selector cache |
  | fast path per field     |
  +-----------+-------------+
              |
              v
extract scalar values + validate
  |
  v
heuristic rank candidates
  |
  v
strict decision gate
  |                       |
  | accepted              | abstained
  v                       v
optional cache learn      optional ranker repair
                          |
                          v
                          strict + safety gates
                          |                   |
                          | accepted          | abstained
                          v                   v
                          optional cache      optional LLM fallback
                          learn               |
                                              v
                                              validate + strict gate
                                              |
                                              v
                                              optional cache learn
  |
  v
report result + optional evidence recording
```

The selector cache is shown beside candidate generation because extraction still builds candidates once per HTML document, but each field can try cached selectors before falling back to ranked candidates.

## Load Spec

`src/semscrape/spec.py` loads a YAML object with a non-empty `fields` list. Each field has a `name`, `type` or `kind`, optional `description`, `hints`, examples, `required`, and validators. Supported field kinds are `text`, `price`, `number`, `date`, `url`, `email`, and `bool`.

Specs can also contain `benchmarks`, keyed by input basename. Benchmarks feed tests, canaries, evidence labels, dataset builds, and false-positive/candidate-recall measurement. They are not required for plain extraction.

## Load Or Render HTML

The CLI loads local files directly. URL inputs are fetched with `requests` unless rendering is requested. Rendered workflows use Playwright through `src/semscrape/render.py` and can wait for a selector with `--wait-for`.

Rendered snapshots preserve replayable files such as `rendered.html`, optional `static.html`, optional screenshots/accessibility trees, candidate rows, and extraction output. This keeps later evaluation offline and repeatable.

## Generate Candidates

`src/semscrape/dom.py` parses HTML with BeautifulSoup and creates compact `Candidate` records. It skips non-content tags such as `script`, `style`, `template`, `noscript`, `link`, `head`, and `svg`, and caps candidate count to keep ranking bounded.

Each candidate records a candidate id, selector path, tag, text, own text, compact attributes, attribute text, parent/sibling context, DOM depth, hidden state, and optional rendered metadata. Candidate recall matters because the ranker and LLM can only choose among generated candidates.

## Validate And Rank Candidates

`src/semscrape/validators.py` extracts a scalar value from each candidate, then validates it against the field type and validators. Validation returns pass/fail state, confidence score, normalized value, positive reasons, soft penalties, and hard disqualifiers.

`src/semscrape/heuristics.py` ranks candidates deterministically from validator confidence, field/context token overlap, type-specific cues, selector/context shape, and safety penalties. This path is the first normal extractor.

## Strict Decision Gate

`src/semscrape/decision.py` converts a ranked candidate into an accept/abstain decision. Strict mode rejects candidates with no candidate, validator hard disqualifiers, validator failure, low validator confidence, low candidate confidence, or insufficient margin over competing candidates.

Safe policies add field-specific gates from `src/semscrape/ranker.py`. A candidate can rank first and still abstain if it looks like a common trap, such as docs navigation text, wrong listing ordinal, wrong table row, updated date instead of published date, annual price instead of monthly price, tag cloud title, or broad container text.

## Optional Ranker Repair

Policies with `ranker` in the name load the packaged default candidate ranker unless `--ranker` points to another model. The ranker runs after the strict heuristic path abstains.

Ranker repair is still gated. The chosen candidate must pass validation, validator confidence, ranker confidence, ranker margin, penalty limits, hidden/visibility checks, and safe-policy field gates. `ranker-local-safe` tightens these thresholds and allows no ranker penalties.

Internal opt-in veto policies can block accepted safe-ranker choices, but they are diagnostic/evaluation tools and are not the public-alpha default.

## Optional LLM Fallback

LLM fallback uses local Ollama. The model is not asked to scrape arbitrary HTML. It receives a bounded top-K candidate list and must return strict JSON choosing one candidate id or abstaining.

Model selections are validated and passed through strict gates before acceptance. In `ranker-plus-llm`, the default fallback policy is `recoverable-only`, so unsafe ranker abstentions suppress the model call instead of asking the model to override safety.

## Cache Learning

`src/semscrape/cache.py` stores selector memory when `--learn` or an explicit cache is used. Cache entries include selector strategy, quality, confidence, successes, failures, and last rejection reason.

The cache is a fast path, not truth. A cached selector is accepted only when it finds a suitable visible candidate and the extracted value validates. Accepted heuristic, ranker, or model-recovery results can be learned; rejected cache entries fall back to normal ranking.

## Evidence Recording

`src/semscrape/evidence.py` records local SQLite evidence when `--record-evidence` is set. Records include policy, field metadata hash, input hash, selected candidate id, status, value shape, validator details, ranker trace summary, failure reason, labels, and top-K candidate feature rows.

Export, bundle, audit, intake, review, and training-export workflows are explicit commands. There is no automatic cloud upload or automatic global training from unverified runs.

## Component Map

```text
src/semscrape/
  assets.py      packaged ranker lookup
  cache.py       selector memory / lock files
  cli.py         command line entrypoint
  dataset.py     candidate-ranking dataset build/split/balance
  decision.py    strict confidence and abstention gates
  dom.py         HTML to compact candidate elements
  evidence.py    SQLite evidence store, bundles, intake, privacy audit
  extract.py     extraction, policies, ranker, LLM fallback, repair loop
  heuristics.py  deterministic candidate ranking
  llm.py         local Ollama candidate chooser
  packs.py       domain pack loading/defaults
  ranker.py      tiny offline candidate ranker and safety gates
  render.py      requests plus optional Playwright rendering
  selectors.py   CSS selector generation
  snapshot.py    rendered-page snapshot capture
  spec.py        YAML spec loader
  validators.py  type-specific scalar validators
```

Some corpora are sealed release-candidate suites. Do not use holdout or adversarial suites for dataset builds, ranker tuning, or promotion training.
