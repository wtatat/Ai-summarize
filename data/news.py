import datetime
import sqlalchemy as sa
from .db_session import SqlAlchemyBase

class NewsItem(SqlAlchemyBase):
    __tablename__ = 'news'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    title = sa.Column(sa.String, nullable=False)
    summary = sa.Column(sa.Text, default='')
    full_text = sa.Column(sa.Text, default='')
    source = sa.Column(sa.String, default='dzen.ru')
    source_type = sa.Column(sa.String, default='website')
    source_icon = sa.Column(sa.String, default='📰')
    topic = sa.Column(sa.String, default='all', index=True)
    url = sa.Column(sa.String, default='', unique=True)
    published_at = sa.Column(sa.DateTime, default=datetime.datetime.now)

    def to_dict(self, read_ids=None):
        return {
            'id': self.id,
            'title': self.title,
            'summary': self.summary,
            'full_text': self.full_text,
            'source': self.source,
            'source_type': self.source_type,
            'source_icon': self.source_icon,
            'topic': self.topic,
            'url': self.url,
            'published_at': self.published_at.isoformat() if self.published_at else '',
            'is_read': bool(read_ids and self.id in read_ids),
        }
