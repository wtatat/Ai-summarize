from flask import jsonify
from flask_login import current_user
from flask_restful import Resource, abort

from data import db_session
from data.news import NewsItem
from data.sources import Source
from data.users import User
from services.notifications import store_site_summary
from services.openrouter import summarize

def _read_ids():
    if not current_user.is_authenticated:
        return set()
    s = db_session.create_session()
    u = s.query(User).get(current_user.id)
    return {n.id for n in u.read_news} if u else set()

class NewsListResource(Resource):
    def get(self):
        s = db_session.create_session()
        items = s.query(NewsItem).order_by(NewsItem.published_at.desc()).all()
        ids = _read_ids()
        return jsonify({'news': [n.to_dict(ids) for n in items]})

class NewsToggleResource(Resource):
    def post(self, news_id):
        if not current_user.is_authenticated:
            abort(401, message='Требуется вход')
        s = db_session.create_session()
        u = s.query(User).get(current_user.id)
        n = s.query(NewsItem).get(news_id)
        if not n:
            abort(404)
        if n in u.read_news:
            u.read_news.remove(n)
            is_read = False
        else:
            u.read_news.append(n)
            is_read = True
        s.commit()
        return jsonify({'id': news_id, 'is_read': is_read})

class SourcesResource(Resource):
    def get(self):
        s = db_session.create_session()
        return jsonify({'sources': [
            {'id': x.id, 'name': x.name, 'type': x.type, 'url': x.url,
             'icon': x.icon, 'is_active': x.is_active}
            for x in s.query(Source).all()
        ]})

class SummarizeResource(Resource):
    def get(self, topic):
        from data.topics import LABEL
        s = db_session.create_session()
        q = s.query(NewsItem)

        raw = (topic or 'all').strip()
        topics_list = [t.strip() for t in raw.split(',') if t.strip() and t.strip() != 'all']

        if topics_list:
            q = q.filter(NewsItem.topic.in_(topics_list))
            label = ', '.join(LABEL.get(t, t) for t in topics_list)
        else:
            label = 'все темы'

        items = q.order_by(NewsItem.published_at.desc()).limit(30).all()
        text = summarize(items, topic_label=label)
        if current_user.is_authenticated:
            user = s.query(User).get(current_user.id)
            if user:
                header = f'Brief. Сводка новостей\nМатериалов: {len(items)}'
                store_site_summary(s, user, header, text)
                s.commit()
        return jsonify({'topic': raw, 'count': len(items), 'summary': text})
