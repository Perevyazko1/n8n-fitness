// HouseWatch FB — сборщик постов из групп аренды Facebook на Mac пользователя (вьетнамский IP, его вход в FB).
// Новые посты шлёт в n8n (вебхук HouseWatch_FB); отбор, GPT и Telegram — в n8n.
//
// launchd дёргает скрипт каждые 2 мин (дёшево: проверка и выход). Поиск идёт, если с прошлого прошло ≥30 мин —
// поэтому после пробуждения Mac поиск стартует почти сразу, а после долгого сна прокрутка глубже (догон).
//
//   node collect.mjs --login   окно Chrome: войти в Facebook и закрыть окно (профиль ~/.housewatch-fb-profile)
//   node collect.mjs           тик launchd: искать, если пора (часы 8–23, интервал 30 мин)
//   node collect.mjs --force   искать сейчас, в любое время
//   node collect.mjs --dry     искать сейчас, без отправки в n8n и без записи «увиденного»
//
// Только чтение: ничего не пишет, не лайкает, в группы не вступает. Картинки/видео не грузит (меньше памяти).
// Не переносить профиль/cookies в Docker или на сервер: 13.11 FB счёл это кражей сессии и разлогинил.
import { chromium } from 'playwright';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const DIR = path.dirname(fileURLToPath(import.meta.url));
try {
  for (const line of fs.readFileSync(path.join(DIR, '.env'), 'utf8').split('\n')) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
    if (m && !(m[1] in process.env)) process.env[m[1]] = m[2].replace(/^['"]|['"]$/g, '');
  }
} catch { /* нет .env */ }

const ARGS = new Set(process.argv.slice(2));
const DATA = path.join(DIR, 'data');
fs.mkdirSync(DATA, { recursive: true });
const CFG = {
  webhook: process.env.HW_FB_WEBHOOK || '',
  token: process.env.HW_FB_TOKEN || '',
  profile: process.env.HW_FB_PROFILE || path.join(os.homedir(), '.housewatch-fb-profile'),
  headless: process.env.HW_FB_HEADLESS !== '0',
  stateFile: path.join(DATA, 'state.json'),
  lockFile: path.join(DATA, 'run.lock'),
  hours: (process.env.HW_FB_HOURS || '8-23').split('-').map(Number), // по часам Mac
  intervalMin: Number(process.env.HW_FB_INTERVAL_MIN || 30),
  scrolls: Number(process.env.HW_FB_SCROLLS || 3),       // 3 прокрутки ≈ последние 30–60 мин в группе на 90+ постов/день
  maxScrolls: Number(process.env.HW_FB_MAX_SCROLLS || 25), // потолок догона после сна/выключения (~6 ч)
  maxOpen: Number(process.env.HW_FB_MAX_OPEN || 15),     // обрезанных постов добрать по ссылке за прогон
  keepDays: 21,
};
// Группы аренды Нячанга (все открытые, вступать не нужно). Порядок — от самых живых.
const GROUPS = [
  { id: 'nhatrang.apartment.and.house', name: 'Nha Trang Apartment And House For Rent' },
  { id: 'canhonhatrang2', name: 'Cho Thuê Căn Hộ Nha Trang' },
  { id: 'chothuecanhonhatrangkhanhhoa', name: 'CHO THUÊ CĂN HỘ NHA TRANG' },
  { id: '2253829621529798', name: 'Nha Trang apartment for rent' },
  { id: 'khachsanvillahomestaynhatrang', name: 'НЯЧАНГ АРЕНДА КВАРТИР' },
  { id: '231515696145986', name: 'Нячанг Аренда Квартир' },
];

const log = (...a) => console.log(new Date().toISOString(), ...a);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const jitter = (a, b) => sleep(a + Math.random() * (b - a));
const loadState = () => { try { return JSON.parse(fs.readFileSync(CFG.stateFile, 'utf8')); } catch { return { seen: {}, loginAlertAt: 0, lastRunAt: 0 }; } };
const saveState = s => fs.writeFileSync(CFG.stateFile, JSON.stringify(s));

const clean = t => String(t || '')
  .replace(/\s*(Показать меньше|Показать перевод|Показать оригинал|Оцените этот перевод|See less|See translation)\s*/g, '\n')
  .replace(/…?\s*(Ещё|See more)\s*$/g, '')
  .replace(/\n{2,}/g, '\n').trim();
const truncated = t => /\s(Ещё|See more)\s*$/.test(String(t || '').trim());
const obviouslyNot = t => /(bán nhà|bán căn|bán đất|cần bán|продаю|продаётся|for sale)/i.test(t) || /^\s*(studio|студи)/i.test(t);
const loggedIn = async (ctx, page) => !/\/login|checkpoint/.test(page.url())
  && (await ctx.cookies('https://www.facebook.com')).some(c => c.name === 'c_user');

// Один прогон за раз: тики идут каждые 2 мин, а поиск длится 2–5 мин.
function lock() {
  try {
    const pid = Number(fs.readFileSync(CFG.lockFile, 'utf8'));
    if (pid && pid !== process.pid) { try { process.kill(pid, 0); return false; } catch { /* процесс умер — лок протух */ } }
  } catch { /* лока нет */ }
  fs.writeFileSync(CFG.lockFile, String(process.pid));
  return true;
}
const unlock = () => { try { fs.unlinkSync(CFG.lockFile); } catch {} };

async function launch(headless) {
  const ctx = await chromium.launchPersistentContext(CFG.profile, {
    channel: 'chrome', headless, viewport: headless ? { width: 1280, height: 900 } : null, locale: 'ru-RU',
  });
  if (headless) {
    // Текст постов есть и без медиа: режем картинки, видео и шрифты — меньше памяти и трафика.
    await ctx.route('**/*', r => ['image', 'media', 'font'].includes(r.request().resourceType()) ? r.abort() : r.continue());
  }
  return ctx;
}

async function readGroup(ctx, page, g, scrolls) {
  await page.goto(`https://www.facebook.com/groups/${g.id}/?sorting_setting=CHRONOLOGICAL`, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await jitter(4000, 6500);
  if (!(await loggedIn(ctx, page))) throw Object.assign(new Error('login required'), { login: true });
  const posts = new Map();
  for (let i = 0; i < scrolls; i++) {
    const batch = await page.evaluate(() => [...document.querySelectorAll('div[role=feed] > div')].map(d => {
      const link = [...d.querySelectorAll('a[href]')].map(a => a.href)
        .find(h => /\/groups\/[^/]+\/(posts|permalink)\/\d+/.test(h)) || '';
      const m = d.querySelector('[data-ad-rendering-role="story_message"], [data-ad-preview="message"]');
      return { link: link.split('?')[0], text: (m || d).innerText || '' };
    }));
    for (const p of batch) {
      const id = (p.link.match(/\/(?:posts|permalink)\/(\d+)/) || [])[1];
      if (id && p.text.length > 30 && !posts.has(id)) posts.set(id, { id, group: g.id, groupName: g.name, link: p.link, raw: p.text });
    }
    await page.mouse.wheel(0, 2600 + Math.random() * 900);
    await jitter(2200, 4200);
  }
  return [...posts.values()];
}

async function fullText(page, p) {
  await page.goto(p.link, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await jitter(3000, 5000);
  const more = page.locator('div[role=button]:text-is("Ещё"), div[role=button]:text-is("See more")');
  const n = Math.min(await more.count(), 3);
  for (let k = 0; k < n; k++) {
    const el = more.nth(k);
    if (await el.isVisible().catch(() => false)) { await el.click({ timeout: 1500 }).catch(() => {}); await sleep(600); }
  }
  return page.evaluate(() => {
    const m = document.querySelector('[data-ad-rendering-role="story_message"]') || document.querySelector('[data-ad-preview="message"]');
    return m ? m.innerText : '';
  });
}

async function send(body) {
  if (!CFG.webhook) throw new Error('HW_FB_WEBHOOK не задан (.env)');
  const r = await fetch(CFG.webhook, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-HW-Token': CFG.token },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`n8n ответил ${r.status}: ${(await r.text()).slice(0, 200)}`);
}

async function loginMode() {
  log('Открываю Chrome для входа в Facebook. Войдите, потом закройте окно.');
  const ctx = await launch(false);
  const page = ctx.pages()[0] || await ctx.newPage();
  await page.goto('https://www.facebook.com/', { waitUntil: 'domcontentloaded' });
  // На macOS закрытие окна не завершает Chrome — ждём, пока закроют последнюю вкладку, и закрываем сами.
  await new Promise(r => {
    ctx.on('close', r);
    const check = () => setTimeout(() => { if (!ctx.pages().length) ctx.close().then(r, r); }, 500);
    ctx.on('page', p => p.on('close', check));
    page.on('close', check);
  });
  log('Окно закрыто, вход сохранён в профиле', CFG.profile);
}

async function search(st, { dry }) {
  // Догон: чем дольше пауза (сон, выключение), тем глубже прокрутка.
  const gapMin = st.lastRunAt ? (Date.now() - st.lastRunAt) / 60000 : CFG.intervalMin;
  const scrolls = Math.min(CFG.maxScrolls, Math.max(CFG.scrolls, Math.round(CFG.scrolls * gapMin / CFG.intervalMin)));
  log(`поиск: пауза ${Math.round(gapMin)} мин, прокруток ${scrolls}`);
  const ctx = await launch(CFG.headless);
  let page = ctx.pages()[0] || await ctx.newPage();
  const fresh = [];
  try {
    for (const g of GROUPS) {
      try {
        const got = await readGroup(ctx, page, g, scrolls);
        const nw = got.filter(p => !st.seen[p.id]);
        log(`${g.id}: постов ${got.length}, новых ${nw.length}`);
        fresh.push(...nw);
      } catch (e) {
        if (e.login) throw e;
        log(`${g.id}: ошибка ${e.message.split('\n')[0]}`);
        if (/crash|closed/i.test(e.message)) { await page.close().catch(() => {}); page = await ctx.newPage(); }
      }
      await jitter(3000, 7000);
    }
    let opened = 0;
    for (const p of fresh) {
      p.text = clean(p.raw);
      if (truncated(p.raw) && !obviouslyNot(p.text) && opened < CFG.maxOpen) {
        opened++;
        try { const t = clean(await fullText(page, p)); if (t.length > p.text.length) p.text = t; } catch (e) { log(`добор ${p.id}: ${e.message.split('\n')[0]}`); }
        await jitter(2000, 4000);
      }
      p.truncated = truncated(p.raw) && p.text.length <= clean(p.raw).length;
      delete p.raw;
    }
    log(`новых всего ${fresh.length}, добрано полных текстов ${opened}`);
  } catch (e) {
    if (!e.login) throw e;
    log('Facebook просит войти заново: node collect.mjs --login');
    if (!dry && Date.now() - (st.loginAlertAt || 0) > 12 * 3600e3) {
      try { await send({ type: 'login_required' }); st.loginAlertAt = Date.now(); } catch (err) { log(err.message); }
    }
    st.lastRunAt = Date.now(); // без входа не долбим FB каждые 2 минуты
    if (!dry) saveState(st);
    return;
  } finally {
    await ctx.close();
  }
  if (dry) { for (const p of fresh) console.log('\n#', p.link, '\n', p.text.slice(0, 300)); return; }
  if (fresh.length) {
    await send({ type: 'posts', run_at: new Date().toISOString(), posts: fresh });
    log(`отправлено в n8n: ${fresh.length}`);
  }
  const now = Date.now();
  for (const p of fresh) st.seen[p.id] = now;
  for (const [id, t] of Object.entries(st.seen)) if (now - t > CFG.keepDays * 86400e3) delete st.seen[id];
  st.lastRunAt = now;
  saveState(st);
}

async function tick() {
  const dry = ARGS.has('--dry'), force = ARGS.has('--force') || dry;
  const st = loadState();
  if (!force) {
    const h = new Date().getHours();
    if (h < CFG.hours[0] || h >= CFG.hours[1]) return;                          // ночь — молча выходим
    if (Date.now() - (st.lastRunAt || 0) < CFG.intervalMin * 60000) return;     // ещё рано
  }
  if (!lock()) return;                                                          // прошлый поиск ещё идёт
  try { await search(st, { dry }); } finally { unlock(); }
}

(ARGS.has('--login') ? loginMode() : tick()).catch(e => { log('ОШИБКА', e.stack || e.message); process.exitCode = 1; });
