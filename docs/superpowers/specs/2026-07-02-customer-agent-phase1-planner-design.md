# Customer Agent Phase 1 Planner Design

## Goal

Upgrade the customer-service agent from direct mixed routing into a safer Phase 1 pipeline:

```text
Soft Router / Planner
-> existing executor paths
-> evidence binding
-> answer composer
-> answer guard
-> timing/debug output
```

This phase is intentionally narrow. It should reduce answer drift and wrong-route failures without rewriting recommendation, RAG, comparison, or QA subsystems.

## Non-Goals

- Do not introduce a public `comparison_recommendation` answer type in Phase 1.
- Do not replace existing recommendation ranking, compare fast paths, product QA fast paths, or MINT normalization.
- Do not rebuild embeddings, import knowledge, or depend on production DB changes.
- Do not split a large executor/composer/guard module set yet. Phase 1 may drive existing paths through planner tasks.
- Do not publish production automatically after implementation.

## Files and Boundaries

### New File

`backend/app/services/customer_agent_planner_service.py`

Responsibilities:

- Soft Router / Planner.
- Deterministic route correction.
- Routing conflict detection.
- Plan JSON generation.
- Task list generation.
- `debug.plan` payload generation.
- Planner timing payload.
- Safe fallback to existing behavior when the planner cannot classify.

### Existing Files

`backend/app/services/customer_agent_intent_service.py`

Keep current responsibilities:

- Existing intent parsing.
- SKU and product mention parsing.
- Recommendation filters and product scope helpers.
- Product field, QA, KB, and compare helpers.

Do not move the full Planner into this file.

`backend/app/services/customer_service_service.py`

Keep as orchestration entry:

- Call existing intent service.
- Call planner service.
- Route planner tasks into existing executor paths.
- Attach `debug.plan`, `debug.timing`, and `answer_metadata.timing`.
- Run Answer Guard on every final result, including fast paths.

Do not turn this file into a complex planner implementation.

## Planner Output

The planner returns a dict with at least:

```json
{
  "primary_intent": "",
  "answer_type": "",
  "tasks": [],
  "product_ref": "",
  "sku": "",
  "requested_field": "",
  "scenario": "",
  "constraints": [],
  "needs_clarification": false,
  "routing_conflict": false,
  "confidence": "low"
}
```

Recommended additional fields:

```json
{
  "field_only": false,
  "must_return_products": false,
  "must_compare_both_products": false,
  "must_make_choice": false,
  "source": "",
  "fallback_reason": ""
}
```

## Planner Trigger Policy

The planner is deterministic-first. It should correct obvious wrong routes without forcing all traffic through new logic.

Planner must run for:

- Fuzzy product recommendation questions, such as `一个人徒步，买什么产品`.
- Product-name or alias plus field questions, such as `瓦片烤盘尺寸是什么`.
- Catalog count/list questions, such as `我们产品库有多少套锅`.
- Compare plus choice questions, such as `行山单锅和激川单锅的区别是什么，我想两个人吃饱应该选哪个`.
- Multi-intent questions where a field/detail task and recommendation task coexist.
- Cases where deterministic routing appears inconsistent with lexical signals.

## Fast Path Policy

Fast paths may remain fast, but every final answer must pass Answer Guard.

Examples:

- Explicit SKU plus explicit field can use deterministic lookup first, but guard must verify the field was answered.
- Purchase-channel questions can use FAQ/fast path, but guard must verify the answer is about purchase channels.
- QA fast path can answer directly, but guard must verify the answer did not become a generic product introduction.
- MINT normalization remains before lookup, but normalized SKU answers still pass guard.

## Product Field Classification

Field questions split into two classes.

### A. Explicit SKU + Explicit Field

Examples:

- `CW-K03-37 能不能装冷水？`
- `CW-C83 能不能用酒精炉？`

These may use deterministic/fast path first, then Answer Guard.

### B. Product Name/Alias + Explicit Field

Examples:

- `瓦片烤盘尺寸是什么`
- `瓦片烤盘多大`
- `瓦片烤盘规格是什么`
- `瓦片烤盘直径是多少`

These must trigger `product_field` planning or `routing_conflict` correction if the old route selects recommendation/generic knowledge.

Expected plan shape:

```json
{
  "primary_intent": "product_field",
  "answer_type": "product_detail",
  "product_ref": "瓦片烤盘",
  "requested_field": "尺寸",
  "field_only": true
}
```

If no field evidence exists, the answer must say:

```text
当前资料里没有找到瓦片烤盘的明确尺寸。
```

It must not answer with selling points, recommendation reasons, or generic product introduction.

## Routing Conflict Rules

Pre-answer planner conflicts:

1. Question contains field words, but deterministic route chooses recommendation or generic knowledge.
2. Question contains catalog/count/list wording, but route does not choose structured catalog query.
3. Question requires compare plus choice, but route lacks compare/recommendation-decision tasks.

Post-answer guard conflicts:

4. Question is recommendation-like and `must_return_products=true`, but final answer contains no product name or SKU.

For post-answer conflict 4, guard must trigger deterministic recommendation answer rebuild where possible. It must not return a bare selling-point sentence.

## Catalog Count / Product Catalog Query

Questions such as:

- `我们产品库有多少套锅？`
- `有哪些套锅？`
- `产品库里有多少锅具？`

must use structured product catalog queries.

They must not:

- Use vector topK as total count.
- Let the LLM guess counts.
- Answer `当前知识库中只有2套` based on retrieved snippets.

If no public `catalog_count` answer type exists yet, Phase 1 may reuse `query_products` or the closest existing compatible type, but:

- `debug.plan.primary_intent = "catalog_count"`
- `answer_metadata.source = "product_catalog_structured_query"`

## Compare + Choice

User question:

```text
行山单锅和激川单锅的区别是什么，我想两个人吃饱应该选哪个
```

Public result:

- `answer_type = "comparison"`

Internal planner:

```json
{
  "primary_intent": "product_compare_recommendation",
  "answer_type": "comparison",
  "tasks": [
    {
      "type": "product_compare",
      "products": ["行山单锅", "激川单锅"],
      "compare_dimensions": ["容量", "适用人数", "重量", "材质", "场景", "优缺点"]
    },
    {
      "type": "knowledge_evidence_lookup",
      "products": ["行山单锅", "激川单锅"],
      "source": "file_knowledge_base"
    },
    {
      "type": "recommendation_decision",
      "scenario": "两个人吃饱",
      "constraints": ["两人", "容量够", "户外吃饭"]
    }
  ],
  "must_compare_both_products": true,
  "must_make_choice": true
}
```

The final answer must include:

- `行山单锅`
- `激川单锅`
- The differences.
- Which product is better for two people eating enough.
- Reasons for that choice.

If capacity/person evidence is missing, the answer must explicitly say the evidence is insufficient and avoid inventing capacity.

## Evidence Priority

For field, compare, and choice tasks, prefer:

1. Product structured fields.
2. Same-product file knowledge.
3. Same-product KB.
4. Same-product QA.
5. Product text, selling points, and usage text.
6. Vector snippets only as supporting context, never as sole source for structured counts.

## Answer Guard

All final answers pass guard, including fast paths.

Guard checks:

- `recommendation`: if `must_return_products=true`, answer must contain product name or SKU and a recommendation reason.
- `product_field`: if `field_only=true`, answer must answer the requested field or explicitly state missing field evidence.
- `catalog_count`: answer must be backed by structured catalog query source.
- `comparison`: if `must_compare_both_products=true`, answer must mention both products.
- `comparison`: if `must_make_choice=true`, answer must include a clear choice or explicit evidence-insufficient decision.
- Purchase channel: answer must answer channel/buying route, not product recommendation.
- QA fast path: answer must answer the QA intent, not generic product introduction.

Guard should first repair via deterministic rebuild when possible. If repair is impossible, it should return a safe evidence-insufficient answer instead of a wrong-route answer.

## Timing

Attach timing to both:

- `answer_metadata.timing`
- `debug.timing`

Use `perf_counter` / monotonic timing.

Fields:

```json
{
  "total_duration_ms": 0,
  "planner_duration_ms": 0,
  "retrieval_duration_ms": 0,
  "executor_duration_ms": 0,
  "llm_duration_ms": 0,
  "llm_call_count": 0,
  "composer_duration_ms": 0,
  "guard_duration_ms": 0
}
```

If a stage does not run, fill `0` or `null`.

## Phase 1 Acceptance Cases

### Recommendation

```text
一个人徒步，买什么产品
```

Expected:

- Planner identifies recommendation.
- Final answer includes product name/SKU.
- Final answer includes recommendation reason.
- It does not return only a generic selling point.

### Product Field

```text
瓦片烤盘尺寸是什么
```

Expected:

- `debug.plan.primary_intent = "product_field"`
- `answer_type = "product_detail"`
- `requested_field = "尺寸"`
- Answer contains the dimension or an explicit missing-field statement.
- Answer does not become product selling points/recommendation.

### Catalog Count

```text
我们产品库有多少套锅
```

Expected:

- `debug.plan.primary_intent = "catalog_count"`
- `answer_metadata.source = "product_catalog_structured_query"`
- Count/list comes from structured product catalog query.
- No vector topK count or guessed number.

### Compare + Choice

```text
行山单锅和激川单锅的区别是什么，我想两个人吃饱应该选哪个
```

Expected:

- `answer_type = "comparison"`
- `debug.plan.primary_intent = "product_compare_recommendation"`
- tasks include `product_compare`, `knowledge_evidence_lookup`, `recommendation_decision`
- Answer includes both product names, differences, choice, and reasons.
- No invented capacity/person evidence.

## Regression Coverage

Must not regress:

- case36
- case44
- case59
- case71
- N065
- N012
- QA fast path
- MINT SKU normalization
- clarification slot carryover
- auth TTL behavior

## Deployment

Implementation should push to `origin/dev` only. Production publication is a separate explicit step.
