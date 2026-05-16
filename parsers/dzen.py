import datetime
import re
from urllib.parse import urljoin, urlparse
import feedparser
import requests
from bs4 import BeautifulSoup

from data import db_session
from data.news import NewsItem
from data.sources import Source
from services.openrouter import classify as ai_classify

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
SKIP_PATH_RE = re.compile(
    r'/(login|signin|signup|register|auth|account|profile|subscribe|subscription|'
    r'tag|tags|category|categories|author|authors|search|privacy|terms|about|contacts?|'
    r'advertis|promo|press-release|rss|feed)(/|$)',
    re.I,
)
SKIP_EXT_RE = re.compile(r'\.(jpg|jpeg|png|gif|webp|svg|pdf|zip|rar|7z|mp3|mp4|avi|mov|css|js)$', re.I)

DEFAULT_SOURCES = [
    ('Telegram', 'telegram', 'https://t.me/telegram', 'TG'),
    ('РИА Культура', 'website', 'https://ria.ru/culture/', '📰'),
    ('Lenta.ru', 'website', 'https://lenta.ru/', '📰'),
]

def _detect_topic(text):
    t = text.lower()
    rules = [
        ('technology', r'технолог|приложен|айфон|apple|google|чип|нейросет|искусствен'),
        ('science', r'учён|исследовани|открыт|космос|spacex|nasa'),
        ('business', r'рынок|акци|биржа|s&p|нефть|долл|евро|рубл|инвест'),
        ('sports', r'хокке|футбол|олимп|чемпионат|матч|спорт'),
        ('health', r'вакцин|болезн|медицин|здоров|covid|вирус'),
        ('culture', r'театр|балет|выставк|живопис|скульпт|художник|литератур'),
        ('entertainment', r'фильм|кино|музык|концерт|сериал|netflix|шоу|режиссёр|актёр'),
        ('politics', r'президент|госдум|кремл|санкци|выбор|политик|премьер'),
        ('world', r'сша|китай|европ|нато|оон|g7|g20'),
    ]
    for tid, pattern in rules:
        if re.search(pattern, t):
            return tid
    return 'world'

def _clean_text(value):
    return re.sub(r'\s+', ' ', value or '').strip()

def _absolute_url(base_url, href):
    if not href:
        return ''
    href = href.strip()
    if href.startswith(('javascript:', 'mailto:', 'tel:', '#')):
        return ''
    return urljoin(base_url, href)

def _is_probable_article_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        return False
    if SKIP_EXT_RE.search(parsed.path) or SKIP_PATH_RE.search(parsed.path):
        return False
    return True

def _meta_content(soup, *keys):
    for key in keys:
        tag = soup.find('meta', attrs={'property': key}) or soup.find('meta', attrs={'name': key})
        if tag and tag.get('content'):
            return _clean_text(tag['content'])
    return ''

def _published_from_soup(soup):
    value = _meta_content(soup, 'article:published_time', 'datePublished', 'date',
                          'pubdate', 'publishdate', 'timestamp')
    if value:
        try:
            return datetime.datetime.fromisoformat(value.replace('Z', '+00:00')).replace(tzinfo=None)
        except Exception:
            pass
    time_el = soup.select_one('time[datetime]')
    if time_el and time_el.get('datetime'):
        try:
            return datetime.datetime.fromisoformat(
                time_el['datetime'].replace('Z', '+00:00')
            ).replace(tzinfo=None)
        except Exception:
            pass
    return datetime.datetime.now()

def _discover_feed_urls(page_url, soup):
    urls = []
    for link in soup.select('link[rel~="alternate"][href]'):
        type_ = (link.get('type') or '').lower()
        if 'rss' in type_ or 'atom' in type_ or 'xml' in type_:
            urls.append(urljoin(page_url, link['href']))
    for a in soup.select('a[href]'):
        href = a.get('href') or ''
        text = _clean_text(a.get_text(' ', strip=True)).lower()
        if any(m in href.lower() for m in ('rss', 'feed', 'atom.xml', 'feed.xml')) or 'rss' in text:
            urls.append(urljoin(page_url, href))
    return list(dict.fromkeys(urls))[:3]

def _parse_rss(source, feed_url=None):
    feed = feedparser.parse(feed_url or source.url, agent=UA)
    out = []
    for e in feed.entries[:20]:
        title = _clean_text(e.get('title'))
        link = e.get('link', '')
        if not title or not link:
            continue
        summary_html = e.get('summary') or e.get('description') or ''
        summary = _clean_text(BeautifulSoup(summary_html, 'html.parser').get_text(' ', strip=True))
        published = (datetime.datetime(*e.published_parsed[:6])
                     if e.get('published_parsed') else datetime.datetime.now())
        out.append({
            'title': title[:300],
            'summary': summary[:500],
            'full_text': summary,
            'source': source.name,
            'source_type': source.type,
            'source_icon': source.icon or '📰',
            'topic': _detect_topic(f'{title} {summary}'),
            'url': link,
            'published_at': published,
        })
    return out

def _score_link(a, url, base_netloc):
    title = _clean_text(a.get_text(' ', strip=True))
    parsed = urlparse(url)
    path = parsed.path.lower()
    score = 0
    if parsed.netloc == base_netloc:
        score += 2
    if 25 <= len(title) <= 180:
        score += 5
    elif 15 <= len(title) < 25:
        score += 1
    if re.search(r'/\d{4}/|\d{4}[-/]\d{2}[-/]\d{2}|/(news|article|story|post|posts|blog|world|tech|politics|business|sport)/', path):
        score += 3
    if a.find_parent('article'):
        score += 3
    if a.find_parent(['h1', 'h2', 'h3']):
        score += 2
    if len(path.strip('/').split('/')) >= 2:
        score += 1
    return score

def _fallback_article(source, url, fallback_title='', fallback_summary=''):
    title = _clean_text(fallback_title)
    if not title:
        return None
    summary = _clean_text(fallback_summary) or title
    return {
        'title': title[:300],
        'summary': summary[:500],
        'full_text': summary[:3000],
        'source': source.name,
        'source_type': source.type,
        'source_icon': source.icon or '📰',
        'topic': _detect_topic(f'{title} {summary}'),
        'url': url,
        'published_at': datetime.datetime.now(),
    }

def _extract_article(source, url, fallback_title='', fallback_summary=''):
    try:
        r = requests.get(url, headers={'User-Agent': UA}, timeout=10)
        r.raise_for_status()
    except Exception:
        return _fallback_article(source, url, fallback_title, fallback_summary)

    soup = BeautifulSoup(r.text, 'html.parser')
    for tag in soup(['script', 'style', 'noscript', 'svg', 'form']):
        tag.decompose()

    title = (
        _meta_content(soup, 'og:title', 'twitter:title')
        or _clean_text(soup.h1.get_text(' ', strip=True) if soup.h1 else '')
        or _clean_text(soup.title.get_text(' ', strip=True) if soup.title else '')
        or _clean_text(fallback_title)
    )
    if not title or len(title) < 12:
        return None

    summary = _meta_content(soup, 'og:description', 'twitter:description', 'description')
    article = soup.find('article') or soup.find('main') or soup.body
    paragraphs = []
    if article:
        for p in article.find_all('p'):
            text = _clean_text(p.get_text(' ', strip=True))
            if len(text) >= 40:
                paragraphs.append(text)
            if len(' '.join(paragraphs)) >= 900:
                break
    full_text = _clean_text(' '.join(paragraphs)) or summary or _clean_text(fallback_summary) or title
    summary = summary or full_text[:500]

    return {
        'title': title[:300],
        'summary': summary[:500],
        'full_text': full_text[:3000],
        'source': source.name,
        'source_type': source.type,
        'source_icon': source.icon or '📰',
        'topic': _detect_topic(f'{title} {summary}'),
        'url': url,
        'published_at': _published_from_soup(soup),
    }

def _parse_html(source):
    try:
        r = requests.get(source.url, headers={'User-Agent': UA}, timeout=10)
        r.raise_for_status()
    except Exception:
        return []
    soup = BeautifulSoup(r.text, 'html.parser')

    for feed_url in _discover_feed_urls(source.url, soup):
        items = _parse_rss(source, feed_url=feed_url)
        if items:
            return items

    for tag in soup(['script', 'style', 'noscript', 'svg', 'form', 'nav', 'header', 'footer', 'aside']):
        tag.decompose()

    base_netloc = urlparse(source.url).netloc
    candidates = []
    seen = set()
    for a in soup.select('a[href]'):
        title = _clean_text(a.get_text(' ', strip=True))
        href = _absolute_url(source.url, a.get('href'))
        if len(title) < 15 or not _is_probable_article_url(href) or href in seen:
            continue
        seen.add(href)
        parent = a.find_parent(['article', 'li', 'section', 'div'])
        parent_text = _clean_text(parent.get_text(' ', strip=True) if parent else title)
        score = _score_link(a, href, base_netloc)
        if score < 4:
            continue
        candidates.append((score, href, title, parent_text))

    candidates.sort(key=lambda item: item[0], reverse=True)
    out = []
    used_urls = set()
    for _, href, title, parent_text in candidates[:25]:
        if href in used_urls:
            continue
        item = _extract_article(source, href, fallback_title=title, fallback_summary=parent_text)
        if not item:
            continue
        used_urls.add(href)
        out.append(item)
        if len(out) >= 15:
            break
    return out

def _telegram_channel_name(value):
    value = (value or '').strip()
    if value.startswith('@'):
        return value[1:].strip('/')
    if not value.startswith(('http://', 'https://')):
        value = 'https://' + value
    parsed = urlparse(value)
    host = parsed.netloc.lower().removeprefix('www.')
    if host not in ('t.me', 'telegram.me'):
        return ''
    parts = [p for p in parsed.path.split('/') if p]
    if not parts:
        return ''
    if parts[0] == 's' and len(parts) > 1:
        name = parts[1].lstrip('@')
        return name if re.fullmatch(r'[A-Za-z0-9_]{5,32}', name) else ''
    if parts[0] in ('c', 'joinchat') or parts[0].startswith('+'):
        return ''
    name = parts[0].lstrip('@')
    return name if re.fullmatch(r'[A-Za-z0-9_]{5,32}', name) else ''

def _telegram_post_url(msg, channel_name):
    link_el = msg.select_one('a.tgme_widget_message_date[href]')
    if link_el and link_el.get('href'):
        return link_el['href'].replace('/s/', '/')
    data_post = (msg.get('data-post') or '').strip()
    if data_post:
        return f'https://t.me/{data_post}'
    return f'https://t.me/{channel_name}' if channel_name else ''

def _telegram_link_preview(msg):
    preview = msg.select_one('a.tgme_widget_message_link_preview[href]')
    if not preview:
        return {'url': '', 'title': '', 'description': ''}
    title_el = preview.select_one('.link_preview_title')
    desc_el = preview.select_one('.link_preview_description')
    return {
        'url': preview.get('href') or '',
        'title': _clean_text(title_el.get_text(' ', strip=True) if title_el else ''),
        'description': _clean_text(desc_el.get_text(' ', strip=True) if desc_el else ''),
    }

def _telegram_text(msg):
    text_el = msg.select_one('.tgme_widget_message_text')
    if not text_el:
        return ''
    for tag in text_el.select('.tgme_widget_message_inline_keyboard, script, style'):
        tag.decompose()
    text = text_el.get_text('\n', strip=True)
    text = re.sub(r'[​‌‍﻿]', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def _telegram_title(text, preview):
    lines = [_clean_text(line) for line in (text or '').splitlines()]
    for line in (line for line in lines if line):
        if len(line) >= 12 and not re.fullmatch(r'[#@][\w_]+', line):
            return line[:240]
    if preview.get('title'):
        return preview['title'][:240]
    compact = _clean_text(text) or preview.get('description') or preview.get('url') or ''
    return compact[:120]

def _telegram_published(msg):
    time_el = msg.select_one('time[datetime]')
    if time_el and time_el.get('datetime'):
        try:
            return datetime.datetime.fromisoformat(
                time_el['datetime'].replace('Z', '+00:00')
            ).replace(tzinfo=None)
        except Exception:
            pass
    return datetime.datetime.now()

def _parse_telegram(source):
    channel_name = _telegram_channel_name(source.url)
    if not channel_name:
        return []
    url = f'https://t.me/s/{channel_name}'
    try:
        r = requests.get(
            url,
            headers={'User-Agent': UA, 'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8'},
            timeout=12,
        )
        r.raise_for_status()
    except Exception as e:
        print(f'[parser] Telegram {source.name}: {e}')
        return []

    soup = BeautifulSoup(r.text, 'html.parser')
    out = []
    seen = set()
    for msg in soup.select('.tgme_widget_message'):
        if msg.select_one('.tgme_widget_message_service'):
            continue
        text = _telegram_text(msg)
        preview = _telegram_link_preview(msg)
        combined = _clean_text(' '.join(
            part for part in (text, preview.get('title'), preview.get('description')) if part
        ))
        if len(combined) < 20:
            continue
        if re.search(r'(^|\s)#?(реклама|advertisement|ad)(\s|$)', combined.lower()):
            continue

        post_url = _telegram_post_url(msg, channel_name) or preview.get('url')
        if not post_url or post_url in seen:
            continue
        seen.add(post_url)

        title = _telegram_title(text, preview)
        summary_parts = [text]
        if preview.get('title') and preview['title'] not in text:
            summary_parts.append(preview['title'])
        if preview.get('description') and preview['description'] not in text:
            summary_parts.append(preview['description'])
        summary = _clean_text(' '.join(part for part in summary_parts if part))
        if not title or len(summary) < 20:
            continue

        full_parts = [text, preview.get('title'), preview.get('description'), preview.get('url')]
        full_text = '\n'.join(part for part in full_parts if part)

        out.append({
            'title': title,
            'summary': summary[:500],
            'full_text': full_text[:3000],
            'source': source.name,
            'source_type': 'telegram',
            'source_icon': source.icon or 'TG',
            'topic': _detect_topic(f'{title} {summary}'),
            'url': post_url,
            'published_at': _telegram_published(msg),
        })

    out.sort(key=lambda x: x['published_at'], reverse=True)
    return out

def _parse_web(source):
    return _parse_rss(source) or _parse_html(source)

def parse_source(source):
    return _parse_telegram(source) if source.type == 'telegram' else _parse_web(source)

def ensure_default_sources(session):
    if session.query(Source).count() > 0:
        return
    for name, type_, url, icon in DEFAULT_SOURCES:
        session.add(Source(name=name, type=type_, url=url, icon=icon, is_active=True))
    session.commit()

def _new_items(session, parsed, seen_urls=None, limit=None):
    out, seen_urls = [], seen_urls or set()
    for it in parsed:
        url = it.get('url')
        if not url or url in seen_urls:
            continue
        if session.query(NewsItem).filter(NewsItem.url == url).first():
            continue
        seen_urls.add(url)
        out.append(it)
        if limit and len(out) >= limit:
            break
    return out

def _classify_and_save(session, items):
    if not items:
        return 0
    ai_topics = ai_classify([f'{x["title"]} — {x["summary"][:200]}' for x in items])
    for i, it in enumerate(items):
        it['topic'] = ai_topics.get(i) or _detect_topic(f'{it["title"]} {it["summary"]}')
        session.add(NewsItem(**it))
    session.commit()
    return len(items)

def fetch_for_source(source_id, limit=10):
    session = db_session.create_session()
    src = session.query(Source).get(source_id)
    if not src:
        session.close()
        return 0
    try:
        return _classify_and_save(session, _new_items(session, parse_source(src), limit=limit))
    except Exception as e:
        print(f'[parser] {src.name}: {e}')
        return 0
    finally:
        session.close()

def refresh_news():
    session = db_session.create_session()
    seen_urls = set()
    new_items = []
    for src in session.query(Source).filter(Source.is_active.is_(True)).all():
        try:
            new_items += _new_items(session, parse_source(src), seen_urls)
        except Exception as e:
            print(f'[parser] {src.name}: {e}')
    added = _classify_and_save(session, new_items)
    session.close()
    return added
