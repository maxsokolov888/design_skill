#!/usr/bin/env python3
"""Черновик человеческого отчёта по разбору сайта.

  python3 report.py <findings.json> <annotated.json> [report.md]

Берёт находки (check.py --json, после ручной правки) и снимки с кружками
(annotate.js) и собирает report.md: резюме, что хорошо, главное, разбор по
снимкам сверху вниз — номер сноски совпадает с номером кружка, — общее по
странице и короткое техническое приложение с номерами правил.
Резюме и «что хорошо» — черновик: агент дописывает их своими словами,
посмотрев на снимки (шаблон — references/report-template.md)."""
import json, sys, os, datetime

VP_RU = {'desktop': 'на компьютере', 'mobile': 'на телефоне'}
VP_HEAD = {'desktop': 'На компьютере (ширина 1440 px)', 'mobile': 'На телефоне (ширина 390 px)'}

def low(s):
    return s[:1].lower() + s[1:] if s else s

def block(f, other_vp=None):
    sev = {3: 'важно', 2: 'заметно', 1: 'мелочь'}.get(f.get('severity', 1), 'мелочь')
    lines = [f'**{f["n"]}. {f["title"]}** · {f["where"]} · _{sev}_', '']
    lines.append(f'{f["what"]} {f["why"]}'.strip())
    lines.append('')
    lines.append(f'Как исправить: {low(f["fix"])}' if f.get('fix') else '')
    if other_vp:
        lines.append('')
        lines.append(f'_То же {VP_RU[other_vp]} — кружок {f["n"]} на снимке ниже._' if other_vp == 'mobile' else f'_То же {VP_RU[other_vp]}._')
    return '\n'.join(l for l in lines) + '\n'

def main():
    fpath, apath = sys.argv[1], sys.argv[2]
    out = sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.dirname(apath) or '.', 'report.md')
    data = json.load(open(fpath)); ann = json.load(open(apath))
    fs = sorted(data['findings'], key=lambda f: f['n'])
    views = ann.get('views', {})
    byn = {f['n']: f for f in fs}
    located = [f for f in fs if f.get('scope') != 'page']
    general = [f for f in fs if f.get('scope') == 'page']
    important = sorted(fs, key=lambda f: (-f.get('severity', 1), f['n']))[:3]
    n3 = sum(1 for f in fs if f.get('severity') == 3)

    md = []
    title = data.get('title') or data.get('url')
    md.append(f'# Разбор дизайна: {title}\n')
    md.append(f'Сайт: {data.get("url")}  \nДата разбора: {datetime.date.today().strftime("%d.%m.%Y")}. '
              f'Страница снята целиком на компьютере (1440 px) и на телефоне (390 px). '
              f'Красный кружок с цифрой на снимке — это сноска с тем же номером в тексте.\n')
    md.append('## Коротко\n')
    md.append(f'Замечаний: {len(fs)}, из них важных: {n3}. Главное: ' +
              '; '.join(f'{low(f["title"])} ({f["n"]})' for f in important) + '.\n')
    md.append('<!-- Агент: замени абзац выше на 2–3 своих предложения: общее впечатление и три главные проблемы. -->\n')
    if data.get('good'):
        md.append('## Что сделано хорошо\n')
        md += [f'- {g}' for g in data['good']]
        md.append('')
    md.append('## Исправить в первую очередь\n')
    md += [f'{i}. {f["title"]} — сноска {f["n"]}.' for i, f in enumerate(important, 1)]
    md.append('')

    shown = set(); echoed = set()
    for vp in ('desktop', 'mobile'):
        v = views.get(vp)
        if not v: continue
        md.append(f'## {VP_HEAD[vp]}\n')
        for i, part in enumerate(v['parts'], 1):
            md.append(f'![{VP_RU[vp].capitalize()}, часть {i} из {len(v["parts"])}]({part["file"]})\n')
            for n in part['numbers']:
                f = byn.get(n)
                if not f or n in shown: 
                    if f and vp == 'mobile' and n in shown and n not in echoed:
                        echoed.add(n)
                        md.append(f'_Кружок {n} — то же, что в сноске {n} выше: {low(f["title"])}._\n')
                    continue
                other = [x for x in f.get('viewports', []) if x != vp]
                md.append(block(f, other[0] if other else None))
                shown.add(n)
    # то, что не попало ни на один снимок (селектор не нашёлся и нет координат)
    rest = [f for f in located if f['n'] not in shown]
    if rest:
        md.append('## Без отметки на снимке\n')
        md.append('Эти места не удалось отметить кружком (элемент появляется только при действии посетителя или скрыт). Найди их по описанию.\n')
        md += [block(f) for f in rest]
    if general:
        md.append('## По всей странице\n')
        md.append('Эти замечания касаются сайта целиком, поэтому кружка у них нет.\n')
        md += [block(f) for f in general]
    md.append('---\n')
    md.append('<details><summary>Техническое приложение: номера правил design-skill</summary>\n')
    md.append('| Сноска | Правило | Где замерено |')
    md.append('|---|---|---|')
    for f in fs:
        md.append(f'| {f["n"]} | {f["rule"]} | {", ".join(VP_RU[x] for x in f.get("viewports", [])) or "—"} |')
    md.append('\n</details>\n')
    open(out, 'w').write('\n'.join(md))
    print('отчёт:', out)

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(2)
    main()
