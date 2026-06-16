import sys
from apscheduler.schedulers.background import BackgroundScheduler
from watcher.queue import IndexQueue

_scheduler = None

def _night_job(queue: IndexQueue, run_pipeline_fn):
    tasks = queue.pop_all_deferred()
    print(f"[scheduler] processing {len(tasks)} deferred tasks", file=sys.stderr)
    for task in tasks:
        try:
            run_pipeline_fn(task.path)
        except Exception as e:
            print(f"[scheduler] error {task.path.name}: {e}", file=sys.stderr)

def start_scheduler(queue: IndexQueue, run_pipeline_fn):
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
        _scheduler.add_job(
            _night_job,
            trigger='cron',
            hour=2,
            minute=0,
            args=(queue, run_pipeline_fn)
        )
        _scheduler.start()
        print("[scheduler] started, deferred jobs run at 02:00", file=sys.stderr)

def stop_scheduler():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown()
        _scheduler = None
        print("[scheduler] stopped", file=sys.stderr)
