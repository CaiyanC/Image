# Customer Recommendation Boundary And Safety Design

## Context

Real HTTP acceptance on the development service (`127.0.0.1:8001`) exposed several customer-facing risks:

- `如果只买锅具，不要炉具和配件，给我一款两个人用的。` was parsed semantically as `subject_kind=cookware` plus `people=2`, but the deterministic contract adapter treated the negated word `配件` as a positive accessory subject. The final contract became `subject_category=配件`, and all candidates were rejected or left without verified people evidence.
- `适合泡咖啡的小锅有吗？` returned cookware rows and passed same-SKU verification, but the coffee use goal stayed in `recommendation_soft_preferences`. It did not expand the candidate pool or control ranking, so `CW-C93` was absent and the answer discussed water containers in unrelated cookware sets.
- `液体酒精炉在帐篷里能用吗？为什么？` entered a SKU-dependent fuel compatibility branch before giving the general safety boundary.
- Multi-category recommendations persisted one combined ordinal sequence, allowing a later ordinal such as “第一个烧水壶” to resolve against the first product of another category.
- Same-SKU product QA could return unsupported gifting marketing claims such as “包装精美、品质出众、绝佳礼物”.

The evidence shows that the first two recommendation failures are primarily contract/routing and candidate-pool problems, not an absence of product rows or an insufficient final LLM prompt. The database contains usable two-person evidence in fields such as `target_audience` and `features`; the coffee candidate `CW-C93` contains small-capacity and fast-boiling evidence but was not in the initial candidate window.

## Goals

1. Preserve positive product scope while correctly applying explicit negative scope phrases.
2. Make cookware-only and people constraints reach the same-SKU verifier without accidental accessory/stove widening.
3. Carry coffee/brewing/boiling intent into candidate expansion, deterministic ranking, and grounded customer-facing narrative.
4. Give generic fuel safety questions a useful general answer before requesting a SKU for product-specific compatibility.
5. Keep ordinal follow-ups within the requested category when a previous answer contains multiple categories.
6. Prevent unsupported gifting and packaging marketing claims from reaching customers.
7. Preserve existing evidence, context, API, and full-regression behavior.

## Non-goals

- Do not invent product facts or turn a use goal into a hard SKU attribute when the catalog does not record it.
- Do not change production services, merge to `master`, or restart production.
- Do not replace the existing sealed same-SKU evidence model with a new retrieval pipeline.
- Do not make the LLM choose SKUs or supply database facts.

## Design

### 1. Recommendation contract and negative scope

The recommendation contract builder will distinguish positive accessory nouns from accessory nouns inside an explicit exclusion phrase such as `不要炉具和配件`, `不含配件`, or `排除炉具`. A semantic `cookware` contract remains cookware when those nouns are exclusions.

Explicit exclusions will be retained in the contract metadata and candidate scope. The existing subject verifier remains the final authority: cookware candidates must be cookware subject rows, and accessory/stove rows must not be returned as recommendation candidates. People evidence continues to be read from the candidate's own structured fields, including `target_audience`, `features`, title, and capacity.

### 2. Coffee and boiling-use goal

Coffee-related wording (`泡咖啡`, `冲咖啡`, `咖啡`, and equivalent boiling-water intent) will be represented as a bounded soft use goal, not as a fabricated catalog scenario. When this goal is present for cookware:

- expand the initial candidate pool within the cookware category so relevant later rows such as `CW-C93` are eligible;
- rank evidence-backed cookware using existing product fields, prioritizing explicit small-pot identity, small/usable capacity, and fast-boiling or boiling-water evidence;
- pass the goal and its evidence requirements to the grounded narrative stage;
- ensure the final answer explicitly addresses the customer's coffee/brewing purpose and does not present a frying pan or griddle as the primary coffee pot.

The goal may guide ranking and wording, but a product is not declared coffee-compatible unless the product's own evidence supports the wording. If no same-SKU evidence supports a strong suitability claim, the answer will state the limitation and keep the recommendation conservative.

### 3. Generic alcohol-stove safety

Before the generic fuel compatibility branch, detect general environment-safety questions involving a tent, enclosed space, ventilation, or carbon-monoxide risk. Return a SKU-independent safety answer that clearly says not to use a fuel-burning stove in a tent or other enclosed space, requires adequate ventilation, and advises stopping use and moving to fresh air when abnormal fumes, leakage, or fire occurs.

The response may request a SKU afterward for product-specific fuel compatibility, but it must not make the customer provide a SKU before receiving the general safety boundary.

### 4. Category-scoped ordinal context

Multi-category recommendation results will persist an ordered SKU list per normalized product scope in addition to the existing combined order. Ordinal resolution will:

1. identify the category named in the current follow-up;
2. use that category's persisted ordered list when available;
3. fall back to the existing combined order only when the current follow-up has no category scope.

This keeps “第一个烧水壶” bound to the first waterware candidate and preserves existing parent-order behavior for replacement recommendations.

### 5. Gifting evidence boundary

Gifting suitability remains a product-QA question. Same-SKU QA or structured evidence may support it only when the evidence directly addresses gifting suitability or an explicit recorded attribute. Unsupported subjective marketing claims about packaging, quality, or being an ideal gift will be rejected or replaced by a conservative answer that states the available evidence boundary. The guard must not substitute heat-source, material, or other unrelated product facts.

## Data flow

```text
customer question
  -> semantic preplan + literal contract reconciliation
  -> negative scope / use-goal normalization
  -> category-scoped candidate expansion
  -> same-SKU subject and constraint verification
  -> deterministic goal-aware ordering
  -> grounded narrative validation
  -> category-aware context persistence and customer answer
```

Every product fact remains sourced from the database or same-SKU QA/evidence bundle. Semantic planning may classify intent and preferences, but it cannot select a SKU or create a fact.

## Error handling

- Invalid or unsupported semantic constraints remain fail-closed with a useful clarification.
- Missing people or coffee evidence must be stated as unknown; it must not be silently upgraded to suitability.
- No-match results must clear unrelated catalog cards and SKU context.
- A generic safety answer must remain available even when product identity is absent.
- A category-scoped ordinal with no matching category context must use the existing clarification response rather than guessing from another category.

## Tests and acceptance

Add focused unit/route regressions before implementation for:

1. Negated `配件` and `炉具` do not override a semantic cookware subject; a two-person cookware candidate with same-SKU people evidence is returned.
2. Coffee cookware recommendations expand and rank evidence-backed small/fast-boiling candidates, include `CW-C93` in the HTTP answer or result set, mention coffee/brewing or boiling purpose, and exclude frying-pan-first wording.
3. Generic tent alcohol-stove safety answers include the no-enclosed-space and ventilation boundary without requiring SKU.
4. A multi-category result resolves ordinals within the named category and never binds a waterware ordinal to a stove SKU.
5. Unsupported gifting marketing claims are not returned; direct evidence or a conservative unknown answer is returned instead.

Then run, against development only:

- focused pytest for recommendation contracts, customer-service route regressions, context, safety, and QA evidence;
- full `backend\\venv\\Scripts\\python.exe -m pytest -q`;
- real HTTP acceptance on `http://127.0.0.1:8001`, including the enterprise matrix and full regression runner;
- Graphify `update . --no-cluster` and `cluster-only . --no-label` from `D:\\CaiYan\\Image-Generation-feature-v5-graphify`.

Success requires zero pytest failures, HTTP 200/non-empty answers, correct category and SKU binding, grounded evidence metadata, and no unsupported marketing or internal-process wording in customer answers.
