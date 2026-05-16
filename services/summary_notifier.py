import os
import threading
import time

from services.notifications import dispatch_due_summaries

_started = False

def start_summary_notifier(poll_seconds=60):
    global _started
    if _started or os.getenv('SUMMARY_NOTIFIER', '1') == '0':
        return
    _started = True

    def loop():
        while True:
            try:
                dispatch_due_summaries()
            except Exception as exc:
                print(f'[summary_notifier] {exc}')
            time.sleep(poll_seconds)

    threading.Thread(target=loop, daemon=True, name='summary-notifier').start()
