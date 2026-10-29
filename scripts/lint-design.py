#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lint-design.py — статический линтер дизайна. Без браузера, без зависимостей.

    python3 lint-design.py index.html
    python3 lint-design.py index.html --greyscale
    python3 lint-design.py index.html --css extra.css --json

Проверяет:
  · кегли вне шкалы 12/14/16/20/32/40/48/56        10.6, DESIGN-RULES 4
  · отступы не кратные 8                            10.18
  · радиусы вне набора 0/12/16/24/капсула            8.8
  · больше пяти разных кеглей на странице           10.6
  · нет h1 / больше одного h1                       3.1
  · перескок уровня заголовка                       3.2
  · кегль подписи в кнопке вне 14–16                8.4
  · пропорция отступов кнопки не 1,5–2 : 1          8.6
  · базовый кегль мельче 13 px                      10.5
  · второй font-family                              2.1
  · контраст пар текст/фон для простых цветов      10.22
  · цветная заливка и тени при --greyscale          1.1, 1.14

Вывод — список кандидатов с номером правила. Это не приговор: кандидат
перепроверяется по скриншоту, ложный отбрасывается с причиной.

Работает на `<style>` в файле, на инлайн-стилях `style="…"`, на подключённых
локальных `<link rel=stylesheet>` и на файлах из `--css`. Понимает CSS-переменные
(`var(--x)` разворачивается), `@media` (кегли внутри медиа-запросов не
суммируются в счётчик страницы).

Код возврата: 0 — замечаний нет, 1 — есть, 2 — ошибка входа.
"""
import sys, os, re, json, argparse
from collections import Counter

# ── Эталоны из нормативa ────────────────────────────────────────────────────

# Восемь пар шкалы: кегль → интерлиньяж (DESIGN-RULES.md, раздел 4).
SCALE = {56: 64, 48: 56, 40: 48, 32: 40, 20: 28, 16: 24, 14: 20, 12: 16}
SCALE_SIZES = set(SCALE)

# Шкала отступов, кратная 8 (10.18). 20 — размер B из правила 8.6,
# 240 — верхняя граница отступа между секциями (10.15).
SPACE_SCALE = {8, 16, 20, 24, 32, 40, 48, 64, 80, 96, 120, 160, 240}

# Набор радиусов (8.8): 0, 12, 16, 24, капсула.
RADII = {0, 12, 16, 24}
PILL_FROM = 100

# Кегль кнопки (8.4) и минимум для смыслового текста (10.5).
BTN_MIN, BTN_MAX = 14, 16
TEXT_MIN = 13

# Контраст (10.22). Крупный — от 24 px или от 18.66 px при весе ≥ 700.
CONTRAST_NORMAL = 4.5
CONTRAST_LARGE = 3.0
LARGE_PX = 24.0
LARGE_PX_BOLD = 18.66

# Оптическая правка 1–2 px (DESIGN-RULES, раздел 3) и мелкие зазоры.
SPACE_TOLERANCE = {1, 2, 3, 4, 5, 6}

CSS_LEN = re.compile(r'(-?\d*\.?\d+)\s*(px|rem|em|pt)?', re.I)
HEX = re.compile(r'#([0-9a-fA-F]{3,8})\b')
RGB = re.compile(r'rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:[\s,/]+([\d.]+%?))?\s*\)', re.I)
NAMED = {
    'black': (0, 0, 0), 'white': (255, 255, 255), 'red': (255, 0, 0),
    'blue': (0, 0, 255), 'green': (0, 128, 0), 'yellow': (255, 255, 0),
    'gray': (128, 128, 128), 'grey': (128, 128, 128), 'silver': (192, 192, 192),
}

TAG = re.compile(r'<([a-zA-Z][\w:-]*)((?:[^>"\']|"[^"]*"|\'[^\']*\')*)>', re.S)
ATTR = re.compile(r'([:\w-]+)\s*=\s*"([^"]*)"|([:\w-]+)\s*=\s*\'([^\']*)\'', re.S)
COMMENT = re.compile(r'<!--.*?-->', re.S)


def px(value, base=16.0):
    """CSS-длина в px. rem/em считаются от base; % и vw не считаются (None)."""
    m = CSS_LEN.match(str(value).strip())
    if not m:
        return None
    num = float(m.group(1))
    unit = (m.group(2) or 'px').lower()
    if unit == 'px':
        return num
    if unit in ('rem', 'em'):
        return num * base
    if unit == 'pt':
        return num * 4 / 3
    return None


# ── Цвет и контраст ────────────────────────────────────────────────────────

def parse_color(text):
    """(r, g, b) или None. Понимает #hex, rgb(), rgba(), имена."""
    if not text:
        return None
    t = re.sub(r'\s*!important\s*$', '', str(text).strip().lower())
    if t in ('transparent', 'inherit', 'currentcolor', 'initial', 'unset',
             'none', 'revert', 'auto'):
        return None
    if t in NAMED:
        return NAMED[t]
    m = HEX.fullmatch(t)
    if m:
        h = m.group(1)
        if len(h) == 3:
            return tuple(int(c * 2, 16) for c in h)
        if len(h) == 4:
            return tuple(int(c * 2, 16) for c in h[:3])
        if len(h) == 6:
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
        if len(h) == 8:
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    m = RGB.search(t)
    if m:
        try:
            rgb = tuple(int(round(float(m.group(i)))) for i in (1, 2, 3))
        except ValueError:
            return None
        return tuple(max(0, min(255, c)) for c in rgb)
    return None


def luminance(rgb):
    def ch(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def chromatic(rgb):
    """>2 — как в library.py: разброс каналов больше 2 значит цвет."""
    return rgb is not None and (max(rgb) - min(rgb)) > 2


# ── Разбор HTML ────────────────────────────────────────────────────────────

VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
        'meta', 'param', 'source', 'track', 'wbr'}


def attrs_of(raw):
    out = {}
    for m in ATTR.finditer(raw or ''):
        k = (m.group(1) or m.group(3) or '').lower()
        v = m.group(2) if m.group(1) else m.group(4)
        if k:
            out[k] = v if v is not None else ''
    return out


def parse_html(text):
    """(tags, styles, links). tags — [(name, attrs)] в порядке следования."""
    text = COMMENT.sub('', text)
    styles = [m.group(1) for m in re.finditer(r'<style[^>]*>(.*?)</style>', text, re.S | re.I)]
    tags, links = [], []
    for m in TAG.finditer(text):
        name = m.group(1).lower()
        a = attrs_of(m.group(2))
        tags.append((name, a))
        if name == 'link' and 'stylesheet' in a.get('rel', '').lower():
            href = a.get('href', '')
            if href and not re.match(r'^(https?:)?//', href):
                links.append(href)
    return tags, styles, links


def parse_decls(block):
    """CSS-блок деклараций → [(prop, value)]. Скобки внутри значений учитываются."""
    out = []
    for chunk in re.split(r';(?![^(]*\))', block):
        if ':' not in chunk:
            continue
        prop, _, val = chunk.partition(':')
        prop, val = prop.strip().lower(), val.strip()
        if not prop or not val:
            continue
        # выкидываем мусор от вложенных селекторов
        if '{' in prop or '}' in prop:
            continue
        out.append((prop, val))
    return out


def parse_css(css):
    """[(selector, decls, in_media)].

    @media/@supports/@layer/@container/@scope — обёртки: правила внутри
    помечаются in_media=True, чтобы счётчик кеглей не складывал десктоп
    и мобильный как одну страницу. @font-face и @keyframes пропускаются.
    """
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    out = []

    def skip_block(i):
        depth = 1
        while i < len(css) and depth:
            if css[i] == '{':
                depth += 1
            elif css[i] == '}':
                depth -= 1
            i += 1
        return i

    def walk(i, in_media):
        while i < len(css):
            j = css.find('{', i)
            k = css.find('}', i)
            if j == -1 and k == -1:
                return len(css)
            if k != -1 and (j == -1 or k < j):
                return k + 1
            header = css[i:j].strip()
            if header.startswith('@'):
                at = header.split()[0].lower()
                if at.split('@')[-1] in ('media', 'supports', 'layer', 'container', 'scope'):
                    i = walk(j + 1, True)
                else:
                    i = skip_block(j + 1)
            else:
                m = css.find('}', j)
                if m == -1:
                    m = len(css)
                if header:
                    out.append((header, parse_decls(css[j + 1:m]), in_media))
                i = m + 1
        return i

    walk(0, False)
    return out


def collect_vars(rules):
    """CSS-переменные верхнего уровня. Медиа-оверрайды не берём: шкала одна."""
    vmap = {}
    for sel, decls, in_media in rules:
        if in_media:
            continue
        for prop, val in decls:
            if prop.startswith('--'):
                vmap[prop] = val
    return vmap


def resolve_var(value, vmap, depth=0):
    """Разворачивает var(--x[, fallback]) до трёх уровней."""
    if depth > 3 or 'var(' not in value:
        return value

    def sub(m):
        name = m.group(1).strip()
        fb = m.group(2)
        if name in vmap:
            return vmap[name]
        return fb.strip() if fb else ''

    out = re.sub(r'var\(\s*(--[\w-]+)\s*(?:,([^()]*))?\)', sub, value)
    return resolve_var(out, vmap, depth + 1)


# ── Находки ────────────────────────────────────────────────────────────────

class Finding:
    __slots__ = ('rule', 'where', 'text')

    def __init__(self, rule, where, text):
        self.rule, self.where, self.text = rule, where, text


def page_index(tags):
    """Что реально есть на странице: теги, классы, id."""
    names = {n for n, _ in tags}
    classes, ids = set(), set()
    for _, a in tags:
        for c in (a.get('class') or '').split():
            classes.add(c)
        if a.get('id'):
            ids.add(a['id'])
    return names, classes, ids


COMPOUND = re.compile(r'([a-zA-Z][\w-]*)?((?:[.#][\w-]+)*)$')


def selector_may_match(sel, index):
    """Может ли селектор зацепить хоть один элемент страницы.

    Проверяется только последний составной селектор (после пробела, >, +, ~):
    он и определяет, есть ли на странице подходящий элемент. Псевдоклассы и
    псевдоэлементы отбрасываются. Если разобрать не удалось — считаем, что
    может: линтер не должен молчать из-за сложного селектора.
    """
    names, classes, ids = index
    last = re.split(r'[\s>+~]+', sel.strip())[-1] if sel.strip() else ''
    last = re.sub(r'::?[\w-]+(\([^)]*\))?', '', last)
    if not last:
        return True
    m = COMPOUND.match(last)
    if not m:
        return True
    tag, rest = m.group(1), m.group(2) or ''
    if tag and tag.lower() not in names:
        return False
    for token in re.findall(r'[.#][\w-]+', rest):
        if token[0] == '.' and token[1:] not in classes:
            return False
        if token[0] == '#' and token[1:] not in ids:
            return False
    return True


def live_rules(rules, index):
    """Правила, чей селектор вообще может сработать на этой странице."""
    out = []
    for sel, decls, in_media in rules:
        for one in sel.split(','):
            if selector_may_match(one, index):
                out.append((sel, decls, in_media))
                break
    return out



# ── Проверки ───────────────────────────────────────────────────────────────

def check_font_sizes(rules, vmap, findings):
    """Кегли вне шкалы и число разных кеглей на странице (10.6)."""
    sizes = Counter()
    for sel, decls, in_media in rules:
        for prop, val in decls:
            if prop not in ('font-size', 'font'):
                continue
            text = resolve_var(val, vmap)
            v = px(text)
            if v is None:
                m = re.search(r'(\d*\.?\d+)\s*(px|rem|em|pt)\b', text)
                v = px(m.group(0)) if m else None
            if v is None or v <= 0:
                continue
            iv = int(round(v))
            if iv not in SCALE_SIZES:
                findings.append(Finding(
                    '10.6', sel,
                    'кегль %d px вне шкалы 12/14/16/20/32/40/48/56 '
                    '(ближайшая ступень %d)'
                    % (iv, min(SCALE_SIZES, key=lambda x: abs(x - iv)))))
            if not in_media:
                sizes[iv] += 1
    distinct = set(sizes)
    if len(distinct) > 5:
        findings.append(Finding(
            '10.6', 'страница',
            'разных кеглей %d (%s) — потолок 5: display, заголовок, лид, текст, мелкий'
            % (len(distinct), ', '.join(str(s) for s in sorted(distinct)))))


def check_spacing(rules, vmap, findings):
    """Отступы не кратные 8 (10.18)."""
    props = ('padding', 'padding-top', 'padding-right', 'padding-bottom',
             'padding-left', 'padding-inline', 'padding-block',
             'margin', 'margin-top', 'margin-right', 'margin-bottom',
             'margin-left', 'margin-inline', 'margin-block',
             'gap', 'row-gap', 'column-gap')
    for sel, decls, in_media in rules:
        for prop, val in decls:
            if prop not in props:
                continue
            for raw in re.split(r'\s+', resolve_var(val, vmap).strip()):
                if raw in ('auto', '0', '0px', 'inherit', 'initial', 'unset', 'revert'):
                    continue
                v = px(raw)
                if v is None:
                    continue
                iv = int(round(v))
                if iv == 0 or iv in SPACE_SCALE or iv in SPACE_TOLERANCE:
                    continue
                findings.append(Finding(
                    '10.18', sel,
                    '%s: %s — не из шкалы, кратной 8 '
                    '(8/16/24/32/40/48/64/80/96/120/160)' % (prop, raw)))


def check_radii(rules, vmap, findings):
    """Радиусы вне набора 0/12/16/24/капсула (8.8)."""
    for sel, decls, in_media in rules:
        for prop, val in decls:
            if not prop.startswith('border') or 'radius' not in prop:
                continue
            for raw in re.split(r'\s+', resolve_var(val, vmap).strip()):
                if raw in ('0', 'inherit', 'initial', 'unset'):
                    continue
                if raw.strip() == '50%':
                    continue                      # круг в квадрате — это капсула
                if '%' in raw:
                    findings.append(Finding(
                        '8.8', sel, 'радиус %s — вне набора 0/12/16/24/капсула' % raw))
                    continue
                v = px(raw)
                if v is None:
                    continue
                if v >= PILL_FROM:
                    continue                      # капсула
                iv = round(v, 1)
                if iv in RADII:
                    continue
                findings.append(Finding(
                    '8.8', sel, 'радиус %g px — вне набора 0/12/16/24/капсула' % iv))


def check_headings(tags, findings):
    """h1 ровно один (3.1), уровни без перескоков (3.2)."""
    heads = [n for n, _ in tags if re.fullmatch(r'h[1-6]', n)]
    h1 = heads.count('h1')
    if h1 == 0:
        findings.append(Finding('3.1', 'структура',
                                'на странице нет h1 — главного заголовка нет в разметке'))
    elif h1 > 1:
        findings.append(Finding('3.1', 'структура',
                                'h1 на странице %d — норма ровно один' % h1))
    prev = None
    for name in heads:
        lv = int(name[1])
        if prev is not None and lv > prev + 1:
            findings.append(Finding(
                '3.2', name,
                'перескок уровня: после h%d идёт h%d — иерархия читается '
                'как набор размеров' % (prev, lv)))
            break
        prev = lv


def check_buttons(rules, vmap, findings):
    """Кегль подписи кнопки 14–16 (8.4) и пропорция отступов 1,5–2 : 1 (8.6)."""
    for sel, decls, in_media in rules:
        if not re.search(r'btn|button|cta', sel.lower()):
            continue
        for prop, val in decls:
            if prop == 'font-size':
                v = px(resolve_var(val, vmap))
                if v is None:
                    continue
                iv = int(round(v))
                if iv < BTN_MIN or iv > BTN_MAX:
                    findings.append(Finding(
                        '8.4', sel,
                        'кегль подписи в кнопке %d px — норма %d–%d'
                        % (iv, BTN_MIN, BTN_MAX)))
            elif prop in ('padding', 'padding-inline', 'padding-block'):
                vals = [px(x) for x in re.split(r'\s+', resolve_var(val, vmap).strip())
                        if px(x) is not None]
                if len(vals) >= 2 and vals[0] and vals[1]:
                    py, px_ = vals[0], vals[1]
                    if not (1.4 <= px_ / py <= 2.2):
                        findings.append(Finding(
                            '8.6', sel,
                            'отступы кнопки %g / %g — горизонтальный должен быть '
                            'в 1,5–2 раза больше вертикального' % (px_, py)))


def check_font_families(rules, vmap, findings):
    """Вторая гарнитура (2.1)."""
    fams = set()
    for sel, decls, in_media in rules:
        for prop, val in decls:
            if prop not in ('font-family', 'font'):
                continue
            text = resolve_var(val, vmap)
            if prop == 'font':
                m = re.search(
                    r'\d(?:px|rem|em)\s*(?:/\s*[\d.]+(?:px|rem|em)?)?\s+(.+)$', text)
                if not m:
                    continue                     # шорткат без размера — не семейство
                text = m.group(1)
            first = text.split(',')[0].strip().strip('"\'')
            if first and first.lower() not in ('inherit', 'initial', 'unset', 'var'):
                fams.add(first.lower())
    if len(fams) > 2:
        findings.append(Finding(
            '2.1', 'шрифты',
            'гарнитур %d: %s — норма одна в разных начертаниях или две согласованные'
            % (len(fams), ', '.join(sorted(fams)))))


def check_contrast(rules, vmap, findings):
    """Контраст пар текст/фон для простых цветов (10.22).

    Пара берётся из одного правила (color + background) или от фона
    body/:root/html, если задан только цвет. Это кандидат: реальный фон
    может приходить от родителя — подтверждать сэмплом пикселей.
    """
    root_bg = None
    for sel, decls, in_media in rules:
        if re.fullmatch(r'\s*(:root|html|body)\s*', sel):
            for prop, val in decls:
                if prop in ('background', 'background-color'):
                    c = parse_color(resolve_var(val, vmap).strip().split()[0])
                    if c:
                        root_bg = c

    for sel, decls, in_media in rules:
        fg = bg = size = None
        weight = 400
        for prop, val in decls:
            text = resolve_var(val, vmap).strip()
            if prop == 'color':
                fg = parse_color(text)
            elif prop in ('background', 'background-color'):
                bg = parse_color(text.split()[0]) if text else None
            elif prop == 'font-size':
                size = px(text)
            elif prop == 'font-weight':
                try:
                    weight = int(text)
                except ValueError:
                    weight = 700 if text in ('bold', 'bolder') else 400
        if not fg:
            continue
        base = bg or root_bg
        if not base or fg == base:
            continue
        ratio = contrast(fg, base)
        large = bool(size and (size >= LARGE_PX or
                               (size >= LARGE_PX_BOLD and weight >= 700)))
        limit = CONTRAST_LARGE if large else CONTRAST_NORMAL
        if ratio < limit:
            note = '' if ratio >= 2.6 else \
                ' (ниже 2,6:1 — провал, который нельзя объяснить стилем)'
            findings.append(Finding(
                '10.22', sel,
                'контраст %.2f:1 между текстом и фоном — норма %.1f:1 для %s текста%s'
                % (ratio, limit, 'крупного' if large else 'обычного', note)))


def check_body_size(rules, vmap, findings):
    """Базовый кегль не мельче 13 px (10.5)."""
    for sel, decls, in_media in rules:
        if not re.fullmatch(r'\s*(body|html|:root)\s*', sel):
            continue
        for prop, val in decls:
            if prop != 'font-size':
                continue
            v = px(resolve_var(val, vmap))
            if v is not None and 0 < v < TEXT_MIN:
                findings.append(Finding(
                    '10.5', sel,
                    'базовый кегль %g px — смысловой текст мельче %d px не набирается'
                    % (v, TEXT_MIN)))


def check_greyscale(rules, tags, vmap, findings):
    """Цветная заливка и тени при --greyscale (1.1, 1.14)."""
    shown = 0
    for sel, decls, in_media in rules:
        for prop, val in decls:
            text = resolve_var(val, vmap)
            if prop in ('box-shadow', 'text-shadow'):
                if text.strip() not in ('none', ''):
                    findings.append(Finding(
                        '1.14', sel,
                        '%s: %s — тени в прототипе запрещены' % (prop, text[:48])))
                continue
            if prop not in ('background', 'background-color', 'color', 'border',
                            'border-color', 'fill', 'stroke', 'background-image'):
                continue
            for raw in re.findall(r'#[0-9a-fA-F]{3,8}|rgba?\([^)]*\)', text):
                c = parse_color(raw)
                if c and chromatic(c):
                    shown += 1
                    if shown <= 8:
                        findings.append(Finding(
                            '1.1', sel,
                            '%s: %s — цвет с насыщенностью, в прототипе только '
                            'серые тона (R = G = B)' % (prop, raw)))
                    break
    for name, attrs in tags:
        st = attrs.get('style')
        if not st:
            continue
        for prop, val in parse_decls(st):
            if prop in ('box-shadow', 'text-shadow') and val.strip() != 'none':
                findings.append(Finding('1.14', '<%s style>' % name,
                                        'тень в инлайн-стиле: %s' % val[:48]))
            for raw in re.findall(r'#[0-9a-fA-F]{3,8}|rgba?\([^)]*\)', val):
                c = parse_color(raw)
                if c and chromatic(c):
                    findings.append(Finding(
                        '1.1', '<%s style>' % name,
                        '%s: %s — цвет с насыщенностью в прототипе' % (prop, raw)))
                    break
    if shown > 8:
        findings.append(Finding('1.1', 'страница',
                                'ещё %d цветных объявлений сверх показанных'
                                % (shown - 8)))


def check_inline_styles(tags, vmap, findings):
    """Инлайн-стили проходят те же проверки, что и <style>."""
    for name, attrs in tags:
        st = attrs.get('style')
        if not st:
            continue
        one = [('<%s style>' % name, parse_decls(st), False)]
        check_font_sizes(one, vmap, findings)
        check_spacing(one, vmap, findings)
        check_radii(one, vmap, findings)


# ── Проход ─────────────────────────────────────────────────────────────────

def lint(path, greyscale=False, extra_css=()):
    with open(path, encoding='utf-8', errors='replace') as f:
        html = f.read()
    tags, styles, links = parse_html(html)

    css_sources = list(styles)
    base = os.path.dirname(os.path.abspath(path))
    for href in links:
        p = os.path.join(base, href)
        if os.path.isfile(p):
            css_sources.append(open(p, encoding='utf-8', errors='replace').read())
    for p in extra_css:
        if os.path.isfile(p):
            css_sources.append(open(p, encoding='utf-8', errors='replace').read())

    rules = []
    for st in css_sources:
        rules.extend(parse_css(st))
    vmap = collect_vars(rules)

    index = page_index(tags)
    live = live_rules(rules, index)

    findings = []
    check_font_sizes(live, vmap, findings)
    check_spacing(live, vmap, findings)
    check_radii(live, vmap, findings)
    check_headings(tags, findings)
    check_buttons(live, vmap, findings)
    check_font_families(live, vmap, findings)
    check_contrast(live, vmap, findings)
    check_body_size(live, vmap, findings)
    check_inline_styles(tags, vmap, findings)
    if greyscale:
        check_greyscale(live, tags, vmap, findings)

    seen, uniq = set(), []
    for f in findings:
        k = (f.rule, f.where, f.text)
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    return uniq


def rule_key(rule):
    return [int(x) if x.isdigit() else 999 for x in re.split(r'[./]', rule)]


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='Статический линтер дизайна по нормативу. Без браузера и зависимостей.')
    ap.add_argument('file', help='HTML-файл')
    ap.add_argument('--greyscale', action='store_true',
                    help='режим прототипа: цветная заливка и тени — ошибка')
    ap.add_argument('--css', action='append', default=[],
                    help='дополнительный CSS-файл (можно несколько раз)')
    ap.add_argument('--json', action='store_true', help='вывод в JSON')
    args = ap.parse_args(argv)

    if not os.path.isfile(args.file):
        print('файл не найден: %s' % args.file, file=sys.stderr)
        return 2

    findings = lint(args.file, greyscale=args.greyscale, extra_css=args.css)

    if args.json:
        print(json.dumps([{'rule': f.rule, 'where': f.where, 'text': f.text}
                          for f in findings], ensure_ascii=False, indent=1))
        return 1 if findings else 0

    print('lint-design: %s%s' % (args.file, ' (greyscale)' if args.greyscale else ''))
    if not findings:
        print('замечаний нет.')
        return 0

    print('кандидатов: %d\n' % len(findings))
    by_rule = {}
    for f in findings:
        by_rule.setdefault(f.rule, []).append(f)
    for rule in sorted(by_rule, key=rule_key):
        print('правило %s:' % rule)
        for f in by_rule[rule]:
            print('  · %s — %s' % (f.where, f.text))
        print()
    print('Это кандидаты, а не приговор: каждый подтверждается скриншотом, '
          'ложный отбрасывается с причиной.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
