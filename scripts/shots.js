// Скриншоты конкретных участков страницы.
// node shots.js <url> <outdir> <y1,y2,...> [height]
// Нужен Node 22, Chrome и puppeteer-core в папке запуска.
const puppeteer = require('puppeteer-core');
const fs = require('fs');

(async () => {
  const [url, out, ys, h] = process.argv.slice(2);
  const H = parseInt(h || '900', 10);
  fs.mkdirSync(out, { recursive: true });
  const b = await puppeteer.launch({ executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome', headless: 'new',
    args: ['--no-sandbox', '--disable-gpu', '--hide-scrollbars'] });
  const p = await b.newPage();
  await p.setViewport({ width: 1440, height: H });
  await p.goto(url, { waitUntil: 'networkidle2', timeout: 45000 });
  await new Promise(r => setTimeout(r, 2500));
  const offsets = ys.split(',').map(Number);
  for (const y of offsets) {
    await p.evaluate(yy => window.scrollTo(0, yy), Math.max(0, y - 100));
    await new Promise(r => setTimeout(r, 1400));
    await p.screenshot({ path: `${out}/view-${y}.png` });
  }
  await b.close();
  console.log('снято:', offsets.join(' '));
})();
