// Замеры сайта для дизайн-проверки. node audit.js <url> <outdir>
// Нужен Node 22 и Chrome. puppeteer-core ставится рядом: npm i puppeteer-core
// puppeteer-core ставится рядом со скриптом: npm i puppeteer-core (из папки scripts).
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');

const url = process.argv[2];
const out = process.argv[3] || 'shots/site';
const CHROME = process.env.CHROME_PATH || '/usr/bin/google-chrome';
if (!url) {
  console.error('audit.js: не указан адрес.\n  node audit.js <url|файл.html> [папка]');
  process.exit(2);
}
fs.mkdirSync(out, { recursive: true });

const collect = () => {
  const px = v => Math.round(parseFloat(v) || 0);
  const pick = el => el ? getComputedStyle(el) : null;
  const visible = el => {
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) return false;
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity) === 0) return false;
    return true;
  };
  const uniq = (arr) => {
    const seen = new Set();
    return arr.filter(e => {
      const k = (e.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 80) + '|' + Math.round(e.getBoundingClientRect().width);
      if (!k || seen.has(k)) return false;
      seen.add(k); return true;
    });
  };
  const info = (el, extra = {}) => {
    if (!el) return null;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return Object.assign({
      tag: el.tagName.toLowerCase(),
      text: (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 90),
      font: s.fontFamily.split(',')[0].replace(/["']/g, ''),
      size: px(s.fontSize), weight: s.fontWeight, lh: px(s.lineHeight),
      color: s.color, bg: s.backgroundColor, align: s.textAlign,
      width: Math.round(r.width), x: Math.round(r.x), y: Math.round(r.y),
      radius: s.borderRadius, shadow: s.boxShadow === 'none' ? '' : s.boxShadow,
      transform: s.textTransform, style: s.fontStyle, letter: s.letterSpacing
    }, extra);
  };
  const result = { url: location.href, title: document.title, viewport: innerWidth };
  result.h1 = uniq([...document.querySelectorAll('h1')].filter(visible)).map(e => info(e));
  result.h2 = uniq([...document.querySelectorAll('h2')].filter(visible)).slice(0, 8).map(e => info(e));
  result.h3 = uniq([...document.querySelectorAll('h3')].filter(visible)).slice(0, 8).map(e => info(e));
  result.p = uniq([...document.querySelectorAll('p')].filter(e => visible(e) && (e.textContent || '').trim().length > 40))
    .slice(0, 8).map(e => info(e, { chars: (e.textContent || '').trim().replace(/\s+/g, ' ').length,
      justify: getComputedStyle(e).textAlign }));
  result.buttons = [...document.querySelectorAll('a,button,[role=button]')]
    .filter(e => visible(e) && (() => { const s = getComputedStyle(e); return s.backgroundColor !== 'rgba(0, 0, 0, 0)' || s.borderWidth !== '0px'; })())
    .slice(0, 12).map(e => info(e, { padding: getComputedStyle(e).padding, border: getComputedStyle(e).borderWidth }));
  result.nav = uniq([...document.querySelectorAll('nav a, header a')].filter(visible)).slice(0, 10).map(e => info(e));
  // палитра: цвета фона и текста у крупных блоков
  const colorCount = {};
  const chromatic = {};
  document.querySelectorAll('body *').forEach(e => {
    const s = getComputedStyle(e);
    const r = e.getBoundingClientRect();
    const area = Math.max(1, Math.round(r.width * r.height));
    const m = c => c && c.match(/rgba?\((\d+), (\d+), (\d+)(?:, ([\d.]+))?/);
    const add = (c, weight) => {
      if (!c || c === 'rgba(0, 0, 0, 0)' || c === 'transparent') return;
      colorCount[c] = (colorCount[c] || 0) + weight;
      const mm = m(c);
      if (mm) {
        const R = +mm[1], G = +mm[2], B = +mm[3];
        if (Math.max(R, G, B) - Math.min(R, G, B) > 18) chromatic[c] = (chromatic[c] || 0) + weight;
      }
    };
    if (s.backgroundColor !== 'rgba(0, 0, 0, 0)') add(s.backgroundColor, area);
    if (s.color && (e.childElementCount === 0)) add(s.color, area * 0.25);
  });
  const byArea = o => Object.entries(o).sort((a, b) => b[1] - a[1]).slice(0, 12).map(([c, a]) => [c, Math.round(a / 1000)]);
  result.colors = byArea(colorCount);
  result.chromatic = byArea(chromatic);
  // контейнер: самая частая ширина крупных блоков
  const widths = {};
  document.querySelectorAll('section, main > div, .container, [class*=container]').forEach(e => {
    const w = Math.round(e.getBoundingClientRect().width);
    if (w > 300 && w < innerWidth - 20) widths[w] = (widths[w] || 0) + 1;
  });
  result.containerWidths = Object.entries(widths).sort((a, b) => b[1] - a[1]).slice(0, 6);
  // секции и отступы между ними
  result.sections = [...document.querySelectorAll('section')].slice(0, 14).map(e => {
    const s = getComputedStyle(e), r = e.getBoundingClientRect();
    return { y: Math.round(r.y + scrollY), h: Math.round(r.height), pt: px(s.paddingTop), pb: px(s.paddingBottom),
      bg: s.backgroundColor, label: (e.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 60) };
  });
  // радиуcы и тени — уникальные
  const radii = {}, shadows = {};
  document.querySelectorAll('*').forEach(e => {
    const s = getComputedStyle(e);
    if (s.borderRadius !== '0px') radii[s.borderRadius] = (radii[s.borderRadius] || 0) + 1;
    if (s.boxShadow !== 'none') shadows[s.boxShadow.slice(0, 60)] = (shadows[s.boxShadow.slice(0, 60)] || 0) + 1;
  });
  result.radii = Object.entries(radii).sort((a, b) => b[1] - a[1]).slice(0, 10);
  result.shadows = Object.entries(shadows).sort((a, b) => b[1] - a[1]).slice(0, 10);
  result.docHeight = document.documentElement.scrollHeight;
  return result;
};

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-gpu', '--hide-scrollbars', '--force-device-scale-factor=1']
  });
  const report = {};
  for (const [name, width, height] of [['desktop', 1440, 900], ['mobile', 390, 844]]) {
    const page = await browser.newPage();
    await page.setViewport({ width, height, deviceScaleFactor: 1 });
    let loaded = true;
    try {
      await page.goto(url, { waitUntil: 'networkidle2', timeout: 45000 });
    } catch (e) {
      loaded = false;
      try { await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 }); loaded = true; }
      catch (e2) { console.error(`audit.js: страницу не удалось открыть (${name}): ${e2.message}`); }
    }
    await new Promise(r => setTimeout(r, 2500));
    await page.evaluate(() => { window.scrollTo(0, document.body.scrollHeight); });
    await new Promise(r => setTimeout(r, 1500));
    await page.evaluate(() => window.scrollTo(0, 0));
    await new Promise(r => setTimeout(r, 800));
    await page.screenshot({ path: path.join(out, `${name}-first.png`) });
    try {
      await page.screenshot({ path: path.join(out, `${name}-full.png`), fullPage: true });
    } catch (e) {}
    if (!loaded) { await page.close(); continue; }
    const got = await page.evaluate(collect);
    // Пустой замер опаснее ошибки: check.py примет его за страницу без заголовков.
    if (!got.docHeight || got.docHeight <= 100) {
      console.error(`audit.js: страница открылась, но ничего не отдала (${name}): проверь адрес и что файл существует.`);
      await page.close();
      continue;
    }
    report[name] = got;
    await page.close();
  }
  // тексты страницы для оценки иерархии и длины строк
  await browser.close();
  if (!report.desktop) {
    console.error('audit.js: замер не сделан — measure.json не записан.');
    process.exit(3);
  }
  fs.writeFileSync(path.join(out, 'measure.json'), JSON.stringify(report, null, 2));
  console.log('готово:', out, '—', path.join(out, 'measure.json'));
})();
