const baseUrl = process.env.FRONTEND_BASE_URL || 'http://localhost:5275';
const username = process.env.CAIYAN_USERNAME || 'admin';
const password = process.env.CAIYAN_PASSWORD || 'admin123';

const questions = [
  '推荐一款适合2个人露营做饭的锅',
  '为什么推荐这个',
  '换一个推荐，不要刚才那个',
];

function parseSse(raw) {
  const events = [];
  for (const block of raw.split(/\n\n+/)) {
    const lines = block.split(/\r?\n/).filter(Boolean);
    if (!lines.length) continue;
    const eventLine = lines.find((line) => line.startsWith('event:'));
    const dataLines = lines.filter((line) => line.startsWith('data:'));
    if (!eventLine || !dataLines.length) continue;
    const type = eventLine.replace(/^event:\s*/, '').trim();
    const dataText = dataLines.map((line) => line.replace(/^data:\s*/, '')).join('\n');
    try {
      events.push({ type, ...JSON.parse(dataText) });
    } catch {
      events.push({ type, raw: dataText });
    }
  }
  return events;
}

function skusFromSources(sources) {
  const agentContext = (sources || []).find((item) => item && item.type === 'agent_context');
  if (agentContext?.result_skus?.length) return agentContext.result_skus;
  return [];
}

async function main() {
  const loginResponse = await fetch(`${baseUrl}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!loginResponse.ok) {
    throw new Error(`login failed: ${loginResponse.status} ${await loginResponse.text()}`);
  }
  const login = await loginResponse.json();
  const token = login.access_token;
  let conversationId = null;
  const turns = [];

  for (const question of questions) {
    const startedAt = new Date().toISOString();
    const response = await fetch(`${baseUrl}/api/customer-service/ask-stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ question, conversation_id: conversationId }),
    });
    const raw = await response.text();
    if (!response.ok) {
      throw new Error(`ask-stream failed: ${response.status} ${raw}`);
    }
    const events = parseSse(raw);
    const meta = [...events].reverse().find((event) => event.type === 'meta') || {};
    const answer = events
      .filter((event) => event.type === 'answer_delta')
      .map((event) => event.text || '')
      .join('')
      || events
        .filter((event) => event.type === 'content')
        .map((event) => event.content || '')
        .join('')
      || meta.answer
      || '';
    const trace = [...events].reverse().find((event) => event.type === 'trace') || {};
    conversationId = meta.conversation_id || conversationId;
    turns.push({
      question,
      started_at: startedAt,
      conversation_id: conversationId,
      message_id: meta.message_id || '',
      trace_id: meta.trace_id || '',
      answer,
      intent: meta.intent || '',
      agent_mode: meta.agent_mode || meta.debug?.agent_mode || '',
      result_skus: skusFromSources(meta.sources || []),
      trace,
      sources: meta.sources || [],
      raw_events: events,
    });
  }

  process.stdout.write(JSON.stringify({ baseUrl, conversation_id: conversationId, turns }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
