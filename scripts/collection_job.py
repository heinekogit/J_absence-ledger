"""Run the configured official-news collection without requiring the web server."""
import argparse
import fcntl
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app

LOCK = ROOT / 'data' / 'collection.lock'

def latest_due(local, weekdays, hour=9, minute=0):
 for offset in range(7):
  day = (local - timedelta(days=offset)).date()
  if day.isoweekday() not in weekdays: continue
  due = datetime(day.year, day.month, day.day, hour, minute, tzinfo=local.tzinfo)
  if due <= local: return day.isoformat()
 return None

def run(force=False):
 app.init()
 with LOCK.open('w') as lock:
  try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
  except BlockingIOError: return {'status': 'already_running'}
  local = datetime.now(ZoneInfo('Asia/Tokyo'))
  with app.db() as c:
   settings = c.execute('SELECT * FROM collection_settings WHERE id=1').fetchone()
   due = latest_due(local, [int(x) for x in settings['weekdays'].split(',')], settings['hour'], settings['minute']) if settings['enabled'] else None
   if not force and not due: return {'status': 'not_scheduled'}
   if not force and c.execute("SELECT 1 FROM collection_jobs WHERE trigger='scheduled' AND scheduled_for=?", (due,)).fetchone():
    return {'status': 'already_ran_for_date', 'scheduled_for': due}
   pending_before = c.execute("SELECT count(*) FROM candidates WHERE state='pending'").fetchone()[0]
   job_id = c.execute('INSERT INTO collection_jobs(started_at,trigger,status,pending_before,scheduled_for) VALUES(?,?,?,?,?)', (local.isoformat(timespec='seconds'), 'manual' if force else 'scheduled', 'running', pending_before, None if force else due)).lastrowid
  try:
   result = app.collect_sources(limit=50, pause=0.5)
   # The J-League suspension notice is a separate official feed.
   with app.db() as c:
    try: suspension = app.collect_suspension_notice(c)
    except Exception as exc: suspension = {'error': str(exc)}
    pending_after = c.execute("SELECT count(*) FROM candidates WHERE state='pending'").fetchone()[0]
    status = 'partial' if result['failed'] or result['partial'] or suspension.get('error') else 'success'
    c.execute('''UPDATE collection_jobs SET finished_at=?,status=?,source_count=?,success_count=?,partial_count=?,failure_count=?,found_count=?,attempted_count=?,pending_after=?,details_json=? WHERE id=?''',
     (app.now(),status,result['sources'],result['success'],result['partial'],result['failed'],result['found'],result['attempted'],pending_after,json.dumps({'sources':result['results'],'suspension':suspension},ensure_ascii=False),job_id))
   return {'job_id':job_id,'status':status,'sources':result['sources'],'failed':result['failed'],'partial':result['partial'],'pending_added':pending_after-pending_before}
  except Exception as exc:
   with app.db() as c:c.execute('UPDATE collection_jobs SET finished_at=?,status=?,details_json=? WHERE id=?',(app.now(),'failed',json.dumps({'error':str(exc)},ensure_ascii=False),job_id))
   raise

if __name__ == '__main__':
 parser=argparse.ArgumentParser()
 parser.add_argument('--force',action='store_true')
 args=parser.parse_args()
 print(json.dumps(run(args.force),ensure_ascii=False))
