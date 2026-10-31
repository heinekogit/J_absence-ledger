"""Read-only snapshots of the prediction project's J.League player CSV."""
import csv
import hashlib
import re
import unicodedata
from collections import Counter
from pathlib import Path
from datetime import datetime, timezone

SOURCE = Path('/Users/dev_tomo/Desktop/tt_prj_restart/data/manual/jleague_club_players.csv')
REQUIRED = {'player_name','position','player_no','birth','club_key','club_name','fetched_at','source_url'}
TEAM_KEYS = {
 '鹿島':'kashima','浦和':'urawa','柏':'kashiwa','FC東京':'ftokyo','東京Ｖ':'tokyov',
 '町田':'machida','川崎Ｆ':'kawasakif','横浜FM':'yokohamafm','横浜FC':'yokohamafc',
 '湘南':'shonan','清水':'shimizu','名古屋':'nagoya','京都':'kyoto','Ｇ大阪':'gosaka',
 'Ｃ大阪':'cosaka','神戸':'kobe','岡山':'okayama','広島':'hiroshima','福岡':'fukuoka',
 '千葉':'chiba','札幌':'sapporo','仙台':'sendai','秋田':'akita','山形':'yamagata',
 'いわき':'iwaki','水戸':'mito','大宮':'omiya','甲府':'kofu','富山':'toyama',
 '磐田':'iwata','藤枝':'fujieda','新潟':'niigata','長崎':'nagasaki','大分':'oita',
 '鳥栖':'tosu','徳島':'tokushima','今治':'imabari','八戸':'hachinohe','栃木Ｃ':'tochigic',
 '宮崎':'miyazaki',
 'C大阪':'cosaka','G大阪':'gosaka','川崎F':'kawasakif','東京V':'tokyov',
 '山口':'yamaguchi','松本':'matsumoto','高知':'kochi','鳥取':'tottori',
 '栃木SC':'tochigi','ロアッソ熊本':'kumamoto',
}

def name_key(value):
 return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value or '')).replace('﨑','崎')

def install(c):
 c.execute('''CREATE TABLE IF NOT EXISTS roster_snapshots(
  id INTEGER PRIMARY KEY, source_path TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE,
  imported_at TEXT NOT NULL, row_count INTEGER NOT NULL, club_count INTEGER NOT NULL,
  fetched_min TEXT NOT NULL, fetched_max TEXT NOT NULL)''')
 c.execute('''CREATE TABLE IF NOT EXISTS roster_players(
  id INTEGER PRIMARY KEY, snapshot_id INTEGER NOT NULL REFERENCES roster_snapshots(id),
  source_row INTEGER NOT NULL, club_key TEXT NOT NULL, club_name TEXT NOT NULL,
  player_name TEXT NOT NULL, normalized_name TEXT NOT NULL, birth TEXT,
  position TEXT, player_no TEXT, fetched_at TEXT NOT NULL, source_url TEXT NOT NULL,
  UNIQUE(snapshot_id,source_row))''')
 c.execute('CREATE INDEX IF NOT EXISTS roster_players_name ON roster_players(snapshot_id,normalized_name)')

def import_snapshot(c, path=SOURCE):
 install(c)
 digest=hashlib.sha256(path.read_bytes()).hexdigest()
 old=c.execute('SELECT * FROM roster_snapshots WHERE sha256=?',(digest,)).fetchone()
 if old:return {'snapshot_id':old['id'],'row_count':old['row_count'],'club_count':old['club_count'],'already_imported':True}
 with path.open(encoding='utf-8-sig',newline='') as f:
  reader=csv.DictReader(f)
  if not REQUIRED.issubset(reader.fieldnames or []):raise ValueError('選手CSVの必要列がありません')
  data=list(reader)
 if not data:raise ValueError('選手CSVが空です')
 bad=[n for n,r in enumerate(data,2) if not all((r[k] or '').strip() for k in ('player_name','club_key','club_name','fetched_at','source_url'))]
 if bad:raise ValueError(f'選手CSVに必須値の欠落があります: {bad[:5]}')
 duplicates=Counter((r['club_key'],name_key(r['player_name'])) for r in data)
 if any(n>1 for n in duplicates.values()):raise ValueError('同一クラブ内に同名の選手が重複しています')
 clubs={r['club_key'] for r in data}
 missing=set(TEAM_KEYS.values())-clubs
 if missing:raise ValueError('J1・J2対象クラブの名簿が不足: '+','.join(sorted(missing)))
 dates=[r['fetched_at'][:10] for r in data]
 if len(set(dates))!=1:raise ValueError('取得日が混在しています')
 counts=Counter(r['club_key'] for r in data)
 if min(counts.values())<10:raise ValueError('選手数が極端に少ないクラブがあります')
 stamp=datetime.now(timezone.utc).isoformat(timespec='seconds')
 sid=c.execute('''INSERT INTO roster_snapshots(source_path,sha256,imported_at,row_count,club_count,fetched_min,fetched_max)
  VALUES(?,?,?,?,?,?,?)''',(str(path),digest,stamp,len(data),len(clubs),min(r['fetched_at'] for r in data),max(r['fetched_at'] for r in data))).lastrowid
 for n,r in enumerate(data,2):
  c.execute('''INSERT INTO roster_players(snapshot_id,source_row,club_key,club_name,player_name,normalized_name,birth,position,player_no,fetched_at,source_url)
   VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(sid,n,r['club_key'],r['club_name'],r['player_name'],name_key(r['player_name']),r['birth'],r['position'],r['player_no'],r['fetched_at'],r['source_url']))
 return {'snapshot_id':sid,'row_count':len(data),'club_count':len(clubs),'already_imported':False}

def case_matches(c):
 snap=c.execute('SELECT max(id) FROM roster_snapshots').fetchone()[0]
 if snap is None:return []
 players={}
 for r in c.execute('SELECT * FROM roster_players WHERE snapshot_id=?',(snap,)):
  players.setdefault(r['normalized_name'],[]).append(dict(r))
 out=[]
 for case in c.execute("SELECT id,team,player,status FROM cases WHERE status='open' ORDER BY team,player,id"):
  matches=players.get(name_key(case['player']),[])
  expected=TEAM_KEYS.get(case['team'])
  same=[r for r in matches if r['club_key']==expected]
  status='same_club' if len(same)==1 and len(matches)==1 else 'ambiguous' if len(matches)>1 else 'other_club' if matches else 'not_found'
  out.append({'case_id':case['id'],'team':case['team'],'player':case['player'],'status':status,'matches':[{'club_key':r['club_key'],'club_name':r['club_name'],'player_name':r['player_name'],'birth':r['birth'],'source_url':r['source_url'],'source_row':r['source_row']} for r in matches]})
 return out
