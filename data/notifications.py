import datetime
import sqlalchemy as sa
import sqlalchemy.orm as orm
from .db_session import SqlAlchemyBase

class Notification(SqlAlchemyBase):
    __tablename__ = 'notifications'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    user_id = sa.Column(sa.Integer, sa.ForeignKey('users.id'), nullable=False, index=True)
    title = sa.Column(sa.String, nullable=False)
    body = sa.Column(sa.Text, default='')
    created_at = sa.Column(sa.DateTime, default=datetime.datetime.now, index=True)
    is_read = sa.Column(sa.Boolean, default=False)

    user = orm.relationship('User')
