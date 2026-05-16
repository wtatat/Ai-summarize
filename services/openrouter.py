import json
import os
import re
import requests

URL = 'https://openrouter.ai/api/v1/chat/completions'
TOPIC_IDS = {'technology', 'politics', 'science', 'business',
             'sports', 'culture', 'entertainment', 'health', 'world'}

def _post(messages, timeout=60):
    api_key = os.getenv('OPENROUTER_API_KEY')
    model = os.getenv('OPENROUTER_MODEL', 'google/gemma-3-27b-it:free')
    if not api_key:
        return None, 'Не задан OPENROUTER_API_KEY в .env'
    try:
        r = requests.post(
            URL,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
                'HTTP-Referer': 'http://localhost:5000',
                'X-Title': 'AI News Summarizer',
            },
            json={'model': model, 'messages': messages},
            timeout=timeout,
        )
        if r.status_code != 200:
            return None, f'OpenRouter {r.status_code}: {r.text[:200]}'
        return r.json()['choices'][0]['message']['content'], None
    except Exception as e:
        return None, f'Ошибка запроса: {e}'

def _stream(messages, timeout=90):
    api_key = os.getenv('OPENROUTER_API_KEY')
    model = os.getenv('OPENROUTER_MODEL', 'google/gemma-3-27b-it:free')
    if not api_key:
        yield '⚠️ Не задан OPENROUTER_API_KEY в .env'
        return
    try:
        with requests.post(
            URL,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
                'HTTP-Referer': 'http://localhost:5000',
                'X-Title': 'AI News Summarizer',
            },
            json={'model': model, 'messages': messages, 'stream': True},
            stream=True,
            timeout=timeout,
        ) as r:
            if r.status_code != 200:
                yield f'⚠️ OpenRouter {r.status_code}: {r.text[:200]}'
                return
            for raw_line in r.iter_lines():
                line = raw_line.decode('utf-8', errors='replace') if raw_line else ''
                if not line or not line.startswith('data:'):
                    continue
                data = line[5:].strip()
                if data == '[DONE]':
                    break
                try:
                    payload = json.loads(data)
                    chunk = payload['choices'][0].get('delta', {}).get('content')
                    if chunk:
                        yield chunk
                except (KeyError, json.JSONDecodeError):
                    continue
    except Exception as e:
        yield f'⚠️ Ошибка запроса: {e}'

def _summary_messages(news_items, topic_label='все темы'):
    headlines = '\n'.join(
        f'{i + 1}. [{n.source}] {n.title} — {n.summary}'
        for i, n in enumerate(news_items[:30])
    )
    return [
        {
            'role': 'system',
            'content': (
                'Ты новостной редактор Brief. Пиши по-русски, коротко и аккуратно. '
                'Используй только факты из списка, не додумывай детали. '
                'Объединяй похожие новости и отбрасывай второстепенный шум.'
            ),
        },
        {
            'role': 'user',
            'content': (
                f'Сделай сводку по теме «{topic_label}».\n'
                'Формат строго Markdown:\n'
                '- 5-7 пунктов максимум.\n'
                '- Каждый пункт начинается с "- " и одного подходящего эмодзи.\n'
                '- В пункте сначала короткая тема, потом суть одним предложением.\n'
                '- Числа, даты и суммы выделяй **жирным**.\n'
                '- Не добавляй заголовок, вступление, выводы и ссылки.\n'
                '- Если заголовок похож на кликбейт или звучит странно, формулируй осторожно: "сообщается", "по данным источника".\n\n'
                f'Новости:\n{headlines}'
            ),
        },
    ]

def summarize(news_items, topic_label='все темы'):
    if not news_items:
        return 'Нет новостей для анализа.'
    text, err = _post(_summary_messages(news_items, topic_label))
    return text if text is not None else f'⚠️ {err}'

def stream_summary(news_items, topic_label='все темы'):
    if not news_items:
        yield 'Нет новостей для анализа.'
        return
    yield from _stream(_summary_messages(news_items, topic_label))

def _dialog_messages(summary_text, question, history=None):
    messages = [
        {
            'role': 'system',
            'content': (
                'Ты ассистент Brief для уточнения новостной сводки. '
                'Отвечай по-русски, ясно и коротко. Опирайся на сводку и историю диалога. '
                'Если в сводке нет нужных данных, прямо скажи, что этих деталей в текущей сводке нет. '
                'Не выдумывай факты, даты, цитаты и источники.'
            ),
        },
        {
            'role': 'user',
            'content': f'Текущая сводка:\n{summary_text}',
        },
    ]
    for item in (history or [])[-12:]:
        role = item.get('role')
        content = item.get('content')
        if role in {'user', 'assistant'} and content:
            messages.append({'role': role, 'content': content})
    messages.append({'role': 'user', 'content': question})
    return messages

def chat_about_summary(summary_text, question, history=None):
    if not summary_text:
        return 'Сначала сгенерируйте сводку, а потом задавайте вопросы по ней.'
    text, err = _post(_dialog_messages(summary_text, question, history), timeout=90)
    return text if text is not None else f'⚠️ {err}'

def stream_chat_about_summary(summary_text, question, history=None):
    if not summary_text:
        yield 'Сначала сгенерируйте сводку, а потом задавайте вопросы по ней.'
        return
    yield from _stream(_dialog_messages(summary_text, question, history), timeout=90)

def classify(items):
    if not items:
        return {}
    listing = '\n'.join(f'{i + 1}. {it[:200]}' for i, it in enumerate(items))
    topics_csv = ', '.join(sorted(TOPIC_IDS))
    prompt = (
        'Ты классификатор новостей. Определи тему каждой новости из списка. '
        f'Допустимые темы (только эти, на английском): {topics_csv}.\n'
        'Ответь СТРОГО списком в формате "номер: тема", по одной паре на строке, '
        'без заголовков и пояснений.\n\n'
        f'Новости:\n{listing}'
    )
    text, _ = _post([{'role': 'user', 'content': prompt}], timeout=90)
    if not text:
        return {}
    out = {}
    for line in text.splitlines():
        m = re.match(r'\s*(\d+)\s*[:.\-]\s*([a-zA-Z]+)', line)
        if not m:
            continue
        idx = int(m.group(1)) - 1
        topic = m.group(2).lower()
        if topic in TOPIC_IDS:
            out[idx] = topic
    return out
