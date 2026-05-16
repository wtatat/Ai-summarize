import sqlalchemy as sa
from .db_session import SqlAlchemyBase

class Source(SqlAlchemyBase):
    __tablename__ = 'sources'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    name = sa.Column(sa.String, nullable=False)
    type = sa.Column(sa.String, nullable=False)
    url = sa.Column(sa.String, nullable=False)
    icon = sa.Column(sa.String, default='')
    is_active = sa.Column(sa.Boolean, default=True)
