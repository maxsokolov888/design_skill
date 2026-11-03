#!/usr/bin/env python3
"""Автопроверка замеров по нормативу.

  python3 check.py <папка с measure.json>                 — находки-кандидаты в консоль
  python3 check.py <папка> --json findings.json          — то же + файл для annotate.js и report.py
  python3 check.py --renumber findings.json              — перенумеровать после ручной правки

Каждая находка написана человеческим языком: где, что не так (с замером), почему
мешает посетителю, как исправить (с числом). Номер правила хранится в поле rule
и в отчёт идёт только в техническое приложение.

Находка — кандидат: агент сверяет её со скриншотом и оставляет только подтверждённое.
Номера правил — из references/: 1.1, 1.14, 1.15, 2.1, 3.1, 3.2, 3.5, 3.9, 3.10,
3.15, 5.1, 8.1, 8.4, 8.5, 8.8, 10.5, 10.6, 10.11, 10.14, 10.15, 10.19, 10.21, 10.22.
Вход — measure.json, который пишет audit.js."""
import json, sys, re, os, colorsys
from collections import Counter, OrderedDict

SEV = {3: 'Важно', 2: 'Заметно', 1: 'Мелочь'}
VP_RU = {'desktop': 'на компьютере', 'mobile': 'на телефоне'}

# ---------- цвет ----------
def rgb(c):
    m = re.findall(r'[\d.]+', c or '')
    return tuple(int(float(x)) for x in m[:3]) if len(m) >= 3 else None

def hexc(p):
    return '#%02X%02X%02X' % tuple(p)

def lum(p):
    def f(v):
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(p[0]) + 0.7152 * f(p[1]) + 0.0722 * f(p[2])

def contrast(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)

def fmt(x, nd=1):
    return (('%.' + str(nd) + 'f') % x).replace('.', ',')

def color_name(p):
    r, g, b = [v / 255 for v in p]
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    if s < 0.12 or max(p) - min(p) < 20:
        if l > 0.93: return 'белый'
        if l > 0.75: return 'светло-серый'
        if l > 0.45: return 'серый'
        if l > 0.15: return 'тёмно-серый'
        return 'чёрный'
    hd = h * 360
    names = [(15, 'красный'), (40, 'оранжевый'), (65, 'жёлтый'), (160, 'зелёный'), (200, 'бирюзовый'),
             (255, 'синий'), (290, 'фиолетовый'), (335, 'розовый'), (361, 'красный')]
    base = next(n for lim, n in names if hd < lim)
    if base in ('оранжевый', 'жёлтый') and s < 0.75 and l < 0.7: base = 'горчичный' if base == 'жёлтый' or hd > 30 else 'коричневый'
    if l > 0.8: return 'светлый ' + base if not base.endswith('ый') else 'светло-' + base
    if l < 0.3: return 'тёмно-' + base
    return base

def color_on(p):
    """«на белом фоне», «на горчичном фоне» — предложный падеж прилагательного."""
    n = color_name(p)
    words = n.split(' ')
    def dec(w):
        for a, b in (('ый', 'ом'), ('ий', 'ем'), ('ой', 'ом')):
            if w.endswith(a): return w[:-2] + b
        return w
    return 'на ' + ' '.join(dec(w) for w in words) + ' фоне'

def _shift(c, target, other, swap):
    """Менять светлоту цвета c (тон сохраняем) в обе стороны; вернуть ближайший вариант с нужным контрастом."""
    h, l, s_ = colorsys.rgb_to_hls(*[v / 255 for v in c])
    best = None
    for sign in (-1, 1):
        for step in range(1, 101):
            nl = l + sign * step / 100
            if not 0 <= nl <= 1: break
            n = tuple(round(v * 255) for v in colorsys.hls_to_rgb(h, nl, s_))
            if contrast(n, other) >= target:
                if best is None or step < best[0]: best = (step, n)
                break
    return best[1] if best else None

def fix_bg(text, bg, target):
    """Ближайший по светлоте фон того же тона, с которым контраст станет target."""
    return _shift(bg, target, text, True)

def fix_text(text, bg, target):
    return _shift(text, target, bg, False)

def plural(n, one, few, many):
    w = one if n % 10 == 1 and n % 100 != 11 else few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many
    return f'{n} {w}'

def px(v):
    try: return float(re.sub(r'[^0-9.]', '', str(v)) or 0)
    except Exception: return 0

def q(t, n=45):
    t = (t or '').strip()
    return t if len(t) <= n else t[:n].rsplit(' ', 1)[0] + '…'

# ---------- где на странице ----------
class Places:
    """Подписывает место на странице: «первый экран», «блок „О нас“», «подвал»."""
    def __init__(self, m):
        self.vh = 900 if m.get('viewport', 1440) > 600 else 844
        self.secs = []
        texts = m.get('texts') or []
        for s in m.get('sections') or []:
            b = s.get('box') or {'y': s.get('y', 0), 'h': s.get('h', 0)}
            inside = [t for t in texts if b['y'] <= t['box']['y'] < b['y'] + b['h'] and len(t['text']) > 2]
            head = max(inside, key=lambda t: (t['size'], -t['box']['y']), default=None)
            self.secs.append((b['y'], b['y'] + b['h'], head['text'] if head else ''))
        self.height = m.get('docHeight') or 1

    def __call__(self, box):
        y = box['y'] + box['h'] / 2
        if y < self.vh: return 'первый экран'
        for i, (a, b, head) in enumerate(self.secs):
            if a <= y < b:
                if i == len(self.secs) - 1 and len(self.secs) > 2: return 'подвал'
                return f'блок «{q(head, 40)}»' if head else f'{i + 1}-й блок сверху'
        f = y / self.height
        return 'верх страницы' if f < .33 else 'середина страницы' if f < .66 else 'низ страницы'

def tgt(e):
    return {'sel': e.get('sel', ''), 'box': e.get('box')}

# ---------- проверки одного вьюпорта ----------
def check_viewport(m, vp):
    out = []
    W = m.get('viewport', 1440)
    where = Places(m)
    texts = m.get('texts') or []
    add = lambda **k: out.append(dict(k, viewport=vp))

    # контраст: 10.22 / 1.15. Группируем по паре «цвет текста / фон».
    pairs = OrderedDict()
    for t in texts:
        if not t.get('bg'): continue
        tc, bc = rgb(t['color']), rgb(t['bg'])
        cr = contrast(tc, bc)
        large = t['size'] >= 24 or (t['size'] >= 19 and t['weight'] >= 700)
        if cr < (3.0 if large else 4.5):
            photo = t.get('bgFrom') == 'photo'
            # на пёстром фото медиана ненадёжна: пропускаем, если разброс огромный и контраст близок к норме
            if photo and t.get('bgSpread', 0) > 120 and cr > 2.0: continue
            pairs.setdefault((tc, bc if not photo else 'photo:' + hexc(tc)), []).append((t, cr, large))
    for (tc, bc), items in pairs.items():
        items.sort(key=lambda x: x[0]['box']['y'])
        photo = isinstance(bc, str)
        if photo:
            bc = rgb(items[0][0]['bg'])
        cr = min(x[1] for x in items)
        need = 3.0 if all(x[2] for x in items) else 4.5
        t0 = items[0][0]
        ex = ', '.join(f'«{q(t.get("full") or t["text"], 30)}»' for t, _, _ in items[:3])
        ex = (f'Это надпись {ex}' if len(items) == 1 else f'Так набраны {ex}')
        nb, nt = fix_bg(tc, bc, need + 0.1), fix_text(tc, bc, need + 0.1)
        ways = []
        dark = (51, 51, 51)
        if lum(tc) > lum(bc) and contrast(dark, bc) >= need + 0.1:
            ways.append(f'набрать текст тёмным {hexc(dark)} (с этим фоном это {fmt(contrast(dark, bc))} к 1)')
        page_bg = color_name(bc) in ('белый', 'чёрный', 'светло-серый')
        if nt and page_bg: ways.append(f'перекрасить текст в {hexc(nt)}')
        if nb and not page_bg: ways.append(f'{"затемнить" if lum(nb) < lum(bc) else "осветлить"} фон до {hexc(nb)}')
        if nt and not page_bg: ways.append(f'перекрасить текст в {hexc(nt)}')
        norm = 'не меньше 3 к 1 (текст тут крупный)' if need == 3.0 else 'не меньше 4,5 к 1 для обычного текста и 3 к 1 для крупных заголовков'
        if photo:
            ways = [f'перекрасить текст в {hexc(nt)}'] if nt else []
            ways.append('положить под текст полупрозрачную тёмную подложку' if lum(tc) > lum(bc) else 'положить под текст светлую подложку')
        bgdesc = f'на фотографии (фон под текстом в среднем {hexc(bc)}, {color_name(bc)})' if photo else f'{color_on(bc)} ({hexc(bc)})'
        add(rule='10.22 / 1.15', severity=3 if cr < 2.6 else 2, key=f'contrast:{hexc(tc)}:{"photo" if photo else hexc(bc)}',
            where=where(t0['box']), y=t0['box']['y'],
            what=f'{color_name(tc).capitalize()} текст ({hexc(tc)}) {bgdesc}: контраст {"около " if photo else ""}{fmt(cr)} к 1. {ex}' + (f' и ещё {len(items) - 3}' if len(items) > 3 else '') + '.',
            why=('Текст сливается с фоном: на солнце, на недорогом экране и людям со слабым зрением его не прочитать.' if cr < 2.6 else
                 'Читать приходится с напряжением, особенно с телефона на улице.'),
            fix=f'Нужен контраст {norm}: ' + '; или '.join(ways[:2]) + '.',
            targets=[tgt(t) for t, _, _ in items[:8]], cr=round(cr, 2))

    # мелкий текст: 10.5
    small = [t for t in texts if t['size'] and t['size'] < 13 and len(t['text']) > 3]
    if small:
        t0 = min(small, key=lambda t: t['box']['y'])
        add(rule='10.5', severity=2, key='small', where=where(t0['box']), y=t0['box']['y'],
            what=f'Текст {int(t0["size"])} px: «{q(t0["text"])}»' + (f' и ещё {plural(len(small) - 1, "надпись", "надписи", "надписей")} такого же размера' if len(small) > 1 else '') + '.',
            why='Мельче 13 px буквы на экране превращаются в узор, их пропускают даже те, кто хорошо видит.',
            fix='Поднять до 14 px для подписей и до 16 px для обычного текста.',
            targets=[tgt(t) for t in sorted(small, key=lambda t: t['box']['y'])[:4]])
    body = [t for t in texts if len(t['text']) > 80 and 13 <= t['size'] < 16 and not t['link']]
    if body:
        t0 = min(body, key=lambda t: t['box']['y'])
        add(rule='10.5', severity=2, key='bodysmall', where=where(t0['box']), y=t0['box']['y'],
            what=f'Основной текст набран {int(t0["size"])} px: «{q(t0["text"])}».',
            why='Длинный текст такого размера читать тяжело, глаз быстро устаёт и человек перестаёт читать.',
            fix='Основной текст — 16–20 px на компьютере и 16–18 px на телефоне.',
            targets=[tgt(t) for t in body[:3]])

    # кнопки: 8.5 высота, 10.19 тач-зона, 8.4 кегль, 8.1 подпись
    btns = [b for b in m.get('buttonsAll') or [] if b.get('filled') and b.get('text') and not b.get('inText')
            and 20 <= b['box']['h'] <= 120 and b['box']['w'] >= 60 and len(b['text']) <= 40]
    # навигационные пункты шапки — не кнопки
    btns = [b for b in btns if not (b['box']['y'] < 120 and b['box']['h'] < 40)]
    seen = set()
    for b in btns:
        k = (b['text'], b['box']['h'])
        if k in seen: continue
        seen.add(k)
        h = b['box']['h']
        if vp == 'mobile' and h < 44:
            add(rule='10.19', severity=3, key=f'touch:{b["text"]}', where=where(b['box']), y=b['box']['y'],
                what=f'Кнопка «{q(b["text"], 30)}» высотой {h} px.', why='Пальцем в неё трудно попасть, человек промахивается и уходит.',
                fix='Высота кнопки на телефоне не меньше 44 px, лучше 50–56 px.', targets=[tgt(b)])
        elif vp == 'desktop' and not (48 <= h <= 62):
            add(rule='8.5', severity=2 if h < 44 else 1, key=f'btnh:{b["text"]}', where=where(b['box']), y=b['box']['y'],
                what=f'Кнопка «{q(b["text"], 30)}» высотой {h} px.',
                why='Низкая кнопка выглядит второстепенной и теряется рядом с текстом.' if h < 48 else 'Слишком высокая кнопка выглядит тяжёлой и спорит с заголовком.',
                fix='Высота кнопки 50–60 px, например 56 px.', targets=[tgt(b)])
        if b['size'] and b['size'] < 14 and vp == 'desktop':
            add(rule='8.4', severity=1, key=f'btnfs:{b["text"]}', where=where(b['box']), y=b['box']['y'],
                what=f'Подпись кнопки «{q(b["text"], 30)}» набрана {b["size"]} px.', why='Мелкую подпись не успевают прочитать, кнопка выглядит неважной.',
                fix='Подпись кнопки 14–16 px.', targets=[tgt(b)])
        if re.fullmatch(r'(подробнее|узнать больше|узнать подробнее|далее|читать далее|ещё|more|read more|learn more|click here|перейти)', b['text'].strip().lower()):
            add(rule='8.1', severity=2, key=f'label:{b["text"].lower()}', where=where(b['box']), y=b['box']['y'],
                what=f'На кнопке написано «{b["text"]}», но не сказано, что будет после нажатия.',
                why='Человек не понимает, зачем нажимать, и кнопку пропускают.',
                fix='Назвать действие с предметом: «Посмотреть меню», «Забронировать столик», «Получить расчёт».', targets=[tgt(b)])

    # H1: 3.1
    h1 = m.get('h1') or []
    if not h1:
        add(rule='3.1', severity=1, key='h1none', scope='page', y=0, where='вся страница',
            what='На странице нет главного заголовка в разметке (тега H1).',
            why='Посетитель этого не видит, но поисковики хуже понимают, о чём страница.',
            fix='Оформить главный заголовок первого экрана тегом H1, а заголовки блоков — H2.')
    elif len(h1) > 1:
        add(rule='3.1', severity=1, key='h1many', y=h1[1]['box']['y'], where=where(h1[1]['box']),
            what=f'Главных заголовков (H1) на странице {len(h1)}: ' + ', '.join(f'«{q(h["text"], 25)}»' for h in h1[:3]) + '.',
            why='Поисковик не понимает, какой из них главный.', fix='Оставить один H1 на первом экране, остальные сделать H2.',
            targets=[tgt(h) for h in h1[1:4]])

    # заголовки в три строки и больше: 10.11
    heads = [dict(h, full=h['text']) for h in h1 if h.get('lh')]
    heads += [t for t in texts if t['size'] >= 32 and t.get('lh')]
    done = set()
    for t in sorted(heads, key=lambda t: t['box']['y']):
        lh = t['lh'] or t['size'] * 1.2
        lines = round(t['box']['h'] / lh) if lh else 1
        k = round(t['box']['y'] / 20)
        if lines >= 3 and k not in done:
            done.add(k)
            add(rule='10.11', severity=2, key=f'lines:{q(t["text"], 20)}', where=where(t['box']), y=t['box']['y'],
                what=f'Заголовок «{q(t.get("full") or t["text"], 40)}» занимает {lines} строки {VP_RU[vp]} (кегль {int(t["size"])} px, ширина {t["box"]["w"]} px).',
                why='Длинный заголовок читают как абзац: суть не схватывается с одного взгляда.',
                fix=f'Уложить в две строки: сократить текст или уменьшить кегль примерно до {int(t["size"] * 2 / lines)} px.',
                targets=[tgt(t)])

    # длина строки: 3.9 / 10.10
    for t in texts:
        if len(t['text']) > 120 and t['size']:
            cpl = int(t['box']['w'] / (t['size'] * 0.5))
            if (vp == 'desktop' and cpl > 75) or (vp == 'mobile' and cpl > 48):
                add(rule='3.9 / 10.10', severity=1, key='cpl', where=where(t['box']), y=t['box']['y'],
                    what=f'Строка в абзаце «{q(t["text"], 35)}» около {cpl} знаков (ширина {t["box"]["w"]} px).',
                    why='На длинной строке глаз теряет начало следующей, читать тяжело.',
                    fix=f'Сузить блок текста до {int(t["size"] * 0.5 * 60)} px — это около 60 знаков; комфортно 40–45.',
                    targets=[tgt(t)])
                break

    # интерлиньяж: 3.5 / 10.9
    for t in texts:
        if len(t['text']) > 80 and t['size'] <= 20 and t['lh']:
            r = t['lh'] / t['size']
            if r < 1.2 or r > 1.75:
                add(rule='3.5', severity=1, key='lh', where=where(t['box']), y=t['box']['y'],
                    what=f'Межстрочный интервал в тексте «{q(t["text"], 35)}» — {int(r * 100)}% от размера шрифта.',
                    why='Строки ' + ('слипаются' if r < 1.2 else 'разваливаются') + ', текст читается хуже.',
                    fix=f'Межстрочный интервал 145–160% для основного текста: при {int(t["size"])} px это {round(t["size"] * 1.5)} px.',
                    targets=[tgt(t)])
                break

    # выключка и прописные: 3.10, 3.15
    for t in texts:
        if len(t['text']) > 80 and t.get('align') == 'justify':
            add(rule='3.10', severity=1, key='justify', where=where(t['box']), y=t['box']['y'],
                what=f'Абзац «{q(t["text"], 35)}» выровнен по ширине.', why='Между словами появляются дыры, строка рвётся, читать неудобно.',
                fix='Выравнивать по левому краю.', targets=[tgt(t)])
            break
    for t in texts:
        if len(t['text']) > 80 and t.get('transform') == 'uppercase':
            add(rule='3.15', severity=1, key='upper', where=where(t['box']), y=t['box']['y'],
                what=f'Абзац «{q(t["text"], 35)}» набран прописными буквами.', why='Текст прописными читается как крик, его пропускают.',
                fix='Прописные только в коротких заголовках и кнопках; абзац — обычными буквами.', targets=[tgt(t)])
            break

    # телефон: горизонтальная прокрутка и поля
    if vp == 'mobile':
        ov = m.get('overflow') or []
        if (m.get('scrollWidth') or W) > W + 2:
            t0 = ov[0] if ov else None
            add(rule='10.21', severity=3, key='overflow', where=where(t0['box']) if t0 else 'вся страница', y=t0['box']['y'] if t0 else 0,
                scope='element' if t0 else 'page',
                what=f'Страница шире экрана телефона: {m["scrollWidth"]} px при ширине {W} px' + (f', вылезает «{q(t0["text"], 30)}»' if t0 and t0.get('text') else '') + '.',
                why='Страница ездит вбок, человеку кажется, что сайт сломан.',
                fix='Ограничить ширину элемента: max-width: 100%, убрать фиксированную ширину.', targets=[tgt(o) for o in ov[:3]])
        edge = [t for t in texts if len(t['text']) > 3 and (t['box']['x'] < 12 or t['box']['x'] + t['box']['w'] > W - 12) and t['box']['w'] < W + 2]
        if edge:
            t0 = min(edge, key=lambda t: t['box']['y'])
            side = t0['box']['x'] if t0['box']['x'] < 12 else W - t0['box']['x'] - t0['box']['w']
            add(rule='10.14 / 10.13', severity=2, key='edge', where=where(t0['box']), y=t0['box']['y'],
                what=f'Текст «{q(t0["text"], 30)}» стоит в {max(0, int(side))} px от края экрана.',
                why='Текст у самого края выглядит обрезанным, его неудобно читать.',
                fix='Поля слева и справа 16–20 px, одинаковые с обеих сторон.', targets=[tgt(t) for t in edge[:3]])
    return out

# ---------- проверки на всю страницу (без кружка) ----------
def check_page(d):
    out = []
    add = lambda **k: out.append(dict(k, viewport='desktop', scope='page', y=10 ** 7, where='вся страница'))
    chrom = d.get('chromatic') or []
    uniq = []
    for c, n in chrom:
        p = rgb(c)
        if n >= 2 and p and all(sum(abs(a - b) for a, b in zip(p, u)) > 40 for u in uniq): uniq.append(p)
    if len(uniq) > 4:
        add(rule='1.1', severity=1, key='palette', what=f'Заметных цветов на странице {len(uniq)}: ' + ', '.join(hexc(u) for u in uniq[:6]) + '.',
            why='Когда цветов много, глаз не понимает, что главное, а что фон.', fix='Оставить 2–3 цвета, максимум 4: фон, текст и один цвет для кнопок.')
    for sh, n in d.get('shadows', [])[:3]:
        if re.search(r'rgba?\(\s*0,\s*0,\s*0', sh) and n >= 2:
            add(rule='1.14 / 8.12', severity=1, key='shadow', what=f'Серые тени у {n} элементов ({sh.split(")")[0]})).',
                why='Чёрная тень выглядит грязно и делает страницу тяжелее.', fix='Убрать тень или взять её в цвет самого элемента, слабую и мягкую.')
            break
    rad = [(r_, n) for r_, n in d.get('radii', []) if n >= 2 and px(r_) > 0]
    if len(rad) > 3:
        add(rule='8.8 / 9.11', severity=1, key='radii', what=f'Углы скруглены по-разному: {len(rad)} вариантов ({", ".join(r_ for r_, _ in rad[:5])}).',
            why='Элементы выглядят собранными из разных сайтов.', fix='Выбрать одну систему: например 12 px для карточек и полное скругление для кнопок.')
    fams = {t.get('font') for t in (d.get('h1', []) + d.get('h2', []) + d.get('h3', []) + d.get('p', []))
            if t.get('font')} | {b.get('font') for b in d.get('buttons', []) if b.get('font') and b.get('text')}
    fams.discard('')
    if len(fams) >= 3:
        add(rule='2.1', severity=1, key='fonts', what=f'На странице {len(fams)} шрифта: {", ".join(sorted(fams))}.',
            why='Разные шрифты спорят друг с другом, страница выглядит неряшливо.', fix='Один шрифт в нескольких начертаниях или два согласованных: один для заголовков, другой для текста.')
    sizes = Counter(int(t['size']) for t in d.get('texts') or [] if t['size'])
    main = sorted(s for s, n in sizes.items() if n >= 1)
    if len(main) > 6:
        add(rule='10.6', severity=1, key='sizes', what=f'Размеров шрифта на странице {len(main)}: {", ".join(map(str, main))} px.',
            why='Близкие размеры читаются как каша: непонятно, что заголовок, а что подпись.', fix='Не больше пяти размеров, например 56 / 32 / 20 / 16 / 14 px.')
    for (s_, w_), tags in _hier(d).items():
        add(rule='3.2', severity=1, key='hier', what=f'Заголовки разных уровней ({", ".join(tags)}) одного размера {s_} px и одной жирности.',
            why='Не видно, где главный раздел, а где подпункт.', fix='Сделать уровни разными по размеру: например 48 / 32 / 20 px.')
        break
    return out

def _hier(d):
    sizes = {}
    for tag in ('h1', 'h2', 'h3'):
        for e in (d.get(tag) or [])[:3]:
            sizes.setdefault((e['size'], e['weight']), set()).add(tag.upper())
    return {k: sorted(v) for k, v in sizes.items() if len(v) > 1}

# ---------- что сделано хорошо ----------
def goods(r, fs):
    d = r['desktop']; m = r.get('mobile') or {}
    keys = {f['key'] for f in fs}
    g = []
    if len(d.get('h1') or []) == 1: g.append('Один главный заголовок, понятно, с чего начинается страница.')
    if m and (m.get('scrollWidth') or 0) <= (m.get('viewport') or 390) + 2: g.append('На телефоне страница не ездит вбок, всё помещается в ширину экрана.')
    if 'bodysmall' not in keys and any(len(t['text']) > 80 and t['size'] >= 16 for t in d.get('texts') or []):
        g.append('Основной текст набран не мельче 16 px, его удобно читать.')
    if not any(k.startswith('contrast') for k in keys): g.append('Текст везде контрастный, читается без напряжения.')
    if 'fonts' not in keys: g.append('Шрифтов немного, страница выглядит цельно.')
    if not any(k.startswith('btnh') or k.startswith('touch') for k in keys) and d.get('buttonsAll'):
        g.append('Кнопки нормального размера, в них легко попасть.')
    if 'palette' not in keys: g.append('Сдержанная палитра, цвета не спорят друг с другом.')
    if 'edge' not in keys and m: g.append('На телефоне у текста есть поля, он не прилипает к краям.')
    return g

# ---------- сборка ----------
def merge(dfs, mfs):
    """Одна и та же проблема на компьютере и телефоне — одна сноска с двумя кружками."""
    out = []
    bykey = {}
    for f in dfs:
        f = dict(f, viewports=['desktop'], targets={'desktop': f.get('targets', [])}, ys={'desktop': f['y']})
        if f['key'] in bykey: continue
        bykey[f['key']] = f; out.append(f)
    for f in mfs:
        if f['key'] in bykey:
            g = bykey[f['key']]
            if 'mobile' in g['viewports']: continue
            g['viewports'].append('mobile'); g['targets']['mobile'] = f.get('targets', []); g['ys']['mobile'] = f['y']
            g['severity'] = max(g['severity'], f['severity'])
            if f['key'].startswith('contrast') and f.get('cr'):
                if abs(f['cr'] - g.get('cr', 0)) >= 0.1: g['what'] += f' На телефоне контраст {fmt(f["cr"])} к 1.'
            elif f['what'] != g['what']: g['what'] += ' На телефоне: ' + f['what'][0].lower() + f['what'][1:]
        else:
            f = dict(f, viewports=['mobile'], targets={'mobile': f.get('targets', [])}, ys={'mobile': f['y']})
            bykey[f['key']] = f; out.append(f)
    for f in out:
        f.pop('viewport', None); f.pop('y', None)
        f.setdefault('scope', 'element')
        if f['scope'] == 'element' and not any(f['targets'].values()): f['scope'] = 'page'
    return out

def number(fs):
    """Номера сверху вниз: сначала то, что видно на компьютере, потом только-мобильное, в конце — общее."""
    def key(f):
        if f.get('scope') == 'page': return (2, -f.get('severity', 1), 0)
        ys = dict(f.get('ys') or {})
        for vp, ts in (f.get('targets') or {}).items():  # ручные находки: y из рамки
            if vp not in ys and ts and ts[0].get('box'): ys[vp] = ts[0]['box']['y']
        if 'desktop' in ys: return (0, ys['desktop'], -f.get('severity', 1))
        return (1, ys.get('mobile', 0), -f.get('severity', 1))
    fs.sort(key=key)
    for i, f in enumerate(fs, 1):
        f['n'] = i
        f['severity_label'] = SEV.get(f.get('severity', 1), 'Мелочь')
        f.setdefault('title', 'Замечание'); f.setdefault('scope', 'element')
    return fs

def title_for(f):
    """Короткий заголовок сноски человеческими словами."""
    k, w = f['key'], f['what']
    if k.endswith(':photo'):
        return f'{w.split(" текст")[0]} текст на фотографии плохо читается'
    m = re.match(r'(.+?) текст \(#\w+\) (на .+? фоне)', w)
    if k.startswith('contrast') and m:
        return f'{m.group(1)} текст {m.group(2)} плохо читается'
    if k.startswith('btnh'):
        h = re.search(r'высотой (\d+)', w)
        return 'Кнопка низковата' if h and int(h.group(1)) < 50 else 'Кнопка слишком высокая'
    t = {
        'small': 'Слишком мелкий текст', 'bodysmall': 'Основной текст мелковат',
        'h1none': 'Нет главного заголовка в разметке', 'h1many': 'Несколько главных заголовков',
        'cpl': 'Слишком длинные строки', 'lh': 'Неудобный межстрочный интервал', 'justify': 'Текст выровнен по ширине',
        'upper': 'Абзац набран прописными', 'overflow': 'Страница шире экрана телефона', 'edge': 'Текст прилип к краю экрана',
        'palette': 'Слишком много цветов', 'shadow': 'Грязные серые тени', 'radii': 'Разные скругления углов',
        'fonts': 'Слишком много шрифтов', 'sizes': 'Слишком много размеров шрифта', 'hier': 'Заголовки разных уровней не отличаются',
    }
    for pre, name in (('touch', 'В кнопку трудно попасть пальцем'), ('btnh', 'Кнопка не того размера'),
                      ('btnfs', 'Мелкая подпись на кнопке'), ('label', 'Кнопка не говорит, что будет после нажатия'),
                      ('lines', 'Заголовок не помещается в две строки')):
        if k.startswith(pre): return name
    return t.get(k, f.get('title') or 'Замечание')

def findings(r):
    d = r['desktop']; m = r.get('mobile')
    dfs = check_viewport(d, 'desktop')
    mfs = check_viewport(m, 'mobile') if m else []
    fs = merge(dfs, mfs) + [dict(f, viewports=['desktop'], targets={}, ys={}) for f in check_page(d)]
    for f in fs:
        f.pop('viewport', None); f.pop('y', None)
        f['title'] = title_for(f)
    number(fs)
    return {'url': d.get('url'), 'title': d.get('title'), 'findings': fs, 'good': goods(r, fs)}

def load(dirpath):
    return json.load(open(os.path.join(dirpath, 'measure.json')))

def rules(r):
    """Старый интерфейс: список (номер правила, текст)."""
    return [(f['rule'], f'{f["where"]}: {f["what"]}') for f in findings(r)['findings']]

if __name__ == '__main__':
    a = sys.argv[1:]
    if not a:
        print(__doc__); sys.exit(2)
    if a[0] == '--renumber':
        data = json.load(open(a[1]))
        number(data['findings'])
        json.dump(data, open(a[1], 'w'), ensure_ascii=False, indent=2)
        print('перенумеровано:', len(data['findings'])); sys.exit(0)
    res = findings(load(a[0]))
    if '--json' in a:
        p = a[a.index('--json') + 1]
        json.dump(res, open(p, 'w'), ensure_ascii=False, indent=2)
    if not res['findings']:
        print('Автопроверка нарушений не нашла — смотри скриншоты вручную.')
    for f in res['findings']:
        mark = '○' if f['scope'] == 'page' else '●'
        print(f'{mark} {f["n"]}. [{f["severity_label"]}] {f["where"]} ({", ".join(VP_RU[v] for v in f["viewports"])}): {f["what"]}  [{f["rule"]}]')
