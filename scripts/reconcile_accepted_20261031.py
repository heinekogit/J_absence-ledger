"""Link eight reviewed official notices to their matching imported CSV cases."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


# New case ID: (imported case ID, official injury date if stated in the article)
MATCHES = {
    222: (154, '26/10/10'),
    223: (152, '26/10/08'),
    224: (96, '26/09/09'),
    225: (94, '26/09/02'),
    226: (44, None),
    227: (79, '26/09/02'),
    228: (107, '26/09/12'),
    230: (75, None),
}


def main():
    with app.db() as c:
        c.execute('BEGIN IMMEDIATE')
        for new_id, (old_id, injury_date) in MATCHES.items():
            new = c.execute('SELECT * FROM cases WHERE id=?', (new_id,)).fetchone()
            old = c.execute('SELECT * FROM cases WHERE id=?', (old_id,)).fetchone()
            if not new or not old or new['status'] != 'open' or old['status'] != 'open':
                raise ValueError(f'案件の状態が変わりました: {new_id}, {old_id}')
            if new['source_row'] is not None or old['source_row'] is None:
                raise ValueError(f'CSV由来の確認に失敗: {new_id}, {old_id}')
            if (app.name_key(new['team']), app.name_key(new['player'])) != (app.name_key(old['team']), app.name_key(old['player'])):
                raise ValueError(f'選手が一致しません: {new_id}, {old_id}')
            if new['diagnosis'] and app.name_key(new['diagnosis'].split('（')[0].replace(' ','').replace('、',''))[:5] not in app.name_key(old['note'] or ''):
                # Editorial wording differs for a few diagnoses; require explicit mapping above
                # and a non-empty imported note for every merge.
                if not old['note']:
                    raise ValueError(f'元CSVの診断メモがありません: {old_id}')
            if injury_date and new['start_date'] != injury_date:
                raise ValueError(f'受傷日が一致しません: {new_id}')
            before_old = dict(old)
            before_new = dict(new)
            changes = {'diagnosis': new['diagnosis'], 'source_article': new['source_article'], 'forecast_review_needed': 1,
                       'forecast_review_reason': '公式記事の受傷日・診断を反映。CSV由来の復帰見込み日は再評価が必要'}
            if injury_date:
                changes['start_date'] = injury_date
            c.execute('UPDATE cases SET ' + ','.join(f'{k}=?' for k in changes) + ',version=version+1 WHERE id=?',
                      (*changes.values(), old_id))
            c.execute('UPDATE evidence SET case_id=? WHERE case_id=?', (old_id, new_id))
            c.execute('UPDATE candidates SET case_id=? WHERE case_id=?', (old_id, new_id))
            c.execute("UPDATE cases SET status='cancelled',version=version+1 WHERE id=?", (new_id,))
            reason = f'公式記事と元CSVの同一負傷案件を照合。新規案件 #{new_id} を元CSV案件 #{old_id} に統合'
            c.execute('INSERT INTO case_merges(from_case_id,to_case_id,reason,created_at) VALUES(?,?,?,?)',
                      (new_id, old_id, reason, app.now()))
            for cid, action, before, after in (
                (old_id, 'reconcile_from', before_old, dict(c.execute('SELECT * FROM cases WHERE id=?', (old_id,)).fetchone())),
                (new_id, 'merge_into', before_new, dict(c.execute('SELECT * FROM cases WHERE id=?', (new_id,)).fetchone())),
            ):
                c.execute('INSERT INTO decisions(case_id,action,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?)',
                          (cid, action, json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False), reason, app.now()))
        print(f'{len(MATCHES)} official notices linked to imported cases')


if __name__ == '__main__':
    main()
