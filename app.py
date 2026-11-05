import csv
import gzip
import argparse
import hashlib
import html
import http.cookiejar
import io
import json
import os
import subprocess
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
import unicodedata
import injury_reference
import roster
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
DB = DATA / 'ledger.sqlite3'
SOURCE_CSV = Path('/Users/dev_tomo/Desktop/tt_prj_restart/data/manual/欠場管理リスト.csv')
COLS = ['season','origin_competition_key','applies_across_competitions','team','player_name','absence_type','start_date','expected_weeks','expected_return_date','note']
SOURCES = [
 ('Jリーグ J1','https://www.jleague.jp/j1/news/','J1','verified-sample'),
 ('Jリーグ J2','https://www.jleague.jp/j2/news/','J2','verified-sample'),
 ('横浜F・マリノス','https://www.f-marinos.com/news/','横浜FM','verified-sample'),
 ('川崎フロンターレ','https://www.frontale.co.jp/info/','川崎Ｆ','verified-sample'),
 ('サガン鳥栖','https://www.sagan-tosu.net/news/team/_/','鳥栖','verified-sample'),
 ('V・ファーレン長崎','https://www.v-varen.com/topteam_news','長崎','verified-sample'),
 ('横浜FC','https://yokohamafc.com/news/','横浜FC','partial'),
 ('湘南ベルマーレ','https://www.bellmare.co.jp/category/all/topics/news/topteamnews/','湘南','verified-sample'),
 ('ガンバ大阪','https://www.gamba-osaka.net/news/index/c/1/','Ｇ大阪','partial'),
 ('鹿島アントラーズ','https://www.antlers.co.jp/ja-world/blogs/news','鹿島','partial'),
 ('柏レイソル','https://www.reysol.co.jp/news/topteam/','柏','verified-sample'),
 ('サンフレッチェ広島','https://www.sanfrecce.co.jp/news?news_category_id=1','広島','partial'),
 ('FC今治','https://www.fcimabari.com/news?category=%E3%83%81%E3%83%BC%E3%83%A0','今治','partial'),
 ('徳島ヴォルティス','https://www.vortis.jp/news/date/2026/?category=team','徳島','partial'),
 ('ヴァンフォーレ甲府','https://www.ventforet.jp/news/team','甲府','partial'),
 ('FC東京','https://www.fctokyo.co.jp/news/','FC東京','partial'),
 ('ファジアーノ岡山','https://www.fagiano-okayama.com/news/','岡山','partial'),
 ('ヴィッセル神戸','https://www.vissel-kobe.co.jp/news/?c=3','神戸','partial'),
 ('FC町田ゼルビア','https://www.zelvia.co.jp/news-category/topteam/','町田','partial'),
 ('浦和レッズ','https://www.urawa-reds.co.jp/topteamtopics/team/','浦和','partial'),
 ('水戸ホーリーホック','https://www.mito-hollyhock.net/news_cat/topteam/','水戸','partial'),
 ('名古屋グランパス','https://nagoya-grampus.jp/news/pressrelease/','名古屋','partial'),
 ('モンテディオ山形','https://www.montedioyamagata.jp/news/2026/team/','山形','partial'),
 ('カターレ富山','https://www.kataller.co.jp/category/all/topteam/','富山','partial'),
 ('藤枝MYFC','https://myfc.co.jp/news/newslist/topteam/','藤枝','partial'),
 ('ジュビロ磐田（公式トップ頁）','https://jubilo-iwata.co.jp/','磐田','partial-home'),
 ('京都サンガF.C.','https://www.sanga-fc.jp/news','京都','partial'),
 ('セレッソ大阪','https://www.cerezo.jp/news/','Ｃ大阪','partial'),
 ('いわきFC','https://iwakifc.com/category/news/team/','いわき','partial'),
 ('ベガルタ仙台','https://www.vegalta.co.jp/news-team/top.html','仙台','partial'),
 ('ヴァンラーレ八戸','https://vanraure.net/archives/category/news','八戸','partial'),
 ('大分トリニータ','https://www.oita-trinita.co.jp/news/','大分','partial'),
 ('アルビレックス新潟','https://www.albirex.co.jp/news/top_team/','新潟','partial'),
 ('栃木シティ','https://tochigi-city.com/category/new/team/','栃木Ｃ','partial'),
 ('ブラウブリッツ秋田','https://blaublitz.jp/category/whatsnew','秋田','partial'),
 ('RB大宮アルディージャ','https://www.rbomiya.com/jp-ja/news','大宮','partial'),
 ('アビスパ福岡','https://www.avispa.co.jp/news_archive?cat=team','福岡','partial'),
 ('ジェフユナイテッド千葉','https://jefunited.co.jp/news/list?c=2&ym=0','千葉','partial-api'),
 ('北海道コンサドーレ札幌','https://www.consadole-sapporo.jp/news/','札幌','partial'),
 ('テゲバジャーロ宮崎','https://www.tegevajaro.com/news?page=1&year=2026','宮崎','partial'),
]

def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def connect():
 DATA.mkdir(exist_ok=True)
 c=sqlite3.connect(DB, timeout=20)
 c.row_factory=sqlite3.Row
 c.execute('PRAGMA foreign_keys=ON')
 c.execute('PRAGMA journal_mode=WAL')
 return c
@contextmanager
def db():
 c=connect()
 try:
  yield c
  c.commit()
 except Exception:
  c.rollback()
  raise
 finally: c.close()
def init():
 with db() as c:
  c.executescript('''
  CREATE TABLE IF NOT EXISTS cases(id INTEGER PRIMARY KEY, source_row INTEGER UNIQUE, team TEXT, player TEXT, absence_type TEXT, diagnosis TEXT, start_date TEXT, start_raw TEXT, duration_raw TEXT, duration_min REAL, duration_max REAL, duration_unit TEXT, duration_status TEXT, expected_weeks TEXT, expected_return_date TEXT, note TEXT, season TEXT, origin_competition_key TEXT, applies_across_competitions TEXT, status TEXT NOT NULL DEFAULT 'open', version INTEGER NOT NULL DEFAULT 1, source_article INTEGER, created_at TEXT);
  CREATE TABLE IF NOT EXISTS articles(id INTEGER PRIMARY KEY, url TEXT UNIQUE, title TEXT, source TEXT, published_at TEXT, fetched_at TEXT, body_hash TEXT, body_excerpt TEXT);
  CREATE TABLE IF NOT EXISTS article_versions(id INTEGER PRIMARY KEY, article_id INTEGER, body_hash TEXT, excerpt TEXT, fetched_at TEXT, UNIQUE(article_id,body_hash));
  CREATE TABLE IF NOT EXISTS article_links(article_id INTEGER, target_url TEXT, PRIMARY KEY(article_id,target_url));
  CREATE TABLE IF NOT EXISTS candidates(id INTEGER PRIMARY KEY, article_id INTEGER, fingerprint TEXT UNIQUE, kind TEXT, team TEXT, player TEXT, diagnosis TEXT, start_raw TEXT, start_date TEXT, duration_raw TEXT, duration_min REAL, duration_max REAL, duration_unit TEXT, duration_status TEXT, event_date TEXT, excerpt TEXT, state TEXT DEFAULT 'pending', case_id INTEGER, created_at TEXT, decision_at TEXT);
  CREATE TABLE IF NOT EXISTS evidence(id INTEGER PRIMARY KEY, case_id INTEGER, article_id INTEGER, candidate_id INTEGER, kind TEXT, excerpt TEXT, event_date TEXT, created_at TEXT, UNIQUE(case_id,candidate_id));
  CREATE TABLE IF NOT EXISTS case_merges(id INTEGER PRIMARY KEY, from_case_id INTEGER UNIQUE, to_case_id INTEGER, reason TEXT, created_at TEXT);
  CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY, case_id INTEGER, candidate_id INTEGER, action TEXT, before_json TEXT, after_json TEXT, reason TEXT, effective_date TEXT, created_at TEXT);
  CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY, name TEXT UNIQUE, url TEXT, club TEXT, coverage TEXT, last_success TEXT, last_failure TEXT, failure TEXT, last_count INTEGER DEFAULT 0);
  CREATE TABLE IF NOT EXISTS source_runs(id INTEGER PRIMARY KEY, source_id INTEGER, list_url TEXT, started_at TEXT, finished_at TEXT, status TEXT, found_count INTEGER DEFAULT 0, attempted_count INTEGER DEFAULT 0, success_count INTEGER DEFAULT 0, failure_count INTEGER DEFAULT 0, details_json TEXT);
  CREATE TABLE IF NOT EXISTS list_entries(id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL, article_url TEXT NOT NULL, title TEXT, first_list_url TEXT, last_list_url TEXT, first_seen_at TEXT, last_seen_at TEXT, auto_selected INTEGER DEFAULT 0, watch_reason TEXT, review_state TEXT DEFAULT 'unreviewed', review_reason TEXT, reviewed_at TEXT, UNIQUE(source_id,article_url));
  CREATE TABLE IF NOT EXISTS list_entry_sightings(entry_id INTEGER,run_id INTEGER,list_url TEXT,seen_at TEXT,PRIMARY KEY(entry_id,run_id));
  CREATE TABLE IF NOT EXISTS exports(id INTEGER PRIMARY KEY, created_at TEXT, sha256 TEXT, row_count INTEGER, rows_json TEXT);
  CREATE TABLE IF NOT EXISTS imports(id INTEGER PRIMARY KEY, created_at TEXT, path TEXT, sha256 TEXT, row_count INTEGER, header_json TEXT);
  CREATE TABLE IF NOT EXISTS search_runs(id INTEGER PRIMARY KEY, case_id INTEGER, query TEXT, searched_at TEXT, status TEXT, error TEXT, result_count INTEGER);
  CREATE TABLE IF NOT EXISTS search_results(id INTEGER PRIMARY KEY, run_id INTEGER, url TEXT, title TEXT, source_type TEXT, fetched_article INTEGER, UNIQUE(run_id,url));
  CREATE TABLE IF NOT EXISTS collection_settings(id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL DEFAULT 1, weekdays TEXT NOT NULL DEFAULT '2,5', hour INTEGER NOT NULL DEFAULT 9, minute INTEGER NOT NULL DEFAULT 0);
  CREATE TABLE IF NOT EXISTS collection_jobs(id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, trigger TEXT NOT NULL, status TEXT NOT NULL, source_count INTEGER DEFAULT 0, success_count INTEGER DEFAULT 0, partial_count INTEGER DEFAULT 0, failure_count INTEGER DEFAULT 0, found_count INTEGER DEFAULT 0, attempted_count INTEGER DEFAULT 0, pending_before INTEGER DEFAULT 0, pending_after INTEGER DEFAULT 0, details_json TEXT);
  ''')
  c.execute("INSERT OR IGNORE INTO collection_settings(id,enabled,weekdays,hour,minute) VALUES(1,1,'2,5',9,0)")
  injury_reference.install(c)
  roster.install(c)
  for s in SOURCES: c.execute('INSERT OR IGNORE INTO sources(name,url,club,coverage) VALUES(?,?,?,?)',s)
  case_columns={x[1] for x in c.execute('PRAGMA table_info(cases)')}
  if 'forecast_review_needed' not in case_columns:
   c.execute('ALTER TABLE cases ADD COLUMN forecast_review_needed INTEGER NOT NULL DEFAULT 0')
  if 'forecast_review_reason' not in case_columns:
   c.execute('ALTER TABLE cases ADD COLUMN forecast_review_reason TEXT')
  if 'scheduled_for' not in {x[1] for x in c.execute('PRAGMA table_info(collection_jobs)')}:
   c.execute('ALTER TABLE collection_jobs ADD COLUMN scheduled_for TEXT')
  if 'list_url' not in {x[1] for x in c.execute('PRAGMA table_info(source_runs)')}:
   c.execute('ALTER TABLE source_runs ADD COLUMN list_url TEXT')
  c.execute('UPDATE source_runs SET list_url=(SELECT url FROM sources WHERE sources.id=source_runs.source_id) WHERE list_url IS NULL')
  for article in c.execute("SELECT id,url FROM articles WHERE url LIKE 'https://www.gamba-osaka.net/news/index/%'").fetchall():
   normalized=canonical(article['url'])
   if normalized!=article['url'] and not c.execute('SELECT 1 FROM articles WHERE url=?',(normalized,)).fetchone():
    c.execute('UPDATE articles SET url=? WHERE id=?',(normalized,article['id']))

def rows(c,sql,args=()): return [dict(x) for x in c.execute(sql,args).fetchall()]
def source_rows():
 with SOURCE_CSV.open(encoding='utf-8-sig',newline='') as f:
  rd=csv.reader(f); header=next(rd); values=list(rd)
 if len(header)!=10 or any(len(x)!=10 for x in values): raise ValueError('元CSVの列数が10ではありません')
 return header, values
def migration_preview(c):
 if not SOURCE_CSV.exists(): return {'error':'元CSVが見つかりません','path':str(SOURCE_CSV)}
 head,values=source_rows(); digest=hashlib.sha256(SOURCE_CSV.read_bytes()).hexdigest()
 return {'path':str(SOURCE_CSV),'header':head,'count':len(values),'sha256':digest,'already_imported':c.execute('SELECT count(*) FROM imports').fetchone()[0]>0,'samples':[{'row':i+2,'values':v} for i,v in enumerate(values[:3])]}
def migrate(c):
 p=migration_preview(c)
 if p.get('already_imported'): raise ValueError('移行済みです')
 if p.get('error'): raise ValueError(p['error'])
 _,values=source_rows()
 for i,v in enumerate(values,2):
  x=dict(zip(COLS,v)); c.execute('''INSERT INTO cases(source_row,team,player,absence_type,start_date,expected_weeks,expected_return_date,note,season,origin_competition_key,applies_across_competitions,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',(i,x['team'],x['player_name'],x['absence_type'],x['start_date'],x['expected_weeks'],x['expected_return_date'],x['note'],x['season'],x['origin_competition_key'],x['applies_across_competitions'],'open',now()))
 c.execute('INSERT INTO imports(created_at,path,sha256,row_count,header_json) VALUES(?,?,?,?,?)',(now(),p['path'],p['sha256'],p['count'],json.dumps(p['header'],ensure_ascii=False)))
 return {'imported':len(values)}

class HTMLText:
 def __init__(self):
  from html.parser import HTMLParser
  class Parser(HTMLParser):
   def __init__(self): super().__init__(); self.parts=[]; self.links=[]; self.href=None; self.skip=0; self.title=False; self.page_title=''
   def handle_starttag(self,tag,attrs):
    d=dict(attrs)
    if tag in ('script','style','nav','footer'): self.skip+=1
    if tag=='a': self.href=d.get('href'); self.links.append([self.href,''])
    if tag=='title': self.title=True
    if tag in ('p','div','h1','h2','h3','tr','li','br','td'): self.parts.append('\n')
   def handle_endtag(self,tag):
    if tag in ('script','style','nav','footer') and self.skip: self.skip-=1
    if tag=='a': self.href=None
    if tag=='title': self.title=False
   def handle_data(self,data):
    if self.title: self.page_title+=data
    if self.skip: return
    if self.href and self.links: self.links[-1][1]+=data
    self.parts.append(data)
  self.parser=Parser()
 def parse(self,body):
  self.parser.feed(body)
  text='\n'.join(x.strip() for x in ''.join(self.parser.parts).splitlines() if x.strip())
  text=re.sub(r'\n{2,}','\n',text)
  return self.parser.page_title.strip(),text,self.parser.links
def fetch(url):
 parsed=urllib.parse.urlparse(url)
 if parsed.scheme!='https' or not parsed.hostname or parsed.hostname not in ALLOWED_HOSTS: raise ValueError('登録済み公式ドメインのHTTPS URLのみ取得できます')
 class RestrictedRedirect(urllib.request.HTTPRedirectHandler):
  def redirect_request(self,req,fp,code,msg,headers,newurl):
   p=urllib.parse.urlparse(newurl)
   if p.scheme!='https' or p.hostname not in ALLOWED_HOSTS: raise ValueError('登録外ドメインへの転送を停止しました')
   return super().redirect_request(req,fp,code,msg,headers,newurl)
 req=urllib.request.Request(url,headers={'User-Agent':'AbsenceLedger/0.1 (personal local use)'})
 with urllib.request.build_opener(RestrictedRedirect()).open(req,timeout=15) as r:
  if r.status!=200: raise ValueError('HTTP '+str(r.status))
  content=r.read(1_500_001)
  if len(content)>1_500_000: raise ValueError('記事が大きすぎます')
  if r.headers.get('Content-Encoding','').lower()=='gzip':
   content=gzip.decompress(content)
   if len(content)>1_500_000:raise ValueError('展開後の記事が大きすぎます')
  charset=r.headers.get_content_charset() or 'utf-8'
 return content.decode(charset,errors='replace')
MANUAL_ARTICLE_HOSTS={'jubilo-iwata.co.jp':('ジュビロ磐田','磐田')}
ALLOWED_HOSTS={urllib.parse.urlparse(s[1]).hostname for s in SOURCES}|set(MANUAL_ARTICLE_HOSTS)|{'data.j-league.or.jp'}
def canonical(url):
 p=urllib.parse.urlparse(url)
 if p.hostname=='www.kataller.co.jp':
  return urllib.parse.urlunparse((p.scheme,p.netloc,urllib.parse.quote(urllib.parse.unquote(p.path),safe='/'),'','',''))
 if p.hostname=='www.gamba-osaka.net':
  match=re.search(r'/news/index/(?:c/\d+/)?no/(\d+)(?:/|$)',p.path)
  if match:return f'https://www.gamba-osaka.net/news/index/no/{match.group(1)}/'
 return urllib.parse.urlunparse((p.scheme,p.netloc,p.path,'','',''))
def name_key(value): return re.sub(r'\s+','',unicodedata.normalize('NFKC',value or ''))
def possible_name_key(value): return name_key(value).replace('﨑','崎')
def source_for(url):
 host=urllib.parse.urlparse(url).hostname
 if host in MANUAL_ARTICLE_HOSTS:return MANUAL_ARTICLE_HOSTS[host]
 for name,base,club,_ in SOURCES:
  if urllib.parse.urlparse(base).hostname==host: return name,club
 return '', ''
def extract(text,title,club):
 # Candidate only. Restrict to the article region and split repeated player sections.
 clean_title=re.split(r'[|｜]',title,maxsplit=1)[0].splitlines()[0].strip()
 if club=='Ｃ大阪' and re.search(r'選手の負傷について',clean_title):
  person=re.search(r'([^\n]{2,30})選手の負傷について',clean_title)
  diagnosis=re.search(r'■\s*傷病名[：:]\s*([^\n]{2,80})',text)
  published=re.search(r'\b(20\d{2})\.\d{1,2}\.\d{1,2}\b',text)
  injury=re.search(r'(\d{1,2})月(\d{1,2})日[^\n]{0,140}負傷',text)
  if person and diagnosis:
   raw=f'{injury[1]}月{injury[2]}日' if injury else ''
   start=f'{published[1]}-{int(injury[1]):02d}-{int(injury[2]):02d}' if published and injury else ''
   return [dict(kind='absence',team=club,player=person[1].strip(),diagnosis=diagnosis[1].strip(),start_raw=raw,start_date=start,duration_raw='',duration_min=None,duration_max=None,duration_unit='',duration_status='not_stated',event_date='',excerpt=text[:700])]
 if club=='宮崎' and '傷病について' in clean_title:
  person=re.search(r'([^\n]{2,30})選手の傷病について',clean_title)
  diagnosis=re.search(r'傷病名[：:]\s*([^\n]{2,80})',text)
  if person and diagnosis:
   raw=re.search(r'(?:本年)?(\d{1,2}月(?:上旬|中旬|下旬|\d{1,2}日))[^\n]{0,50}負傷',text)
   duration=re.search(r'全治約?(\d+)\s*([カかヶ]月|週間|週)',text)
   qualitative=re.search(r'復帰まで数か月',text)
   return [dict(kind='absence',team=club,player=person[1].strip(),diagnosis=diagnosis[1].strip(),start_raw=raw[1] if raw else '',start_date='',duration_raw=duration[0] if duration else (qualitative[0] if qualitative else ''),duration_min=int(duration[1]) if duration else None,duration_max=int(duration[1]) if duration else None,duration_unit=duration[2] if duration else '',duration_status='stated' if duration or qualitative else 'not_stated',event_date='',excerpt=text[-700:])]
 if '復帰' in clean_title and re.search(r'(?:期限付き移籍|レンタル).{0,80}(?:復帰|所属)|(?:期限付き移籍|レンタル)(?:していた|しておりました|から)',text):
  return []
 if club in ('J1','J2'):
  if '出場停止選手のお知らせ' in clean_title:
   out=[]
   article=text.split('出場停止試合\n',1)[-1].split('\n・大会「J1」',1)[0].split('\n役員\n役職\n',1)[0]
   for match in re.finditer(r'([^\n]{2,40})\n([^\n]{1,20})\n(J[12]\([a-z]\))\n([^\n]*明治安田Ｊ[１２]リーグ[^\n]*)',article):
    player,team,code,fixture=match.groups()
    fixture=unicodedata.normalize('NFKC',fixture)
    date=re.search(r'\((\d{1,2}/\d{1,2})\)',fixture)
    out.append(dict(kind='suspension',team=team.strip(),player=re.sub(r'\s+',' ',player).strip(),diagnosis='',start_raw=date.group(1) if date else '',start_date='',duration_raw='',duration_min=None,duration_max=None,duration_unit='',duration_status='not_stated',event_date='',excerpt=f'出場停止: {code} / {fixture}'))
   return out
  if '【サマリー' in clean_title and '復帰後初ゴール' in text:
   goal=re.search(r'(?:\d{1,2}分には)([一-龥々ァ-ヴー・\s]{2,25})の復帰後初ゴール',text)
   team=re.search(r'ホームで[^。\n]{1,30}と対戦した([^、。\n]{1,12})は、[^。\n]{0,150}復帰後初ゴール',text)
   date=re.search(r'(20\d{2})/(\d{1,2})/(\d{1,2})',text)
   if goal and team and date:
    event_date=f'{date[1]}-{int(date[2]):02d}-{int(date[3]):02d}'
    excerpt=re.search(r'ホームで[^。\n]{1,30}と対戦した[^。\n]*復帰後初ゴール[^。\n]*。',text)
    return [dict(kind='appearance',team=team.group(1).strip(),player=goal.group(1).strip(),diagnosis='',start_raw='',start_date='',duration_raw='',duration_min=None,duration_max=None,duration_unit='',duration_status='not_stated',event_date=event_date,excerpt=excerpt.group(0) if excerpt else goal.group(0))]
  labels=re.findall(r'【([^】]+)】',clean_title)
  if labels: club=labels[-1].strip()
  headline_injury=re.search(r'(?:GK|DF|MF|FW)\s*([^\nが]{2,30}?)が全治(?:約)?(\d+)(?:[〜～~-](\d+))?(か月|ヶ月|カ月|週間|週)の負傷',clean_title)
  if headline_injury:
   short_name=headline_injury.group(1).strip()
   person=short_name
   full_name=re.search(r'(?:GK|DF|MF|FW)\s*'+re.escape(short_name)+r'\s+([一-龥々ァ-ヴー・]{1,15})の負傷',text)
   if full_name:person+=' '+full_name.group(1)
   sentence=re.search(re.escape(short_name)+r'は[^。\n]{0,120}?([^、。\n]{2,60}?)と診断',text)
   if sentence:
    diagnosis=sentence.group(1).strip().rsplit('し、',1)[-1].strip()
    excerpt=text[sentence.start():sentence.end()+120].split('関連リンク',1)[0][:450]
    return [dict(kind='absence',team=club,player=person,diagnosis=diagnosis,start_raw='',start_date='',duration_raw=headline_injury.group(0).split('全治',1)[-1].split('の負傷',1)[0].join(['全治','']),duration_min=int(headline_injury.group(2)),duration_max=int(headline_injury.group(3) or headline_injury.group(2)),duration_unit=headline_injury.group(4),duration_status='stated',event_date='',excerpt=excerpt)]
  if re.search(r'(?:GK|DF|MF|FW)[^\sが]{1,20}が全治(?:約)?\d+(?:か月|ヶ月|カ月|週間|週)の負傷',clean_title):
   detail=re.search(r'(?:GK|DF|MF|FW)\s*([^\n、。]{2,30}?)が([^。\n]{2,80}?)で(全治(?:約)?\d+(?:か月|ヶ月|カ月|週間|週))の診断',text)
   if detail:
    person,diagnosis,duration_raw=detail.groups()
    injury=re.search(r'((?:\d{1,2}月)?(?:上旬|中旬|下旬|\d{1,2}日))[^。\n]{0,50}負傷',text[detail.end():detail.end()+180])
    length=re.search(r'(\d+)(か月|ヶ月|カ月|週間|週)',duration_raw)
    return [dict(kind='absence',team=club,player=person.strip(),diagnosis=diagnosis.strip(),start_raw=injury.group(1) if injury else '',start_date='',duration_raw=duration_raw,duration_min=int(length.group(1)) if length else None,duration_max=int(length.group(1)) if length else None,duration_unit=length.group(2) if length else '',duration_status='stated' if length else 'not_stated',event_date='',excerpt=text[detail.start():detail.end()+180].split('関連リンク',1)[0])]
  multiple=re.search(r'(?:GK|DF|MF|FW)\s*([一-龥々ァ-ヴー・\s]{2,24})と(?:GK|DF|MF|FW)\s*([一-龥々ァ-ヴー・\s]{2,24})の負傷を発表しました',text)
  if multiple:
   out=[]
   for person in (multiple.group(1).strip(),multiple.group(2).strip()):
    short=person.split()[0]
    sentence=re.search(r'[^。\n]*'+re.escape(short)+r'[^。\n]*と診断され[^。\n]*。',text)
    if not sentence:continue
    detail=sentence.group(0)
    diagnosis=re.search(re.escape(short)+r'は([一-龥々ァ-ヴー・]{2,40})と診断され',detail)
    date=re.search(r'(\d{1,2}日)[^。\n]*負傷',detail)
    out.append(dict(kind='absence',team=club,player=person,diagnosis=diagnosis.group(1) if diagnosis else '',start_raw=date.group(1) if date else '',start_date='',duration_raw='',duration_min=None,duration_max=None,duration_unit='',duration_status='not_stated',event_date='',excerpt=detail))
   if out:return out
  name_match=re.search(r'(?:GK|DF|MF|FW)\s*([一-龥々ァ-ヴー・\s]{2,30})の負傷を発表しました',text)
  prognosis_match=re.search(r'(?:GK|DF|MF|FW)\s*([一-龥々ァ-ヴー・\s]{2,30}?)が([^。\n]{2,60}?)で(全治\d+[〜～~-]\d+週間)の診断',text)
  diagnosis_match=re.search(r'([^。\n]{2,50})と診断され',text)
  if (name_match and diagnosis_match) or prognosis_match:
   person=(name_match or prognosis_match).group(1).strip()
   diagnosis=(diagnosis_match.group(1) if diagnosis_match else prognosis_match.group(2)).strip()
   if '、' in diagnosis: diagnosis=diagnosis.rsplit('、',1)[-1]
   date_match=re.search(r'(\d{1,2}日)に行われた[^。\n]{0,100}で負傷',text)
   start_raw=date_match.group(1) if date_match else ''
   duration_raw=prognosis_match.group(3) if prognosis_match else ''
   duration_parts=re.search(r'(\d+)[〜～~-](\d+)週間',duration_raw)
   excerpt_match=re.search(r'[^\n]{0,100}'+re.escape(person)+r'[^\n]{0,250}',text)
   excerpt=(text[excerpt_match.start():] if excerpt_match else text).split('関連リンク',1)[0][:450]
   return [dict(kind='absence',team=club,player=person,diagnosis=diagnosis,start_raw=start_raw,start_date='',duration_raw=duration_raw,duration_min=int(duration_parts.group(1)) if duration_parts else None,duration_max=int(duration_parts.group(2)) if duration_parts else None,duration_unit='週' if duration_parts else '',duration_status='stated' if duration_parts else 'not_stated',event_date='',excerpt=excerpt)]
  return []
 if club=='湘南' and re.search(r'[^\n]{2,20}選手・[^\n]{2,20}選手',clean_title):
  names=re.findall(r'([^\n、・]{2,20})選手\n◆負傷状況\n([^\n]{2,80})',text)
  if len(names)>1:
   date=re.search(r'(\d{1,2}月\d{1,2}日)[^\n]{0,80}負傷',text)
   return [dict(kind='absence',team=club,player=name.strip(),diagnosis=diagnosis.strip(),start_raw=date.group(1) if date else '',start_date='',duration_raw='',duration_min=None,duration_max=None,duration_unit='',duration_status='not_stated',event_date='',excerpt=f'{name}選手\n◆負傷状況\n{diagnosis}') for name,diagnosis in names]
 if club=='今治' and re.search(r'選手の(?:負傷|手術)について',clean_title):
  person=re.search(r'([^\n]{2,30})選手の(?:負傷|手術)について',clean_title)
  block=text.split('このニュースをシェア',1)[0]
  diagnosis=re.search(r'診断名[：:]\s*([^\n]{2,80})',block)
  injury_date=re.search(r'(\d{1,2}月\d{1,2}日)[^\n]{0,80}受傷',block)
  if person and diagnosis:
   return [dict(kind='absence',team=club,player=person.group(1).strip(),diagnosis=diagnosis.group(1).strip(),start_raw=injury_date.group(1) if injury_date else '',start_date='',duration_raw='',duration_min=None,duration_max=None,duration_unit='',duration_status='not_stated',event_date='',excerpt=block[-450:])]
 if club=='徳島' and re.search(r'選手\s*負傷のお知らせ',clean_title):
  person=re.search(r'([^\n]{2,30})選手\s*負傷のお知らせ',clean_title)
  block=text.split('## SPONSOR',1)[0].split('スポンサー',1)[0]
  diagnosis=re.search(r'診断名\s*\n([^\n]{2,80})',block)
  injury_date=re.search(r'受傷日\s*\n(\d{1,2}月\d{1,2}日)',block)
  if person and diagnosis:
   return [dict(kind='absence',team=club,player=person.group(1).strip(),diagnosis=diagnosis.group(1).strip(),start_raw=injury_date.group(1) if injury_date else '',start_date='',duration_raw='',duration_min=None,duration_max=None,duration_unit='',duration_status='not_stated',event_date='',excerpt=block[-450:])]
 if club=='甲府' and re.search(r'選手の(?:手術|負傷)について',clean_title):
  person=re.search(r'([^\n]{2,30})選手の(?:手術|負傷)について',clean_title)
  positions=[m.start() for m in re.finditer(re.escape(clean_title),text)]
  block=text[positions[1] if len(positions)>1 else (positions[0] if positions else 0):].split('このページの上部へ',1)[0]
  diagnosis=re.search(r'診断(?:結果|名)[：:]\s*([^\n]{2,80})',block)
  injury_date=re.search(r'(?:受傷日|負傷日)[：:]\s*((?:20\d{2}年)?\d{1,2}月\d{1,2}日)',block)
  duration=re.search(r'全治[：:]\s*(?:約)?\s*(\d+)\s*(ヶ月|か月|カ月|週|週間)',block)
  if person and diagnosis:
   return [dict(kind='absence',team=club,player=person.group(1).strip(),diagnosis=diagnosis.group(1).strip(),start_raw=injury_date.group(1) if injury_date else '',start_date='',duration_raw=duration.group(0) if duration else '',duration_min=int(duration.group(1)) if duration else None,duration_max=int(duration.group(1)) if duration else None,duration_unit=duration.group(2) if duration else '',duration_status='stated' if duration else 'not_stated',event_date='',excerpt=block[:450])]
 if club=='FC東京' and re.search(r'選手の負傷について',clean_title):
  person=re.search(r'([^\n]{2,30})選手の負傷について',clean_title)
  block=text.split('傷病名\n',1)
  diagnosis=block[1].split('\n',1)[0].strip() if len(block)>1 else ''
  injury_date=re.search(r'(\d{1,2}月\d{1,2}日)[^\n]{0,100}(?:戦にて|戦で)負傷',text)
  if person and diagnosis:
   return [dict(kind='absence',team=club,player=person.group(1).strip(),diagnosis=diagnosis,start_raw=injury_date.group(1) if injury_date else '',start_date='',duration_raw='',duration_min=None,duration_max=None,duration_unit='',duration_status='not_stated',event_date='',excerpt=text[:450])]
 if club=='岡山' and re.search(r'選手の(?:怪我|負傷|手術)について',clean_title):
  person=re.search(r'([^\n]{2,30})選手の(?:怪我|負傷|手術)について',clean_title)
  start=text.find('【受傷日】');end=text.find('【診断名】')
  date=re.search(r'(20\d{2}年\d{1,2}月\d{1,2}日)',text[start:end] if start>=0 and end>start else '')
  diagnosis=''
  if end>=0:
   diagnosis='、'.join(x.strip() for x in re.split(r'【(?:全治|手術日|備考)】|このページの先頭へ',text[end+len('【診断名】'):],maxsplit=1)[0].split('\n') if x.strip())[:150]
  duration=re.search(r'【全治】\s*([^\n]+)',text[end:] if end>=0 else '')
  duration_text=duration.group(1).strip() if duration else ''
  if person and diagnosis:
   return [dict(kind='absence',team=club,player=person.group(1).strip(),diagnosis=diagnosis,start_raw=date.group(1) if date else '',start_date='',duration_raw=duration_text,duration_min=None,duration_max=None,duration_unit='',duration_status='stated' if duration else 'not_stated',event_date='',excerpt=text[start:end+len('【診断名】')+160] if start>=0 else text[:450])]
 if club=='神戸' and re.search(r'選手の負傷について',clean_title):
  headline=re.split(r'\s*[:：]\s*',clean_title)[-1]
  person=re.search(r'(?:GK|DF|MF|FW)?\s*([^\n]{2,30})選手の負傷について',headline)
  block=text.split(headline,1)[-1].split('一覧へ戻る',1)[0]
  diagnosis=re.search(r'結果[、,]\s*([^。\n]{2,60})と診断され',block)
  date=re.search(r'((?:20\d{2}年)?\d{1,2}月\d{1,2}日)[^。\n]{0,100}負傷',block)
  if person and diagnosis:
   return [dict(kind='absence',team=club,player=person.group(1).strip(),diagnosis=diagnosis.group(1).strip(),start_raw=date.group(1) if date else '',start_date='',duration_raw='',duration_min=None,duration_max=None,duration_unit='',duration_status='not_stated',event_date='',excerpt=block[:450])]
 if club=='水戸' and re.search(r'選手の負傷について',clean_title):
  person=re.search(r'([^\n]{2,30})選手の負傷について',clean_title)
  block=text.split('このニュースをシェアする',1)[0]
  diagnosis=re.search(r'■診断名\s*\n([^\n]{2,80})',block)
  injury_date=re.search(r'((?:20\d{2}年)?\d{1,2}月\d{1,2}日)[^。\n]{0,100}負傷',block)
  if person and diagnosis:
   return [dict(kind='absence',team=club,player=person.group(1).strip(),diagnosis=diagnosis.group(1).strip(),start_raw=injury_date.group(1) if injury_date else '',start_date='',duration_raw='',duration_min=None,duration_max=None,duration_unit='',duration_status='not_stated',event_date='',excerpt=block[-450:])]
 if club=='名古屋' and re.search(r'選手のけがについて',clean_title):
  person=re.search(r'([^\n]{2,30})選手のけがについて',clean_title)
  block=text.split('カテゴリ\n',1)[0]
  date=re.search(r'◇受傷日\s*\n([^\n]+)',block)
  diagnosis_matches=list(re.finditer(r'◇診断名\s*\n([^\n]{2,80})',block))
  diagnosis=diagnosis_matches[-1] if diagnosis_matches else None
  if not date and len(diagnosis_matches)>1 and re.search(r'\d{1,2}月\d{1,2}日',diagnosis_matches[0].group(1)):
   date=diagnosis_matches[0]
  injury_date=re.search(r'((?:20\d{2}年)?\d{1,2}月\d{1,2}日)',date.group(1)) if date else None
  if person and diagnosis:
   return [dict(kind='absence',team=club,player=person.group(1).strip(),diagnosis=diagnosis.group(1).strip(),start_raw=injury_date.group(1) if injury_date else '',start_date='',duration_raw='',duration_min=None,duration_max=None,duration_unit='',duration_status='not_stated',event_date='',excerpt=block[-450:])]
 if club=='山形' and re.search(r'選手の負傷について',clean_title):
  person=re.search(r'([^\n]{2,30})選手の負傷について',clean_title)
  block=text.split('#チーム',1)[0]
  date=re.search(r'受傷日[：:]\s*\n((?:20\d{2}年)?\d{1,2}月\d{1,2}日)',block)
  diagnosis=re.search(r'診断名[：:]\s*\n([^\n]{2,80})',block)
  if person and diagnosis:
   return [dict(kind='absence',team=club,player=person.group(1).strip(),diagnosis=diagnosis.group(1).strip(),start_raw=date.group(1) if date else '',start_date='',duration_raw='',duration_min=None,duration_max=None,duration_unit='',duration_status='not_stated',event_date='',excerpt=block[-450:])]
 if club=='藤枝' and re.search(r'選手の怪我について',clean_title):
  person=re.search(r'([^\n|]{2,30}?)\s*選手の怪我について',clean_title)
  block=text.rsplit('選手の怪我について',1)[-1].split('この記事をシェアする',1)[0]
  injury=re.search(r'【負傷日】\s*((?:20\d{2}年)?\d{1,2}月\d{1,2}日)',block)
  if not injury:injury=re.search(r'※\s*((?:20\d{2}年)?\d{1,2}月\d{1,2}日)[^\n]*(?:負傷|受傷)',block)
  diagnosis=re.search(r'【診断】\s*([^（\n]{2,80})',block)
  duration=re.search(r'復帰までの期間[：:\s]*約?\s*(\d+)\s*[〜～~-]\s*(\d+)\s*(週|週間|か月|ヶ月|カ月)',block)
  if not duration:duration=re.search(r'全治\s*約?\s*(\d+)\s*(週間|週|か月|ヶ月|カ月)',block)
  if person and diagnosis:
   return [dict(kind='absence',team=club,player=person.group(1).strip(),diagnosis=diagnosis.group(1).strip(),start_raw=injury.group(1) if injury else '',start_date='',duration_raw=duration.group(0) if duration else '',duration_min=int(duration.group(1)) if duration else None,duration_max=int(duration.group(2)) if duration and duration.lastindex>=3 else (int(duration.group(1)) if duration else None),duration_unit=duration.group(3) if duration and duration.lastindex>=3 else (duration.group(2) if duration else ''),duration_status='stated' if duration else 'not_stated',event_date='',excerpt=block[:450])]
 if club=='磐田' and re.search(r'選手の負傷について',clean_title):
  person=re.search(r'([^\n|｜]{2,30}?)\s*選手の負傷について',clean_title)
  block=text.rsplit(clean_title,1)[-1].split('一覧に戻る',1)[0]
  diagnosis=re.search(r'診断名\s*\n\s*([^\n]{2,80})',block)
  injury=re.search(r'((?:20\d{2}年)?\d{1,2}月\d{1,2}日)[^。\n]{0,100}負傷',block)
  duration_line=re.search(r'トレーニング合流まで\s*\n\s*([^\n]{2,60})',block)
  duration=re.search(r'(?:術後)?\s*(\d+)(?:[〜～~-](\d+))?\s*(ヶ月|か月|カ月|週間|週)',duration_line.group(1)) if duration_line else None
  if person and diagnosis:
   return [dict(kind='absence',team=club,player=person.group(1).strip(),diagnosis=diagnosis.group(1).strip(),start_raw=injury.group(1) if injury else '',start_date='',duration_raw=('トレーニング合流まで '+duration_line.group(1).strip()) if duration_line else '',duration_min=int(duration.group(1)) if duration else None,duration_max=int(duration.group(2) or duration.group(1)) if duration else None,duration_unit=duration.group(3) if duration else '',duration_status='stated' if duration else 'not_stated',event_date='',excerpt=block[:450])]
 if club=='いわき' and 'の負傷について' in clean_title:
  person=re.match(r'(.{2,30}?)の負傷について',clean_title)
  block=text.rsplit(clean_title,1)[-1].split('\nSHARE',1)[-1]
  diagnosis=re.search(r'診断名\s*\n\s*([^\n]{2,80})',block)
  injury=re.search(r'受傷日\s*\n\s*(\d{1,2}月\d{1,2}日)',block)
  published=re.search(r'(20\d{2})\.(\d{2})\.(\d{2})',text)
  start_date=''
  if injury and published:
   day=re.search(r'(\d{1,2})月(\d{1,2})日',injury[1]);year=int(published[1])-(int(day[1])-int(published[2])>6)
   start_date=f'{year:04d}-{int(day[1]):02d}-{int(day[2]):02d}'
  duration=re.search(r'全治\s*\n\s*(\d+)(?:[〜～~-](\d+))?\s*(ヶ月|か月|カ月|週間|週)',block)
  if person and diagnosis:
   return [dict(kind='absence',team=club,player=person[1].strip(),diagnosis=diagnosis[1].strip(),start_raw=injury[1] if injury else '',start_date=start_date,duration_raw=duration[0].replace('\n',' ') if duration else '',duration_min=int(duration[1]) if duration else None,duration_max=int(duration[2] or duration[1]) if duration else None,duration_unit=duration[3] if duration else '',duration_status='stated' if duration else 'not_stated',event_date='',excerpt=block[:450])]
 if club=='千葉' and '選手の怪我について' in clean_title:
  person=re.match(r'(.{2,30}?)\s*選手の怪我について',clean_title)
  block=text.rsplit(clean_title,1)[-1].split('\n一覧に戻る',1)[0]
  diagnosis=re.search(r'【診断名】\s*\n\s*([^\n]{2,80})',block)
  injury=re.search(r'【受傷日】\s*\n\s*((?:20\d{2}年)?\d{1,2}月\d{1,2}日)',block)
  published=re.search(r'20\d{2}\.\d{2}\.\d{2}',text)
  full=re.match(r'(20\d{2})年(\d{1,2})月(\d{1,2})日',injury[1]) if injury else None
  short=re.match(r'(\d{1,2})月(\d{1,2})日',injury[1]) if injury else None
  start_date=f'{int(full[1]):04d}-{int(full[2]):02d}-{int(full[3]):02d}' if full else (f'{int(published[0][:4]):04d}-{int(short[1]):02d}-{int(short[2]):02d}' if short and published else '')
  duration=re.search(r'【全治】\s*\n\s*(\d+)(?:[〜～~-](\d+))?\s*(週間|週|か月|ヶ月|カ月)',block)
  if person and diagnosis:
   return [dict(kind='absence',team=club,player=person[1].strip(),diagnosis=diagnosis[1].strip(),start_raw=injury[1] if injury else '',start_date=start_date,duration_raw=duration[0].replace('\n',' ') if duration else '',duration_min=int(duration[1]) if duration else None,duration_max=int(duration[2] or duration[1]) if duration else None,duration_unit=duration[3] if duration else '',duration_status='stated' if duration else 'not_stated',event_date='',excerpt=block[:450])]
 if club=='札幌' and '負傷のお知らせ' in clean_title:
  person=re.match(r'(.{2,30}?)\s*選手\s*負傷のお知らせ',clean_title)
  block=text.rsplit(clean_title,1)[-1].split('\nこの記事をシェアする',1)[0]
  diagnosis=re.search(r'診断結果[：:]\s*([^\n]{2,80})',block)
  injury=re.search(r'(\d{1,2})月(\d{1,2})日[^\n]{0,80}負傷',block)
  published=re.search(r'(20\d{2})\.(\d{2})\.(\d{2})',text)
  start_date=f'{int(published[1]):04d}-{int(injury[1]):02d}-{int(injury[2]):02d}' if published and injury else ''
  if person and diagnosis:
   return [dict(kind='absence',team=club,player=person[1].strip(),diagnosis=diagnosis[1].strip(),start_raw=f'{injury[1]}月{injury[2]}日' if injury else '',start_date=start_date,duration_raw='',duration_min=None,duration_max=None,duration_unit='',duration_status='not_stated',event_date='',excerpt=block[:450])]
 if club=='大分' and '負傷に関するお知らせ' in clean_title:
  person=re.search(r'】\s*([^\n]{2,30}?)選手\s*負傷に関するお知らせ',clean_title)
  block=text.split(clean_title,1)[-1].split('\nこの記事をシェアする',1)[0]
  diagnosis=re.search(r'【診断名】\s*\n((?:・[^\n]+\n?)+)',block)
  injury=re.search(r'【受傷日】\s*(20\d{2})年(\d{1,2})月(\d{1,2})日',block)
  if person and diagnosis:
   return [dict(kind='absence',team=club,player=person[1].strip(),diagnosis='、'.join(line.lstrip('・').strip() for line in diagnosis[1].splitlines() if line.strip()),start_raw=injury[0] if injury else '',start_date=f'{int(injury[1]):04d}-{int(injury[2]):02d}-{int(injury[3]):02d}' if injury else '',duration_raw='',duration_min=None,duration_max=None,duration_unit='',duration_status='not_stated',event_date='',excerpt=block[:450])]
 if club=='富山' and re.search(r'選手(?:の(?:怪我|負傷)について|負傷のお知らせ)',clean_title):
  headline=clean_title.split(' – ',1)[0]
  person=re.search(r'([^\n]{2,30})選手(?:の(?:怪我|負傷)について|負傷のお知らせ)',headline)
  diag_pos=text.find('■診断名')
  article_pos=text.rfind(headline,0,diag_pos) if diag_pos>=0 else -1
  block=text[article_pos:] if article_pos>=0 else text
  diagnosis=re.search(r'■診断名[：:]\s*([^\n]{2,80})',block)
  injury=re.search(r'■受傷日[：:]\s*([^\n]{2,100})',block)
  duration=re.search(r'■全治[：:]\s*約?\s*(\d+)\s*(ヶ月|か月|カ月|週間|週)',block)
  if person and diagnosis:
   return [dict(kind='absence',team=club,player=person.group(1).strip(),diagnosis=diagnosis.group(1).strip(),start_raw=injury.group(1).strip() if injury else '',start_date='',duration_raw=duration.group(0) if duration else '',duration_min=int(duration.group(1)) if duration else None,duration_max=int(duration.group(1)) if duration else None,duration_unit=duration.group(2) if duration else '',duration_status='stated' if duration else 'not_stated',event_date='',excerpt=block[:450])]
 if club=='柏' and '負傷について' in clean_title:
  person=re.search(r'([^\n]{2,30})選手の負傷について',clean_title)
  paragraph=re.search(r'[^\n]{0,100}選手が、?[^\n]{0,250}(?:と診断されました|の診断を受け[^。\n]*。)',text)
  if person and paragraph:
   diagnosis=re.search(r'「([^」]{2,90})」(?:と診断|の診断を受け)',paragraph.group(0))
   date=re.search(r'(\d{1,2}月\d{1,2}日)',paragraph.group(0))
   return [dict(kind='absence',team=club,player=person.group(1).strip(),diagnosis=diagnosis.group(1) if diagnosis else '',start_raw=date.group(1) if date else '',start_date='',duration_raw='',duration_min=None,duration_max=None,duration_unit='',duration_status='not_stated',event_date='',excerpt=paragraph.group(0))]
 if club=='柏' and '代表を離脱' in clean_title:
  person=re.search(r'([^\n]{2,30})選手\s*日本代表を離脱',clean_title)
  paragraph=re.search(r'[^\n]{0,100}選手が、?[^\n]{0,250}負傷し、[^\n]{0,100}代表チームを離脱[^\n]*',text)
  if person and paragraph:
   date=re.search(r'(\d{1,2}月\d{1,2}日)',paragraph.group(0))
   return [dict(kind='absence',team=club,player=person.group(1).strip(),diagnosis='',start_raw=date.group(1) if date else '',start_date='',duration_raw='',duration_min=None,duration_max=None,duration_unit='',duration_status='not_stated',event_date='',excerpt=paragraph.group(0))]
 if club=='広島' and 'チーム再合流' in clean_title:return []
 if club=='広島' and '手術について' in clean_title:
  person=re.search(r'([^\n]{2,30})選手の手術について',clean_title)
  article=re.search(re.escape(clean_title)+r'\n20\d{2}\.\d{2}\.\d{2}[^\n]*\n',text)
  block=text[article.start():].split('\nチーム関連ニュース',1)[0] if article else text
  operation=re.search(r'手術名\n([^\n]{2,100})',block)
  duration=re.search(r'全[\s　]*治\n(\d+)\s*(ヶ月|か月|カ月|週|週間)',block)
  if person and operation:
   return [dict(kind='surgery',team=club,player=person.group(1).strip(),diagnosis='',start_raw='',start_date='',duration_raw=duration.group(0).replace('\n',' ') if duration else '',duration_min=int(duration.group(1)) if duration else None,duration_max=int(duration.group(1)) if duration else None,duration_unit=duration.group(2) if duration else '',duration_status='stated' if duration else 'not_stated',event_date='',excerpt=block[:450])]
 heading=clean_title.split('選手')[0].strip()
 occurrences=[m.start() for m in re.finditer(re.escape(clean_title),text)]
 pos=occurrences[1] if len(occurrences)>1 else (occurrences[0] if occurrences else -1)
 if pos>=0: text=text[pos:]
 if club=='鹿島':
  article=re.search(re.escape(clean_title)+r'\n20\d{2}\.\d{2}\.\d{2}[^\n]*\n',text)
  if article:text=text[article.start():].split('\nicon_home',1)[0]
 text=re.split(r'\n(?:関連するお知らせ|関連ニュース|チーム関連ニュース|トップチーム最新ニュース|最新ニュース|シェアする|ホーム\n)',text,maxsplit=1)[0]
 sections=list(re.finditer(r'\n([^\n、]{2,25})選手\s*診断結果\n',text))
 if len(sections)>1:
  blocks=[(m.group(1).strip(),text[m.start():sections[i+1].start() if i+1<len(sections) else len(text)]) for i,m in enumerate(sections)]
 else:
  m=re.search(r'([一-龥々ァ-ヴー・\s]{2,24})選手',clean_title)
  blocks=[(m.group(1).strip() if m else '',text)]
 out=[]
 for name,block in blocks:
  if not name:
   m=re.search(r'(?:選手名|氏名)\s*[:：]?\s*([^\n]{2,35})',block)
   if m: name=re.split(r'\s{2,}|（|\(',m.group(1))[0].strip()
  if not name:
   m=re.search(r'([一-龥々ァ-ヴー・\s]{2,24})選手(?:の|が|に関する|について)',title)
   if m: name=m.group(1).strip().split('\n')[-1].strip()
  if not name or len(name)>24: continue
  diag=''
  for label in ('診断名','傷病名','負傷名','診断結果'):
   m=re.search(label+r'[ \t]*[:：]?[ \t]*\n([^\n]{2,80})',block)
   if m and m.group(1) not in ('診断名','受傷日','全治'):
    diag=m.group(1).strip();break
  if club=='Ｇ大阪' and diag:
   m=re.search(r'◇診断名\s*\n[^\n]+\n([^\n]{2,80})',block)
   if m and re.search(r'(?:損傷|断裂|骨折|炎|捻挫|肉離れ)$',m.group(1).strip()):diag+='、'+m.group(1).strip()
  if not diag:
   m=re.search(r'[^\n]{2,25}選手[／/]([^\n]{2,80})',block)
   if m: diag=m.group(1).strip()
  start_raw=''; start_date=''
  m=re.search(r'受傷日\s*\n\s*((?:20\d{2}年)?\d{1,2}月\d{1,2}日|\d{1,2}/\d{1,2})',block)
  if not m: m=re.search(r'((?:20\d{2}年)?\d{1,2}月\d{1,2}日|\d{1,2}/\d{1,2})(?:[^\n]{0,95}(?:負傷|受傷))',block)
  if m:
   start_raw=m.group(1)
   full=re.fullmatch(r'(20\d{2})年(\d{1,2})月(\d{1,2})日',start_raw)
   if full: start_date=f'{int(full[1]):04d}-{int(full[2]):02d}-{int(full[3]):02d}'
  dur=''; lo=hi=None; unit=''; status='not_stated'
  m=re.search(r'(?:全治|復帰まで)\s*[:：]?\s*(?:約|およそ)?\s*(\d+)\s*(週間|週|か月|ヶ月|カ月|日)?\s*[〜～~-]\s*(\d+)\s*(週間|週|か月|ヶ月|カ月|日)',block)
  if m: dur=m.group(0);lo=int(m[1]);hi=int(m[3]);unit=m[4];status='stated'
  else:
   m=re.search(r'(?:全治|復帰まで)\s*[:：]?\s*(?:約|およそ)?\s*(\d+)\s*(週間|週|か月|ヶ月|カ月|日)',block)
   if m: dur=m.group(0);lo=hi=int(m[1]);unit=m[2];status='stated'
  if status=='not_stated' and re.search(r'全治.{0,12}(?:未定|経過観察|判断)',block): status='undetermined';dur=re.search(r'全治[^\n]{0,35}',block).group(0)
  kind='absence'
  if re.search(r'全体練習.{0,10}(?:合流|参加)|(?:合流|参加).{0,10}全体練習',block): kind='full_training'
  elif re.search(r'公式戦.{0,12}出場|試合に出場',block): kind='appearance'
  elif re.search(r'ベンチ入り',block): kind='bench'
  elif re.search(r'部分合流|一部合流|別メニュー',block): kind='partial_training'
  out.append(dict(kind=kind,team=club,player=name,diagnosis=diag,start_raw=start_raw,start_date=start_date,duration_raw=dur,duration_min=lo,duration_max=hi,duration_unit=unit,duration_status=status,event_date='',excerpt=block[:450]))
 return out
def ingest(c,url):
 parsed=urllib.parse.urlparse(url)
 if parsed.hostname=='www.sanfrecce.co.jp' and not re.fullmatch(r'/news/team/\d+/?',parsed.path):raise ValueError('広島は男子トップチーム記事のみ対象です')
 body=fetch(url); title,text,links=HTMLText().parse(body); url=canonical(url); source,club=source_for(url)
 if club=='宮崎':
  for m in re.finditer(r'self\.__next_f\.push\(\[1,("(?:\\.|[^"\\])*")\]\)',body):
   try: fragment=json.loads(m.group(1))
   except json.JSONDecodeError:continue
   if '<!DOCTYPE html' in fragment:text+='\n'+HTMLText().parse(fragment)[1]
 digest=hashlib.sha256(text.encode()).hexdigest(); old=c.execute('SELECT * FROM articles WHERE url=?',(url,)).fetchone()
 if old:
  aid=old['id']; changed=old['body_hash']!=digest
  c.execute('UPDATE articles SET title=?,source=?,fetched_at=?,body_hash=?,body_excerpt=? WHERE id=?',(title,source,now(),digest,text[:2000],aid))
 else:
  cur=c.execute('INSERT INTO articles(url,title,source,fetched_at,body_hash,body_excerpt) VALUES(?,?,?,?,?,?)',(url,title,source,now(),digest,text[:2000]));aid=cur.lastrowid;changed=True
 c.execute('INSERT OR IGNORE INTO article_versions(article_id,body_hash,excerpt,fetched_at) VALUES(?,?,?,?)',(aid,digest,text[:2000],now()))
 for target,_ in links:
  if not target: continue
  resolved=urllib.parse.urljoin(url,target)
  parsed=urllib.parse.urlparse(resolved)
  if parsed.scheme=='https' and parsed.hostname in ALLOWED_HOSTS and canonical(resolved)!=url:
   c.execute('INSERT OR IGNORE INTO article_links(article_id,target_url) VALUES(?,?)',(aid,canonical(resolved)))
 created=0
 for x in extract(text,title,club):
  facts=(x['kind'],name_key(x['player']),name_key(x['diagnosis']),x['start_raw'],x['start_date'],x['duration_raw'],x['event_date'])
  existing=c.execute('SELECT kind,player,diagnosis,start_raw,start_date,duration_raw,event_date FROM candidates WHERE article_id=?',(aid,))
  if any((v['kind'],name_key(v['player']),name_key(v['diagnosis']),v['start_raw'] or '',v['start_date'] or '',v['duration_raw'] or '',v['event_date'] or '')==facts for v in existing):continue
  fp=hashlib.sha256((str(aid)+'|'+json.dumps(facts,ensure_ascii=False)).encode()).hexdigest()
  cur=c.execute('''INSERT OR IGNORE INTO candidates(article_id,fingerprint,kind,team,player,diagnosis,start_raw,start_date,duration_raw,duration_min,duration_max,duration_unit,duration_status,event_date,excerpt,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(aid,fp,x['kind'],x['team'],x['player'],x['diagnosis'],x['start_raw'],x['start_date'],x['duration_raw'],x['duration_min'],x['duration_max'],x['duration_unit'],x['duration_status'],x['event_date'],x['excerpt'],now()))
  created+=cur.rowcount
 return {'article_id':aid,'title':title,'changed':changed,'candidates_created':created,'extracted':len(extract(text,title,club))}

def articles_linked(c,left_id,right_id):
 if not left_id or not right_id or left_id==right_id: return False
 urls={x['id']:x['url'] for x in c.execute('SELECT id,url FROM articles WHERE id IN (?,?)',(left_id,right_id))}
 if len(urls)!=2:return False
 return bool(c.execute('''SELECT 1 FROM article_links WHERE (article_id=? AND target_url=?) OR (article_id=? AND target_url=?) LIMIT 1''',(left_id,urls[right_id],right_id,urls[left_id])).fetchone())

def candidate_suggestions(c,candidate):
 matches=[];related=[];needle=possible_name_key(candidate['player'])
 if not needle:return {'cases':matches,'candidates':related}
 for case in c.execute('SELECT * FROM cases'):
  if possible_name_key(case['player'])!=needle:continue
  same_team=bool(candidate['team'] and name_key(candidate['team'])==name_key(case['team']))
  same_suspension=bool(candidate['kind']=='suspension' and case['absence_type']=='card' and candidate['start_raw'] and candidate['start_raw'] in unicodedata.normalize('NFKC',case['note'] or '') and re.search(r'J[12]\([a-z]\)',candidate['excerpt'] or '') and re.search(r'J[12]\([a-z]\)',candidate['excerpt'] or '').group(0) in unicodedata.normalize('NFKC',case['note'] or ''))
  diagnosis=name_key(candidate['diagnosis'])
  same_diagnosis=bool(diagnosis and (diagnosis==name_key(case['diagnosis']) or diagnosis in name_key(case['note'])))
  article_ids={case['source_article']} if case['source_article'] else set()
  article_ids.update(x[0] for x in c.execute('SELECT article_id FROM evidence WHERE case_id=?',(case['id'],)))
  linked=any(articles_linked(c,candidate['article_id'],aid) for aid in article_ids)
  if not (same_team or same_diagnosis or linked):continue
  reasons=[]
  if linked:reasons.append('元記事への直接リンク')
  if same_team:reasons.append('氏名・クラブ一致')
  if same_suspension:reasons.append('停止コード・対象試合一致')
  if same_diagnosis:reasons.append('診断・元メモ一致')
  if candidate['kind']!='suspension' and candidate['start_raw'] and case['start_date'] and not linked:
   reasons.append('受傷日と既存開始日の同一性は未確認')
  if case['status']!='open':reasons.append('既存案件は終了状態')
  score=(100 if linked else 0)+(80 if same_suspension else 0)+(20 if same_diagnosis else 0)+(10 if same_team else 0)
  matches.append({'case_id':case['id'],'team':case['team'],'player':case['player'],'absence_type':case['absence_type'],'start_date':case['start_date'],'expected_return_date':case['expected_return_date'],'note':case['note'],'status':case['status'],'score':score,'reasons':reasons})
 for other in c.execute('SELECT * FROM candidates WHERE id<>? AND state IN (\'pending\',\'held\',\'accepted\')',(candidate['id'],)):
  if possible_name_key(other['player'])!=needle or other['article_id']==candidate['article_id']:continue
  linked=articles_linked(c,candidate['article_id'],other['article_id'])
  same_team=bool(candidate['team'] and name_key(candidate['team'])==name_key(other['team']))
  same_diag=bool(candidate['diagnosis'] and name_key(candidate['diagnosis'])==name_key(other['diagnosis']))
  if not (linked or same_team and same_diag):continue
  reasons=['元記事への直接リンク'] if linked else ['氏名・クラブ・診断一致']
  related.append({'candidate_id':other['id'],'article_id':other['article_id'],'case_id':other['case_id'],'state':other['state'],'reasons':reasons})
 matches.sort(key=lambda x:(-x['score'],x['case_id']))
 related.sort(key=lambda x:x['candidate_id'])
 return {'cases':matches[:10],'candidates':related[:10]}

NEWS_WORDS=re.compile(r'負傷|怪我|けが|ケガ|手術|復帰|出場停止|合流')
WATCH_WORDS=re.compile(r'離脱|欠場|治療|療養|復調|コンディション|リハビリ|休養')
ARTICLE_PATHS={
 'www.jleague.jp':r'/news/article/\d+/',
 'www.f-marinos.com':r'/news/team/\d+',
 'www.frontale.co.jp':r'/info/20\d{2}/[^/]+\.html',
 'www.sagan-tosu.net':r'/news/p/\d+/',
 'www.v-varen.com':r'/news/\d+\.html',
 'yokohamafc.com':r'/20\d{2}/\d{2}/\d{2}/[^/]+/',
 'www.bellmare.co.jp':r'/\d+/',
 'www.gamba-osaka.net':r'/news/index/(?:c/\d+/)?no/\d+(?:/.*)?',
 'www.antlers.co.jp':r'/(?:ja-world/)?blogs/news/[^/]+',
 'www.reysol.co.jp':r'/news/topteam/(?!index_)\S+\.html',
 'www.sanfrecce.co.jp':r'/news/team/\d+/?',
 'www.fcimabari.com':r'/news/[a-z0-9_-]+',
 'www.vortis.jp':r'/news/\d+/',
 'www.ventforet.jp':r'/news/team/\d+',
 'www.fctokyo.co.jp':r'/news/details/\d+/',
 'www.fagiano-okayama.com':r'/news/\d{12}/?',
 'www.vissel-kobe.co.jp':r'/news/article/\d+\.html',
 'www.zelvia.co.jp':r'/news/news-\d+/',
 'www.urawa-reds.co.jp':r'/topteamtopics/\d+(?:\.html|/)',
 'www.mito-hollyhock.net':r'/news/p(?:=|%3[Dd])\d+/',
 'nagoya-grampus.jp':r'/news/pressrelease/20\d{2}/[^/]+\.php',
 'www.montedioyamagata.jp':r'/news/p/\d+/',
 'www.kataller.co.jp':r'/all/topteam/[^/]+/',
 'myfc.co.jp':r'/news/20\d{6}/\d+/',
 'jubilo-iwata.co.jp':r'/news/[^/]+',
 'www.sanga-fc.jp':r'/news/detail/\d+',
 'www.cerezo.jp':r'/news/20\d{2}-\d{4}-\d{4}/',
 'iwakifc.com':r'/20\d{2}/\d{2}/\d{2}/[^/]+/',
 'www.vegalta.co.jp':r'/news-team/20\d{2}/\d{2}/[^/]+\.html',
 'vanraure.net':r'/archives/\d+',
 'www.oita-trinita.co.jp':r'/news/news-\d+/',
 'www.albirex.co.jp':r'/news/\d+/',
 'tochigi-city.com':r'/new/20\d{2}/\d{2}/\d{2}/[^/]+/',
 'blaublitz.jp':r'/whatsnew/\d+\.html',
 'www.rbomiya.com':r'/jp-ja/news/omiya-\d+',
 'www.avispa.co.jp':r'/news/post-\d+',
 'jefunited.co.jp':r'/news/detail/\d+',
 'www.consadole-sapporo.jp':r'/news/20\d{2}/\d{2}/[^/]+/',
 'www.tegevajaro.com':r'/news/\d+',
}
def embedded_imabari_entries(source_url,html_body):
 if urllib.parse.urlparse(source_url).hostname!='www.fcimabari.com':return []
 found=[];seen=set()
 for match in re.finditer(r'\\"href\\":\\"(/news/[a-z0-9_-]+)\\"',html_body):
  title_match=re.search(r'\\"alt\\":\\"([^\\"]+)\\"',html_body[match.end():match.end()+2500])
  if not title_match:continue
  url=urllib.parse.urljoin(source_url,match.group(1))
  if url in seen:continue
  seen.add(url);found.append({'url':url,'title':html.unescape(title_match.group(1))})
 return found
def discover_list_entries(source_url,html_body):
 host=urllib.parse.urlparse(source_url).hostname
 selected={x['url']:x for x in discover_articles(source_url,html_body)}
 found={url:{**item,'auto_selected':1,'watch_reason':''} for url,item in selected.items()}
 for item in embedded_imabari_entries(source_url,html_body):
  if item['url'] in found:continue
  found[item['url']]={**item,'auto_selected':0,'watch_reason':','.join(dict.fromkeys(WATCH_WORDS.findall(item['title'])))}
 _,_,links=HTMLText().parse(html_body)
 for href,label in links:
  if not href:continue
  url=urllib.parse.urljoin(source_url,html.unescape(href));p=urllib.parse.urlparse(url)
  if p.scheme!='https' or p.hostname!=host or not re.fullmatch(ARTICLE_PATHS.get(host,r'(?!)'),p.path):continue
  title=re.sub(r'\s+',' ',html.unescape(label)).strip()
  if not title:continue
  url=canonical(url)
  if url in found:continue
  reason=','.join(dict.fromkeys(WATCH_WORDS.findall(title)))
  found[url]={'url':url,'title':title,'auto_selected':0,'watch_reason':reason}
 if host=='www.v-varen.com':
  for block in re.findall(r'<article\b[^>]*>.*?</article>',html_body,re.S|re.I):
   match=re.search(r'<a\b[^>]*href=["\']([^"\']+)',block,re.I)
   heading=re.search(r'<h4\b[^>]*>(.*?)</h4>',block,re.S|re.I)
   if not match or not heading:continue
   url=canonical(urllib.parse.urljoin(source_url,html.unescape(match.group(1))))
   p=urllib.parse.urlparse(url)
   if p.hostname!=host or not re.fullmatch(ARTICLE_PATHS[host],p.path):continue
   title=re.sub(r'\s+',' ',re.sub(r'<[^>]+>','',html.unescape(heading.group(1)))).strip()
   date=re.search(r'<aside\b[^>]*>\s*(20\d{2})\.(\d{1,2})\.(\d{1,2})\s*</aside>',block,re.S|re.I)
   if url in found:
    if date:found[url]['published_date']=f'{date[1]}-{int(date[2]):02d}-{int(date[3]):02d}'
   elif title:found[url]={'url':url,'title':title,'auto_selected':0,'watch_reason':','.join(dict.fromkeys(WATCH_WORDS.findall(title))),'published_date':f'{date[1]}-{int(date[2]):02d}-{int(date[3]):02d}' if date else ''}
 if host=='www.zelvia.co.jp':
  for block in re.findall(r'<article\b[^>]*>.*?</article>',html_body,re.S|re.I):
   link=re.search(r'<h2\b[^>]*>\s*<a\b[^>]*href=["\']([^"\']+)',block,re.S|re.I)
   date=re.search(r'<time\b[^>]*datetime=["\'](20\d{2}-\d{2}-\d{2})',block,re.I)
   if link and date:
    url=canonical(urllib.parse.urljoin(source_url,html.unescape(link[1])))
    if url in found:found[url]['published_date']=date[1]
 if host=='yokohamafc.com':
  for href,title in re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>\s*<p\b[^>]*>.*?</p>\s*<p\b[^>]*>(.*?)</p>',html_body,re.S|re.I):
   url=canonical(urllib.parse.urljoin(source_url,html.unescape(href)))
   if url in found:
    clean=re.sub(r'\s+',' ',re.sub(r'<[^>]+>','',html.unescape(title))).strip()
    if clean:found[url]['title']=clean;found[url]['watch_reason']=','.join(dict.fromkeys(WATCH_WORDS.findall(clean)))
 return list(found.values())

def save_list_entries(c,source_id,run_id,list_url,entries):
 for item in entries:
  c.execute('''INSERT INTO list_entries(source_id,article_url,title,first_list_url,last_list_url,first_seen_at,last_seen_at,auto_selected,watch_reason) VALUES(?,?,?,?,?,?,?,?,?)
   ON CONFLICT(source_id,article_url) DO UPDATE SET title=excluded.title,last_list_url=excluded.last_list_url,last_seen_at=excluded.last_seen_at,auto_selected=max(list_entries.auto_selected,excluded.auto_selected),watch_reason=excluded.watch_reason''',
   (source_id,item['url'],item['title'],list_url,list_url,now(),now(),item['auto_selected'],item['watch_reason']))
  eid=c.execute('SELECT id FROM list_entries WHERE source_id=? AND article_url=?',(source_id,item['url'])).fetchone()[0]
  c.execute('INSERT OR IGNORE INTO list_entry_sightings(entry_id,run_id,list_url,seen_at) VALUES(?,?,?,?)',(eid,run_id,list_url,now()))
def fetch_list_entry(c,entry_id):
 entry=c.execute('SELECT article_url FROM list_entries WHERE id=?',(entry_id,)).fetchone()
 if not entry:raise ValueError('一覧見出しがありません')
 return ingest(c,entry['article_url'])

def review_list_entry(c,entry_id,state,reason):
 if state not in ('unreviewed','excluded'):raise ValueError('確認状態が不正です')
 if state=='excluded' and not reason.strip():raise ValueError('対象外の理由を入力してください')
 if not c.execute('SELECT 1 FROM list_entries WHERE id=?',(entry_id,)).fetchone():raise ValueError('一覧見出しがありません')
 c.execute('UPDATE list_entries SET review_state=?,review_reason=?,reviewed_at=? WHERE id=?',(state,reason,now(),entry_id))
 return {'state':state}
def discover_articles(source_url,html_body):
 _,_,links=HTMLText().parse(html_body)
 found=[];seen=set();source_host=urllib.parse.urlparse(source_url).hostname
 def add(href,label):
  if not href or not (NEWS_WORDS.search(label) or source_host=='www.reysol.co.jp' and '代表を離脱' in label or source_host=='www.tegevajaro.com' and '傷病' in label):return
  if source_host=='www.tegevajaro.com' and '復帰' in label and ('移籍' in label or 'へ復帰' in label):return
  if source_host=='myfc.co.jp' and '監督' in label:return
  url=urllib.parse.urljoin(source_url,html.unescape(href))
  p=urllib.parse.urlparse(url)
  if p.scheme!='https' or p.hostname!=source_host:return
  if source_host=='www.sanfrecce.co.jp' and not re.fullmatch(r'/news/team/\d+/?',p.path):return
  if source_host in ('www.fagiano-okayama.com','www.sanga-fc.jp','www.cerezo.jp','iwakifc.com','www.vegalta.co.jp','vanraure.net','www.oita-trinita.co.jp','www.albirex.co.jp','tochigi-city.com','blaublitz.jp','www.rbomiya.com','www.avispa.co.jp','jefunited.co.jp','www.consadole-sapporo.jp','www.tegevajaro.com') and not re.fullmatch(ARTICLE_PATHS[source_host],p.path):return
  url=canonical(url)
  if url==canonical(source_url) or url in seen:return
  seen.add(url);found.append({'url':url,'title':re.sub(r'\s+',' ',html.unescape(label)).strip()})
 for href,label in links:add(href,label)
 for item in embedded_imabari_entries(source_url,html_body):add(item['url'],item['title'])
 if source_host=='www.v-varen.com':
  for block in re.findall(r'<article\b[^>]*>.*?</article>',html_body,re.S|re.I):
   title=re.search(r'<h4[^>]*>(.*?)</h4>',block,re.S|re.I)
   link=re.search(r'<a\s+[^>]*href=["\']([^"\']+)["\']',block,re.S|re.I)
   if title and link:add(link.group(1),re.sub(r'<[^>]+>','',title.group(1)))
 if source_host=='www.consadole-sapporo.jp':
  for link,heading in re.findall(r'<a\s+href=["\'](https://www\.consadole-sapporo\.jp/news/20\d{2}/\d{2}/[^"\']+/)["\'][^>]*></a>.{0,1200}?<h3[^>]*>(.*?)</h3>',html_body,re.S|re.I):
   add(link,re.sub(r'<[^>]+>','',heading).strip())
 return found

def discover_archive_pages(source_url,html_body):
 _,_,links=HTMLText().parse(html_body);host=urllib.parse.urlparse(source_url).hostname;found=[];seen=set()
 for href,label in links:
  if not href:continue
  url=urllib.parse.urljoin(source_url,html.unescape(href));p=urllib.parse.urlparse(url)
  if p.scheme!='https' or p.hostname!=host:continue
  if host=='www.sagan-tosu.net':valid=bool(re.fullmatch(r'/news/team/20\d{2}_(?:[1-9]|1[0-2])/',p.path))
  elif host=='www.v-varen.com':valid=bool(re.fullmatch(r'/topteam_news/page/[1-9]\d*/',p.path))
  elif host=='www.antlers.co.jp':valid=p.path=='/ja-world/blogs/news' and bool(re.fullmatch(r'page=[1-9]\d*',p.query))
  elif host=='www.reysol.co.jp':valid=bool(re.fullmatch(r'/news/topteam/index_(?:[2-9]|[1-9]\d+)\.html',p.path)) and not p.query
  elif host=='www.fctokyo.co.jp':valid=bool(re.fullmatch(r'/news/page/(?:[2-9]|[1-9]\d+)/',p.path)) and not p.query
  elif host=='www.fagiano-okayama.com':valid=bool(re.fullmatch(r'/news/(?:lm/)?l0_20\d{4}/?',p.path)) and not p.query
  elif host=='www.urawa-reds.co.jp':valid=bool(re.fullmatch(r'/topteamtopics/team/20\d{2}(?:0[1-9]|1[0-2])/index\.html',p.path)) and not p.query
  elif host=='nagoya-grampus.jp':valid=bool(re.fullmatch(r'/news/pressrelease/index_(?:[2-9]|[1-9]\d+)\.php',p.path)) and not p.query
  elif host=='www.montedioyamagata.jp':valid=bool(re.fullmatch(r'/news/20\d{2}/team/(?:[2-9]|[1-9]\d+)/',p.path)) and not p.query
  elif host=='www.zelvia.co.jp':valid=bool(re.fullmatch(r'/news-category/topteam/page/(?:[2-9]|[1-9]\d+)/',p.path)) and not p.query
  elif host=='myfc.co.jp':valid=bool(re.fullmatch(r'/news/newslist/topteam/page/(?:[2-9]|[1-9]\d+)/',p.path)) and not p.query
  else:valid=False
  if valid and url not in seen:
   page_label=f'{urllib.parse.parse_qs(p.query)["page"][0]}ページ' if host=='www.antlers.co.jp' else (re.search(r'index_(\d+)\.html',p.path).group(1)+'ページ' if host=='www.reysol.co.jp' else (re.search(r'/page/(\d+)/',p.path).group(1)+'ページ' if host=='www.fctokyo.co.jp' else (re.sub(r'\s+',' ',label).strip() or p.path)))
   seen.add(url);found.append({'url':url,'label':page_label})
 if host=='www.gamba-osaka.net':
  current=urllib.parse.urlparse(source_url)
  match=re.fullmatch(r'/news/append/c/1/year/(20\d{2})/month/(0?[1-9]|1[0-2])/p/([1-9]\d*)',current.path)
  if match:year,month,page=match.group(1),match.group(2),int(match.group(3))+1
  else:
   year_match=re.search(r'<select[^>]+id=["\']year["\'][^>]*>.*?<option value=["\'](20\d{2})["\'] selected',html_body,re.S|re.I)
   month_match=re.search(r'<select[^>]+id=["\']month["\'][^>]*>.*?<option value=["\'](0?[1-9]|1[0-2])["\'] selected',html_body,re.S|re.I)
   year,month,page=(year_match.group(1),month_match.group(1),1) if year_match and month_match else ('','',0)
  if page and '<!--end-->' not in html_body:
   url=f'https://www.gamba-osaka.net/news/append/c/1/year/{year}/month/{month}/p/{page}'
   found.append({'url':url,'label':f'{year}年{int(month)}月・続き{page}'})
 if host=='www.sanfrecce.co.jp':
  query=urllib.parse.parse_qs(urllib.parse.urlparse(source_url).query)
  if query.get('year') and query.get('month'):
   year,month=int(query['year'][0]),int(query['month'][0])
  else:
   year_match=re.search(r'<select[^>]+name=["\']year["\'][^>]*>.*?<option value=["\'](20\d{2})["\'] selected',html_body,re.S|re.I)
   month_match=re.search(r'<select[^>]+name=["\']month["\'][^>]*>.*?<option value=["\'](0?[1-9]|1[0-2])["\'] selected',html_body,re.S|re.I)
   year,month=(int(year_match.group(1)),int(month_match.group(1))) if year_match and month_match else (0,0)
  if year and month:
   prior_year,prior_month=(year,month-1) if month>1 else (year-1,12)
   if prior_year>=2018:
    found.append({'url':f'https://www.sanfrecce.co.jp/news?news_category_id=1&month={prior_month}&year={prior_year}','label':f'{prior_year}年{prior_month}月'})
 if host=='www.zelvia.co.jp' and re.search(r'<article\b[^>]*id=["\']post-\d+',html_body):
  p=urllib.parse.urlparse(source_url);m=re.fullmatch(r'/news-category/topteam/page/(\d+)/',p.path)
  next_page=int(m[1])+1 if m else 2
  found.append({'url':f'https://www.zelvia.co.jp/news-category/topteam/page/{next_page}/','label':f'{next_page}ページ'})
 if host=='www.tegevajaro.com':
  p=urllib.parse.urlparse(source_url);q=urllib.parse.parse_qs(p.query)
  page=int(q['page'][0]) if p.path=='/news' and re.fullmatch(r'[1-9]\d*',q.get('page',[''])[0]) else 0
  year=q.get('year',[''])[0]
  article_links={href for href,_ in links if re.fullmatch(r'/news/\d+',href)}
  if page and page<100 and re.fullmatch(r'20\d{2}',year) and len(article_links)>=20:
   found.append({'url':f'https://www.tegevajaro.com/news?page={page+1}&year={year}','label':f'{year}年・{page+1}ページ'})
 return found

def checked_list_url(source_url,list_url):
 if not list_url:return source_url
 source=urllib.parse.urlparse(source_url);p=urllib.parse.urlparse(list_url)
 if p.scheme!='https' or p.hostname!=source.hostname:raise ValueError('登録情報源と同じHTTPSドメインの過去一覧URLだけ指定できます')
 if source.hostname=='www.sagan-tosu.net' and re.fullmatch(r'/news/team/20\d{2}_(?:[1-9]|1[0-2])/',p.path):return list_url
 if source.hostname=='www.v-varen.com' and re.fullmatch(r'/topteam_news/page/[1-9]\d*/',p.path):return list_url
 if source.hostname=='www.antlers.co.jp' and p.path=='/ja-world/blogs/news' and re.fullmatch(r'page=[1-9]\d*',p.query):return list_url
 if source.hostname=='www.reysol.co.jp' and re.fullmatch(r'/news/topteam/index_(?:[2-9]|[1-9]\d+)\.html',p.path) and not p.query:return list_url
 if source.hostname=='www.fctokyo.co.jp' and re.fullmatch(r'/news/page/(?:[2-9]|[1-9]\d+)/',p.path) and not p.query:return list_url
 if source.hostname=='www.fagiano-okayama.com' and re.fullmatch(r'/news/(?:lm/)?l0_20\d{4}/?',p.path) and not p.query:return list_url
 if source.hostname=='www.urawa-reds.co.jp' and re.fullmatch(r'/topteamtopics/team/20\d{2}(?:0[1-9]|1[0-2])/index\.html',p.path) and not p.query:return list_url
 if source.hostname=='nagoya-grampus.jp' and re.fullmatch(r'/news/pressrelease/index_(?:[2-9]|[1-9]\d+)\.php',p.path) and not p.query:return list_url
 if source.hostname=='www.montedioyamagata.jp' and re.fullmatch(r'/news/20\d{2}/team/(?:[2-9]|[1-9]\d+)/',p.path) and not p.query:return list_url
 if source.hostname=='www.zelvia.co.jp' and re.fullmatch(r'/news-category/topteam/page/(?:[2-9]|[1-9]\d+)/',p.path) and not p.query:return list_url
 if source.hostname=='myfc.co.jp' and re.fullmatch(r'/news/newslist/topteam/page/(?:[2-9]|[1-9]\d+)/',p.path) and not p.query:return list_url
 if source.hostname=='www.tegevajaro.com' and p.path=='/news' and re.fullmatch(r'page=(?:[2-9]|[1-9]\d+)&year=20\d{2}',p.query) and not p.fragment:return list_url
 if source.hostname=='www.sanfrecce.co.jp' and p.path=='/news' and re.fullmatch(r'news_category_id=1&month=(?:[1-9]|1[0-2])&year=20\d{2}',p.query) and not p.fragment:return list_url
 if source.hostname=='www.gamba-osaka.net' and re.fullmatch(r'/news/append/c/1/year/20\d{2}/month/(?:0?[1-9]|1[0-2])/p/[1-9]\d*',p.path) and not p.query:return list_url
 raise ValueError('この情報源の過去一覧URLは未検証です')

def fetch_source_page(source_url,page_url):
 if urllib.parse.urlparse(source_url).hostname=='jefunited.co.jp':
  if page_url!=source_url:raise ValueError('千葉公式の過去一覧は未検証です')
  data=json.loads(fetch('https://jefunited.co.jp/api/news/list?ym=0&c=2&s=official'))
  if not isinstance(data.get('news'),list):raise ValueError('千葉公式APIのニュース一覧が不正です')
  return '<html>'+''.join(f'<a href="{html.escape(item["link"],quote=True)}">{html.escape(item.get("ymd","")+" "+item.get("title",""))}</a>' for item in data['news'] if re.fullmatch(r'/news/detail/\d+',item.get('link','')) )+'</html>'
 if urllib.parse.urlparse(source_url).hostname!='www.gamba-osaka.net' or page_url==source_url:return fetch(page_url)
 if checked_list_url(source_url,page_url)!=page_url:raise ValueError('一覧URLが不正です')
 class RestrictedRedirect(urllib.request.HTTPRedirectHandler):
  def redirect_request(self,req,fp,code,msg,headers,newurl):
   p=urllib.parse.urlparse(newurl)
   if p.scheme!='https' or p.hostname!='www.gamba-osaka.net':raise ValueError('登録外ドメインへの転送を停止しました')
   return super().redirect_request(req,fp,code,msg,headers,newurl)
 jar=http.cookiejar.CookieJar();opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar),RestrictedRedirect())
 headers={'User-Agent':'AbsenceLedger/0.1 (personal local use)'}
 with opener.open(urllib.request.Request(source_url,headers=headers),timeout=15) as response:
  content=response.read(1_500_001)
  if len(content)>1_500_000:raise ValueError('一覧が大きすぎます')
  base=content.decode(response.headers.get_content_charset() or 'utf-8',errors='replace')
 token=re.search(r"var ctn = '([a-f0-9]+)'",base)
 if not token:raise ValueError('公式一覧の追加取得トークンが見つかりません')
 payload=urllib.parse.urlencode({'gmb-pc-ctn':token.group(1)}).encode()
 request=urllib.request.Request(page_url,data=payload,headers={**headers,'Referer':source_url,'X-Requested-With':'XMLHttpRequest'})
 with opener.open(request,timeout=15) as response:
  body=response.read(1_500_001).decode(response.headers.get_content_charset() or 'utf-8',errors='replace')
 if len(body)>1_500_000 or 'エラー｜ガンバ大阪オフィシャルサイト' in body:raise ValueError('公式の追加一覧を取得できません')
 return body

def archive_url_year(url):
 p=urllib.parse.urlparse(url);q=urllib.parse.parse_qs(p.query)
 if q.get('year') and re.fullmatch(r'20\d{2}',q['year'][0]):return int(q['year'][0])
 for pattern in (r'/year/(20\d{2})/',r'/news/team/(20\d{2})_',r'/news/(?:lm/)?l0_(20\d{2})\d{2}',r'/topteamtopics/team/(20\d{2})\d{2}/',r'/news/(20\d{2})/team/'):
  m=re.search(pattern,p.path)
  if m:return int(m[1])
 return None

def archive_url_month(url):
 p=urllib.parse.urlparse(url);q=urllib.parse.parse_qs(p.query)
 if q.get('year') and q.get('month'):
  try:return f'{int(q["year"][0]):04d}-{int(q["month"][0]):02d}'
  except ValueError:return None
 for pattern in (r'/year/(20\d{2})/month/(0?[1-9]|1[0-2])/',r'/news/team/(20\d{2})_(0?[1-9]|1[0-2])/',r'/news/(?:lm/)?l0_(20\d{2})(0[1-9]|1[0-2])',r'/topteamtopics/team/(20\d{2})(0[1-9]|1[0-2])/',r'/news/(20\d{2})/team/'):
  m=re.search(pattern,p.path)
  if m and m.lastindex>=2:return f'{int(m[1]):04d}-{int(m[2]):02d}'
 return None

def list_entry_date(entry):
 value=entry['published_date'] if 'published_date' in entry.keys() else ''
 if value and re.fullmatch(r'20\d{2}-\d{2}-\d{2}',value):return value
 m=re.search(r'(?<!\d)(20\d{2})[./年-](\d{1,2})[./月-](\d{1,2})(?:日|\b)',entry['title'])
 if m:return f'{int(m[1]):04d}-{int(m[2]):02d}-{int(m[3]):02d}'
 m=re.match(r'(?<!\d)(\d{2})\.(\d{1,2})\.(\d{1,2})(?!\d)',entry['title'])
 if m:return f'{2000+int(m[1]):04d}-{int(m[2]):02d}-{int(m[3]):02d}'
 url=entry['article_url'] if 'article_url' in entry.keys() else entry['url']
 m=re.search(r'/(20\d{2})/(\d{1,2})/(\d{1,2})/',urllib.parse.urlparse(url).path)
 if m:return f'{int(m[1]):04d}-{int(m[2]):02d}-{int(m[3]):02d}'
 return None

def list_entry_year(entry):
 if 'published_date' in entry.keys() and entry['published_date']:
  m=re.fullmatch(r'(20\d{2})-\d{2}-\d{2}',entry['published_date'])
  if m:return int(m[1])
 m=re.search(r'(?<!\d)(20\d{2})[./年-](?:0?[1-9]|1[0-2])(?:[./月-]|\b)',entry['title'])
 if m:return int(m[1])
 date=list_entry_date(entry)
 if date:return int(date[:4])
 m=re.search(r'/(20\d{2})/(?:0?[1-9]|1[0-2])(?:/|\d)',entry['article_url'] if 'article_url' in entry.keys() else entry['url'])
 return int(m[1]) if m else None

def run_source(c,source_id,limit=8,list_url=None,min_year=None):
 src=c.execute('SELECT * FROM sources WHERE id=?',(source_id,)).fetchone()
 if not src:raise ValueError('情報源がありません')
 page_url=checked_list_url(src['url'],list_url)
 rid=c.execute('INSERT INTO source_runs(source_id,list_url,started_at,status) VALUES(?,?,?,?)',(source_id,page_url,now(),'running')).lastrowid
 try:
  page=fetch_source_page(src['url'],page_url)
  listed=discover_list_entries(page_url,page)
  discovered=discover_articles(page_url,page)
  year_boundary=False
  if min_year is not None:
   dated=[list_entry_year(x) for x in listed];dated=[y for y in dated if y is not None]
   content_year_required=urllib.parse.urlparse(src['url']).hostname=='www.gamba-osaka.net'
   year_boundary=(archive_url_year(page_url) is None or content_year_required) and (not dated or min(dated)<min_year)
   years_by_url={canonical(x['url']):list_entry_year(x) for x in listed}
   discovered=[x for x in discovered if (years_by_url.get(canonical(x['url'])) or (None if content_year_required else archive_url_year(page_url)) or 0)>=min_year]
  save_list_entries(c,source_id,rid,page_url,listed)
  archive_pages=discover_archive_pages(page_url if urllib.parse.urlparse(src['url']).hostname in ('www.gamba-osaka.net','www.sanfrecce.co.jp','www.zelvia.co.jp','www.tegevajaro.com') else src['url'],page)
 except Exception as e:
  error=str(e)
  c.execute('UPDATE source_runs SET finished_at=?,status=?,details_json=? WHERE id=?',(now(),'failed',json.dumps({'error':error},ensure_ascii=False),rid))
  c.execute('UPDATE sources SET last_failure=?,failure=? WHERE id=?',(now(),error,source_id))
  return {'run_id':rid,'status':'failed','error':error,'found':0,'attempted':0,'coverage':'一覧初頁の取得に失敗'}
 outcomes=[]
 for item in discovered[:limit]:
  try:outcomes.append({'url':item['url'],**ingest(c,item['url'])})
  except Exception as e:outcomes.append({'url':item['url'],'error':str(e)})
  if len(outcomes)<min(len(discovered),limit):time.sleep(0.3)
 failures=[x for x in outcomes if 'error' in x]
 skipped=max(0,len(discovered)-limit)
 status='partial' if failures or skipped else 'success'
 coverage='公式トップ頁の最新記事のみ。ニュース一覧は取得不可' if src['coverage']=='partial-home' else ('初頁のみ。過去ページは未取得' if page_url==src['url'] else '指定した過去一覧ページのみ取得')
 detail={'outcomes':outcomes,'skipped':skipped,'listed_count':len(listed),'watch_count':sum(bool(x['watch_reason']) for x in listed if not x['auto_selected']),'zero_candidate_count':sum(x.get('extracted')==0 for x in outcomes if 'error' not in x),'archive_pages':archive_pages,'published_dates':{x['url']:x['published_date'] for x in listed if x.get('published_date')},'archive_year_stop':year_boundary,'min_year':min_year,'coverage':coverage}
 c.execute('''UPDATE source_runs SET finished_at=?,status=?,found_count=?,attempted_count=?,success_count=?,failure_count=?,details_json=? WHERE id=?''',(now(),status,len(discovered),len(outcomes),len(outcomes)-len(failures),len(failures),json.dumps(detail,ensure_ascii=False),rid))
 c.execute('UPDATE sources SET last_success=?,last_failure=?,failure=?,last_count=? WHERE id=?',(now() if status=='success' else src['last_success'],now() if status=='partial' else None,'; '.join(x['error'] for x in failures) or (f'{skipped}件未取得' if skipped else ''),len(discovered),source_id))
 return {'run_id':rid,'status':status,'list_url':page_url,'found':len(discovered),'attempted':len(outcomes),'failed':len(failures),'skipped':skipped,'outcomes':outcomes,'archive_pages':archive_pages,'coverage':detail['coverage']}

def collect_sources(source_ids=None,limit=8,pause=0.5):
 if not 1<=limit<=50:raise ValueError('記事取得上限は1～50にしてください')
 with db() as c:
  available={r['id']:r['name'] for r in c.execute('SELECT id,name FROM sources ORDER BY id')}
 ids=list(available) if source_ids is None else list(source_ids)
 if any(sid not in available for sid in ids):raise ValueError('登録されていない情報源IDがあります')
 results=[]
 for index,sid in enumerate(ids):
  try:
   with db() as c: result=run_source(c,sid,limit=limit)
  except Exception as e:
   result={'status':'failed','error':str(e),'found':0,'attempted':0,'failed':0,'skipped':0}
  results.append({'source_id':sid,'name':available[sid],**result})
  if index+1<len(ids) and pause:time.sleep(pause)
 return {'sources':len(results),'success':sum(x['status']=='success' for x in results),'partial':sum(x['status']=='partial' for x in results),'failed':sum(x['status']=='failed' for x in results),'found':sum(x.get('found',0) for x in results),'attempted':sum(x.get('attempted',0) for x in results),'results':results}

def archive_queue(c,source_id,exclude=(),min_year=2026):
 source=c.execute('SELECT url FROM sources WHERE id=?',(source_id,)).fetchone()
 if not source:raise ValueError('情報源がありません')
 runs=c.execute('SELECT id,list_url,status,details_json FROM source_runs WHERE source_id=? ORDER BY id DESC',(source_id,)).fetchall()
 latest_archive=next((r for r in runs if r['list_url']!=source['url'] and r['status']=='success'),None)
 if latest_archive and (archive_url_year(latest_archive['list_url']) is None or urllib.parse.urlparse(source['url']).hostname=='www.gamba-osaka.net'):
  entries=c.execute('''SELECT e.title,e.article_url FROM list_entries e JOIN list_entry_sightings z ON z.entry_id=e.id WHERE z.run_id=?''',(latest_archive['id'],)).fetchall()
  try:published_dates=json.loads(latest_archive['details_json'] or '{}').get('published_dates',{})
  except (ValueError,TypeError):published_dates={}
  years=[list_entry_year({**dict(x),'published_date':published_dates.get(x['article_url'],'')}) for x in entries];years=[y for y in years if y is not None]
  if not years or min(years)<min_year:return []
 completed={r['list_url'] or source['url'] for r in runs if r['status']=='success'}
 seen=set(completed)|set(exclude)|{source['url']};queue=[]
 for run in runs:
  if run['status'] not in ('success','partial'):continue
  try:pages=json.loads(run['details_json'] or '{}').get('archive_pages',[])
  except (ValueError,TypeError):continue
  if not isinstance(pages,list):continue
  for page in pages:
   if not isinstance(page,dict) or not isinstance(page.get('url'),str):continue
   url=page['url']
   page_year=archive_url_year(url)
   if page_year is not None and page_year<min_year:continue
   try:checked_list_url(source['url'],url)
   except ValueError:continue
   if url in seen:continue
   seen.add(url);queue.append({'url':url,'label':page.get('label') or url})
 if urllib.parse.urlparse(source['url']).hostname=='myfc.co.jp':
  queue.sort(key=lambda item:int(re.search(r'/page/(\d+)/',item['url']).group(1)))
 return queue

def collect_archives(source_ids=None,max_pages=3,limit=50,pause=0.5,min_year=2026):
 if not 1<=max_pages<=20:raise ValueError('1情報源の過去ページ上限は1～20にしてください')
 if not 1<=limit<=50:raise ValueError('記事取得上限は1～50にしてください')
 with db() as c:available={r['id']:r['name'] for r in c.execute('SELECT id,name FROM sources ORDER BY id')}
 ids=list(available) if source_ids is None else list(source_ids)
 if any(sid not in available for sid in ids):raise ValueError('登録されていない情報源IDがあります')
 results=[]
 for sid in ids:
  attempted_urls=set();pages=[]
  while len(pages)<max_pages:
   with db() as c:queue=archive_queue(c,sid,attempted_urls,min_year)
   if not queue:break
   url=queue[0]['url'];attempted_urls.add(url)
   try:
    with db() as c:result=run_source(c,sid,limit=limit,list_url=url,min_year=min_year)
   except Exception as e:result={'status':'failed','list_url':url,'error':str(e),'found':0,'attempted':0,'failed':0,'skipped':0}
   pages.append(result)
   if len(pages)<max_pages and pause:time.sleep(pause)
  results.append({'source_id':sid,'name':available[sid],'pages':pages,'remaining_discovered':len(archive_queue_for_source(sid,min_year))})
  if sid!=ids[-1] and pause:time.sleep(pause)
 all_pages=[p for source in results for p in source['pages']]
 return {'sources':len(results),'pages':len(all_pages),'success':sum(x['status']=='success' for x in all_pages),'partial':sum(x['status']=='partial' for x in all_pages),'failed':sum(x['status']=='failed' for x in all_pages),'found':sum(x.get('found',0) for x in all_pages),'attempted':sum(x.get('attempted',0) for x in all_pages),'results':results}

def archive_queue_for_source(source_id,min_year=2026):
 with db() as c:return archive_queue(c,source_id,min_year=min_year)

def decide(c,data):
 cid=int(data['candidate_id']); cand=c.execute('SELECT * FROM candidates WHERE id=?',(cid,)).fetchone()
 if not cand: raise ValueError('候補がありません')
 action=data['action']
 if cand['state'] not in ('pending','held'): raise ValueError('この候補は処理済みです')
 if action in ('hold','reject'):
  c.execute('UPDATE candidates SET state=?,decision_at=? WHERE id=?',('held' if action=='hold' else 'rejected',now(),cid))
  c.execute('INSERT INTO decisions(candidate_id,action,reason,created_at) VALUES(?,?,?,?)',(cid,action,data.get('reason',''),now()))
  return {'state':action}
 if action=='resume':
  if cand['state']!='held':raise ValueError('保留中の候補ではありません')
  c.execute('UPDATE candidates SET state=?,decision_at=? WHERE id=?',('pending',now(),cid))
  c.execute('INSERT INTO decisions(candidate_id,action,reason,created_at) VALUES(?,?,?,?)',(cid,action,data.get('reason',''),now()))
  return {'state':'pending'}
 if action!='accept': raise ValueError('操作が不正です')
 case_id=data.get('case_id'); current=None
 if case_id:
  current=c.execute('SELECT * FROM cases WHERE id=?',(int(case_id),)).fetchone()
  if not current: raise ValueError('案件がありません')
  if cand['kind']=='suspension' and current['absence_type']!='card':raise ValueError('出場停止候補はカード案件へ結び付けてください')
  if int(data.get('version',-1))!=current['version']: raise ValueError('案件が別タブで変更されています。再読み込みしてください')
  if cand['kind'] in ('absence','suspension') and not data.get('reason','').strip(): raise ValueError('記事を既存案件へ結び付ける理由を入力してください')
 elif cand['kind'] not in ('absence','suspension'): raise ValueError('経過・復帰候補には対象案件を指定してください')
 if current:
  before=json.dumps(dict(current),ensure_ascii=False)
  c.execute('UPDATE cases SET version=version+1 WHERE id=?',(current['id'],));case_id=current['id']; after={'linked_candidate':cid}
 else:
  team=data.get('team') or cand['team']; player=data.get('player') or cand['player']
  if not team or not player: raise ValueError('クラブと選手を入力してください')
  start=data.get('start_date',cand['start_date'])
  if start and not re.fullmatch(r'\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{2}',start):raise ValueError('受傷日の書式が不正です')
  if start:
   try: datetime.strptime(start,'%Y-%m-%d' if '-' in start else '%y/%m/%d')
   except ValueError: raise ValueError('受傷日が実在する日付ではありません')
  if start and start!=cand['start_date'] and not data.get('reason','').strip():raise ValueError('受傷日を補記・変更する根拠を入力してください')
  if start and re.fullmatch(r'\d{4}-\d{2}-\d{2}',start): start=start[2:4]+'/'+start[5:7]+'/'+start[8:10]
  cur=c.execute('''INSERT INTO cases(team,player,absence_type,diagnosis,start_raw,start_date,duration_raw,duration_min,duration_max,duration_unit,duration_status,expected_weeks,expected_return_date,note,season,origin_competition_key,applies_across_competitions,source_article,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(team,player,'card' if cand['kind']=='suspension' else 'injury',cand['diagnosis'],cand['start_raw'],start,cand['duration_raw'],cand['duration_min'],cand['duration_max'],cand['duration_unit'],cand['duration_status'],data.get('expected_weeks',''),data.get('expected_return_date',''),data.get('note',''),data.get('season','2026'),data.get('origin_competition_key',''),data.get('applies_across_competitions',''),cand['article_id'],now()))
  case_id=cur.lastrowid;before='';after={'new_case':case_id,'start_date':start,'expected_return_date':data.get('expected_return_date','')}
 c.execute('INSERT OR IGNORE INTO evidence(case_id,article_id,candidate_id,kind,excerpt,event_date,created_at) VALUES(?,?,?,?,?,?,?)',(case_id,cand['article_id'],cid,cand['kind'],cand['excerpt'],cand['event_date'],now()))
 c.execute('UPDATE candidates SET state=?,case_id=?,decision_at=? WHERE id=?',('accepted',case_id,now(),cid))
 c.execute('INSERT INTO decisions(case_id,candidate_id,action,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?,?)',(case_id,cid,'accept',before,json.dumps(after,ensure_ascii=False),data.get('reason',''),now()))
 return {'case_id':case_id}

def merge_cases(c,from_id,to_id,reason):
 if from_id==to_id or not reason.strip():raise ValueError('統合元・先と理由を指定してください')
 source=c.execute('SELECT * FROM cases WHERE id=?',(from_id,)).fetchone()
 target=c.execute('SELECT * FROM cases WHERE id=?',(to_id,)).fetchone()
 if not source or not target or source['status']!='open' or target['status']!='open':raise ValueError('未終了の2案件を指定してください')
 if source['source_row'] or target['source_row']:raise ValueError('元CSV由来の案件は自動統合しません')
 if (name_key(source['team']),name_key(source['player']),name_key(source['diagnosis']))!=(name_key(target['team']),name_key(target['player']),name_key(target['diagnosis'])):raise ValueError('クラブ・選手・診断が一致しません')
 if not articles_linked(c,source['source_article'],target['source_article']):raise ValueError('公式記事間の直接リンクを確認できません')
 if any(source[k] for k in ('expected_weeks','expected_return_date','note')):raise ValueError('統合元に利用者の採用値があります')
 if c.execute('SELECT 1 FROM case_merges WHERE from_case_id=?',(from_id,)).fetchone():raise ValueError('統合済みです')
 before=json.dumps(dict(source),ensure_ascii=False)
 c.execute('UPDATE evidence SET case_id=? WHERE case_id=?',(to_id,from_id))
 c.execute('UPDATE candidates SET case_id=? WHERE case_id=?',(to_id,from_id))
 c.execute("UPDATE cases SET status='cancelled',version=version+1 WHERE id=?",(from_id,))
 c.execute('UPDATE cases SET version=version+1 WHERE id=?',(to_id,))
 c.execute('INSERT INTO case_merges(from_case_id,to_case_id,reason,created_at) VALUES(?,?,?,?)',(from_id,to_id,reason,now()))
 c.execute('INSERT INTO decisions(case_id,action,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?)',(from_id,'merge_into',before,json.dumps({'to_case_id':to_id},ensure_ascii=False),reason,now()))
 c.execute('INSERT INTO decisions(case_id,action,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?)',(to_id,'merge_from','',json.dumps({'from_case_id':from_id},ensure_ascii=False),reason,now()))
 return {'from_case_id':from_id,'to_case_id':to_id}

def change_case(c,data):
 x=c.execute('SELECT * FROM cases WHERE id=?',(int(data['id']),)).fetchone()
 if not x: raise ValueError('案件がありません')
 if x['version']!=int(data.get('version',-1)): raise ValueError('案件が別タブで変更されています。再読み込みしてください')
 action=data['action']; before=dict(x); effective=data.get('effective_date',''); reason=data.get('reason','').strip()
 if action in ('return','serve_suspension','serve_suspension_date_confirmed','exclude','cancel'):
  if action=='serve_suspension_date_confirmed':
   if x['absence_type']!='card':raise ValueError('出場停止案件のみ消化済みにできます')
   if x['status']!='open':raise ValueError('未終了の出場停止案件を指定してください')
   if not data.get('checked'):raise ValueError('対象日経過と処分消化を確認してください')
   try: target=datetime.strptime(x['start_date'],'%y/%m/%d').date()
   except (ValueError,TypeError):raise ValueError('保存済みの対象日を確認できません')
   if target>=datetime.now(ZoneInfo('Asia/Tokyo')).date():raise ValueError('対象日を過ぎてから確認してください')
   if not (x['note'] or x['start_raw']):raise ValueError('保存済みの出場停止情報を確認できません')
   effective=target.isoformat()
   reason='保存済みの出場停止情報と対象日経過を利用者が確認: '+(x['note'] or x['start_raw'])
  if not effective or not reason: raise ValueError('有効日と根拠・理由が必要です')
  try: datetime.strptime(effective,'%Y-%m-%d')
  except ValueError: raise ValueError('有効日が実在する日付ではありません')
  if action=='serve_suspension':
   if x['absence_type']!='card':raise ValueError('出場停止案件のみ消化済みにできます')
   if x['status']!='open':raise ValueError('未終了の出場停止案件を指定してください')
   if not data.get('checked'):raise ValueError('対象試合の実施と処分消化を確認してください')
   if not data.get('fixture','').strip():raise ValueError('対象試合を入力してください')
  if action=='return' and x['absence_type']=='card':raise ValueError('出場停止案件は消化済み操作を使ってください')
  if action=='return' and not data.get('checked'): raise ValueError('復帰確認のチェックが必要です')
  status={'return':'returned','serve_suspension':'served','serve_suspension_date_confirmed':'served','exclude':'excluded','cancel':'cancelled'}[action]
 elif action=='reopen':
  if not reason: raise ValueError('確認取消の理由が必要です')
  status='open'
 elif action=='edit': status=x['status']
 else: raise ValueError('操作が不正です')
 if action=='edit':
  fields=['team','player','diagnosis','start_date','expected_weeks','expected_return_date','note','origin_competition_key','applies_across_competitions','forecast_review_needed','forecast_review_reason']
  updates={k:data[k] for k in fields if k in data}
  if 'forecast_review_needed' in updates:updates['forecast_review_needed']=1 if updates['forecast_review_needed'] else 0
  if not updates or not reason: raise ValueError('変更内容と理由が必要です')
  c.execute('UPDATE cases SET '+','.join(k+'=?' for k in updates)+',version=version+1 WHERE id=?',(*updates.values(),x['id']))
 else: c.execute('UPDATE cases SET status=?,version=version+1 WHERE id=?',(status,x['id']))
 after=dict(c.execute('SELECT * FROM cases WHERE id=?',(x['id'],)).fetchone())
 if action=='serve_suspension':after['fixture']=data['fixture'].strip()
 c.execute('INSERT INTO decisions(case_id,action,before_json,after_json,reason,effective_date,created_at) VALUES(?,?,?,?,?,?,?)',(x['id'],action,json.dumps(before,ensure_ascii=False),json.dumps(after,ensure_ascii=False),reason,effective,now()))
 return after

def search_case(c,case_id):
 case=c.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
 if not case: raise ValueError('案件がありません')
 query=f'"{case["player"]}" 復帰 全体練習 出場'
 cur=c.execute('INSERT INTO search_runs(case_id,query,searched_at,status) VALUES(?,?,?,?)',(case_id,query,now(),'running'));run_id=cur.lastrowid
 try:
  url='https://lite.duckduckgo.com/lite/?q='+urllib.parse.quote(query)
  req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
  with urllib.request.urlopen(req,timeout=15) as r:
   body=r.read(500_000).decode('utf-8',errors='replace')
  found=[]
  for href,title in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*class=["\']result-link["\'][^>]*>(.*?)</a>',body,re.S|re.I):
   href=html.unescape(href); title=re.sub('<[^>]+>','',html.unescape(title)).strip()
   p=urllib.parse.urlparse(href)
   actual=urllib.parse.parse_qs(p.query).get('uddg',[href])[0]
   if urllib.parse.urlparse(actual).scheme!='https': continue
   if actual not in [x[0] for x in found]:found.append((actual,title))
  for link,title in found[:20]:
   source_type='official' if urllib.parse.urlparse(link).hostname in ALLOWED_HOSTS else 'external_unverified'
   c.execute('INSERT OR IGNORE INTO search_results(run_id,url,title,source_type) VALUES(?,?,?,?)',(run_id,link,title,source_type))
  c.execute('UPDATE search_runs SET status=?,result_count=? WHERE id=?',('success',min(len(found),20),run_id))
  return {'run_id':run_id,'status':'success','count':min(len(found),20)}
 except Exception as e:
  c.execute('UPDATE search_runs SET status=?,error=? WHERE id=?',('failed',str(e),run_id))
  return {'run_id':run_id,'status':'failed','error':str(e)}

def manual_event(c,data):
 case=c.execute('SELECT * FROM cases WHERE id=?',(int(data['case_id']),)).fetchone()
 if not case: raise ValueError('案件がありません')
 kind=data.get('kind','')
 if kind not in ('full_training','partial_training','bench','appearance','reinury','other'): raise ValueError('経過種別が不正です')
 excerpt=data.get('excerpt','').strip()
 if not excerpt: raise ValueError('利用者判断の内容・理由を入力してください')
 url=data.get('url','').strip()
 if url and urllib.parse.urlparse(url).scheme!='https': raise ValueError('URLはHTTPSで入力してください')
 if not url: url='manual:'+hashlib.sha256((str(case['id'])+now()+excerpt).encode()).hexdigest()
 cur=c.execute('INSERT OR IGNORE INTO articles(url,title,source,fetched_at,body_excerpt) VALUES(?,?,?,?,?)',(url,'手動登録','利用者判断',now(),excerpt))
 aid=cur.lastrowid or c.execute('SELECT id FROM articles WHERE url=?',(url,)).fetchone()[0]
 fp=hashlib.sha256((str(aid)+'|'+kind+'|'+str(case['id'])+'|'+excerpt).encode()).hexdigest()
 cur=c.execute('''INSERT OR IGNORE INTO candidates(article_id,fingerprint,kind,team,player,event_date,excerpt,case_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)''',(aid,fp,kind,case['team'],case['player'],data.get('event_date',''),excerpt,case['id'],now()))
 return {'candidate_id':cur.lastrowid,'created':bool(cur.rowcount)}

def preview(c):
 cases=rows(c,'SELECT * FROM cases ORDER BY team,player,id'); pending=rows(c,"SELECT id,player,team,kind FROM candidates WHERE state IN ('pending','held')")
 keys={}; holds=[]; export=[]; forecast_review_count=0
 today_jst=datetime.now(ZoneInfo('Asia/Tokyo')).date()
 for x in cases:
  key=(x['team'],re.sub(r'\s+','',x['player']))
  if x['status']=='open': keys[key]=keys.get(key,0)+1
 for x in cases:
  reasons=[]
  if x['status']!='open': reasons.append('終了案件のCSV方針が未決')
  if not x['team'] or not x['player']: reasons.append('所属または選手名が不明')
  if not x['start_date'] or not x['expected_return_date']: reasons.append('開始日またはCSV用の復帰見込み日が不明')
  if x['start_date'] and not re.fullmatch(r'\d{2}/\d{2}/\d{2}',x['start_date']): reasons.append('開始日の書式がyy/mm/ddではない')
  if x['expected_return_date'] and not re.fullmatch(r'\d{2}/\d{2}/\d{2}',x['expected_return_date']): reasons.append('見込み日の書式がyy/mm/ddではない')
  if x['expected_return_date'] and re.fullmatch(r'\d{2}/\d{2}/\d{2}',x['expected_return_date']):
   try:
    if datetime.strptime(x['expected_return_date'],'%y/%m/%d').date()<today_jst: reasons.append('復帰見込み日を経過（現在の状態を要確認）')
   except ValueError: reasons.append('見込み日が実在する日付ではない')
  if x['expected_weeks'] and not re.fullmatch(r'\s*\d+(?:\.\d+)?\s*',x['expected_weeks']): reasons.append('週数が数値ではない')
  if keys.get((x['team'],re.sub(r'\s+','',x['player'])),0)>1: reasons.append('同じ選手に複数の未終了案件')
  if not x['origin_competition_key']: reasons.append('大会キーが未設定')
  if reasons: holds.append({'id':x['id'],'player':x['player'],'team':x['team'],'reason':'、'.join(reasons)})
  else:
   export.append({k: x['player'] if k=='player_name' else x['absence_type'] if k=='absence_type' else x.get(k,'') for k in COLS})
   forecast_review_count+=bool(x['forecast_review_needed'])
 old=c.execute('SELECT rows_json FROM exports ORDER BY id DESC LIMIT 1').fetchone(); oldrows=json.loads(old[0]) if old else []
 ident=lambda v:(v['team'],v['player_name'],v['absence_type'],v['start_date'])
 a={ident(x):x for x in oldrows};b={ident(x):x for x in export}; diff=[]
 for k in b.keys()-a.keys(): diff.append({'type':'追加','row':b[k]})
 for k in a.keys()-b.keys(): diff.append({'type':'削除','row':a[k]})
 for k in a.keys()&b.keys():
  if a[k]!=b[k]: diff.append({'type':'変更','before':a[k],'row':b[k]})
 return {'rows':export,'holds':holds,'pending':pending,'diff':diff,'can_download':bool(cases) and not holds and not pending,'can_download_partial':bool(export),'forecast_review_count':forecast_review_count,'last_export_exists':bool(old)}
def csv_bytes(data):
 output=io.StringIO(newline=''); w=csv.DictWriter(output,fieldnames=COLS);w.writeheader();w.writerows(data)
 return ('\ufeff'+output.getvalue()).encode('utf-8')

class MatchTableParser(HTMLParser):
 def __init__(self,min_cells=8):
  super().__init__();self.rows=[];self.row=None;self.cell=None;self.link='';self.min_cells=min_cells
 def handle_starttag(self,tag,attrs):
  if tag=='tr':self.row=[]
  elif tag in ('td','th') and self.row is not None:self.cell=[];self.link=''
  elif tag=='a' and self.cell is not None:self.link=dict(attrs).get('href','')
  elif tag=='img' and self.cell is not None and 'icon_kome' in dict(attrs).get('src','') and '※' not in self.cell:self.cell.append('※')
 def handle_data(self,data):
  if self.cell is not None:self.cell.append(data)
 def handle_endtag(self,tag):
  if tag in ('td','th') and self.cell is not None:
   self.row.append((''.join(self.cell).strip(),self.link));self.cell=None
  elif tag=='tr' and self.row is not None:
   if len(self.row)>=self.min_cells:self.rows.append(self.row)
   self.row=None

def parse_suspension_notice(body):
 date_match=re.search(r'<div\s+class=["\']data-txt["\'][^>]*>\s*<p>\s*(20\d{2}/\d{1,2}/\d{1,2})',body)
 if not date_match:raise ValueError('出場停止のお知らせの日付を確認できません')
 published=datetime.strptime(date_match.group(1),'%Y/%m/%d').date()
 parser=MatchTableParser(min_cells=5);parser.feed(body)
 active=False;players=[]
 for row in parser.rows:
  cells=[unicodedata.normalize('NFKC',x[0]).strip() for x in row]
  if cells[:2]==['選手','チーム'] and '出場停止試合' in cells:active=True;continue
  if cells and cells[0] in ('役員','役職'):active=False
  if not active or len(cells)<5:continue
  name,team,_,code,fixture=cells[:5]
  if not name or not team or not fixture:continue
  if not re.search(r'明治安田J[12]リーグ',fixture):continue
  date=re.search(r'\((\d{1,2})/(\d{1,2})\)',fixture)
  if not date:continue
  month,day=map(int,date.groups());year=published.year+(month-published.month<-6)
  try:target=datetime(year,month,day).strftime('%Y-%m-%d')
  except ValueError:continue
  code=code.replace('※※','※').strip()
  players.append({'player':re.sub(r'\s+',' ',name).strip(),'team':team,'code':code,'fixture':fixture,'start_raw':f'{month:02d}/{day:02d}','start_date':target})
 return published.isoformat(),players

def collect_suspension_notice(c,fetcher=None):
 url='https://data.j-league.or.jp/SFIN03/'
 body=(fetcher or fetch)(url);published,players=parse_suspension_notice(body)
 if not players:raise ValueError('J1・J2の選手行を確認できません。ページ構造を点検してください')
 title=f'出場停止のお知らせ（{published}） | Jリーグデータサイト'
 digest=hashlib.sha256(body.encode()).hexdigest()
 old=c.execute('SELECT id FROM articles WHERE url=?',(url,)).fetchone()
 if old:
  aid=old['id'];c.execute('UPDATE articles SET title=?,source=?,published_at=?,fetched_at=?,body_hash=?,body_excerpt=? WHERE id=?',(title,'Jリーグデータサイト',published,now(),digest,json.dumps(players,ensure_ascii=False)[:2000],aid))
 else:
  aid=c.execute('INSERT INTO articles(url,title,source,published_at,fetched_at,body_hash,body_excerpt) VALUES(?,?,?,?,?,?,?)',(url,title,'Jリーグデータサイト',published,now(),digest,json.dumps(players,ensure_ascii=False)[:2000])).lastrowid
 c.execute('INSERT OR IGNORE INTO article_versions(article_id,body_hash,excerpt,fetched_at) VALUES(?,?,?,?)',(aid,digest,json.dumps(players,ensure_ascii=False)[:2000],now()))
 created=matched=existing_candidate=0
 canonical_teams=[x['team'] for x in c.execute('SELECT DISTINCT team FROM cases WHERE team IS NOT NULL')]
 for item in players:
  item['team']=next((team for team in canonical_teams if name_key(team)==name_key(item['team'])),item['team'])
  same_case=False
  for case in c.execute("SELECT * FROM cases WHERE absence_type='card'"):
   if name_key(case['team'])!=name_key(item['team']) or possible_name_key(case['player'])!=possible_name_key(item['player']):continue
   note=unicodedata.normalize('NFKC',(case['note'] or '')+' '+(case['start_raw'] or ''))
   if case['start_date']==item['start_date'][2:4]+'/'+item['start_date'][5:7]+'/'+item['start_date'][8:10] and (item['code'] in note or item['fixture'] in note):same_case=True;break
  if same_case:matched+=1;continue
  duplicate=False
  for prior in c.execute("SELECT * FROM candidates WHERE kind='suspension' AND start_raw=? AND state IN ('pending','held','accepted')",(item['start_raw'],)):
   if prior['start_date']==item['start_date'] and name_key(prior['team'])==name_key(item['team']) and possible_name_key(prior['player'])==possible_name_key(item['player']) and item['code'] in (prior['excerpt'] or ''):duplicate=True;break
  if duplicate:existing_candidate+=1;continue
  excerpt=f"出場停止: {item['code'] or '※'} / {item['fixture']}"
  fp=hashlib.sha256((published+'|'+item['team']+'|'+name_key(item['player'])+'|'+excerpt).encode()).hexdigest()
  cur=c.execute('''INSERT OR IGNORE INTO candidates(article_id,fingerprint,kind,team,player,start_raw,start_date,excerpt,created_at) VALUES(?,?,?,?,?,?,?,?,?)''',(aid,fp,'suspension',item['team'],item['player'],item['start_raw'],item['start_date'],excerpt,now()))
  created+=cur.rowcount
 return {'published_at':published,'listed_players':len(players),'created':created,'already_in_cases':matched,'already_candidates':existing_candidate,'article_url':url}

def parse_match_results(body,base_url):
 parser=MatchTableParser();parser.feed(body);matches=[]
 for row in parser.rows:
  season,league,round_text,date,_,home,score,away=([x[0] for x in row[:8]])
  date_match=re.match(r'(\d{2})/(\d{2})/(\d{2})',date)
  if not date_match or league.strip() not in ('Ｊ１','Ｊ２','J1','J2'):continue
  match_date='20'+date_match.group(1)+'-'+date_match.group(2)+'-'+date_match.group(3)
  result_url=urllib.parse.urljoin(base_url,row[6][1]) if re.fullmatch(r'\d+\s*-\s*\d+',score) and row[6][1].startswith('/SFMS02/') else ''
  matches.append({'season':season,'league':'J1' if '１' in league or league=='J1' else 'J2','round':unicodedata.normalize('NFKC',round_text).replace(' ','').strip(),'date':match_date,'home':home.strip(),'away':away.strip(),'score':score.strip(),'result_url':result_url})
 return matches

def suspension_match_review(c,fetcher=None):
 fetcher=fetcher or fetch
 today=datetime.now(ZoneInfo('Asia/Tokyo')).date()
 cases=c.execute("SELECT * FROM cases WHERE absence_type='card' AND status='open' ORDER BY id").fetchall()
 months=set()
 for x in cases:
  try:date=datetime.strptime(x['start_date'],'%y/%m/%d')
  except (ValueError,TypeError):continue
  if date.date()>today:continue
  if date.year==2026:months.add(date.month)
 fetched=[];errors=[];all_matches=[]
 for league_id in (1,2):
  for month in sorted(months):
   url=f'https://data.j-league.or.jp/SFMS01/search?competition_frame_ids={league_id}&competition_years=2026&section_months={month}'
   try:
    body=fetcher(url);all_matches.extend(parse_match_results(body,url));fetched.append(url)
   except Exception as exc:errors.append({'url':url,'error':str(exc)})
 candidates=[];unresolved=[]
 for x in cases:
  try:target=datetime.strptime(x['start_date'],'%y/%m/%d').strftime('%Y-%m-%d')
  except (ValueError,TypeError):unresolved.append({'case_id':x['id'],'reason':'対象試合日が不明'});continue
  if target>today.isoformat():continue
  note=unicodedata.normalize('NFKC',(x['note'] or '')+' '+(x['start_raw'] or ''))
  league_match=re.search(r'J([12])',note,re.I)
  round_match=re.search(r'第\s*(\d+)\s*節\s*第\s*(\d+)\s*日',note)
  possible=[m for m in all_matches if m['date']==target and x['team'] in (m['home'],m['away']) and (not league_match or m['league']=='J'+league_match.group(1)) and (not round_match or m['round']==f'第{int(round_match.group(1))}節第{int(round_match.group(2))}日')]
  if len(possible)!=1:
   unresolved.append({'case_id':x['id'],'reason':'公式結果に対象試合を一意に照合できない' if not possible else '対象試合が複数一致'});continue
  m=possible[0]
  if not m['result_url']:
   unresolved.append({'case_id':x['id'],'reason':'試合結果が未掲載または試合未実施','match':m});continue
  if not re.search(r'J[12]\([af]\)',note,re.I) and not ('※' in note and '他大会' in note):
   unresolved.append({'case_id':x['id'],'reason':'単一試合の停止と確認できないため手動確認','match':m});continue
  candidates.append({'case_id':x['id'],'version':x['version'],'team':x['team'],'player':x['player'],'match':m})
 return {'checked_at':now(),'fetched_urls':fetched,'errors':errors,'candidates':candidates,'unresolved':unresolved}

def state_data(c):
 candidates=rows(c,'SELECT candidates.*,articles.url,articles.title,articles.source,articles.published_at FROM candidates JOIN articles ON articles.id=candidates.article_id ORDER BY candidates.id DESC')
 all_runs=rows(c,'SELECT id,source_id,list_url,started_at,finished_at,status,found_count,attempted_count,success_count,failure_count,details_json FROM source_runs ORDER BY id DESC')
 coverage={}
 for source in rows(c,'SELECT id,url FROM sources'):
  runs=[r for r in all_runs if r['source_id']==source['id']]
  checked={r['list_url'] or source['url'] for r in runs if r['status'] in ('success','partial')}
  dates=[];months=[];boundary=False
  for run in runs:
   if run['status'] not in ('success','partial'):continue
   try:detail=json.loads(run['details_json'] or '{}')
   except (ValueError,TypeError):detail={}
   if not isinstance(detail,dict):detail={}
   current_month=archive_url_month(run['list_url'] or source['url'])
   pages=detail.get('archive_pages',[])
   if not isinstance(pages,list):pages=[]
   older_link=any(isinstance(p,dict) and isinstance(p.get('url'),str) and archive_url_year(p['url']) is not None and archive_url_year(p['url'])<2026 for p in pages)
   boundary=boundary or bool(detail.get('archive_year_stop') and detail.get('min_year')==2026) or bool(current_month=='2026-01' and older_link)
   month=archive_url_month(run['list_url'] or source['url']) if urllib.parse.urlparse(source['url']).hostname!='www.gamba-osaka.net' else None
   if month and month[:4]=='2026':months.append(month)
   published=detail.get('published_dates',{})
   if not isinstance(published,dict):published={}
   entries=c.execute('''SELECT e.title,e.article_url FROM list_entries e JOIN list_entry_sightings z ON z.entry_id=e.id WHERE z.run_id=?''',(run['id'],)).fetchall()
   for entry in entries:
    date=list_entry_date({**dict(entry),'published_date':published.get(entry['article_url'],'')})
    if date and date[:4]=='2026':dates.append(date)
  unvisited=archive_queue(c,source['id'])
  successful_archives=sum(r['status']=='success' and (r['list_url'] or source['url'])!=source['url'] for r in runs)
  if boundary:period_status='year_boundary';period_reason='2025年の記事に達したため停止'
  elif runs and runs[0]['status']=='failed':period_status='retry';period_reason='直近の取得に失敗。再取得が必要'
  elif unvisited:period_status='more_pages';period_reason='発見済みの未取得ページあり'
  elif successful_archives:period_status='unverified_end';period_reason='続きページ未発見。年境界は未確認'
  elif checked:period_status='first_page_only';period_reason='初頁のみ取得。過去ページは未確認'
  else:period_status='not_checked';period_reason='一覧を取得していません'
  coverage[str(source['id'])]={'checked_pages':len(checked),'checked_history':[{'url':r['list_url'] or source['url'],'status':r['status'],'at':r['finished_at'],'found':r['found_count'],'fetched':r['success_count']} for r in runs],'found_unchecked_pages':len(unvisited),'unchecked_pages':unvisited[:30],'oldest_publication_date':min(dates) if dates else None,'oldest_checked_month':min(months) if months else None,'period_status':period_status,'period_reason':period_reason,'last_checked_at':runs[0]['finished_at'] if runs else None,'last_checked_url':runs[0]['list_url'] if runs else None,'failed_runs':sum(r['status']=='failed' for r in runs),'partial_runs':sum(r['status']=='partial' for r in runs)}
 return {'list_entries':rows(c,'''SELECT e.*,a.id AS article_id,a.fetched_at,(SELECT count(*) FROM candidates v WHERE v.article_id=a.id) AS candidate_count FROM list_entries e LEFT JOIN articles a ON a.url=e.article_url ORDER BY e.last_seen_at DESC,e.id DESC'''),'cases':rows(c,'SELECT * FROM cases ORDER BY team,player,id'),'case_merges':rows(c,'SELECT * FROM case_merges ORDER BY id DESC'),'candidates':candidates,'candidate_suggestions':{str(x['id']):candidate_suggestions(c,x) for x in candidates if x['state'] in ('pending','held')},'articles':rows(c,'SELECT id,url,title,source,fetched_at FROM articles ORDER BY id DESC'),'sources':rows(c,'SELECT * FROM sources'),'source_runs':all_runs[:100],'source_coverage':coverage,'decisions':rows(c,'SELECT * FROM decisions ORDER BY id DESC LIMIT 200'),'evidence':rows(c,'SELECT * FROM evidence ORDER BY id DESC'),'imports':rows(c,'SELECT * FROM imports'),'exports':rows(c,'SELECT id,created_at,sha256,row_count FROM exports ORDER BY id DESC'),'search_runs':rows(c,'SELECT * FROM search_runs ORDER BY id DESC'),'search_results':rows(c,'SELECT * FROM search_results ORDER BY id DESC'),'injury_guide_versions':rows(c,'SELECT * FROM injury_guide_versions ORDER BY id DESC'),'injury_guide_rows':rows(c,'SELECT * FROM injury_guide_rows WHERE version_id=(SELECT max(id) FROM injury_guide_versions) ORDER BY source_row'),'collection_settings':dict(c.execute('SELECT * FROM collection_settings WHERE id=1').fetchone()),'collection_jobs':rows(c,'SELECT * FROM collection_jobs ORDER BY id DESC LIMIT 20'),'roster_snapshots':rows(c,'SELECT * FROM roster_snapshots ORDER BY id DESC'),'roster_matches':roster.case_matches(c)}

class Handler(BaseHTTPRequestHandler):
 def send(self,code,obj,typ='application/json; charset=utf-8',name=None):
  body=obj if isinstance(obj,bytes) else json.dumps(obj,ensure_ascii=False).encode()
  self.send_response(code);self.send_header('Content-Type',typ);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
  if name:self.send_header('Content-Disposition','attachment; filename="'+name+'"')
  self.end_headers();self.wfile.write(body)
 def do_GET(self):
  path=urllib.parse.urlparse(self.path).path
  if path=='/': return self.send(200,(ROOT/'index.html').read_bytes(),'text/html; charset=utf-8')
  try:
   with db() as c:
    if path=='/api/state': return self.send(200,state_data(c))
    if path=='/api/migration': return self.send(200,migration_preview(c))
    if path=='/api/preview': return self.send(200,preview(c))
    if path=='/api/backup':
     dest=DATA/'backup-download.sqlite3'
     with sqlite3.connect(dest) as target:c.backup(target)
     data=dest.read_bytes();dest.unlink();return self.send(200,data,'application/x-sqlite3','ledger-backup.sqlite3')
    if path=='/api/export':
     p=preview(c)
     if not p['can_download']: raise ValueError('保留行または未採用候補があります。プレビューを確認してください')
     data=csv_bytes(p['rows']);digest=hashlib.sha256(data).hexdigest()
     c.execute('INSERT INTO exports(created_at,sha256,row_count,rows_json) VALUES(?,?,?,?)',(now(),digest,len(p['rows']),json.dumps(p['rows'],ensure_ascii=False)))
     return self.send(200,data,'text/csv; charset=utf-8','absence-ledger.csv')
    if path=='/api/export-partial':
     p=preview(c)
     if not p['can_download_partial']:raise ValueError('出力できる行がありません')
     data=csv_bytes(p['rows']);digest=hashlib.sha256(data).hexdigest()
     c.execute('INSERT INTO exports(created_at,sha256,row_count,rows_json) VALUES(?,?,?,?)',(now(),digest,len(p['rows']),json.dumps(p['rows'],ensure_ascii=False)))
     return self.send(200,data,'text/csv; charset=utf-8','absence-ledger-partial.csv')
   self.send(404,{'error':'Not found'})
  except Exception as e:self.send(400,{'error':str(e)})
 def do_POST(self):
  try:
   n=int(self.headers.get('Content-Length','0'))
   if n>100000: raise ValueError('入力が大きすぎます')
   data=json.loads(self.rfile.read(n) or b'{}'); path=urllib.parse.urlparse(self.path).path
   with db() as c:
    if path=='/api/migrate': result=migrate(c)
    elif path=='/api/roster/import': result=roster.import_snapshot(c)
    elif path=='/api/collection/settings':
     days=data.get('weekdays')
     if days not in ('2,5','4','5'):raise ValueError('収集日は火・金、木、金から選んでください')
     enabled=1 if data.get('enabled') else 0
     c.execute('UPDATE collection_settings SET enabled=?,weekdays=? WHERE id=1',(enabled,days))
     result={'enabled':enabled,'weekdays':days}
    elif path=='/api/collection/run':
     running=c.execute("SELECT 1 FROM collection_jobs WHERE status='running' ORDER BY id DESC LIMIT 1").fetchone()
     if running:raise ValueError('収集が実行中です')
     with (DATA/'collection-job.log').open('ab') as log:
      subprocess.Popen([sys.executable,str(ROOT/'scripts'/'collection_job.py'),'--force'],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
     result={'started':True}
    elif path=='/api/ingest': result=ingest(c,data['url'])
    elif path=='/api/decide': result=decide(c,data)
    elif path=='/api/case': result=change_case(c,data)
    elif path=='/api/search': result=search_case(c,int(data['case_id']))
    elif path=='/api/manual': result=manual_event(c,data)
    elif path=='/api/suspension/check': result=suspension_match_review(c)
    elif path=='/api/suspension/collect': result=collect_suspension_notice(c)
    elif path=='/api/source/run':
     result=run_source(c,int(data['id']),list_url=data.get('list_url'))
    elif path=='/api/list-entry/fetch': result=fetch_list_entry(c,int(data['id']))
    elif path=='/api/list-entry/review': result=review_list_entry(c,int(data['id']),data['state'],data.get('reason',''))
    else: raise ValueError('不明な操作です')
   self.send(200,result)
  except Exception as e:self.send(400,{'error':str(e)})

if __name__=='__main__':
 if len(sys.argv)>1 and sys.argv[1]=='collect':
  parser=argparse.ArgumentParser(description='登録済み公式ニュース初頁を一括取得')
  parser.add_argument('--source-id',type=int,action='append',help='指定した情報源だけ取得。複数指定可')
  parser.add_argument('--archives',action='store_true',help='発見済みの未取得過去ページを辿る')
  parser.add_argument('--max-pages',type=int,default=3,help='過去ページを取得する場合の1情報源あたりの上限（既定3）')
  parser.add_argument('--since-year',type=int,default=2026,help='過去ページ収集の対象記事の開始年（既定2026）')
  parser.add_argument('--limit',type=int,help='情報源ごとの記事取得上限（初頁8、過去ページ50）')
  args=parser.parse_args(sys.argv[2:])
  init()
  summary=collect_archives(args.source_id,args.max_pages,args.limit or 50,min_year=args.since_year) if args.archives else collect_sources(args.source_id,args.limit or 8)
  print(json.dumps(summary,ensure_ascii=False,indent=2))
  sys.exit(1 if summary['failed'] or summary['partial'] else 0)
 init();server=ThreadingHTTPServer(('127.0.0.1',8765),Handler)
 print('http://127.0.0.1:8765  保存先:',DB,flush=True)
 server.serve_forever()
