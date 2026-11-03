// Скриншот страницы с пронумерованными кружками на местах ошибок.
//   node annotate.js <url> <findings.json> [папка] [--part 1800]
// findings.json пишет check.py (--json). Находка:
//   { "n": 1, "viewports": ["desktop","mobile"],
//     "targets": { "desktop": [{ "sel": "css-селектор", "box": {x,y,w,h} }], "mobile": [...] } }
// Кружок ставится по селектору на живой странице; если селектор не нашёлся — по box
// (координаты документа). Находки со scope = "page" кружка не получают.
// Выход: annotated-desktop.png, annotated-mobile.png (вся страница),
//        annotated-desktop-1.png … (части для отчёта), annotated.json (что где).
// Нужен Node 22, Chrome и puppeteer-core (как для audit.js).
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');
const { prepare, sleep } = require(path.join(__dirname, 'prepare.js'));

const args = process.argv.slice(2);
const flag = (name, def) => { const i = args.indexOf(name); if (i < 0) return def; const v = args[i + 1]; args.splice(i, 2); return v; };
const PART = parseInt(flag('--part', '1800'), 10);
const [url, findingsPath, outArg] = args;
const out = outArg || '.';
if (!url || !findingsPath) {
  console.error('annotate.js: node annotate.js <url> <findings.json> [папка] [--part 1800]');
  process.exit(2);
}
const CHROME = process.env.CHROME_PATH || '/usr/bin/google-chrome';
const data = JSON.parse(fs.readFileSync(findingsPath, 'utf8'));
const list = (data.findings || data).filter(f => f.scope !== 'page');
fs.mkdirSync(out, { recursive: true });

const VIEWS = [
  { name: 'desktop', width: 1440, height: 900, scale: 1, r: 19 },
  { name: 'mobile', width: 390, height: 844, scale: 2, r: 14 },
];

// В браузере: найти элементы, нарисовать рамки и кружки, вернуть их координаты.
const draw = (marks, R) => {
  const old = document.getElementById('__ds_marks'); if (old) old.remove();
  window.scrollTo(0, 0);
  const W = document.documentElement.scrollWidth, H = document.documentElement.scrollHeight;
  const layer = document.createElement('div');
  layer.id = '__ds_marks';
  layer.style.cssText = `position:absolute;left:0;top:0;width:${W}px;height:0;z-index:2147483647;pointer-events:none;`;
  document.documentElement.appendChild(layer);
  const placed = [];
  const res = [];
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  // Лежит ли кружок с левым верхним углом (x, y) поверх букв: проверяем пять точек
  // по прямоугольникам строк текста под ними.
  const onText = (x, y) => {
    const pts = [[R, R], [R * 0.3, R * 0.3], [R * 1.7, R * 0.3], [R * 0.3, R * 1.7], [R * 1.7, R * 1.7]];
    for (const [dx, dy] of pts) {
      const px = x + dx, py = y + dy;
      window.scrollTo(0, Math.max(0, py - innerHeight / 2));
      const vx = px - scrollX, vy = py - scrollY;
      if (vx < 0 || vy < 0 || vx >= innerWidth || vy >= innerHeight) continue;
      for (const el of document.elementsFromPoint(vx, vy).slice(0, 4)) {
        for (const n of el.childNodes) {
          if (n.nodeType !== 3 || !n.textContent.trim()) continue;
          const rg = document.createRange(); rg.selectNodeContents(n);
          for (const rc of rg.getClientRects()) {
            if (vx >= rc.left - 2 && vx <= rc.right + 2 && vy >= rc.top - 2 && vy <= rc.bottom + 2) { window.scrollTo(0, 0); return true; }
          }
        }
      }
    }
    window.scrollTo(0, 0);
    return false;
  };
  for (const m of marks) {
    const got = [];
    for (const t of m.targets.slice(0, 8)) {
      let b = null, how = 'box';
      if (t.sel) {
        try {
          const el = document.querySelector(t.sel);
          if (el && vis(el)) {
            const r = el.getBoundingClientRect();
            b = { x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height }; how = 'sel';
          }
        } catch (e) {}
      }
      if (!b && t.box) b = t.box;
      if (!b) continue;
      got.push(Object.assign({ how }, b));
    }
    for (const b of got) {
      const pad = 4;
      const fx = Math.max(1, b.x - pad), fy = Math.max(1, b.y - pad);
      const fw = Math.min(W - fx - 1, b.w + pad * 2), fh = b.h + pad * 2;
      const fr = document.createElement('div');
      fr.style.cssText = `position:absolute;left:${fx}px;top:${fy}px;width:${fw}px;height:${fh}px;box-sizing:border-box;` +
        `border:3px solid #E5262B;border-radius:6px;box-shadow:0 0 0 2px #fff, inset 0 0 0 1px rgba(255,255,255,.8);`;
      layer.appendChild(fr);
      // кружок снаружи рамки, чтобы не закрывать сам текст: слева по центру,
      // если слева нет места — над рамкой, если и там нет — справа, в крайнем случае внутри
      const free = (x, y) => x >= 2 && y >= 2 && x <= W - 2 * R - 2 &&
        !placed.some(p => Math.abs(p.x - x) < 2 * R + 4 && Math.abs(p.y - y) < 2 * R + 4) && !onText(x, y);
      const mid = fy + Math.min(fh, 4 * R) / 2 - R;
      const options = [
        [fx - 2 * R - 6, mid],
        [fx - R * 0.4, fy - 2 * R - 4],
        [fx + fw + 6, mid],
        [fx - 2 * R - 6, fy - 2 * R - 2],
        [fx + fw - 2 * R + 4, fy - 2 * R - 4],
        [fx - R * 0.4, fy + fh + 4],
        [fx - R, fy - R],
      ];
      let [cx, cy] = options.find(([x, y]) => free(x, y)) || options[options.length - 1];
      cx = Math.min(Math.max(2, cx), W - 2 * R - 2); cy = Math.max(2, cy);
      for (let k = 0; k < 30 && !free(cx, cy); k++) cy += 2 * R + 6;
      placed.push({ x: cx, y: cy });
      const c = document.createElement('div');
      c.textContent = String(m.n);
      c.style.cssText = `position:absolute;left:${cx}px;top:${cy}px;width:${2 * R}px;height:${2 * R}px;border-radius:50%;` +
        `background:#E5262B;color:#fff;border:3px solid #fff;box-sizing:border-box;box-shadow:0 2px 6px rgba(0,0,0,.45);` +
        `font:700 ${Math.round(R * (m.n > 9 ? 0.85 : 1.05))}px/1 Arial,Helvetica,sans-serif;display:flex;align-items:center;justify-content:center;letter-spacing:-.02em;`;
      layer.appendChild(c);
      res.push({ n: m.n, how: b.how, x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.w), h: Math.round(b.h), cy: Math.round(cy) });
    }
  }
  return { marks: res, W, H: document.documentElement.scrollHeight };
};

// Разрезать длинную страницу на части, не разрезая рамки.
const cuts = (H, boxes, part) => {
  const parts = []; let y0 = 0;
  while (y0 < H) {
    let y1 = Math.min(H, y0 + part);
    if (y1 < H) {
      for (let k = 0; k < 5; k++) {
        const cross = boxes.find(b => b.y - 30 < y1 && b.y + b.h + 10 > y1);
        if (!cross) break;
        const up = cross.y - 30;
        if (up - y0 > part * 0.5) y1 = up; else { y1 = Math.min(H, cross.y + cross.h + 20); break; }
      }
      if (H - y1 < part * 0.25) y1 = H; // хвост приклеиваем к последней части
    }
    parts.push([y0, y1]); y0 = y1;
  }
  return parts;
};

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-gpu', '--hide-scrollbars', '--force-device-scale-factor=1']
  });
  const result = { url, views: {} };
  for (const v of VIEWS) {
    const marks = list.filter(f => (f.viewports || []).includes(v.name) && f.targets && (f.targets[v.name] || []).length)
      .map(f => ({ n: f.n, targets: f.targets[v.name] }));
    const page = await browser.newPage();
    await page.setViewport({ width: v.width, height: v.height, deviceScaleFactor: 1 });
    if (v.name === 'mobile') await page.setUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1');
    const ok = await prepare(page, url);
    if (!ok) { console.error(`annotate.js: страница не открылась (${v.name})`); await page.close(); continue; }
    const d = await page.evaluate(draw, marks, v.r);
    await sleep(300);
    const full = `annotated-${v.name}.png`;
    // целиком: на телефоне длинную страницу снимаем в масштабе 1, чтобы не упереться в предел Chrome
    try {
      await page.screenshot({ path: path.join(out, full), fullPage: true, captureBeyondViewport: true });
    } catch (e) { console.error('annotate.js: полный снимок не удался:', e.message); }
    const parts = [];
    const ps = cuts(d.H, d.marks, PART);
    for (let i = 0; i < ps.length; i++) {
      const [y0, y1] = ps[i];
      const file = `annotated-${v.name}-${i + 1}.png`;
      try {
        await page.screenshot({ path: path.join(out, file), captureBeyondViewport: true,
          clip: { x: 0, y: y0, width: Math.min(d.W, v.width), height: y1 - y0, scale: v.scale } });
      } catch (e) { console.error(`annotate.js: часть ${i + 1} не снята:`, e.message); continue; }
      const nums = [...new Set(d.marks.filter(m => m.cy + v.r >= y0 && m.cy + v.r < y1).map(m => m.n))].sort((a, b) => a - b);
      parts.push({ file, y0, y1, numbers: nums });
    }
    const wanted = marks.map(m => m.n);
    const drawn = new Set(d.marks.map(m => m.n));
    const viaBox = [...new Set(d.marks.filter(m => m.how === 'box').map(m => m.n))];
    result.views[v.name] = { full, width: v.width, height: d.H, parts, marks: d.marks,
      missing: wanted.filter(n => !drawn.has(n)), byBox: viaBox };
    console.log(`${v.name}: кружков ${d.marks.length}, частей ${parts.length}` +
      (viaBox.length ? `, по координатам (селектор не нашёлся): ${viaBox.join(', ')}` : '') +
      (result.views[v.name].missing.length ? `, не нарисованы: ${result.views[v.name].missing.join(', ')}` : ''));
    await page.close();
  }
  await browser.close();
  if (!Object.keys(result.views).length) { console.error('annotate.js: ни один снимок не сделан.'); process.exit(3); }
  fs.writeFileSync(path.join(out, 'annotated.json'), JSON.stringify(result, null, 2));
  console.log('готово:', path.join(out, 'annotated.json'));
})();
