import datetime
import json
import os
import secrets
from flask import (Flask, abort, flash, redirect, render_template, request,
                   Response, send_from_directory, stream_with_context, url_for)
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_restful import Api
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from sqlalchemy import func, true

from data import db_session
from data.news import NewsItem
from data.notifications import Notification
from data.sources import Source
from data.users import User
from data.topics import TOPICS, LABEL, EMOJI
from forms.auth import LoginForm, RegisterForm
from forms.source import SourceForm, ProfileForm
from parsers.dzen import refresh_news, ensure_default_sources, fetch_for_source
from parsers.detect import detect_source
from api.resources import (NewsListResource, NewsToggleResource,
                           SourcesResource, SummarizeResource)
from services.dialog import append_dialog_turn, load_dialog_history, save_summary_context
from services.notifications import (deliver_summary, normalize_interval,
                                    normalize_topics, store_site_summary)
from services.openrouter import stream_chat_about_summary, stream_summary
from services.schema import migrate_database
from services.summary_notifier import start_summary_notifier

load_dotenv()

DB_PATH = 'db/news.sqlite'
UPLOAD_DIR = 'static/uploads'

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret')
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Войдите, чтобы продолжить'

api = Api(app)
api.add_resource(NewsListResource, '/api/news')
api.add_resource(NewsToggleResource, '/api/news/<int:news_id>/read')
api.add_resource(SourcesResource, '/api/sources')
api.add_resource(SummarizeResource, '/api/summarize/<topic>')

@login_manager.user_loader
def load_user(user_id):
    s = db_session.create_session()
    return s.get(User, int(user_id))

@app.before_request
def redirect_guests_to_register():
    public_endpoints = {'register', 'login', 'static', 'cookie_image', 'cookie_archive'}
    if current_user.is_authenticated or request.endpoint in public_endpoints:
        return None
    return redirect(url_for('register'))

@app.context_processor
def inject_globals():
    import traceback as _tb
    defaults = {
        'unread_count': 0,
        'sidebar_topics': [],
        'sidebar_sources': [],
        'sidebar_total_news': 0,
        'notification_unread_count': 0,
    }
    try:
        s = db_session.create_session()

        unread = 0
        notification_unread_count = 0
        if current_user.is_authenticated:
            u = s.get(User, current_user.id)
            if u:
                read_ids = {n.id for n in u.read_news}
                unread = s.query(NewsItem).filter(~NewsItem.id.in_(read_ids) if read_ids else true()).count()
                notification_unread_count = (s.query(Notification)
                                             .filter(Notification.user_id == u.id,
                                                     Notification.is_read.is_(False))
                                             .count())

        counts = dict(s.query(NewsItem.topic, func.count(NewsItem.id)).group_by(NewsItem.topic).all())
        sidebar_topics = [(tid, emoji, label, counts.get(tid, 0))
                          for tid, emoji, label in TOPICS if tid != 'all']

        sidebar_sources = (s.query(Source)
                           .filter(Source.is_active.is_(True))
                           .order_by(Source.id).limit(8).all())
        sidebar_total_news = s.query(NewsItem).count()

        return {
            'unread_count': unread,
            'sidebar_topics': sidebar_topics,
            'sidebar_sources': sidebar_sources,
            'sidebar_total_news': sidebar_total_news,
            'notification_unread_count': notification_unread_count,
        }
    except Exception:
        print('[inject_globals ERROR]', flush=True)
        _tb.print_exc()
        return defaults

@app.route('/cookie-image.png')
@app.route('/куки.png')
def cookie_image():
    return send_from_directory(app.root_path, 'куки.png')

@app.route('/cookie-files.zip')
def cookie_archive():
    return send_from_directory(os.path.join(app.root_path, 'файлы куки'),
                               'файлы куки.zip',
                               as_attachment=True,
                               download_name='файлы куки.zip')

@app.template_filter('time_ago')
def time_ago(dt):
    if not dt:
        return ''
    delta = datetime.datetime.now() - dt
    secs = int(delta.total_seconds())
    if secs < 60:
        return 'только что'
    mins = secs // 60
    if mins < 60:
        return f'{mins} мин. назад'
    hrs = mins // 60
    if hrs < 24:
        return f'{hrs} ч. назад'
    return f'{hrs // 24} дн. назад'

def save_upload(file):
    if not file or not getattr(file, 'filename', ''):
        return ''
    name = f'{secrets.token_hex(4)}_{secure_filename(file.filename)}'
    file.save(os.path.join(UPLOAD_DIR, name))
    return name

def delete_upload(filename):
    if not filename:
        return

    upload_root = os.path.abspath(UPLOAD_DIR)
    path = os.path.abspath(os.path.join(upload_root, filename))
    if not path.startswith(upload_root + os.sep):
        return

    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass

@app.route('/')
def index():
    raw_topics = (request.args.get('topics') or request.args.get('topic') or 'all').strip()
    raw_sources = (request.args.get('sources') or request.args.get('source') or 'all').strip()
    query = request.args.get('q', '').strip()
    allowed_topics = {tid for tid, _emoji, _label in TOPICS if tid != 'all'}
    selected_topic_ids = []
    for part in raw_topics.split(','):
        topic_id = part.strip()
        if topic_id in allowed_topics and topic_id not in selected_topic_ids:
            selected_topic_ids.append(topic_id)
    selected_topics = selected_topic_ids or ['all']

    s = db_session.create_session()
    source_rows = s.query(Source).order_by(Source.name).all()
    source_counts = dict(s.query(NewsItem.source, func.count(NewsItem.id))
                         .filter(NewsItem.source != '')
                         .group_by(NewsItem.source).all())
    news_source_rows = (s.query(NewsItem.source, NewsItem.source_type, NewsItem.source_icon)
                        .filter(NewsItem.source != '')
                        .group_by(NewsItem.source).all())
    source_meta = {src.name: src for src in source_rows}
    news_source_meta = {name: (source_type, source_icon)
                        for name, source_type, source_icon in news_source_rows}
    source_names = []
    for src in source_rows:
        if src.name not in source_names:
            source_names.append(src.name)
    for name, _source_type, _source_icon in news_source_rows:
        if name not in source_names:
            source_names.append(name)
    source_options = []
    for name in source_names:
        src = source_meta.get(name)
        source_type, source_icon = news_source_meta.get(name, ('rss', ''))
        count = source_counts.get(name, 0)
        if not count:
            continue
        source_options.append({
            'name': name,
            'type': src.type if src else source_type,
            'icon': src.icon if src else source_icon,
            'count': count,
            'is_active': src.is_active if src else True,
        })
    allowed_sources = {src['name'] for src in source_options}
    selected_source_names = []
    for part in raw_sources.split(','):
        source_name = part.strip()
        if source_name in allowed_sources and source_name not in selected_source_names:
            selected_source_names.append(source_name)
    selected_sources = selected_source_names or ['all']

    q = s.query(NewsItem)
    if selected_topic_ids:
        q = q.filter(NewsItem.topic.in_(selected_topic_ids))
    if selected_source_names:
        q = q.filter(NewsItem.source.in_(selected_source_names))
    if query:
        like = f'%{query}%'
        q = q.filter((NewsItem.title.ilike(like)) |
                     (NewsItem.summary.ilike(like)) |
                     (NewsItem.source.ilike(like)))
    news = q.order_by(NewsItem.published_at.desc()).all()

    read_ids = set()
    if current_user.is_authenticated:
        u = s.get(User, current_user.id)
        read_ids = {n.id for n in u.read_news}
    unread = sum(1 for n in news if n.id not in read_ids)

    return render_template('index.html', news=news, topics=TOPICS,
                           selected_topics=selected_topics, query=query,
                           source_options=source_options,
                           selected_sources=selected_sources,
                           topic_label=', '.join(LABEL.get(t, t) for t in selected_topic_ids) or 'Все',
                           topic_emoji=EMOJI.get(selected_topic_ids[0], '🌐') if selected_topic_ids else '🌐',
                           read_ids=read_ids, unread=unread)

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        s = db_session.create_session()
        u = s.query(User).filter(User.email == form.email.data).first()
        if u and u.check_password(form.password.data):
            login_user(u)
            return redirect(url_for('index'))
        flash('Неверный email или пароль', 'danger')
    return render_template('login.html', form=form)

@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        s = db_session.create_session()
        if s.query(User).filter(User.email == form.email.data).first():
            flash('Этот email уже занят', 'warning')
        else:
            u = User(name=form.name.data, email=form.email.data)
            u.set_password(form.password.data)
            s.add(u)
            s.commit()
            login_user(u)
            flash('Добро пожаловать!', 'success')
            return redirect(url_for('index'))
    return render_template('register.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/more', methods=['GET', 'POST'])
def more():
    form = ProfileForm()
    user = None
    read_count = 0
    notifications = []
    selected_notify_topics = {'all'}
    next_summary_at = None
    if current_user.is_authenticated:
        s = db_session.create_session()
        user = s.get(User, current_user.id)
        if form.validate_on_submit() and form.avatar.data:
            old_avatar = user.avatar
            user.avatar = save_upload(form.avatar.data)
            s.commit()
            if old_avatar != user.avatar:
                delete_upload(old_avatar)
            flash('Аватар обновлён', 'success')
            return redirect(url_for('more'))
        read_count = len(user.read_news)
        notifications = (s.query(Notification)
                         .filter(Notification.user_id == user.id)
                         .order_by(Notification.created_at.desc())
                         .limit(8).all())
        selected_notify_topics = set((user.summary_notify_topics or 'all').split(','))
        if user.summary_notify_enabled:
            last = user.summary_notify_last_sent_at
            interval = datetime.timedelta(hours=normalize_interval(user.summary_notify_interval_hours))
            next_summary_at = (last + interval) if last else datetime.datetime.now()
    return render_template('more.html', form=form, user=user, read_count=read_count,
                           notifications=notifications,
                           selected_notify_topics=selected_notify_topics,
                           notify_topics=TOPICS,
                           next_summary_at=next_summary_at)

@app.route('/profile')
def profile():
    return redirect(url_for('more'))

@app.route('/settings/notifications', methods=['POST'])
@login_required
def update_notification_settings():
    s = db_session.create_session()
    user = s.get(User, current_user.id)
    raw_interval = request.form.get('interval_hours')
    interval = normalize_interval(raw_interval)
    try:
        requested_interval = int(raw_interval or 0)
    except ValueError:
        requested_interval = 0

    user.summary_notify_enabled = bool(request.form.get('enabled'))
    user.summary_notify_interval_hours = interval
    user.summary_notify_topics = normalize_topics(request.form.getlist('topics'))
    user.summary_notify_site = bool(request.form.get('site'))

    if not user.summary_notify_site:
        user.summary_notify_site = True
        flash('Оставил уведомления на сайте: нужен хотя бы один канал доставки', 'warning')
    elif interval != requested_interval:
        flash('Интервал не может быть меньше 2 часов', 'warning')
    else:
        flash('Настройки уведомлений сохранены', 'success')

    s.commit()
    return redirect(url_for('more'))

@app.route('/settings/notifications/send-now', methods=['POST'])
@login_required
def send_summary_now():
    s = db_session.create_session()
    user = s.get(User, current_user.id)
    deliver_summary(s, user, update_last=True, force_site=True)
    s.commit()
    flash('Сводка отправлена', 'success')
    return redirect(url_for('more'))

@app.route('/notifications/read', methods=['POST'])
@login_required
def mark_notifications_read():
    s = db_session.create_session()
    (s.query(Notification)
     .filter(Notification.user_id == current_user.id,
             Notification.is_read.is_(False))
     .update({'is_read': True}, synchronize_session=False))
    s.commit()
    return redirect(url_for('more'))

@app.route('/sources', methods=['GET', 'POST'])
@login_required
def sources():
    form = SourceForm()
    s = db_session.create_session()
    if form.validate_on_submit():
        raw_url = form.url.data
        src_type, src_url, hint, err = detect_source(raw_url)
        if err:
            flash(err, 'danger')
            items = s.query(Source).order_by(Source.id).all()
            return render_template('sources.html', form=form, sources=items)

        src = Source(name=form.name.data, type=src_type, url=src_url,
                     icon=save_upload(form.icon.data), is_active=True)
        s.add(src)
        s.commit()
        added = fetch_for_source(src.id, limit=10)

        parts = [f'Источник «{src.name}» добавлен']
        if hint:
            parts.append(hint)
        if added == 0:
            parts.append('новостей пока не получено — попробуйте обновить позже')
            flash(' · '.join(parts), 'warning')
        else:
            parts.append(f'загружено новостей: {added}')
            flash(' · '.join(parts), 'success')
        return redirect(url_for('sources'))
    items = s.query(Source).order_by(Source.id).all()
    return render_template('sources.html', form=form, sources=items)

@app.route('/sources/<int:sid>/toggle', methods=['POST'])
@login_required
def toggle_source(sid):
    s = db_session.create_session()
    src = s.get(Source, sid) or abort(404)
    src.is_active = not src.is_active
    s.commit()
    return redirect(url_for('sources'))

@app.route('/sources/<int:sid>/delete', methods=['POST'])
@login_required
def delete_source(sid):
    s = db_session.create_session()
    src = s.get(Source, sid) or abort(404)
    name = src.name
    removed = s.query(NewsItem).filter(NewsItem.source == name).delete(synchronize_session=False)
    s.delete(src)
    s.commit()
    if removed:
        flash(f'Источник «{name}» удалён · убрано новостей: {removed}', 'info')
    else:
        flash(f'Источник «{name}» удалён', 'info')
    return redirect(url_for('sources'))

@app.route('/news/<int:news_id>/read', methods=['POST'])
@login_required
def toggle_read(news_id):
    s = db_session.create_session()
    u = s.get(User, current_user.id)
    n = s.get(NewsItem, news_id) or abort(404)
    if n in u.read_news:
        u.read_news.remove(n)
    else:
        u.read_news.append(n)
    s.commit()
    return redirect(request.referrer or url_for('index'))

@app.route('/news/read-all', methods=['POST'])
@login_required
def read_all():
    s = db_session.create_session()
    u = s.get(User, current_user.id)
    u.read_news = s.query(NewsItem).all()
    s.commit()
    flash('Все новости отмечены как прочитанные', 'success')
    return redirect(request.referrer or url_for('index'))

@app.route('/refresh', methods=['POST', 'GET'])
def refresh():
    added = refresh_news()
    flash(f'Загружено новых новостей: {added}', 'info')
    return redirect(url_for('index'))

@app.route('/news/reload', methods=['POST'])
@login_required
def reload_news():
    from data.users import read_assoc
    s = db_session.create_session()
    s.execute(read_assoc.delete())
    removed = s.query(NewsItem).delete()
    s.commit()
    s.close()

    added = refresh_news()
    flash(f'Перезагрузка завершена · удалено: {removed}, загружено: {added}', 'success')
    return redirect(request.referrer or url_for('sources'))

@app.route('/summarize')
def summarize_page():
    raw = (request.args.get('topics') or request.args.get('topic') or 'all').strip()
    parts = [t.strip() for t in raw.split(',') if t.strip() and t.strip() != 'all']

    s = db_session.create_session()

    counts_rows = s.query(NewsItem.topic, func.count(NewsItem.id)).group_by(NewsItem.topic).all()
    counts = dict(counts_rows)
    topic_counts = {tid: counts.get(tid, 0) for tid, _, _ in TOPICS if tid != 'all'}

    topic_labels = {tid: f'{emoji} {label}' for tid, emoji, label in TOPICS}

    q = s.query(NewsItem)
    if parts:
        q = q.filter(NewsItem.topic.in_(parts))
    count = q.count()

    selected_set = list(parts) if parts else ['all']
    return render_template('summarize.html', topics=TOPICS,
                           selected_topics=selected_set,
                           topic_counts=topic_counts,
                           topic_labels=topic_labels,
                           news_count=count)

@app.route('/api/summarize-stream/<path:topic>')
def summarize_stream(topic):
    raw = (topic or 'all').strip()
    topics_list = [t.strip() for t in raw.split(',') if t.strip() and t.strip() != 'all']

    s = db_session.create_session()
    user_id = current_user.id if current_user.is_authenticated else None
    q = s.query(NewsItem)
    if topics_list:
        q = q.filter(NewsItem.topic.in_(topics_list))
        label = ', '.join(LABEL.get(t, t) for t in topics_list)
    else:
        label = 'все темы'
    items = q.order_by(NewsItem.published_at.desc()).limit(30).all()
    s.close()

    def event(name, data):
        payload = json.dumps(data, ensure_ascii=False)
        return f'event: {name}\ndata: {payload}\n\n'

    @stream_with_context
    def generate():
        text = ''
        header = f'Brief. Сводка новостей\nМатериалов: {len(items)}'
        yield event('meta', {'topic': raw, 'count': len(items)})

        for chunk in stream_summary(items, topic_label=label):
            text += chunk
            yield event('chunk', chunk)

        if user_id:
            store_session = db_session.create_session()
            try:
                user = store_session.get(User, user_id)
                if user:
                    store_site_summary(store_session, user, header, text)
                    store_session.commit()
            finally:
                store_session.close()
        yield event('done', {'summary': text})

    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/summary-chat-stream', methods=['POST'])
@login_required
def summary_chat_stream():
    payload = request.get_json(silent=True) or {}
    question = (payload.get('question') or '').strip()
    fallback_summary = (payload.get('summary') or '').strip()
    if not question:
        return Response('event: error\ndata: "empty question"\n\n', mimetype='text/event-stream')

    s = db_session.create_session()
    user = s.get(User, current_user.id)
    summary_text = (user.ai_dialog_summary or '').strip()
    if not summary_text and fallback_summary:
        summary_text = fallback_summary
        save_summary_context(user, summary_text)
        s.commit()
    history = load_dialog_history(user)
    s.close()

    def event(name, data):
        payload = json.dumps(data, ensure_ascii=False)
        return f'event: {name}\ndata: {payload}\n\n'

    @stream_with_context
    def generate():
        answer = ''
        yield event('meta', {'status': 'streaming'})
        for chunk in stream_chat_about_summary(summary_text, question, history):
            answer += chunk
            yield event('chunk', chunk)

        store_session = db_session.create_session()
        try:
            store_user = store_session.get(User, current_user.id)
            if store_user and summary_text:
                if not store_user.ai_dialog_summary and summary_text:
                    save_summary_context(store_user, summary_text)
                append_dialog_turn(store_user, question, answer)
                store_session.commit()
        finally:
            store_session.close()
        yield event('done', {'answer': answer})

    return Response(generate(), mimetype='text/event-stream')

@app.errorhandler(404)
def not_found(_):
    return render_template('error.html', code=404, msg='Страница не найдена'), 404

@app.errorhandler(413)
def too_large(_):
    flash('Файл слишком большой (макс. 2 МБ)', 'warning')
    return redirect(request.referrer or url_for('index'))

@app.errorhandler(500)
def internal_error(e):
    import traceback
    traceback.print_exc()
    return '<h1>500 — Внутренняя ошибка сервера</h1><p>Смотри логи для деталей.</p>', 500

def init_app():
    os.makedirs('db', exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    db_session.global_init(DB_PATH)
    migrate_database(DB_PATH)
    s = db_session.create_session()
    ensure_default_sources(s)
    seed_needed = s.query(NewsItem).count() == 0
    s.close()
    if seed_needed:
        refresh_news()

init_app()
start_summary_notifier()

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
