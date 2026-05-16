import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')

def _looks_like_feed(content_type, text_head):
    ct = (content_type or '').lower()
    head = (text_head or '').lower().lstrip()
    return (
        'xml' in ct or 'rss' in ct or 'atom' in ct
        or head.startswith('<?xml')
        or '<rss' in head or '<feed' in head or '<channel' in head
    )

def _try_rss_fallbacks(base_url):
    parsed = urlparse(base_url)
    host = parsed.netloc.lower()
    candidates = []

    if 'news.google' in host:
        candidates.append(f'{parsed.scheme}://{parsed.netloc}/rss?{parsed.query}'
                          if parsed.query else
                          f'{parsed.scheme}://{parsed.netloc}/rss')

    base = f'{parsed.scheme}://{parsed.netloc}{parsed.path}'.rstrip('/')
    root = f'{parsed.scheme}://{parsed.netloc}'
    for suffix in ('/rss', '/rss.xml', '/feed', '/feed.xml', '/feed/', '/atom.xml', '/rss/news'):
        candidates.append(base + suffix)
        if base != root:
            candidates.append(root + suffix)

    seen = set()
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        try:
            r = requests.get(c, headers={'User-Agent': UA}, timeout=8, allow_redirects=True)
            if r.status_code != 200:
                continue
            if _looks_like_feed(r.headers.get('Content-Type'), r.text[:2048]):
                return r.url
        except Exception:
            continue
    return None

def _telegram_channel_name(raw_url):
    value = (raw_url or '').strip()
    if value.startswith('@'):
        return value[1:].strip('/'), ''
    if not value.startswith(('http://', 'https://')):
        value = 'https://' + value
    parsed = urlparse(value)
    host = parsed.netloc.lower().removeprefix('www.')
    if host not in ('t.me', 'telegram.me'):
        return '', ''
    parts = [p for p in parsed.path.split('/') if p]
    if not parts:
        return '', 'Укажите публичный Telegram-канал'
    if parts[0] == 's' and len(parts) > 1:
        name = parts[1].lstrip('@')
    elif parts[0] in ('c', 'joinchat') or parts[0].startswith('+'):
        return '', 'Приватные и invite-ссылки Telegram нельзя читать без API-доступа'
    else:
        name = parts[0].lstrip('@')
    if not re.fullmatch(r'[A-Za-z0-9_]{5,32}', name):
        return '', 'Не удалось распознать публичный Telegram-канал'
    return name, ''

def detect_source(raw_url):
    url = (raw_url or '').strip()
    if not url:
        return None, url, '', 'URL не указан'

    if url.startswith('@') or re.search(r'(^|//)(?:www\.)?(?:t\.me|telegram\.me)/', url, re.I):
        channel_name, error = _telegram_channel_name(url)
        if error:
            return None, url, '', error
        return 'telegram', f'https://t.me/{channel_name}', '', ''

    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    try:
        r = requests.get(url, headers={'User-Agent': UA}, timeout=12, allow_redirects=True)
        r.raise_for_status()
    except requests.exceptions.Timeout:
        return None, url, '', 'Сайт долго не отвечает'
    except requests.exceptions.SSLError:
        return None, url, '', 'Проблема с SSL-сертификатом сайта'
    except requests.exceptions.ConnectionError:
        return None, url, '', 'Не удалось подключиться к сайту'
    except requests.exceptions.HTTPError as e:
        return None, url, '', f'Сайт вернул ошибку {e.response.status_code}'
    except Exception as e:
        return None, url, '', f'Ошибка загрузки: {e}'

    final_url = r.url
    content_type = (r.headers.get('Content-Type') or '').lower()
    head_text = r.text[:4096]

    if _looks_like_feed(content_type, head_text):
        return 'website', final_url, '', ''

    if 'html' in content_type or '<html' in head_text.lower():
        soup = BeautifulSoup(r.text, 'html.parser')
        candidates = []
        for link in soup.find_all('link'):
            rels = link.get('rel') or []
            if isinstance(rels, str):
                rels = [rels]
            if 'alternate' not in [rr.lower() for rr in rels]:
                continue
            t = (link.get('type') or '').lower()
            href = link.get('href')
            if not href:
                continue
            if 'rss' in t or 'atom' in t or 'xml' in t:
                candidates.append((t, urljoin(final_url, href)))

        if candidates:
            for needle in ('rss', 'atom', 'xml'):
                for t, href in candidates:
                    if needle in t:
                        return 'website', href, 'Автоматически найден RSS-фид', ''
            return 'website', candidates[0][1], 'Автоматически найден RSS-фид', ''

        fallback = _try_rss_fallbacks(final_url)
        if fallback:
            return 'website', fallback, 'Автоматически найден RSS-фид', ''

        return 'website', final_url, '', ''

    return 'website', final_url, '', ''
