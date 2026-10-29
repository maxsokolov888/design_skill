#!/usr/bin/env python3
"""Автопроверка замеров по нормативу. python3 check.py <папка с measure.json> [правило...]
Печатает находки-кандидаты с номером правила. Это не отчёт: агент читает вывод,
перепроверяет по скриншоту и оставляет только подтверждённое.

Номера правил — из references/ (RULES.md): 1.1, 1.14, 1.15, 2.1, 3.1, 3.2, 3.5,
3.9, 3.10, 3.13, 3.15, 4/5.1, 5.3, 5.4, 8.4, 8.7, 8.8/9.11.
Вход — measure.json, который пишет audit.js."""
import json, sys, re, os
from collections import Counter

def px(v):
    try: return float(re.sub(r'[^0-9.]', '', str(v)) or 0)
    except: return 0

def lum(p):
    def f(v):
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(p[0]) + 0.7152 * f(p[1]) + 0.0722 * f(p[2])

def contrast(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return round((hi + 0.05) / (lo + 0.05), 2)

def rgb(c):
    m = re.findall(r'[\d.]+', c or '')
    return tuple(int(float(x)) for x in m[:3]) if len(m) >= 3 else None

def load(d):
    return json.load(open(os.path.join(d, 'measure.json')))

def rules(r):
    out = []
    d = r['desktop']; m = r.get('mobile') or d

    # 1.1 палитра
    chrom = d.get('chromatic') or []
    cols = [(c, n) for c, n in chrom if n >= 2]
    uniq = []
    for c, n in cols:
        p = rgb(c)
        if p and p not in [rgb(u) for u in uniq]: uniq.append(c)
    if len(uniq) > 4:
        out.append(('1.1', f'Хроматических цветов {len(uniq)}: {", ".join(uniq[:7])} — норма 2–3 значимых, максимум 4.'))

    # 1.14 тени
    for sh, n in d.get('shadows', [])[:3]:
        if re.search(r'rgba?\(\s*0,\s*0,\s*0', sh) and n >= 2:
            out.append(('1.14 / 8.12', f'Чёрная тень у {n} элементов: {sh} — тень берётся в цвет кнопки.'))
            break
    else:
        pass

    # 3.1 единственность H1
    if len(d['h1']) > 1:
        out.append(('3.1', f'H1 на странице {len(d["h1"])} штук: {[h["text"][:40] for h in d["h1"][:3]]} — норма один.'))
    if not d['h1']:
        out.append(('3.1', 'H1 не найден — заголовок первого экрана не размечен заголовком.'))

    # 3.2 иерархия: одинаковые размеры у разных уровней
    sizes = {}
    for tag, arr in (('H1', d['h1']), ('H2', d['h2']), ('H3', d['h3'])):
        for e in arr[:3]:
            sizes.setdefault((e['size'], e['weight']), []).append(tag)
    for (s, w), tags in sizes.items():
        if len(set(tags)) > 1:
            out.append(('3.2', f'Кегль {s} px / вес {w} у разных уровней ({", ".join(sorted(set(tags)))}) — иерархия не читается.'))

    # 3.5 интерлиньяж
    bad = []
    for tag, arr in (('H1', d['h1']), ('H2', d['h2']), ('H3', d['h3']), ('P', d['p'])):
        for e in arr:
            if e['size'] and e['lh']:
                ratio = e['lh'] / e['size']
                if ratio < 1.05 or ratio > 1.75:
                    bad.append((tag, e['size'], e['lh'], round(ratio, 2), e['text'][:32]))
    for b in bad[:4]:
        out.append(('3.5', f'{b[0]} {b[1]}px при интерлиньяже {b[2]}px — {int(b[3]*100)}%, норма 120–150%: «{b[4]}».'))

    # 3.9 длина строки
    for e in d['p'][:6]:
        w, s = e['width'], e['size'] or 16
        approx = int(w / (s * 0.5))
        if approx > 75:
            out.append(('3.9', f'Строка ~{approx} знаков при {w}px и {s}px — норма 40–45 (терпимо до 70): «{e["text"][:40]}».'))

    # 3.10 выключка
    for e in d['p'][:6]:
        if e.get('justify') == 'justify':
            out.append(('3.10', f'Выключка по ширине: «{e["text"][:40]}» — запрещена.'))
            break

    # 3.15 прописные в абзацах
    for e in d['p'][:6]:
        if e.get('transform') == 'uppercase':
            out.append(('3.15', f'Прописные в абзаце: «{e["text"][:40]}».'))
            break

    # 1.15 контраст текста (с оговоркой: точный коэффициент требует исходных цветов)
    for tag, arr in (('P', d['p'][:4]), ('H3', d['h3'][:2])):
        for e in arr:
            tc, bc = rgb(e.get('color')), rgb(e.get('bg'))
            if tc and bc and bc != (0, 0, 0):
                cr = contrast(tc, bc)
                if cr < 3.0:
                    out.append(('1.15', f'Контраст {tag} {e["size"]}px «{e["text"][:30]}» ≈ {cr}:1 (текст {e["color"]} на {e["bg"]}) — проверить глазами, при таком отношении не читается.'))
                    break

    # 8.4 кегль в кнопке / 8.5 высота
    for b in d['buttons'][:10]:
        if b['size'] and b['size'] < 13:
            out.append(('8.4', f'Кегль в кнопке {b["size"]} px, норма 14–16: «{b["text"][:30]}».'))
            break
    # 8.8 / 9.11 система радиусов
    rad = [(r_, n) for r_, n in d.get('radii', []) if n >= 2 and px(r_) > 0]
    if len(rad) > 3:
        out.append(('8.8 / 9.11', f'{len(rad)} разных радиусов: {", ".join(r_ for r_, _ in rad[:6])} — нужна одна система: 0 / 7–15 / 20–30 / капсула.'))

    # 5.x шаг отступов между секциями
    ps = [(s['y'], s['pt'], s['pb'], s['label']) for s in d.get('sections', [])]
    gaps = []
    for i in range(len(ps) - 1):
        gaps.append(ps[i][2] + ps[i + 1][1])
    gaps = [g for g in gaps if g > 0]
    if len(gaps) >= 3:
        c = Counter(gaps)
        if len(set(gaps)) > 2 and max(gaps) - min(gaps) > 24:
            out.append(('5.3 / 5.4', f'Отступы между секциями разные: {gaps[:8]} — нужен единый шаг.'))

    # 5.7 близость внутри/снаружи (по секциям)
    for s in d.get('sections', [])[:8]:
        if s['pt'] and s['pb'] and s['pt'] != s['pb'] and abs(s['pt'] - s['pb']) > 16:
            out.append(('5.3', f'У секции «{s["label"][:30]}» верх {s["pt"]} px и низ {s["pb"]} px — разнобой без причины.'))
            break

    # 4.x контейнер: кластеризуем ширины, ругаемся только на реально разные сетки
    cw = sorted((int(w), n) for w, n in d.get('containerWidths', []) if n >= 2)
    clusters = []
    for w, n in cw:
        if clusters and w - clusters[-1][-1][0] <= 48:
            clusters[-1].append((w, n))
        else:
            clusters.append([(w, n)])
    reps = [max(c, key=lambda t: t[1])[0] for c in clusters if sum(n for _, n in c) >= 2]
    if len(reps) > 1 and max(reps) - min(reps) > 64:
        out.append(('4 / 5.1', f'Контейнеры разной ширины: {", ".join(map(str, reps[:5]))} px — блоки стоят на разных сетках.'))

    # 2.1 число гарнитур
    fams = {}
    for tag, arr in (('H1', d['h1']), ('H2', d['h2']), ('H3', d['h3']), ('P', d['p'])):
        for e in arr:
            if e.get('font'): fams.setdefault(e['font'], 0)
            if e.get('font'): fams[e['font']] += 1
    btn_fonts = {b.get('font') for b in d['buttons'] if b.get('font') and b.get('text')}
    allf = set(fams) | btn_fonts
    if len(allf) >= 3:
        out.append(('2.1', f'Гарнитур в макете {len(allf)}: {", ".join(sorted(allf))} — норма одна гарнитура в разных начертаниях или две согласованные.'))

    # мобильное
    if m is not d and m.get('viewport'):
        if len(m.get('h1', [])) > 1:
            out.append(('3.1', f'На мобильном H1 тоже {len(m["h1"])}.'))
        for b in m.get('buttons', [])[:6]:
            if b['width'] and b['width'] < 90 and b['text'] and len(b['text']) > 12:
                out.append(('8.7', f'На мобильном кнопка {b["width"]}px с текстом {len(b["text"])} знаков: «{b["text"][:30]}» — сжата.'))
                break
    return out

if __name__ == '__main__':
    d = sys.argv[1]
    res = rules(load(d))
    if not res:
        print('Автопроверка нарушений не нашла — смотри скриншоты вручную.')
    for code, text in res:
        print(f'[{code}] {text}')
