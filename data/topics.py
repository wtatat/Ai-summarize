TOPICS = [
    ('all', '', 'Все'),
    ('technology', '', 'Технологии'),
    ('politics', '', 'Политика'),
    ('science', '', 'Наука'),
    ('business', '', 'Бизнес'),
    ('sports', '', 'Спорт'),
    ('culture', '', 'Искусство'),
    ('entertainment', '', 'Развлечения'),
    ('health', '', 'Здоровье'),
    ('world', '', 'Мир'),
]

LABEL = {tid: label for tid, _e, label in TOPICS}
EMOJI = {tid: emoji for tid, emoji, _l in TOPICS}
