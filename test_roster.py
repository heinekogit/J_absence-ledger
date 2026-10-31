import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

import roster

class RosterTests(unittest.TestCase):
 def test_snapshot_is_versioned_and_case_match_is_only_a_suggestion(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'players.csv'
   with path.open('w',encoding='utf-8',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=sorted(roster.REQUIRED));writer.writeheader()
    for club in sorted(set(roster.TEAM_KEYS.values())):
     for i in range(10):
      writer.writerow({'player_name':('山田 太郎' if club=='kashima' and i==0 else f'{club} 選手{i}'),'position':'MF','player_no':str(i+1),'birth':'2000/1/1','club_key':club,'club_name':club,'fetched_at':'2026-10-31T10:00:00','source_url':'https://www.jleague.jp/club/'+club+'/player/'})
   c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
   roster.install(c)
   c.execute("CREATE TABLE cases(id INTEGER PRIMARY KEY,team TEXT,player TEXT,status TEXT)")
   c.execute("INSERT INTO cases VALUES(1,'鹿島','山田 太郎','open')")
   first=roster.import_snapshot(c,path);second=roster.import_snapshot(c,path)
   self.assertEqual(first['snapshot_id'],second['snapshot_id'])
   self.assertTrue(second['already_imported'])
   self.assertEqual(roster.case_matches(c)[0]['status'],'same_club')
   self.assertEqual(c.execute('SELECT count(*) FROM roster_snapshots').fetchone()[0],1)
   c.close()

if __name__=='__main__':unittest.main()
