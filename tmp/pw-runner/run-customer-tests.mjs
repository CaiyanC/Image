import { chromium } from 'playwright';
import fs from 'node:fs/promises';

const BASE = 'http://127.0.0.1:5275';
const OUT = new URL('./customer-test-results.jsonl', import.meta.url);
const START_ID = Number(process.env.START_ID || '1');
const END_ID = Number(process.env.END_ID || '999');
const APPEND = process.env.APPEND === '1';

const tests = [
  { id: 1, turns: ['800ml不粘单兵套锅有多重？'] },
  { id: 2, turns: ['800ml不粘单兵套锅容量多大？'] },
  { id: 3, turns: ['800ml不粘单兵套锅有什么核心卖点？'] },
  { id: 4, turns: ['800ml不粘单兵套锅怎么清洗保养？'] },
  { id: 5, turns: ['800ml不粘单兵套锅有什么禁止操作？'] },
  { id: 6, turns: ['800ml不粘单兵套锅怎么辨别正品？'] },
  { id: 7, turns: ['稳稳水袋是什么材质？'] },
  { id: 8, turns: ['稳稳水袋有多重？'] },
  { id: 9, turns: ['稳稳水袋适合哪些场景？'] },
  { id: 10, turns: ['稳稳水袋有质保吗？'] },
  { id: 11, turns: ['CW-C93 行山单锅容量是多少？'] },
  { id: 12, turns: ['CW-C93 行山单锅是什么材质？'] },
  { id: 13, turns: ['CS-B14 旋焰酒精炉多重？'] },
  { id: 14, turns: ['CS-G25 小金炉适合什么场景？'] },
  { id: 15, turns: ['CS-G25 小金炉容量是多少？如果没有就告诉我没有'] },
  { id: 16, turns: ['我一个人轻量徒步，推荐一款锅具'] },
  { id: 17, turns: ['两个人周末露营，想煮面烧水，推荐锅具和炉具'] },
  { id: 18, turns: ['家庭露营，想煎烤和煮汤，推荐更合适的产品组合'] },
  { id: 19, turns: ['高海拔低温环境，推荐什么气罐和炉具？'] },
  { id: 20, turns: ['新手第一次露营，推荐不容易踩坑的做饭套装'] },
  { id: 21, turns: ['CW-C94 和 CW-C93 哪个更适合单人徒步？'] },
  { id: 22, turns: ['CW-C83 和 CW-C93 容量、重量差别大吗？'] },
  { id: 23, turns: ['酒精炉和气罐炉分别适合什么人？'] },
  { id: 24, turns: ['230g高山气罐和450g气罐怎么选？'] },
  { id: 25, turns: ['800ml不粘单兵套锅有多重？', '那它适合几个人用？'] },
  { id: 26, turns: ['稳稳水袋是什么材质？', '它适合自驾露营吗？', '有质保吗？'] },
  { id: 27, turns: ['我要一个人徒步。', '帮我选锅具。', '再配一个燃料方案。'] },
  { id: 28, turns: ['推荐露营锅具。', '要轻一点。', '最好能两个人用。'] },
  { id: 29, turns: ['CW-C94 和 CW-C93 对比一下。', '如果只看重量选哪个？', '如果只看容量呢？'] },
  { id: 30, turns: ['推荐一个高海拔徒步做饭方案。', '为什么不是普通气罐？', '有什么安全注意事项？'] },
  { id: 31, turns: ['CW-C94 有什么卖点？', '那稳稳水袋呢？', '这两个能一起用于什么场景？'] },
  { id: 32, turns: ['我周末自驾露营。', '需要烧水、煮面、喝水。', '锅具、水具、燃料各推荐一个'] },
  { id: 33, turns: ['CS-B14 有哪些QA？', '如果QA库没有，就根据产品库回答。', '哪些信息是不确定的？'] },
  { id: 34, turns: ['推荐A类产品。', '要适合家庭露营。', '再给一个更便宜的备选'] },
  { id: 35, turns: ['用户说不粘锅不好清洗，客服怎么回复？'] },
  { id: 36, turns: ['用户说产品收到有划痕/破损，应该怎么回复？'] },
  { id: 37, turns: ['酒精炉能不能在帐篷里用？'] },
  { id: 38, turns: ['高山气罐能不能暴晒或靠近明火存放？'] },
  { id: 39, turns: ['我想找“轻量徒步烧水”的产品，有哪些？'] },
  { id: 40, turns: ['搜索高山气罐、露营燃料、低温燃烧气罐，分别能找到什么产品？'] },
];

function parseSse(text) {
  const compact = {
    answer: '',
    trace: null,
    meta: null,
    eventTypes: [],
  };
  for (const block of text.split(/\r?\n\r?\n/)) {
    const eventLine = block.split(/\r?\n/).find((line) => line.startsWith('event:'));
    const dataLines = block.split(/\r?\n/).filter((line) => line.startsWith('data:'));
    if (!eventLine || dataLines.length === 0) continue;
    const type = eventLine.replace(/^event:\s*/, '').trim();
    compact.eventTypes.push(type);
    const dataText = dataLines.map((line) => line.replace(/^data:\s*/, '')).join('\n');
    try {
      const event = { type, ...JSON.parse(dataText) };
      if (event.type === 'answer_delta') compact.answer += event.text || '';
      if (event.type === 'content') compact.answer += event.content || '';
      if (event.type === 'trace') {
        compact.trace = {
          trace_id: event.trace_id || '',
          conversation_id: event.conversation_id || '',
          agent_mode: event.agent_mode || '',
          intent: event.intent || '',
          result_skus: event.result_skus || [],
          llm_call_count: event.llm_call_count,
          hit_faq_fast_path: event.hit_faq_fast_path,
        };
      }
      if (event.type === 'meta') {
        compact.meta = {
          conversation_id: event.conversation_id || '',
          intent: event.intent || '',
          answer_type: event.answer_type || '',
          confidence: event.confidence || '',
          result_skus: Array.isArray(event.results) ? event.results.map((item) => item.sku).filter(Boolean).slice(0, 8) : [],
        };
      }
    } catch {
      // Ignore malformed events for this report.
    }
  }
  compact.answer = compact.answer.trim();
  return compact;
}

async function launch() {
  for (const channel of ['chrome', 'msedge', undefined]) {
    try {
      return await chromium.launch({ channel, headless: true });
    } catch (error) {
      if (channel === undefined) throw error;
    }
  }
}

async function login(page) {
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' });
  await page.locator('input[type="text"]').fill('admin');
  await page.locator('input[type="password"]').fill('admin123');
  await page.locator('button[type="submit"]').click();
  await page.waitForURL(/\/($|customer-service|products|history|profile)/, { timeout: 30000 }).catch(() => {});
  await page.goto(`${BASE}/customer-service`, { waitUntil: 'domcontentloaded' });
  const textarea = await page.waitForSelector('textarea', { timeout: 10000 }).catch(() => null);
  if (!textarea) {
    await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' });
    await page.evaluate(async () => {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: 'admin', password: 'admin123' }),
      });
      if (!response.ok) throw new Error(`login failed: ${response.status}`);
      const data = await response.json();
      localStorage.setItem('token', data.access_token);
      localStorage.setItem('user', JSON.stringify(data.user));
    });
    await page.goto(`${BASE}/customer-service`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('textarea', { timeout: 30000 });
  }
  await installSseCapture(page);
}

async function installSseCapture(page) {
  await page.evaluate(() => {
    if (window.__customerSseCaptureInstalled) return;
    window.__customerSseCaptureInstalled = true;
    window.__customerSseCaptures = [];
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (...args) => {
      const response = await originalFetch(...args);
      const rawUrl = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
      if (String(rawUrl).includes('/customer-service/ask-stream')) {
        const clone = response.clone();
        const record = { url: String(rawUrl), status: response.status, done: false, body: '', error: '' };
        window.__customerSseCaptures.push(record);
        clone.text().then((text) => {
          record.body = text;
          record.done = true;
        }).catch((error) => {
          record.error = error?.message || String(error);
          record.done = true;
        });
      }
      return response;
    };
  });
}

async function newConversation(page) {
  const button = page.locator('button', { hasText: /新|鏂/ }).first();
  await button.click().catch(async () => {
    await page.evaluate(() => {
      for (const key of Object.keys(localStorage)) {
        if (key.startsWith('customer-service:draft:')) localStorage.removeItem(key);
      }
    });
    await page.reload({ waitUntil: 'domcontentloaded' });
  });
  await page.waitForSelector('textarea');
}

async function askTurn(page, question) {
  const captureIndex = await page.evaluate(() => window.__customerSseCaptures?.length || 0);
  await page.locator('textarea').fill(question);
  await page.keyboard.press('Enter');
  await page.waitForFunction(
    (index) => {
      const captures = window.__customerSseCaptures || [];
      return captures.length > index && captures[index].done;
    },
    captureIndex,
    { timeout: 180000 },
  );
  const captured = await page.evaluate((index) => window.__customerSseCaptures[index], captureIndex);
  if (captured.error) throw new Error(captured.error);
  const body = captured.body || '';
  const parsed = parseSse(body);
  await page.waitForFunction(() => {
    const buttons = [...document.querySelectorAll('button')];
    return !buttons.some((button) => /处理|澶勭悊/.test(button.textContent || ''));
  }, null, { timeout: 180000 }).catch(() => {});
  return {
    question,
    status: captured.status,
    answer: parsed.answer,
    trace: parsed.trace,
    meta: parsed.meta,
    events: parsed.eventTypes,
  };
}

const browser = await launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const results = [];

try {
  if (!APPEND) await fs.writeFile(OUT, '', 'utf8');
  await login(page);
  for (const test of tests) {
    if (test.id < START_ID) continue;
    if (test.id > END_ID) continue;
    await newConversation(page);
    const turns = [];
    for (const question of test.turns) {
      const turn = await askTurn(page, question);
      turns.push(turn);
      console.log(JSON.stringify({
        id: test.id,
        turn: turns.length,
        intent: turn.trace?.intent || turn.meta?.intent || '',
        skus: turn.trace?.result_skus || [],
        llm: turn.trace?.llm_call_count,
        faq: turn.trace?.hit_faq_fast_path,
        answerHead: turn.answer.slice(0, 80),
      }));
    }
    const item = { id: test.id, turns };
    results.push(item);
    await fs.appendFile(OUT, `${JSON.stringify(item)}\n`, 'utf8');
  }
} finally {
  await browser.close();
}
