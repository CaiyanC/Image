import fs from 'node:fs'
import { randomUUID } from 'node:crypto'

const token = process.env.CUSTOMER_TOKEN
if (!token) {
  throw new Error('CUSTOMER_TOKEN is required')
}

const baseUrl = 'http://localhost:5275'
const endpoint = `${baseUrl}/api/customer-service/ask-stream`

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function ask(question, conversation_id = randomUUID()) {
  const started = Date.now()
  const payload = { question }
  if (conversation_id) {
    payload.conversation_id = conversation_id
  }
  const res = await fetch(endpoint, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
  const raw = await res.text()
  const elapsed_wall_ms = Date.now() - started
  const events = []
  let current = null
  for (const line of raw.split(/\r?\n/)) {
    if (line.startsWith('event: ')) {
      current = { event: line.slice(7), data: '' }
    } else if (line.startsWith('data: ') && current) {
      current.data += line.slice(6)
    } else if (line === '' && current) {
      try {
        current.json = JSON.parse(current.data)
      } catch {
        current.json = null
      }
      events.push(current)
      current = null
    }
  }
  const done = [...events].reverse().find((event) => event.event === 'done')?.json || null
  const trace = [...events].reverse().find((event) => event.event === 'trace')?.json || null
  const meta = [...events].reverse().find((event) => event.event === 'meta')?.json || null
  const error = [...events].reverse().find((event) => event.event === 'error')?.json || null
  const answer = events
    .filter((event) => event.event === 'content' || event.event === 'answer_delta')
    .map((event) => event.json?.content || event.json?.text || '')
    .join('')
  return {
    question,
    conversation_id: conversation_id || trace?.conversation_id || meta?.conversation_id || '',
    http_status: res.status,
    elapsed_wall_ms,
    done,
    meta,
    trace,
    error,
    answer,
    raw_length: raw.length,
  }
}

function metrics(values) {
  const n = values.length
  const mean = values.reduce((acc, value) => acc + value, 0) / n
  const min = Math.min(...values)
  const max = Math.max(...values)
  const variance = values.reduce((acc, value) => acc + (value - mean) ** 2, 0) / n
  return {
    n,
    mean_ms: Number(mean.toFixed(2)),
    min_ms: Number(min.toFixed(2)),
    max_ms: Number(max.toFixed(2)),
    stddev_ms: Number(Math.sqrt(variance).toFixed(2)),
  }
}

function compactMeasured(result) {
  return {
    question: result.question,
    trace_id: result.trace?.trace_id || '',
    total_ms: result.trace?.total_ms,
    first_token_ms: result.trace?.first_token_ms,
    prompt_chars: result.trace?.prompt_chars,
    llm_call_count: result.trace?.llm_call_count,
    intent: result.trace?.intent || result.meta?.intent || '',
    agent_mode: result.trace?.agent_mode || result.meta?.debug?.agent_mode || '',
    result_skus: result.trace?.result_skus || result.meta?.results?.map((item) => item.sku).filter(Boolean) || [],
    entered_semantic_retrieve: result.trace?.entered_semantic_retrieve,
    entered_hybrid_search: result.trace?.entered_hybrid_search,
    hit_faq_fast_path: result.trace?.hit_faq_fast_path,
    http_status: result.http_status,
    wall_ms: result.elapsed_wall_ms,
    error: result.error,
    answer: result.answer,
  }
}

async function runPerfScenario(name, runner) {
  const runs = []
  for (let index = 1; index <= 10; index += 1) {
    const result = await runner()
    runs.push(result)
    const measured = result.measured.trace || {}
    console.log(
      `[${name}] ${index}/10 total_ms=${measured.total_ms} first_token_ms=${measured.first_token_ms} llm=${measured.llm_call_count} trace=${measured.trace_id || ''}`,
    )
    await sleep(300)
  }
  return { name, runs }
}

const report = {
  generated_at: new Date().toISOString(),
  baseUrl,
  performance: [],
  faq_variants: [],
}

report.performance.push(
  await runPerfScenario('explicit_product_detail', async () => {
    const measured = await ask('旋焰酒精炉表面处理是什么', null)
    return {
      conversation_id: measured.trace?.conversation_id || measured.meta?.conversation_id || measured.conversation_id,
      measured,
    }
  }),
)

report.performance.push(
  await runPerfScenario('recommendation_first_turn', async () => {
    const measured = await ask('推荐一款适合2个人露营做饭的锅', null)
    return {
      conversation_id: measured.trace?.conversation_id || measured.meta?.conversation_id || measured.conversation_id,
      measured,
    }
  }),
)

report.performance.push(
  await runPerfScenario('entity_stack_energy_ring_fastpath', async () => {
    const setup = await ask('行山单锅容量是多少', null)
    const conversation_id = setup.trace?.conversation_id || setup.meta?.conversation_id || setup.conversation_id
    await sleep(200)
    const measured = await ask('这个聚能环是做什么的', conversation_id)
    return { conversation_id, setup, measured }
  }),
)

for (const question of ['怎么联系售后', '售后客服电话', '出了问题找谁', '有质量问题怎么办', '退换货怎么联系你们']) {
  const result = await ask(question, null)
  report.faq_variants.push(result)
  console.log(
    `[faq] ${question} status=${result.http_status} intent=${result.trace?.intent || result.meta?.intent || ''} mode=${result.trace?.agent_mode || result.meta?.debug?.agent_mode || ''} llm=${result.trace?.llm_call_count} error=${Boolean(result.error)}`,
  )
  await sleep(200)
}

for (const scenario of report.performance) {
  const values = scenario.runs.map((run) => Number(run.measured.trace?.total_ms)).filter(Number.isFinite)
  scenario.metrics = metrics(values)
  scenario.runs = scenario.runs.map((run, index) => ({
    index: index + 1,
    conversation_id: run.conversation_id,
    setup: run.setup ? compactMeasured(run.setup) : undefined,
    measured: compactMeasured(run.measured),
  }))
}

report.faq_variants = report.faq_variants.map((result) => ({
  question: result.question,
  conversation_id: result.conversation_id,
  http_status: result.http_status,
  error: result.error,
  trace_id: result.trace?.trace_id || '',
  total_ms: result.trace?.total_ms,
  first_token_ms: result.trace?.first_token_ms,
  llm_call_count: result.trace?.llm_call_count,
  intent: result.trace?.intent || result.meta?.intent || '',
  agent_mode: result.trace?.agent_mode || result.meta?.debug?.agent_mode || '',
  hit_faq_fast_path: result.trace?.hit_faq_fast_path,
  answer: result.answer,
  exposes_phone_like: /\b1[3-9]\d{9}\b|\d{3,4}[- ]?\d{7,8}|400[- ]?\d{3}[- ]?\d{4}/.test(result.answer),
}))

fs.writeFileSync('reports/perf_recalibration_and_faq_variants_5275_8000.json', JSON.stringify(report, null, 2), 'utf8')
console.log('REPORT reports/perf_recalibration_and_faq_variants_5275_8000.json')
console.log(
  JSON.stringify(
    {
      performance: report.performance.map((scenario) => ({
        name: scenario.name,
        metrics: scenario.metrics,
      })),
      faq: report.faq_variants.map((item) => ({
        question: item.question,
        status: item.http_status,
        intent: item.intent,
        mode: item.agent_mode,
        llm: item.llm_call_count,
        phone: item.exposes_phone_like,
      })),
    },
    null,
    2,
  ),
)
