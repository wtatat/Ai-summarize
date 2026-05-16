import datetime
import json

MAX_HISTORY_ITEMS = 12

def save_summary_context(user, summary_text):
    user.ai_dialog_summary = summary_text or ''
    user.ai_dialog_history = '[]'
    user.ai_dialog_updated_at = datetime.datetime.now()

def load_dialog_history(user):
    try:
        history = json.loads(user.ai_dialog_history or '[]')
    except (TypeError, ValueError):
        return []
    return history if isinstance(history, list) else []

def save_dialog_history(user, history):
    user.ai_dialog_history = json.dumps(history[-MAX_HISTORY_ITEMS:], ensure_ascii=False)
    user.ai_dialog_updated_at = datetime.datetime.now()

def append_dialog_turn(user, question, answer):
    history = load_dialog_history(user)
    history.append({'role': 'user', 'content': (question or '')[:1200]})
    history.append({'role': 'assistant', 'content': (answer or '')[:3500]})
    save_dialog_history(user, history)
