import datetime

from data import db_session
from data.news import NewsItem
from data.notifications import Notification
from data.topics import LABEL
from data.users import User
from services.dialog import save_summary_context
from services.openrouter import stream_summary, summarize

MIN_INTERVAL_HOURS = 2

def normalize_interval(value):
    try:
        return max(MIN_INTERVAL_HOURS, int(value))
    except (TypeError, ValueError):
        return MIN_INTERVAL_HOURS

def normalize_topics(values):
    allowed = set(LABEL)
    picked = [v for v in values if v in allowed and v != 'all']
    return ','.join(picked) if picked else 'all'

def _topic_parts(topics_csv):
    return [x.strip() for x in (topics_csv or 'all').split(',') if x.strip() and x.strip() != 'all']

def _topic_label(topics_csv):
    parts = _topic_parts(topics_csv)
    return ', '.join(LABEL.get(x, x) for x in parts) if parts else 'все темы'

def _summary_items(session, topics_csv='all', limit=30):
    q = session.query(NewsItem)
    if parts := _topic_parts(topics_csv):
        q = q.filter(NewsItem.topic.in_(parts))
    return q.order_by(NewsItem.published_at.desc()).limit(limit).all()

def build_summary(session, topics_csv='all'):
    items = _summary_items(session, topics_csv)
    return summarize(items, topic_label=_topic_label(topics_csv)), len(items)

def build_summary_stream(session, topics_csv='all'):
    items = _summary_items(session, topics_csv)
    return len(items), stream_summary(items, topic_label=_topic_label(topics_csv))

def store_site_summary(session, user, header, text):
    body = f'{header}\n\n{text}'
    session.add(Notification(user_id=user.id, title='Сводка новостей', body=body))
    save_summary_context(user, body)
    return body

def deliver_summary(session, user, update_last=True, force_site=False, topics_csv=None):
    topics = topics_csv or user.summary_notify_topics or 'all'
    count, chunks = build_summary_stream(session, topics)
    header = f'Brief. Сводка новостей\nМатериалов: {count}'
    text = ''.join(chunks)
    save_to_site = force_site or user.summary_notify_site
    body = store_site_summary(session, user, header, text) if save_to_site else f'{header}\n\n{text}'
    if update_last:
        user.summary_notify_last_sent_at = datetime.datetime.now()
    return body

def is_due(user, now=None):
    if not user.summary_notify_enabled:
        return False
    now = now or datetime.datetime.now()
    last = user.summary_notify_last_sent_at
    interval = normalize_interval(user.summary_notify_interval_hours)
    return not last or last + datetime.timedelta(hours=interval) <= now

def dispatch_due_summaries(limit=5):
    session = db_session.create_session()
    try:
        users = session.query(User).filter(User.summary_notify_enabled.is_(True)).all()
        sent = 0
        for user in users:
            if sent >= limit:
                break
            if is_due(user):
                deliver_summary(session, user)
                session.commit()
                sent += 1
        return sent
    finally:
        session.close()
