"""Import the legacy injury guide as immutable, versioned reference rows."""
import hashlib
import json
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

SOURCE = Path('/Users/dev_tomo/Desktop/tt_prj_restart/data/manual/欠場管理リスト.xlsx')
SHEET = '判断目安_整理案'
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
FIELDS = ('key', 'base', 'mild', 'moderate', 'severe', 'memo', 'search_terms')

def normalize(value):
 return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value or '')).replace('靱', '靭').replace('損傷', '損傷')

def read_rows(path=SOURCE):
 with zipfile.ZipFile(path) as z:
  workbook = ET.fromstring(z.read('xl/workbook.xml'))
  sheets = workbook.findall('.//m:sheet', NS)
  sheet = next((x for x in sheets if x.get('name') == SHEET), None)
  if sheet is None: raise ValueError('判断目安シートが見つかりません')
  rid = sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
  rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
  target = next(x.get('Target') for x in rels if x.get('Id') == rid)
  location = target.lstrip('/') if target.startswith('/xl/') else 'xl/' + target.lstrip('/')
  shared = ET.fromstring(z.read('xl/sharedStrings.xml')) if 'xl/sharedStrings.xml' in z.namelist() else None
  strings = [''.join(t.text or '' for t in si.findall('.//m:t', NS)) for si in shared.findall('m:si', NS)] if shared is not None else []
  sheet_xml = ET.fromstring(z.read(location))
  result = []
  for row in sheet_xml.findall('.//m:sheetData/m:row', NS):
   values = [''] * 7
   for cell in row.findall('m:c', NS):
    column = re.match(r'[A-Z]+', cell.get('r', ''))
    if not column or column.group() not in tuple('ABCDEFG'): continue
    index = ord(column.group()) - ord('A')
    raw = cell.find('m:v', NS)
    inline = cell.find('m:is', NS)
    value = raw.text if raw is not None and raw.text is not None else ''.join(t.text or '' for t in inline.findall('.//m:t', NS)) if inline is not None else ''
    if cell.get('t') == 's': value = strings[int(value)]
    values[index] = value
   if row.get('r') == '1':
    if values != ['判断キー', '基本', '軽度', '中等度', '重度', '判断メモ', '検索文字列']: raise ValueError('判断表の列が変わっています')
   elif values[0].strip(): result.append({'source_row': int(row.get('r')), **dict(zip(FIELDS, values))})
 return result

def install(c):
 c.execute('''CREATE TABLE IF NOT EXISTS injury_guide_versions(
  id INTEGER PRIMARY KEY, source_path TEXT NOT NULL, sheet_name TEXT NOT NULL,
  sha256 TEXT NOT NULL UNIQUE, imported_at TEXT NOT NULL, row_count INTEGER NOT NULL)''')
 c.execute('''CREATE TABLE IF NOT EXISTS injury_guide_rows(
  id INTEGER PRIMARY KEY, version_id INTEGER NOT NULL REFERENCES injury_guide_versions(id),
  source_row INTEGER NOT NULL, key TEXT NOT NULL, base TEXT, mild TEXT, moderate TEXT,
  severe TEXT, memo TEXT, search_terms TEXT, normalized_key TEXT NOT NULL,
  UNIQUE(version_id,source_row))''')

def import_guide(c, path=SOURCE, timestamp=None):
 install(c)
 digest = hashlib.sha256(path.read_bytes()).hexdigest()
 existing = c.execute('SELECT id,row_count FROM injury_guide_versions WHERE sha256=?', (digest,)).fetchone()
 if existing: return {'version_id': existing['id'], 'row_count': existing['row_count'], 'already_imported': True}
 data = read_rows(path)
 if not data: raise ValueError('判断表にデータがありません')
 from datetime import datetime, timezone
 imported_at = timestamp or datetime.now(timezone.utc).isoformat(timespec='seconds')
 version = c.execute('INSERT INTO injury_guide_versions(source_path,sheet_name,sha256,imported_at,row_count) VALUES(?,?,?,?,?)', (str(path), SHEET, digest, imported_at, len(data))).lastrowid
 for row in data:
  c.execute('''INSERT INTO injury_guide_rows(version_id,source_row,key,base,mild,moderate,severe,memo,search_terms,normalized_key)
   VALUES(?,?,?,?,?,?,?,?,?,?)''', (version,row['source_row'],*(row[field] for field in FIELDS),normalize(row['key'])))
 return {'version_id': version, 'row_count': len(data), 'already_imported': False}

def matches(c, diagnosis):
 if not diagnosis: return []
 version = c.execute('SELECT max(id) FROM injury_guide_versions').fetchone()[0]
 if version is None: return []
 target = normalize(diagnosis)
 if not target: return []
 matched = []
 for row in c.execute('SELECT * FROM injury_guide_rows WHERE version_id=? ORDER BY source_row', (version,)):
  terms = [row['key']] + re.split(r'[,、，\n]', row['search_terms'] or '')
  normalized = [normalize(x) for x in terms if x.strip()]
  if any(t == target for t in normalized): matched.append(dict(row))
 return matched
