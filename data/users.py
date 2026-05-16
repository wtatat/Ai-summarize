import datetime
import sqlalchemy as sa
import sqlalchemy.orm as orm
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from .db_session import SqlAlchemyBase

read_assoc = sa.Table(
    'read_assoc', SqlAlchemyBase.metadata,
    sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id'), primary_key=True),
    sa.Column('news_id', sa.Integer, sa.ForeignKey('news.id'), primary_key=True),
)

class User(SqlAlchemyBase, UserMixin):
    __tablename__ = 'users'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    name = sa.Column(sa.String, nullable=False)
    email = sa.Column(sa.String, unique=True, nullable=False, index=True)
    password_hash = sa.Column(sa.String, nullable=False)
    avatar = sa.Column(sa.String, default='')
    created_at = sa.Column(sa.DateTime, default=datetime.datetime.now)
    summary_notify_enabled = sa.Column(sa.Boolean, default=False)
    summary_notify_interval_hours = sa.Column(sa.Integer, default=2)
    summary_notify_topics = sa.Column(sa.String, default='all')
    summary_notify_site = sa.Column(sa.Boolean, default=True)
    summary_notify_last_sent_at = sa.Column(sa.DateTime, nullable=True)
    ai_dialog_summary = sa.Column(sa.Text, default='')
    ai_dialog_history = sa.Column(sa.Text, default='[]')
    ai_dialog_updated_at = sa.Column(sa.DateTime, nullable=True)
    read_news = orm.relationship('NewsItem', secondary=read_assoc, lazy='subquery')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
