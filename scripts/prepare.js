// Общая подготовка живой страницы перед замером и снимком.
// Используют audit.js и annotate.js, чтобы координаты совпадали.
// Ничего не роняет: каждая попытка обёрнута в try.
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function open(page, url) {
  try {
    await page.goto(url, { waitUntil: 'networkidle2', timeout: 45000 });
    return true;
  } catch (e) {
    try { await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 }); return true; }
    catch (e2) { console.error(`страницу не удалось открыть: ${e2.message}`); return false; }
  }
}

// Закрыть cookie-баннеры и всплывающие окна. Мягко: кликаем «Принять»,
// жмём Escape, прячем оставшиеся оверлеи на пол-экрана.
async function dismiss(page) {
  try { await page.keyboard.press('Escape'); } catch (e) {}
  try {
    await page.evaluate(() => {
      const words = /^(принять|принимаю|согласен|согласна|согласиться|хорошо|понятно|ок|ok|okay|accept|accept all|agree|got it|allow all|закрыть|×|✕)$/i;
      const zone = /cookie|consent|gdpr|policy|banner|popup|modal|t-popup|t706|t-cookie/i;
      const clickable = [...document.querySelectorAll('button, a, [role=button], .t-btn, div[class*=btn], span[class*=close], div[class*=close]')];
      for (const el of clickable) {
        const t = (el.textContent || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ');
        let p = el, inZone = false;
        for (let i = 0; i < 8 && p; i++, p = p.parentElement) {
          const s = getComputedStyle(p);
          const pc = (typeof p.className === 'string' ? p.className : '') + ' ' + (p.id || '');
          if (zone.test(pc) || s.position === 'fixed') { inZone = true; break; }
        }
        if (inZone && (words.test(t) || (/cookie|куки/i.test(t) && t.length < 30))) { try { el.click(); } catch (e) {} }
      }
      // Tilda: открытые попапы
      document.querySelectorAll('.t-popup_show, .t-popup.t-popup_show').forEach(e => e.classList.remove('t-popup_show'));
      document.body.classList.remove('t-body_noscrolling');
      document.documentElement.style.overflow = ''; document.body.style.overflow = '';
      // оставшиеся оверлеи: fixed/sticky, перекрывают больше 30% экрана
      const vw = innerWidth, vh = innerHeight;
      document.querySelectorAll('body *').forEach(e => {
        const s = getComputedStyle(e);
        if (s.position !== 'fixed') return;
        const r = e.getBoundingClientRect();
        const area = Math.max(0, Math.min(r.right, vw) - Math.max(r.left, 0)) * Math.max(0, Math.min(r.bottom, vh) - Math.max(r.top, 0));
        const cls = (typeof e.className === 'string' ? e.className : '') + ' ' + (e.id || '');
        if (area > 0.3 * vw * vh || /cookie|consent|gdpr/i.test(cls)) e.setAttribute('data-ds-hidden', '1');
      });
      document.querySelectorAll('[data-ds-hidden]').forEach(e => { e.style.setProperty('display', 'none', 'important'); });
    });
  } catch (e) {}
}

// Проскролл страницы шагами, чтобы догрузились картинки и сработали анимации появления.
async function scrollThrough(page) {
  try {
    const h = await page.evaluate(() => document.documentElement.scrollHeight);
    const vh = await page.evaluate(() => innerHeight);
    for (let y = 0; y < Math.min(h, 40000); y += Math.round(vh * 0.7)) {
      await page.evaluate(yy => window.scrollTo(0, yy), y);
      await sleep(180);
    }
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await sleep(1200);
    // отключить анимации, чтобы ничего не осталось полупрозрачным
    await page.addStyleTag({ content: '*,*::before,*::after{animation-duration:0s!important;animation-delay:0s!important;transition:none!important;caret-color:transparent!important}' });
    await page.evaluate(() => {
      document.querySelectorAll('img[loading=lazy]').forEach(i => { i.loading = 'eager'; });
      // Tilda: элементы с анимацией появления
      document.querySelectorAll('.t-animate').forEach(e => e.classList.add('t-animate_started'));
    });
    await page.evaluate(() => window.scrollTo(0, 0));
    await sleep(900);
  } catch (e) {}
}

async function prepare(page, url) {
  const ok = await open(page, url);
  if (!ok) return false;
  await sleep(2500);
  await dismiss(page);
  await scrollThrough(page);
  await dismiss(page);
  await sleep(400);
  return true;
}

module.exports = { prepare, open, dismiss, scrollThrough, sleep };
