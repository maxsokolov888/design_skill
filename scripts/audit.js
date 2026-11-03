// Замеры сайта для дизайн-проверки. node audit.js <url> <outdir>
// Нужен Node 22 и Chrome. puppeteer-core ставится рядом: npm i puppeteer-core
// puppeteer-core ставится рядом со скриптом: npm i puppeteer-core (из папки scripts).
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');
const { prepare } = require(path.join(__dirname, 'prepare.js'));

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
  // служебные плашки конструкторов (Tilda, Wix, Taplink…) — не часть дизайна сайта
  const service = el => !!el.closest('.t-tildalabel, #tildacopy, [class*=tildalabel], a[href*="tilda.cc"], a[href*="tilda.ru"], #WIX_ADS, [class*=made-with]');
  const visible = el => {
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) return false;
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity) === 0) return false;
    if (service(el)) return false;
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
  // Уникальный CSS-селектор элемента: по id, иначе цепочка tag:nth-of-type до ближайшего id.
  const selOf = el => {
    if (!el || el.nodeType !== 1) return '';
    const parts = [];
    let e = el;
    while (e && e.nodeType === 1 && e !== document.documentElement) {
      if (e.id && /^[A-Za-z][\w-]*$/.test(e.id) && document.querySelectorAll('#' + e.id).length === 1) {
        parts.unshift('#' + e.id); break;
      }
      let i = 1, sib = e;
      while ((sib = sib.previousElementSibling)) if (sib.tagName === e.tagName) i++;
      parts.unshift(e.tagName.toLowerCase() + ':nth-of-type(' + i + ')');
      e = e.parentElement;
    }
    return parts.join(' > ');
  };
  // Рамка элемента в координатах документа (не окна).
  const boxOf = el => {
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.left + scrollX), y: Math.round(r.top + scrollY), w: Math.round(r.width), h: Math.round(r.height) };
  };
  const parseC = c => { const m = (c || '').match(/rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?/); return m ? [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]] : null; };
  // Фактический фон под текстом: идём вверх по предкам до непрозрачного фона.
  // Если по дороге встречается картинка/видео/фон-изображение — фон неизвестен (null).
  const bgUnder = el => {
    let stack = [];
    for (let p = el; p; p = p.parentElement) {
      const s = getComputedStyle(p);
      if (s.backgroundImage && s.backgroundImage !== 'none') return null;
      const c = parseC(s.backgroundColor);
      if (c && c[3] > 0) { stack.push(c); if (c[3] >= 0.99) break; }
    }
    // под текстом может лежать соседний слой с картинкой (обложки Tilda): проверяем по точке
    let r = el.getBoundingClientRect();
    if (r.top < 0 || r.bottom > innerHeight) { window.scrollTo(0, Math.max(0, r.top + scrollY - 200)); r = el.getBoundingClientRect(); }
    const cx = r.left + Math.min(r.width / 2, 40), cy = r.top + Math.min(r.height / 2, 20);
    if (cy >= 0 && cy < innerHeight && cx >= 0 && cx < innerWidth) {
      const under = document.elementsFromPoint(cx, cy);
      const idx = under.indexOf(el);
      for (const u of under.slice(Math.max(0, idx))) {
        if (el.contains(u) && u !== el) continue;
        if (u.contains(el)) continue;
        const s = getComputedStyle(u);
        if (/^(IMG|VIDEO|CANVAS|IFRAME|PICTURE)$/.test(u.tagName) || (s.backgroundImage && s.backgroundImage !== 'none')) return null;
        const c = parseC(s.backgroundColor);
        if (c && c[3] >= 0.99) break;
      }
    }
    let base = [255, 255, 255];
    for (let i = stack.length - 1; i >= 0; i--) {
      const [r2, g, b, a] = stack[i];
      base = [r2 * a + base[0] * (1 - a), g * a + base[1] * (1 - a), b * a + base[2] * (1 - a)];
    }
    return base.map(Math.round);
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
      transform: s.textTransform, style: s.fontStyle, letter: s.letterSpacing,
      h: Math.round(r.height), sel: selOf(el), box: boxOf(el)
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
    if (service(e)) return;
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
  let secEls = [...document.querySelectorAll('section')];
  const recs = [...document.querySelectorAll('#allrecords .t-rec, .t-records > .t-rec')]; // Tilda
  if (recs.length > secEls.length) secEls = recs;
  secEls = secEls.filter(e => e.getBoundingClientRect().height > 40 && getComputedStyle(e).display !== 'none' && getComputedStyle(e).position !== 'fixed');
  result.sections = secEls.slice(0, 30).map(e => {
    const s = getComputedStyle(e), r = e.getBoundingClientRect();
    return { y: Math.round(r.y + scrollY), h: Math.round(r.height), pt: px(s.paddingTop), pb: px(s.paddingBottom),
      bg: s.backgroundColor, label: (e.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 60), sel: selOf(e), box: boxOf(e) };
  });
  // радиуcы и тени — уникальные
  const radii = {}, shadows = {};
  document.querySelectorAll('body *').forEach(e => {
    if (service(e) || e.getBoundingClientRect().width === 0) return;
    const s = getComputedStyle(e);
    if (s.borderRadius !== '0px') radii[s.borderRadius] = (radii[s.borderRadius] || 0) + 1;
    if (s.boxShadow !== 'none') shadows[s.boxShadow.slice(0, 60)] = (shadows[s.boxShadow.slice(0, 60)] || 0) + 1;
  });
  result.radii = Object.entries(radii).sort((a, b) => b[1] - a[1]).slice(0, 10);
  result.shadows = Object.entries(shadows).sort((a, b) => b[1] - a[1]).slice(0, 10);
  // Все видимые текстовые узлы: кегль, цвет, фон под ними, рамка и селектор.
  // По ним check.py ищет мелкий и бледный текст и ставит кружок точно на элемент.
  const texts = [];
  document.querySelectorAll('body *').forEach(el => {
    if (texts.length >= 600) return;
    if (/^(SCRIPT|STYLE|NOSCRIPT|SVG|PATH|OPTION|TEMPLATE)$/i.test(el.tagName)) return;
    const own = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim().replace(/\s+/g, ' ');
    if (own.length < 2) return;
    if (!visible(el)) return;
    const s = getComputedStyle(el);
    const tc = parseC(s.color);
    if (!tc || tc[3] === 0) return;
    const bg = bgUnder(el);
    let col = tc.slice(0, 3);
    if (bg && tc[3] < 1) col = col.map((v, i) => Math.round(v * tc[3] + bg[i] * (1 - tc[3])));
    let op = 1; for (let p = el; p; p = p.parentElement) op *= parseFloat(getComputedStyle(p).opacity);
    if (op < 0.2) return;
    const link = el.closest('a,button,[role=button]');
    // служебные плашки конструктора (Tilda) — не часть дизайна сайта
    if (service(el)) return;
    texts.push({ el, full: (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 120), tag: el.tagName.toLowerCase(), text: own.slice(0, 90), size: px(s.fontSize), weight: +s.fontWeight || 400,
      lh: px(s.lineHeight), color: 'rgb(' + col.join(', ') + ')', bg: bg ? 'rgb(' + bg.join(', ') + ')' : null,
      opacity: Math.round(op * 100) / 100, link: !!link, transform: s.textTransform, align: s.textAlign,
      sel: selOf(el) });
  });
  // рамки считаем при прокрутке 0: так fixed-шапка получает свои настоящие координаты
  window.scrollTo(0, 0);
  const onPage = b => b.w > 0 && b.h > 0 && b.x < innerWidth && b.x + b.w > 0 && b.y + b.h > 0;
  texts.forEach(t => { t.box = boxOf(t.el); delete t.el; });
  result.texts = texts.filter(t => onPage(t.box));
  // Кнопки целиком: высота, ширина, подпись.
  result.buttonsAll = [...document.querySelectorAll('a,button,[role=button],input[type=submit]')]
    .filter(e => visible(e) && !service(e)).map(e => {
      const s = getComputedStyle(e);
      const filled = s.backgroundColor !== 'rgba(0, 0, 0, 0)' || (parseFloat(s.borderTopWidth) > 0 && parseFloat(s.borderBottomWidth) > 0);
      const icon = !(e.textContent || '').trim() && !!e.querySelector('svg,img');
      return { text: (e.textContent || e.value || e.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 60),
        filled, icon, size: px(s.fontSize), inText: !!e.closest('p,li') && !filled, sel: selOf(e), box: boxOf(e) };
    }).filter(b => onPage(b.box)).slice(0, 120);
  // Что вылезает за правый край окна (горизонтальная прокрутка).
  result.scrollWidth = document.documentElement.scrollWidth;
  const wide = [];
  if (document.documentElement.scrollWidth > innerWidth + 2) {
    document.querySelectorAll('body *').forEach(e => {
      if (wide.length > 40) return;
      const r = e.getBoundingClientRect();
      if (r.right > innerWidth + 2 && r.width > 0 && r.height > 8 && visible(e)) {
        const s = getComputedStyle(e);
        if (s.position === 'fixed') return;
        // только самый внешний виновник
        const par = e.parentElement && e.parentElement.getBoundingClientRect();
        if (par && par.right > innerWidth + 2 && e.parentElement !== document.body) return;
        wide.push({ tag: e.tagName.toLowerCase(), text: (e.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 60), right: Math.round(r.right), sel: selOf(e), box: boxOf(e) });
      }
    });
  }
  result.overflow = wide;
  result.docHeight = document.documentElement.scrollHeight;
  return result;
};

// Текст на фото или градиенте: цвет фона под ним снимаем с картинки.
// Прячем сам текст, снимаем его рамку, берём медианный цвет пикселей.
async function photoBg(page, texts) {
  const todo = texts.filter(t => !t.bg && t.box && t.box.w > 4 && t.box.h > 4).slice(0, 40);
  for (const t of todo) {
    try {
      const ok = await page.evaluate(sel => {
        const el = document.querySelector(sel); if (!el) return false;
        el.setAttribute('data-ds-probe', '1');
        if (!document.getElementById('__ds_probe')) {
          const st = document.createElement('style'); st.id = '__ds_probe';
          st.textContent = '[data-ds-probe],[data-ds-probe] *{color:transparent!important;text-shadow:none!important;-webkit-text-stroke:0!important}';
          document.head.appendChild(st);
        }
        return true;
      }, t.sel);
      if (!ok) continue;
      const b = t.box;
      const shot = await page.screenshot({ encoding: 'base64', captureBeyondViewport: true,
        clip: { x: Math.max(0, b.x), y: Math.max(0, b.y), width: Math.max(4, b.w), height: Math.max(4, b.h) } });
      const c = await page.evaluate(async (data, sel) => {
        const el = document.querySelector(sel); if (el) el.removeAttribute('data-ds-probe');
        const img = new Image(); img.src = 'data:image/png;base64,' + data;
        await img.decode();
        const cv = document.createElement('canvas'); cv.width = img.width; cv.height = img.height;
        const ctx = cv.getContext('2d'); ctx.drawImage(img, 0, 0);
        const px = ctx.getImageData(0, 0, cv.width, cv.height).data;
        const L = [];
        for (let i = 0; i < px.length; i += 16) L.push([0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2], px[i], px[i + 1], px[i + 2]]);
        L.sort((a, b) => a[0] - b[0]);
        const med = L[Math.floor(L.length / 2)];
        const spread = L[Math.floor(L.length * 0.9)][0] - L[Math.floor(L.length * 0.1)][0];
        return { rgb: [med[1], med[2], med[3]], spread: Math.round(spread) };
      }, shot, t.sel);
      t.bg = 'rgb(' + c.rgb.join(', ') + ')';
      t.bgFrom = 'photo';
      t.bgSpread = c.spread;
    } catch (e) {}
  }
}

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-gpu', '--hide-scrollbars', '--force-device-scale-factor=1']
  });
  const report = {};
  for (const [name, width, height] of [['desktop', 1440, 900], ['mobile', 390, 844]]) {
    const page = await browser.newPage();
    await page.setViewport({ width, height, deviceScaleFactor: 1 });
    // тот же агент, что в annotate.js: сайт с отдельной мобильной вёрсткой отдаст её и там, и там
    if (name === 'mobile') await page.setUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1');
    const loaded = await prepare(page, url);
    if (!loaded) console.error(`audit.js: страницу не удалось открыть (${name})`);
    await page.screenshot({ path: path.join(out, `${name}-first.png`) });
    try {
      await page.screenshot({ path: path.join(out, `${name}-full.png`), fullPage: true });
    } catch (e) {}
    if (!loaded) { await page.close(); continue; }
    const got = await page.evaluate(collect);
    await page.evaluate(() => window.scrollTo(0, 0));
    await photoBg(page, got.texts || []);
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
