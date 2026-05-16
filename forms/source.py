from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import SelectField, StringField, SubmitField
from wtforms.validators import DataRequired

IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'webp', 'gif']

class SourceForm(FlaskForm):
    name = StringField('Название', validators=[DataRequired()])
    type = SelectField(
        'Тип',
        choices=[
            ('website', 'Сайт'),
            ('telegram', 'Telegram'),
        ],
    )
    url = StringField(
        'URL',
        validators=[DataRequired()],
    )
    icon = FileField(
        'Иконка (PNG/JPG)',
        validators=[FileAllowed(IMAGE_EXTS, 'Только изображения')],
    )
    submit = SubmitField('Добавить')

class ProfileForm(FlaskForm):
    avatar = FileField(
        'Новый аватар',
        validators=[FileAllowed(IMAGE_EXTS, 'Только изображения')],
    )
    submit = SubmitField('Загрузить')
