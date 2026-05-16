import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
RSS_HINT = 'Автоматически найден RSS-фид'


def _looks_like_feed(content_type, text_head):
    ct = (content_type or '').lower()
    head = (text_head or '').lower().lstrip()
    return ('xml' in ct or 'rss' in ct or 'atom' in ct or head.startswith('<?xml')
            or '<rss' in head or '<feed' in head or '<channel' in head)


def _rss_candidates(url):
    parsed = urlparse(url)
    base = f'{parsed.scheme}://{parsed.netloc}{parsed.path}'.rstrip('/')
    root = f'{parsed.scheme}://{parsed.netloc}'
    out = []
    if 'news.google' in parsed.netloc.lower():
        out.append(f'{root}/rss?{parsed.query}' if parsed.query else f'{root}/rss')
    for suffix in ('/rss', '/rss.xml', '/feed', '/feed.xml', '/feed/', '/atom.xml', '/rss/news'):
        out.append(base + suffix)
        if base != root:
            out.append(root + suffix)
    return dict.fromkeys(out)


def _try_rss_fallbacks(base_url):
    for url in _rss_candidates(base_url):
        try:
            r = requests.get(url, headers={'User-Agent': UA}, timeout=8, allow_redirects=True)
            if r.status_code == 200 and _looks_like_feed(r.headers.get('Content-Type'), r.text[:2048]):
                return r.url
        except Exception:
            pass
    return None


def _telegram_channel_name(raw_url):
    value = (raw_url or '').strip()
    if value.startswith('@'):
        name = value[1:].strip('/')
    else:
        if not value.startswith(('http://', 'https://')):
            value = 'https://' + value
        parsed = urlparse(value)
        if parsed.netloc.lower().removeprefix('www.') not in ('t.me', 'telegram.me'):
            return '', ''
        parts = [p for p in parsed.path.split('/') if p]
        if not parts:
            return '', 'Укажите публичный Telegram-канал'
        if parts[0] in ('c', 'joinchat') or parts[0].startswith('+'):
            return '', 'Приватные и invite-ссылки Telegram нельзя читать без API-доступа'
        name = (parts[1] if parts[0] == 's' and len(parts) > 1 else parts[0]).lstrip('@')
    return (name, '') if re.fullmatch(r'[A-Za-z0-9_]{5,32}', name) else (
        '', 'Не удалось распознать публичный Telegram-канал')


def _vk_source(raw_url):
    m = re.match(r'^(?:https?://)?(?:m\.)?(?:vk\.com|vk\.ru)/(@?[^/?#]+)', raw_url, re.I)
    if not m:
        return None
    name = m.group(1).strip().lstrip('@')
    if name.startswith(('wall', 'photo', 'video', 'market')):
        return None, raw_url, '', 'Укажите ссылку на страницу или сообщество VK, а не на отдельную запись'
    if not re.fullmatch(r'[A-Za-z0-9_.]+', name):
        return None, raw_url, '', 'Не удалось распознать страницу или сообщество VK'
    return 'vk', f'https://vk.com/{name}', '', ''


def detect_source(raw_url):
    url = (raw_url or '').strip()
    if not url:
        return None, url, '', 'URL не указан'

    if url.startswith('@') or re.search(r'(^|//)(?:www\.)?(?:t\.me|telegram\.me)/', url, re.I):
        name, error = _telegram_channel_name(url)
        return (None, url, '', error) if error else ('telegram', f'https://t.me/{name}', '', '')

    if vk := _vk_source(url):
        return vk

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
    head = r.text[:4096]
    if _looks_like_feed(content_type, head):
        return 'rss', final_url, '', ''

    if 'html' in content_type or '<html' in head.lower():
        soup = BeautifulSoup(r.text, 'html.parser')
        feeds = []
        for link in soup.find_all('link'):
            rels = link.get('rel') or []
            rels = [rels] if isinstance(rels, str) else rels
            type_ = (link.get('type') or '').lower()
            href = link.get('href')
            if href and 'alternate' in [r.lower() for r in rels] and any(x in type_ for x in ('rss', 'atom', 'xml')):
                feeds.append((type_, urljoin(final_url, href)))
        if feeds:
            for needle in ('rss', 'atom', 'xml'):
                for type_, href in feeds:
                    if needle in type_:
                        return 'rss', href, RSS_HINT, ''
            return 'rss', feeds[0][1], RSS_HINT, ''
        if fallback := _try_rss_fallbacks(final_url):
            return 'rss', fallback, RSS_HINT, ''
    return 'website', final_url, '', ''
