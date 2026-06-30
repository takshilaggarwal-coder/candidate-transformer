# Multi-Source Candidate Data Transformer

Ingest messy candidate data from several sources, resolve who-is-who, and emit
**one canonical profile per candidate** — normalized, deduplicated, with
**provenance** (where each value came from) and **confidence** (how much to
trust it). A runtime config reshapes the output without touching the engine.

Design principle throughout: **deterministic and explainable**. Same input →
same output, every value traceable to a source and a method, and *honestly-empty
beats wrong-but-confident* — a normalizer returns `None` rather than guess.

---

## Quick start

```bash
# 1. install (Python 3.9+)
pip install -r requirements.txt
#    or, to also get the UI + test extras and a `candidate-transformer` command:
pip install -e ".[web,dev]"

# 2. run the CLI over the bundled samples (default canonical schema -> stdout)
python -m candidate_transformer \
  -s samples/inputs/recruiters.csv \
  -s samples/inputs/ats.json \
  -s samples/inputs/resume_jane_doe.pdf \
  -s samples/inputs/resume_raj_patel.docx \
  -s samples/inputs/notes.txt \
  -s ats_json=samples/inputs/garbage.json

# 3. apply a runtime config and write to a file
python -m candidate_transformer \
  -s samples/inputs/recruiters.csv -s samples/inputs/ats.json \
  -c configs/custom_example.json -o out.json

# 4. launch the web UI (needs the [web] extra)
python -m candidate_transformer.web        # -> http://127.0.0.1:5000

# 5. run the tests
pytest
```

No install needed to *run* it — the package is `src`-layout and the tests put
`src` on the path themselves. Installing just adds the console-script alias.

---

## Deploy the web UI to Vercel

The repo ships ready to deploy as a Vercel serverless function. The Flask app is
exposed to Vercel's `@vercel/python` runtime by `api/index.py`, and `vercel.json`
routes every request to it and bundles the data files (`src/`, `samples/inputs/`,
`configs/`) the UI reads at runtime.

**Fastest way to a live link — Vercel CLI (~1 min):**

```bash
npm i -g vercel
cd candidate-transformer
vercel          # first run: log in + answer the prompts -> preview URL
vercel --prod   # promote to the production URL
```

The CLI handles login in your browser and prints the URL when it finishes.

**Or deploy from GitHub:** push this repo, then in the Vercel dashboard *Add New
→ Project → Import* it. Vercel auto-detects `vercel.json`; no settings to change.
Once it's public you can also wire up a one-click button:

```md
[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/<you>/candidate-transformer)
```

Notes: the function only ever *reads* the bundled samples, so the read-only
serverless filesystem is fine. Cold starts pull in `pdfplumber`/`python-docx`, so
the first request after idle is a beat slower — normal for serverless. For an
always-on Flask process, Render or Railway are an equally simple alternative.

---

## Pipeline

```
detect → extract → normalize → merge (identity + conflict) → confidence → project → validate
```

| Stage | Module | What it does |
|-------|--------|--------------|
| detect | `sources/__init__.py` | Pick an adapter from the file type (overridable on the CLI). |
| extract | `sources/*.py` | Each adapter reads its format and emits raw, **un-normalized** `RawCandidate` records. Failures are isolated (`safe_extract`) so a broken file never crashes the run. |
| normalize | `normalize.py`, `skills.py` | Pure, deterministic primitives turn raw strings into canonical formats, returning `None` when unsure. |
| merge | `merge.py` | Cluster records that refer to the same person (union-find), then resolve each field by trust-weighted confidence. |
| confidence | `merge.py` | Noisy-OR over the trust weights of agreeing sources. |
| project | `projection.py` | The **only** place that reads the runtime config and reshapes the canonical record for output. |
| validate | `validation.py` | Check the output against the default schema, or the config's declared types + `required`. |

The canonical record (`canonical.py`) is the single source of truth; the
projection layer is thin. That separation is what lets the same engine serve the
default schema and any custom config with no code changes.

### Sources (adapters)

| Source type | Input | Role |
|-------------|-------|------|
| `recruiter_csv` | CSV with header aliasing | Structured contact data. |
| `ats_json` | ATS export (nested/renamed fields) | Field **remapping** from ATS vocabulary to ours. |
| `resume` | PDF / DOCX / TXT | Section-driven parse (summary, experience, education, skills). |
| `recruiter_notes` | Free-text `.txt` | Low-precision regex extraction (emails, phones, name, skills). |

Adding a source (GitHub, LinkedIn, …) is a two-line change: implement
`SourceAdapter.extract` and register it. Nothing downstream needs to know.

---

## Canonical schema & normalized formats

One profile is a `candidate_id`, `full_name`, `emails[]`, `phones[]`,
`location{city,region,country}`, `links{linkedin,github,portfolio,other[]}`,
`headline`, `years_experience`, `skills[]`, `experience[]`, `education[]`, plus
`provenance[]` and `overall_confidence`.

| Field | Normalized to | Example |
|-------|---------------|---------|
| phone | E.164 | `(415) 555-0186` → `+14155550186` |
| date (experience) | `YYYY-MM` | `Mar 2021` → `2021-03`; `present` → `null` |
| graduation | `YYYY` (int) | `Class of 2018` → `2018` |
| country | ISO-3166 alpha-2 | `USA` → `US`, `India` → `IN` |
| skill | controlled vocabulary | `k8s` → `Kubernetes`, `js` → `JavaScript` |
| email | lowercased, unwrapped | `<MAILTO:A@B.com>` → `a@b.com` |
| URL | scheme-normalized | `github.com/x` → `https://github.com/x` |

Skill canonicalization is a **deterministic alias table, not a fuzzy matcher** —
fuzzy matching would invent links we can't explain. Unknown skills pass through
title-cased rather than being force-mapped to the nearest known one.

---

## Merge, conflict resolution & confidence

**Identity resolution.** A union-find clusters per-source records using strong
keys (shared email, shared phone), a weak key (name + company/country), and a
name-only key that links note-style sources. Roots are chosen deterministically.

**Conflict resolution.** Each field's value is chosen by **combined confidence**,
not by source order. The weight of one (source, field) claim is:

```
weight = source_trust × field_multiplier
```

| Source | Base trust |
|--------|-----------|
| `recruiter_csv` | 0.90 |
| `ats_json` | 0.85 |
| `resume` | 0.80 |
| `recruiter_notes` | 0.50 |

Field multipliers encode *who is authoritative for what* — resumes win on
experience/skills, structured sources win on contact details. All tunables live
in one place (`FIELD_TRUST` / `SOURCE_TRUST` in `merge.py`).

**Confidence = noisy-OR** over the weights of the sources that agree on a value:

```
confidence = 1 − Π(1 − wᵢ)
```

Independent corroboration raises confidence (but never above 1.0); a lone
low-trust source stays low. Ties break by source priority, then lexicographically
— so the result is fully reproducible. The winning value records its source and
method (`direct`, `remapped`, `extracted`, `+E164`, `+canonical`, …) in
`provenance`.

The profile-level **`overall_confidence`** then multiplies that corroboration
(the mean of the per-field confidences) by **coverage** — the fraction of the
core signals (name, email, phone, location, skills, experience) actually present.
A fully-populated profile has coverage 1.0, so it's unaffected; a sparse record
can't look confident just because its one filled-in field came from a trusted
source.

> **Worked example (Jane).** Four sources report her phone in four spellings →
> one `+14155550186` at high confidence. `"Jane A. Doe"` (ATS + resume) outranks
> `"Jane Doe"` (CSV + notes) because two corroborating sources beat two others on
> noisy-OR. Her CSV row lists a stale current employer; the resume's real end date
> wins the per-field resolution.

---

## The runtime config (configurable output)

A JSON config reshapes output without changing the engine. Pass it with `-c`.

```jsonc
{
  "fields": [
    { "path": "full_name",      "type": "string",   "required": true },
    { "path": "primary_email",  "from": "emails[0]", "type": "string", "required": true },
    { "path": "phone",          "from": "phones[0]", "normalize": "E164" },
    { "path": "location.country","from": "location.country", "normalize": "iso3166" },
    { "path": "current_title",  "from": "experience[0].title", "on_missing": "null" },
    { "path": "skills",         "from": "skills[].name", "type": "string[]", "normalize": "canonical" }
  ],
  "include_confidence": true,
  "include_provenance": false,
  "on_missing": "null",
  "default_region": "US"
}
```

- **subset / rename** — `path` is the output key; `from` is the canonical source path.
- **path grammar** — `emails[0]` (index), `skills[].name` (wildcard map), `location.country` (nested).
- **per-field `normalize`** — `E164`, `canonical`, `iso3166`, `yyyy-mm`, `lowercase`, `uppercase`.
- **`on_missing`** — `null` | `omit` | `error`, global with per-field override.
- **toggles** — `include_confidence`, `include_provenance` (provenance is filtered to the fields you actually project).

Two ready-made configs ship in `configs/`: `custom_example.json` (exercises every
capability) and `recruiter_card.json` (a lean card: essentials only, missing
fields omitted, provenance/confidence off).

---

## Edge cases handled & deliberate descoping

**Handled**

1. **US-state / country-code collision.** `"San Francisco, CA"` keeps `CA` as a
   region — it is *not* read as Canada — while `"…, USA"` still resolves the country.
2. **Garbage source.** A malformed JSON file (`samples/inputs/garbage.json`) is
   caught at the adapter boundary, logged as a warning, and contributes nothing
   instead of aborting the batch.
3. **Stale "current" employer.** Conflicting end-dates for the same job are
   resolved per-field by trust, so a resume corrects a stale CSV "present".
4. **Contact-less candidate + `required`.** A notes-only candidate with no email
   is dropped (with a warning) when the config marks email `required`, rather
   than emitting a half-empty record.
5. **Region-aware phones.** A bare `9876543210` parses to `+91…` when the record's
   country is India; unparseable numbers are dropped, never half-formatted.

**Deliberately descoped** (called out, not hidden)

- Skill matching is a curated alias table, not embeddings/fuzzy matching.
- Resume parsing is heuristic and tuned to common section layouts.
- `recruiter_notes` does not attempt employment-history parsing (low precision).
- Identity resolution uses a name-only fallback key, so true homonyms with no
  contact overlap could over-merge — documented in `merge.py`.

---

## Project layout

```
src/candidate_transformer/
  canonical.py     internal data model (single source of truth)
  normalize.py     pure normalizers (email, phone, date, country, location, …)
  skills.py        deterministic skill alias table
  sources/         adapters: recruiter_csv, ats_json, resume, recruiter_notes
  merge.py         identity resolution + trust/confidence + conflict resolution
  config.py        runtime config parsing + validation
  projection.py    canonical → requested output shape (only config-aware module)
  validation.py    default-schema + config-schema validation
  pipeline.py      wires the stages together (used by CLI and UI)
  cli.py           argparse CLI            web.py  minimal Flask UI
configs/           sample runtime configs
samples/inputs/    five sources incl. a deliberately broken one
samples/outputs/   produced outputs (default + both configs)
tests/             unit + end-to-end + a gold-profile snapshot
```

## Tests

`pytest` runs 141 tests: normalizer units, the trust/confidence math, conflict
and identity resolution, the projection grammar + config policies, and an
end-to-end run over the real samples (asserting the location-collision fix,
stale-date resolution, garbage-doesn't-crash, determinism, and a gold-profile
snapshot of Jane's merged record).
