import csv
import io
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import app


class LedgerTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.old_data,self.old_db=app.DATA,app.DB
  app.DATA=pathlib.Path(self.tmp.name)
  app.DB=app.DATA/'test.sqlite3'
  app.init()

 def tearDown(self):
  app.DATA,app.DB=self.old_data,self.old_db
  self.tmp.cleanup()

 def test_miyazaki_list_keeps_injury_and_skips_transfer_return(self):
  url='https://www.tegevajaro.com/news?page=1&year=2026'
  body='<a href="/news/579">橋本 啓吾選手の傷病について</a><a href="/news/799">岡本選手 千葉へ復帰のお知らせ</a>'
  self.assertEqual([x['url'] for x in app.discover_articles(url,body)],['https://www.tegevajaro.com/news/579'])
  self.assertEqual(len(app.discover_list_entries(url,body)),2)

 def test_miyazaki_embedded_article_extracts_diagnosis_without_inventing_date(self):
  text='このたび、宮脇茂夫選手の傷病につきまして、以下のとおりお知らせいたします。\n•傷病名：左アキレス腱断裂\n•状況：本年1月中旬のトレーニング中に負傷し、全治約6カ月との診断です。'
  result=app.extract(text,'宮脇 茂夫選手の傷病について - テゲバジャーロ宮崎','宮崎')
  self.assertEqual(len(result),1)
  self.assertEqual(result[0]['diagnosis'],'左アキレス腱断裂')
  self.assertEqual(result[0]['start_raw'],'1月中旬')
  self.assertEqual(result[0]['start_date'],'')
  self.assertEqual(result[0]['duration_min'],6)

 def test_cerezo_inline_diagnosis_and_injury_date(self):
  text='2026.04.15\n阪田 澪哉選手が、4月11日（土）のＧ大阪戦で負傷し、検査を行いました。\n■傷病名：左ハムストリング筋損傷'
  result=app.extract(text,'阪田 澪哉選手の負傷について | セレッソ大阪','Ｃ大阪')
  self.assertEqual(result[0]['diagnosis'],'左ハムストリング筋損傷')
  self.assertEqual(result[0]['start_date'],'2026-04-11')

 def test_suspension_match_review_only_proposes_completed_unique_match(self):
  base='https://data.j-league.or.jp/SFMS01/search?competition_frame_ids=1&competition_years=2026&section_months=10'
  def row(team,date,score,href=''):
   return '<tr>'+''.join(f'<td>{value}</td>' for value in ('2026/27','Ｊ１','第１節第１日',date,'14:00',team))+f'<td><a href="{href}">{score}</a></td><td>清水</td><td>会場</td></tr>'
  body='<table>'+row('京都','26/10/01(木)','2-1','/SFMS02/?match_card_id=123')+row('名古屋','26/10/01(木)','vs')+'</table>'
  parsed=app.parse_match_results(body,base)
  self.assertEqual(parsed[0]['result_url'],'https://data.j-league.or.jp/SFMS02/?match_card_id=123')
  self.assertEqual(parsed[1]['result_url'],'')
  with app.db() as c:
   for team,player in [('京都','佐藤 響'),('名古屋','高嶺 朋樹')]:
    c.execute("INSERT INTO cases(team,player,absence_type,start_date,note,status,created_at) VALUES(?,?, 'card','26/10/01','J1(f) 第1節第1日','open',?)",(team,player,app.now()))
   result=app.suspension_match_review(c,fetcher=lambda url:body if 'competition_frame_ids=1' in url else '<table></table>')
   self.assertEqual([x['player'] for x in result['candidates']],['佐藤 響'])
   self.assertEqual(result['unresolved'][0]['reason'],'試合結果が未掲載または試合未実施')

 def test_collect_suspension_notice_is_idempotent_and_excludes_staff(self):
  body='''<div class="data-txt"><p>2026/10/29</p></div><table><tr><th>選手</th><th>チーム</th><th>前回の停止</th><th>今回の停止</th><th>出場停止試合</th></tr><tr><td>佐藤　響</td><td>京都</td><td></td><td>J1(f)</td><td>２０２６／２７明治安田Ｊ１リーグ第１３節第１日(10/31)</td></tr><tr><td>高嶺　朋樹</td><td>名古屋</td><td></td><td><img src="../images/common/icon_kome2.gif"></td><td>２０２６／２７明治安田Ｊ１リーグ第１３節第１日(10/31)</td></tr><tr><td>川﨑　修平</td><td>奈良</td><td></td><td>J3(f)</td><td>２０２６／２７明治安田Ｊ３リーグ第１４節第１日(10/31)</td></tr></table><table><tr><th>役員</th><th>役職</th><th>チーム</th><th>今回の停止</th><th>出場停止試合</th></tr><tr><td>槙野 智章</td><td>監督</td><td>藤枝</td><td>J2(b)</td><td>２０２６／２７明治安田Ｊ２リーグ第１４節第１日(10/31)</td></tr></table>'''
  published,found=app.parse_suspension_notice(body)
  self.assertEqual(published,'2026-10-29')
  self.assertEqual([(x['player'],x['code']) for x in found],[('佐藤 響','J1(f)'),('高嶺 朋樹','※')])
  with app.db() as c:
   c.execute("INSERT INTO cases(team,player,absence_type,start_date,note,status,created_at) VALUES('京都','佐藤 響','card','26/10/31','J1(f) 第13節第1日','open',?)",(app.now(),))
   first=app.collect_suspension_notice(c,fetcher=lambda url:body)
   second=app.collect_suspension_notice(c,fetcher=lambda url:body)
   self.assertEqual((first['listed_players'],first['created'],first['already_in_cases']), (2,1,1))
   self.assertEqual((second['created'],second['already_candidates']),(0,1))

 def test_iwaki_injury_without_player_suffix_has_full_date(self):
  text='岩下航の負傷について\n2026.09.17\nSHARE\n岩下航選手が負傷しました。\n受傷日\n9月12日（土）\n診断名\n右大腿二頭筋肉離れ\n全治\n2ヶ月程度を要する見込み'
  x=app.extract(text,'岩下航の負傷について - いわきFC Official Site','いわき')[0]
  self.assertEqual((x['player'],x['start_date'],x['diagnosis'],x['duration_min']),('岩下航','2026-09-12','右大腿二頭筋肉離れ',2))

 def test_jef_api_news_list_excludes_non_article_links(self):
  payload={'news':[{'link':'/news/detail/5705','title':'選手の怪我について','ymd':'2026.10.30'},{'link':'/teams/top/','title':'負傷','ymd':'2026.10.30'}]}
  with patch.object(app,'fetch',return_value=json.dumps(payload)):
   body=app.fetch_source_page('https://jefunited.co.jp/news/list?c=2&ym=0','https://jefunited.co.jp/news/list?c=2&ym=0')
  self.assertEqual([x['url'] for x in app.discover_articles('https://jefunited.co.jp/news/list?c=2&ym=0',body)],['https://jefunited.co.jp/news/detail/5705'])

 def test_suspension_article_excludes_staff_section(self):
  body='出場停止試合\n佐藤　響\n京都\nJ1(f)\n２０２６／２７明治安田Ｊ１リーグ第１３節第１日(10/31)\n役員\n役職\nチーム\n槙野　智章\n監督\n藤枝\nJ2(b)\n２０２６／２７明治安田Ｊ２リーグ第１４節第１日(10/31)\n・大会「J1」'
  found=app.extract(body,'出場停止選手のお知らせ（2026/10/29）','J1')
  self.assertEqual([(x['team'],x['player']) for x in found],[('京都','佐藤 響')])

 def test_fujieda_injury_and_archive_page(self):
  base='https://myfc.co.jp/news/newslist/topteam/'
  page='<a href="/news/20261016/1192376/">菊井 悠介 選手の怪我について</a><a href="/news/20261029/1193009/">槙野 智章 監督の出場停止について</a><a href="/news/newslist/topteam/page/2/">2</a>'
  self.assertEqual([x['url'] for x in app.discover_articles(base,page)],['https://myfc.co.jp/news/20261016/1192376/'])
  self.assertEqual(app.discover_archive_pages(base,page)[0]['url'],base+'page/2/')
  self.assertEqual(app.checked_list_url(base,base+'page/2/'),base+'page/2/')
  body='菊井 悠介 選手の怪我について\n【負傷日】10月3日（土）\n【診断】右反復性肩関節脱臼（復帰までの期間 約4～5か月）\n※10月15日に手術が終了しました。'
  found=app.extract(body,'菊井 悠介 選手の怪我について | 藤枝MYFC','藤枝')
  self.assertEqual((found[0]['player'],found[0]['diagnosis'],found[0]['start_raw'],found[0]['duration_min'],found[0]['duration_max']),('菊井 悠介','右反復性肩関節脱臼','10月3日',4,5))
  older='近藤優成 選手の怪我について\n【診断】\n左肘肘関節脱臼（全治約8週間）\n※3月7日（土）明治安田Ｊ２・Ｊ３百年構想リーグで負傷'
  prior=app.extract(older,'近藤優成 選手の怪我について | 藤枝MYFC','藤枝')
  self.assertEqual((prior[0]['start_raw'],prior[0]['duration_raw'],prior[0]['duration_min'],prior[0]['duration_max']),('3月7日','全治約8週間',8,8))

 def test_iwata_homepage_discovery_and_injury(self):
  base='https://jubilo-iwata.co.jp/'
  page='<a href="/news/topteam20260918infoK9m2R">2026.09.18トップチーム渡邉 りょう選手の負傷について</a>'
  self.assertEqual(app.discover_articles(base,page)[0]['url'],'https://jubilo-iwata.co.jp/news/topteam20260918infoK9m2R')
  body='渡邉 りょう選手の負傷について\n渡邉 りょう選手が、9月6日(日)に開催された試合にて負傷しました。\n診断名\n右腓腹筋肉離れ\nトレーニング合流まで\n2ヶ月程度見込み\n一覧に戻る'
  found=app.extract(body,'渡邉 りょう選手の負傷について｜ジュビロ磐田','磐田')
  self.assertEqual((found[0]['player'],found[0]['diagnosis'],found[0]['start_raw'],found[0]['duration_raw']),('渡邉 りょう','右腓腹筋肉離れ','9月6日','トレーニング合流まで 2ヶ月程度見込み'))
  surgery='甲斐 佑蒼選手の負傷について\nなお、甲斐選手は7月14日(火)に手術しました。\n診断名\n左第5中足骨骨折\nトレーニング合流まで\n術後3ヶ月程度見込み'
  assessed=app.extract(surgery,'甲斐 佑蒼選手の負傷について｜ジュビロ磐田','磐田')
  self.assertEqual((assessed[0]['start_raw'],assessed[0]['duration_min'],assessed[0]['duration_max']),('',3,3))
  range_body='植村 洋斗選手の負傷について\n診断名\n左腓骨骨折\nトレーニング合流まで\n8-10週程度見込み'
  range_found=app.extract(range_body,'植村 洋斗選手の負傷について｜ジュビロ磐田','磐田')
  self.assertEqual((range_found[0]['duration_min'],range_found[0]['duration_max']),(8,10))

 def test_jleague_iwata_headline_range_keeps_full_name(self):
  body='ジュビロ磐田は20日、MF植村 洋斗の負傷を発表しました。\n植村はトレーニング中に負傷し、左腓骨骨折と診断。全治まで8〜10週間を要する見込みとなっています。'
  found=app.extract(body,'【公式】MF植村が全治8〜10週間の負傷【磐田】 | Ｊリーグ公式サイト','J2')
  self.assertEqual((found[0]['team'],found[0]['player'],found[0]['diagnosis'],found[0]['duration_min'],found[0]['duration_max']),('磐田','植村 洋斗','左腓骨骨折',8,10))

 def test_loan_return_article_is_not_injury_return(self):
  body='松本 遥翔選手 復帰のお知らせ\nカターレ富山に育成型期限付き移籍していた松本 遥翔選手が、鹿島アントラーズへ復帰することになりました。'
  self.assertEqual(app.extract(body,'松本 遥翔選手 復帰のお知らせ','鹿島'),[])

 def test_loan_return_with_club_name_in_title_is_not_injury_return(self):
  body='土屋 巧選手 柏レイソルに復帰\nヴァンフォーレ甲府へ期限付き移籍しておりました土屋 巧選手の、柏レイソルへの復帰が決定しました。'
  self.assertEqual(app.extract(body,'土屋 巧選手 柏レイソルに復帰','柏'),[])

 def test_jleague_two_player_injury_article(self):
  body='ＦＣ今治は27日、MF新井 光とDF市原 亮太の負傷を発表しました。\n新井は左後脛骨筋腱部分損傷と診断され、9日に手術を行っています。\n16日のトレーニング中に負傷した市原は左膝前十字靭帯断裂と診断されています。'
  found=app.extract(body,'MF新井とDF市原の負傷を発表【今治】','J2')
  self.assertEqual([(x['player'],x['diagnosis']) for x in found],[('新井 光','左後脛骨筋腱部分損傷'),('市原 亮太','左膝前十字靭帯断裂')])

 def test_imabari_embedded_news_and_injury(self):
  page='next_f.push([1,"\\\"href\\\":\\\"/news/abc123\\\" blah \\\"alt\\\":\\\"市原 亮太選手の負傷について\\\""])'
  url='https://www.fcimabari.com/news?category=team'
  self.assertEqual([x['url'] for x in app.discover_articles(url,page)],['https://www.fcimabari.com/news/abc123'])
  body='市原 亮太選手の負傷について\nこの度、市原 亮太選手が10月16日（金）のトレーニング中に受傷し、診断されました。\n診断名：左膝前十字靭帯断裂\nこのニュースをシェア'
  found=app.extract(body,'市原 亮太選手の負傷について','今治')
  self.assertEqual([(x['player'],x['diagnosis'],x['start_raw']) for x in found],[('市原 亮太','左膝前十字靭帯断裂','10月16日')])

 def test_vortis_injury_article(self):
  body='稲見 哲行選手 負傷のお知らせ\n稲見 哲行選手が10月3日の試合で負傷しました。\n診断名\n右ヒラメ筋肉離れ\n受傷日\n10月3日（土）'
  found=app.extract(body,'稲見 哲行選手 負傷のお知らせ','徳島')
  self.assertEqual([(x['player'],x['diagnosis'],x['start_raw']) for x in found],[('稲見 哲行','右ヒラメ筋肉離れ','10月3日')])

 def test_ventforet_surgery_article(self):
  body='井上樹選手の手術について\nNEWS\n井上樹選手の手術について\n2026.10.06\nDF2井上樹選手が手術を行いました。\n診断結果：左前十字靭帯断裂\n手術日：2026年10月1日\n全治：約8ヶ月\n前へ\n井上樹選手の手術について'
  found=app.extract(body,'井上樹選手の手術について','甲府')
  self.assertEqual([(x['player'],x['diagnosis'],x['start_raw'],x['duration_raw']) for x in found],[('井上樹','左前十字靭帯断裂','','全治：約8ヶ月')])

 def test_fctokyo_injury_and_archive_page(self):
  body='室屋成選手の負傷について\n9月29日(火)ルヴァンカップ愛媛FC戦にて負傷した室屋成選手についてお知らせします。\n傷病名\n左ヒラメ筋肉離れ'
  found=app.extract(body,'室屋成選手の負傷について','FC東京')
  self.assertEqual([(x['player'],x['diagnosis'],x['start_raw']) for x in found],[('室屋成','左ヒラメ筋肉離れ','9月29日')])
  base='https://www.fctokyo.co.jp/news/'
  self.assertEqual(app.checked_list_url(base,'https://www.fctokyo.co.jp/news/page/6/'),'https://www.fctokyo.co.jp/news/page/6/')

 def test_fagiano_injury_and_month_page(self):
  body='田上大地選手の怪我について\n【受傷日】\n2026年10月7日\n天皇杯3回戦\n【診断名】\n前十字靭帯損傷\n外側半月板損傷\n内側側副靱帯損傷\nこのページの先頭へ'
  found=app.extract(body,'田上大地選手の怪我について','岡山')
  self.assertEqual([(x['player'],x['diagnosis'],x['start_raw']) for x in found],[('田上大地','前十字靭帯損傷、外側半月板損傷、内側側副靱帯損傷','2026年10月7日')])
  base='https://www.fagiano-okayama.com/news/'
  self.assertEqual(app.checked_list_url(base,'https://www.fagiano-okayama.com/news/lm/l0_202610/'),'https://www.fagiano-okayama.com/news/lm/l0_202610/')
  self.assertEqual(app.checked_list_url(base,'https://www.fagiano-okayama.com/news/l0_202610'),'https://www.fagiano-okayama.com/news/l0_202610')
  self.assertEqual(app.discover_archive_pages(base,'<a href="/news/l0_202610">2026年 10月</a>')[0]['url'],'https://www.fagiano-okayama.com/news/l0_202610')

 def test_fagiano_diagnosis_stops_before_duration(self):
  body='小倉 幸成選手の怪我について\n2026.08.07\nまた6月15日に手術を行いました。\n【診断名】 左膝外側半月板断裂\n【全治】 術後6か月程度\nこのページの先頭へ'
  found=app.extract(body,'小倉 幸成選手の怪我について','岡山')
  self.assertEqual((found[0]['diagnosis'],found[0]['duration_raw'],found[0]['start_raw']),('左膝外側半月板断裂','術後6か月程度',''))

 def test_fagiano_surgery_keeps_operation_date_out_of_injury_date(self):
  body='木村太哉選手の手術について\n2026.06.09お知らせ\n木村太哉選手の手術について\n6月8日に手術を行いました。\n【診断名】 左足内果疲労骨折\n【全治】 2〜3か月程度\nこのページの先頭へ'
  found=app.extract(body,'木村太哉選手の手術について','岡山')
  self.assertEqual((found[0]['diagnosis'],found[0]['start_raw']),('左足内果疲労骨折',''))

 def test_forecast_review_flag_is_saved_with_history(self):
  with app.db() as c:
   cid=c.execute("INSERT INTO cases(team,player,absence_type,status) VALUES('甲府','例','injury','open')").lastrowid
   app.change_case(c,{'id':cid,'version':1,'action':'edit','forecast_review_needed':1,'forecast_review_reason':'受傷日不明','reason':'原記事で確認'})
   row=c.execute('SELECT forecast_review_needed,forecast_review_reason,version FROM cases WHERE id=?',(cid,)).fetchone()
   self.assertEqual(tuple(row),(1,'受傷日不明',2))
   self.assertEqual(c.execute("SELECT action FROM decisions WHERE case_id=? ORDER BY id DESC LIMIT 1",(cid,)).fetchone()[0],'edit')

 def test_vissel_injury_article(self):
  body='FW佐々木大樹選手の負傷について\nFW佐々木大樹選手（26）が負傷し、病院で検査を行った結果、右外側半月板損傷と診断されましたので、お知らせいたします。'
  found=app.extract(body,'ヴィッセル神戸 ニュース/レポート : FW佐々木大樹選手の負傷について','神戸')
  self.assertEqual([(x['player'],x['diagnosis'],x['start_raw']) for x in found],[('佐々木大樹','右外側半月板損傷','')])

 def test_list_headline_audit_and_review(self):
  page='''<a href="/news/topteam/post-9001.html">選手の負傷について</a><a href="/news/topteam/post-9002.html">選手が治療を開始</a><a href="/news/topteam/post-9003.html">試合のお知らせ</a>'''
  url='https://www.reysol.co.jp/news/topteam/'
  entries=app.discover_list_entries(url,page)
  self.assertEqual(len(entries),3)
  self.assertEqual(sum(x['auto_selected'] for x in entries),1)
  self.assertEqual(next(x for x in entries if '9002' in x['url'])['watch_reason'],'治療')
  with app.db() as c:
   sid=c.execute("SELECT id FROM sources WHERE club='柏'").fetchone()[0]
   rid=c.execute('INSERT INTO source_runs(source_id,list_url,started_at,status) VALUES(?,?,?,?)',(sid,url,app.now(),'success')).lastrowid
   app.save_list_entries(c,sid,rid,url,entries)
   app.save_list_entries(c,sid,rid,url,entries)
   self.assertEqual(c.execute('SELECT count(*) FROM list_entries').fetchone()[0],3)
   self.assertEqual(c.execute('SELECT count(*) FROM list_entry_sightings').fetchone()[0],3)
   entry=c.execute("SELECT id FROM list_entries WHERE article_url LIKE '%9002%'").fetchone()[0]
   with self.assertRaises(ValueError):app.review_list_entry(c,entry,'excluded','')
   app.review_list_entry(c,entry,'excluded','試合関連の記事')
   self.assertEqual(c.execute('SELECT review_state FROM list_entries WHERE id=?',(entry,)).fetchone()[0],'excluded')
   self.assertEqual(len(app.state_data(c)['list_entries']),3)

 def test_yokohama_fc_list_headline(self):
  page='''<a href="/2026/10/27/player-news/"><p>2026.10.27 Tue</p><p>山田選手が治療を開始</p><span>お知らせ</span></a>'''
  entries=app.discover_list_entries('https://yokohamafc.com/news/',page)
  self.assertEqual(len(entries),1)
  self.assertEqual(entries[0]['title'],'山田選手が治療を開始')
  self.assertEqual(entries[0]['watch_reason'],'治療')

 def test_accept_requires_reason_for_corrected_date(self):
  with app.db() as c:
   article=c.execute("INSERT INTO articles(url,title,source,fetched_at) VALUES('https://www.jleague.jp/news/article/999001/','負傷','Jリーグ',?)",(app.now(),)).lastrowid
   cid=c.execute("INSERT INTO candidates(article_id,fingerprint,kind,team,player,start_raw,start_date,state) VALUES(?,'date-review','absence','湘南','山田','17日','','pending')",(article,)).lastrowid
   data={'candidate_id':cid,'action':'accept','team':'湘南','player':'山田','start_date':'2026-10-17'}
   with self.assertRaisesRegex(ValueError,'根拠'):app.decide(c,data)
   result=app.decide(c,{**data,'reason':'クラブ原記事に10月17日と記載'})
   self.assertEqual(c.execute('SELECT start_date FROM cases WHERE id=?',(result['case_id'],)).fetchone()[0],'26/10/17')
   self.assertEqual(c.execute('SELECT reason FROM decisions WHERE candidate_id=?',(cid,)).fetchone()[0],'クラブ原記事に10月17日と記載')

 def test_jleague_suspension_rows_are_separate_candidates(self):
  text='出場停止試合\n佐藤　響\n京都\nJ1(f)\n２０２６／２７明治安田Ｊ１リーグ第１３節第１日(10/31)\n乾　貴士\n磐田\nJ2(a)\n２０２６／２７明治安田Ｊ２リーグ第１４節第１日(10/31)\n・大会「J1」'
  out=app.extract(text,'出場停止選手のお知らせ（2026/10/26）','J1')
  self.assertEqual([(x['team'],x['player'],x['start_raw']) for x in out],[('京都','佐藤 響','10/31'),('磐田','乾 貴士','10/31')])
  with app.db() as c:
   article=c.execute("INSERT INTO articles(url,title,source,fetched_at) VALUES('https://www.jleague.jp/news/article/999002/','出場停止','Jリーグ',?)",(app.now(),)).lastrowid
   cid=c.execute("INSERT INTO candidates(article_id,fingerprint,kind,team,player,start_raw,state) VALUES(?,'suspension-review','suspension','京都','佐藤 響','10/31','pending')",(article,)).lastrowid
   case_id=app.decide(c,{'candidate_id':cid,'action':'accept','start_date':'2026-10-31','reason':'記事の対象試合日を確認'})['case_id']
   self.assertEqual(c.execute('SELECT absence_type,start_date FROM cases WHERE id=?',(case_id,)).fetchone()[:],('card','26/10/31'))

 def test_jleague_summary_creates_dated_appearance_candidate(self):
  text='明治安田Ｊ１リーグ\n2026/10/24 (土) 18:40\nホームで清水と対戦した広島は、50分には浅野 拓磨の復帰後初ゴールでリードを広げた。'
  result=app.extract(text,'広島は浅野復帰弾【サマリー：明治安田Ｊ１ 第12節】','J1')
  self.assertEqual(len(result),1)
  self.assertEqual((result[0]['kind'],result[0]['team'],result[0]['player'],result[0]['event_date']),('appearance','広島','浅野 拓磨','2026-10-24'))

 def test_card_case_requires_fixture_and_evidence_to_close(self):
  with app.db() as c:
   card=c.execute("INSERT INTO cases(team,player,absence_type,status,version,created_at) VALUES('京都','佐藤 響','card','open',1,?)",(app.now(),)).lastrowid
   base={'id':card,'version':1,'action':'serve_suspension','effective_date':'2026-10-31','reason':'公式試合記録URL','checked':True}
   with self.assertRaisesRegex(ValueError,'対象試合'):app.change_case(c,base)
   with self.assertRaisesRegex(ValueError,'消化'):app.change_case(c,{**base,'fixture':'J1第13節','checked':False})
   with self.assertRaisesRegex(ValueError,'消化済み操作'):app.change_case(c,{**base,'action':'return','fixture':'J1第13節'})
   result=app.change_case(c,{**base,'fixture':'J1第13節 京都対相手クラブ'})
   self.assertEqual(result['status'],'served')
   history=c.execute('SELECT action,after_json,effective_date,reason FROM decisions WHERE case_id=?',(card,)).fetchone()
   self.assertEqual(history['action'],'serve_suspension')
   self.assertEqual(json.loads(history['after_json'])['fixture'],'J1第13節 京都対相手クラブ')
   with self.assertRaisesRegex(ValueError,'未終了'):app.change_case(c,{**base,'version':2,'fixture':'J1第13節'})
   self.assertEqual(app.change_case(c,{'id':card,'version':2,'action':'reopen','reason':'処分消化の判断を訂正'})['status'],'open')

 def test_card_date_confirmation_uses_saved_notice_without_live_article(self):
  with app.db() as c:
   card=c.execute("INSERT INTO cases(team,player,absence_type,start_date,note,status,version,created_at) VALUES('甲府','遠藤 光','card','26/11/03','出場停止: J2(f) / 第15節第1日(11/03)','open',1,?)",(app.now(),)).lastrowid
   request={'id':card,'version':1,'action':'serve_suspension_date_confirmed','checked':True}
   with self.assertRaisesRegex(ValueError,'確認'):app.change_case(c,{**request,'checked':False})
   with patch.object(app,'datetime',wraps=app.datetime) as clock:
    clock.now.return_value=app.datetime(2026,11,5,tzinfo=app.ZoneInfo('Asia/Tokyo'))
    result=app.change_case(c,request)
   self.assertEqual(result['status'],'served')
   decision=c.execute('SELECT effective_date,reason FROM decisions WHERE case_id=? ORDER BY id DESC',(card,)).fetchone()
   self.assertEqual(decision['effective_date'],'2026-11-03')
   self.assertIn('J2(f)',decision['reason'])

 def test_card_date_confirmation_rejects_target_day_and_injury(self):
  with app.db() as c:
   card=c.execute("INSERT INTO cases(team,player,absence_type,start_date,note,status,version,created_at) VALUES('甲府','選手A','card','26/11/05','出場停止: J2(f)','open',1,?)",(app.now(),)).lastrowid
   injury=c.execute("INSERT INTO cases(team,player,absence_type,start_date,note,status,version,created_at) VALUES('甲府','選手B','injury','26/11/03','負傷','open',1,?)",(app.now(),)).lastrowid
   with patch.object(app,'datetime',wraps=app.datetime) as clock:
    clock.now.return_value=app.datetime(2026,11,5,tzinfo=app.ZoneInfo('Asia/Tokyo'))
    with self.assertRaisesRegex(ValueError,'対象日を過ぎて'):app.change_case(c,{'id':card,'version':1,'action':'serve_suspension_date_confirmed','checked':True})
    with self.assertRaisesRegex(ValueError,'出場停止案件のみ'):app.change_case(c,{'id':injury,'version':1,'action':'serve_suspension_date_confirmed','checked':True})

 def test_suspension_matching_existing_card_does_not_create_duplicate(self):
  with app.db() as c:
   article=c.execute("INSERT INTO articles(url,title,source,fetched_at) VALUES('https://www.jleague.jp/news/article/999003/','出場停止','Jリーグ',?)",(app.now(),)).lastrowid
   cid=c.execute("INSERT INTO candidates(article_id,fingerprint,kind,team,player,start_raw,excerpt,state) VALUES(?,'suspension-match','suspension','今治','ガブリエル ゴメス','10/25','出場停止: J2(f) / 2026/27明治安田J2リーグ第13節第2日(10/25)','pending')",(article,)).lastrowid
   card=c.execute("INSERT INTO cases(team,player,absence_type,start_date,note,status,version,created_at) VALUES('今治','ガブリエルゴメス','card','26/10/23','J2(f) ２０２６／２７明治安田Ｊ２リーグ第１３節第２日(10/25)','open',1,?)",(app.now(),)).lastrowid
   candidate=c.execute('SELECT * FROM candidates WHERE id=?',(cid,)).fetchone()
   self.assertIn('停止コード・対象試合一致',app.candidate_suggestions(c,candidate)['cases'][0]['reasons'])
   before=c.execute('SELECT count(*) FROM cases').fetchone()[0]
   self.assertEqual(app.decide(c,{'candidate_id':cid,'action':'accept','case_id':card,'version':1,'reason':'停止コードと対象試合が一致'})['case_id'],card)
   self.assertEqual(c.execute('SELECT count(*) FROM cases').fetchone()[0],before)
   self.assertEqual(c.execute('SELECT start_date FROM cases WHERE id=?',(card,)).fetchone()[0],'26/10/23')

 def test_migration_preserves_rows_and_blocks_ambiguous_export(self):
  with app.db() as c:
   preview=app.migration_preview(c)
   self.assertEqual(preview['count'],169)
   self.assertEqual(app.migrate(c)['imported'],169)
   self.assertEqual(c.execute('SELECT count(*) FROM cases').fetchone()[0],169)
   self.assertEqual(c.execute("SELECT count(*) FROM cases WHERE absence_type='card'").fetchone()[0],47)
   output=app.preview(c)
   self.assertFalse(output['can_download'])
   self.assertTrue(output['can_download_partial'])
   self.assertTrue(output['rows'])
   self.assertEqual(list(output['rows'][0]),app.COLS)
   self.assertTrue(any('複数' in x['reason'] for x in output['holds']))
  with app.db() as c:
   self.assertEqual(c.execute('SELECT count(*) FROM cases').fetchone()[0],169)

 def test_preview_holds_overdue_forecast_without_marking_returned(self):
  with app.db() as c:
   case_id=c.execute("INSERT INTO cases(team,player,absence_type,start_date,expected_return_date,season,origin_competition_key,status,created_at) VALUES('千葉','確認選手','injury','26/09/01','26/10/01','2026','regular_2026_27','open',?)",(app.now(),)).lastrowid
   output=app.preview(c)
   self.assertFalse(any(row['player_name']=='確認選手' for row in output['rows']))
   self.assertIn('復帰見込み日を経過',next(row['reason'] for row in output['holds'] if row['id']==case_id))
   self.assertEqual(c.execute('SELECT status FROM cases WHERE id=?',(case_id,)).fetchone()[0],'open')

 def test_candidate_idempotence_return_and_reopen(self):
  body='''<title>山田太郎選手の負傷について</title><h1>山田太郎選手の負傷について</h1><p>山田太郎選手 診断結果</p><p>診断名</p><p>右膝半月板損傷</p><p>受傷日</p><p>2026年10月8日に負傷</p><p>全治</p><p>全治6〜8週間</p>'''
  url='https://www.sagan-tosu.net/news/p/999999/'
  with patch.object(app,'fetch',return_value=body):
   with app.db() as c:
    first=app.ingest(c,url)
    second=app.ingest(c,url)
    self.assertEqual(first['candidates_created'],1)
    self.assertEqual(second['candidates_created'],0)
    candidate=c.execute('SELECT * FROM candidates').fetchone()
    cid=candidate['id']
    self.assertEqual(candidate['start_date'],'2026-10-08')
    self.assertEqual(candidate['duration_min'],6)
    self.assertEqual(candidate['duration_max'],8)
    result=app.decide(c,{'candidate_id':cid,'action':'accept','team':'鳥栖','player':'山田太郎','expected_return_date':'26/12/01','origin_competition_key':'regular_2026_27'})
    case=c.execute('SELECT * FROM cases WHERE id=?',(result['case_id'],)).fetchone()
    self.assertEqual(case['start_date'],'26/10/08')
    with self.assertRaises(ValueError): app.decide(c,{'candidate_id':cid,'action':'accept'})
    app.change_case(c,{'id':case['id'],'version':case['version'],'action':'return','effective_date':'2026-10-24','reason':url,'checked':True})
    returned=c.execute('SELECT * FROM cases WHERE id=?',(case['id'],)).fetchone()
    self.assertEqual(returned['status'],'returned')
    app.change_case(c,{'id':case['id'],'version':returned['version'],'action':'reopen','reason':'復帰判断を訂正'})
    self.assertEqual(c.execute('SELECT status FROM cases WHERE id=?',(case['id'],)).fetchone()[0],'open')
    self.assertEqual(c.execute('SELECT count(*) FROM decisions WHERE case_id=?',(case['id'],)).fetchone()[0],3)

 def test_navigation_change_does_not_repeat_same_candidate(self):
  article='<title>山田太郎選手の負傷について</title><h1>山田太郎選手の負傷について</h1><p>診断名</p><p>右膝損傷</p><p>受傷日</p><p>2026年10月8日</p>'
  url='https://www.sagan-tosu.net/news/p/999998/'
  with patch.object(app,'fetch',side_effect=[article+'<aside>関連記事A</aside>',article+'<aside>関連記事B</aside>']):
   with app.db() as c:
    self.assertEqual(app.ingest(c,url)['candidates_created'],1)
    self.assertEqual(app.ingest(c,url)['candidates_created'],0)
    self.assertEqual(c.execute('SELECT count(*) FROM candidates').fetchone()[0],1)

 def test_csv_quotes_note(self):
  row={k:'' for k in app.COLS}
  row.update(season='2026',team='鳥栖',player_name='山田太郎',note='日本語,引用"あり"\n次行')
  data=app.csv_bytes([row])
  read=list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'),newline='')))
  self.assertEqual(read,[row])

 def test_manual_followup_is_candidate_then_evidence(self):
  with app.db() as c:
   case=c.execute("INSERT INTO cases(team,player,absence_type,status,created_at) VALUES('鳥栖','山田太郎','injury','open',?)",(app.now(),)).lastrowid
   result=app.manual_event(c,{'case_id':case,'kind':'full_training','event_date':'2026-10-24','excerpt':'全体練習への合流を利用者が確認'})
   self.assertTrue(result['created'])
   self.assertEqual(c.execute('SELECT status FROM cases WHERE id=?',(case,)).fetchone()[0],'open')
   app.decide(c,{'candidate_id':result['candidate_id'],'action':'accept','case_id':case,'version':1})
   self.assertEqual(c.execute('SELECT kind FROM evidence WHERE case_id=?',(case,)).fetchone()[0],'full_training')
   self.assertEqual(c.execute('SELECT status FROM cases WHERE id=?',(case,)).fetchone()[0],'open')

 def test_sqlite_backup_restores_cases_and_decisions(self):
  import sqlite3
  with app.db() as c:
   cid=c.execute("INSERT INTO cases(team,player,absence_type,status,created_at) VALUES('鳥栖','山田太郎','injury','open',?)",(app.now(),)).lastrowid
   app.change_case(c,{'id':cid,'version':1,'action':'return','effective_date':'2026-10-24','reason':'公式試合出場','checked':True})
  copy=app.DATA/'copy.sqlite3'
  with app.db() as c,sqlite3.connect(copy) as target:c.backup(target)
  with sqlite3.connect(copy) as restored:
   self.assertEqual(restored.execute('SELECT status FROM cases WHERE id=?',(cid,)).fetchone()[0],'returned')
   self.assertEqual(restored.execute('SELECT count(*) FROM decisions WHERE case_id=?',(cid,)).fetchone()[0],1)

 def test_jleague_and_club_articles_suggest_one_case_with_two_sources(self):
  club='https://www.frontale.co.jp/info/2026/1018_1.html'
  league='https://www.jleague.jp/news/article/35153/?navicode=j1'
  pages={
   club:'<title>野田裕人選手のケガについて | KAWASAKI FRONTALE</title><h1>野田裕人選手のケガについて</h1><p>10月3日に行われた試合で負傷した野田裕人選手。</p><p>診断結果</p><p>右腓腹筋肉離れ</p>',
   league:'<title>【公式】DF野田の負傷を発表【川崎Ｆ】 | Ｊリーグ公式サイト</title><h1>【公式】DF野田の負傷を発表【川崎Ｆ】</h1><p>川崎フロンターレは18日、DF野田 裕人の負傷を発表しました。</p><p>野田は3日に行われた試合で負傷し、右腓腹筋肉離れと診断されています。</p><a href="'+club+'">元記事</a>'
  }
  with patch.object(app,'fetch',side_effect=lambda url:pages[url]):
   with app.db() as c:
    app.ingest(c,club);app.ingest(c,league)
    a=app.rows(c,'SELECT * FROM candidates ORDER BY id')
    self.assertEqual(len(a),2)
    self.assertEqual(a[1]['team'],'川崎Ｆ')
    self.assertEqual(app.name_key(a[1]['player']),app.name_key(a[0]['player']))
    self.assertEqual(app.candidate_suggestions(c,a[1])['candidates'][0]['reasons'],['元記事への直接リンク'])
    first=app.decide(c,{'candidate_id':a[0]['id'],'action':'accept','team':'川崎Ｆ','player':'野田裕人'})
    suggestion=app.candidate_suggestions(c,a[1])['cases'][0]
    self.assertEqual(suggestion['case_id'],first['case_id'])
    self.assertIn('元記事への直接リンク',suggestion['reasons'])
    case=c.execute('SELECT version FROM cases WHERE id=?',(first['case_id'],)).fetchone()
    app.decide(c,{'candidate_id':a[1]['id'],'action':'accept','case_id':first['case_id'],'version':case['version'],'reason':'Jリーグ記事がクラブ元記事へ直接リンクしている'})
    self.assertEqual(c.execute('SELECT count(*) FROM cases').fetchone()[0],1)
    self.assertEqual(c.execute('SELECT count(*) FROM evidence').fetchone()[0],2)

 def test_merge_linked_duplicate_cases_keeps_history(self):
  club='https://www.frontale.co.jp/info/2026/1018_1.html'
  league='https://www.jleague.jp/news/article/35153/'
  pages={club:'<title>野田裕人選手のケガについて</title><h1>野田裕人選手のケガについて</h1><p>診断結果</p><p>右腓腹筋肉離れ</p>',league:'<title>【公式】DF野田の負傷を発表【川崎Ｆ】</title><h1>【公式】DF野田の負傷を発表【川崎Ｆ】</h1><p>DF野田 裕人の負傷を発表しました。</p><p>右腓腹筋肉離れと診断されています。</p><a href="'+club+'">元記事</a>'}
  with patch.object(app,'fetch',side_effect=lambda url:pages[url]):
   with app.db() as c:
    app.ingest(c,club);app.ingest(c,league)
    candidates=list(c.execute('SELECT * FROM candidates ORDER BY id'))
    to_id=app.decide(c,{'candidate_id':candidates[0]['id'],'action':'accept','team':'川崎Ｆ','player':'野田裕人'})['case_id']
    from_id=app.decide(c,{'candidate_id':candidates[1]['id'],'action':'accept','team':'川崎Ｆ','player':'野田 裕人'})['case_id']
    app.merge_cases(c,from_id,to_id,'同じ受傷と診断でJリーグ記事がクラブ原記事に直接リンク')
    self.assertEqual(c.execute('SELECT status FROM cases WHERE id=?',(from_id,)).fetchone()[0],'cancelled')
    self.assertEqual(c.execute('SELECT count(*) FROM evidence WHERE case_id=?',(to_id,)).fetchone()[0],2)
    self.assertEqual(c.execute('SELECT count(*) FROM decisions WHERE case_id=?',(from_id,)).fetchone()[0],2)
    self.assertEqual(c.execute('SELECT count(*) FROM case_merges').fetchone()[0],1)
    with self.assertRaises(ValueError):app.merge_cases(c,from_id,to_id,'再実行')

 def test_suspension_table_does_not_create_fake_player(self):
  title='【公式】出場停止選手のお知らせ（2026/10/26） | Ｊリーグ公式サイト'
  body='出場停止選手のお知らせ\n選手\nチーム\n佐藤 響\n京都\n出場停止試合'
  self.assertEqual(app.extract(body,title,'J1'),[])

 def test_held_candidate_can_resume_and_be_accepted(self):
  body='<title>山田太郎選手の負傷について</title><h1>山田太郎選手の負傷について</h1><p>診断名</p><p>右膝損傷</p>'
  with patch.object(app,'fetch',return_value=body):
   with app.db() as c:
    app.ingest(c,'https://www.sagan-tosu.net/news/p/999997/')
    cid=c.execute('SELECT id FROM candidates').fetchone()[0]
    app.decide(c,{'candidate_id':cid,'action':'hold','reason':'本文確認中'})
    self.assertEqual(c.execute('SELECT state FROM candidates WHERE id=?',(cid,)).fetchone()[0],'held')
    app.decide(c,{'candidate_id':cid,'action':'resume'})
    self.assertEqual(c.execute('SELECT state FROM candidates WHERE id=?',(cid,)).fetchone()[0],'pending')
    app.decide(c,{'candidate_id':cid,'action':'accept','team':'鳥栖','player':'山田太郎'})
    self.assertEqual(c.execute('SELECT state FROM candidates WHERE id=?',(cid,)).fetchone()[0],'accepted')

 def test_shonan_multi_player_article_is_split(self):
  title='渡邊啓吾選手・加瀬直輝選手 負傷に関するお知らせ'
  body='渡邊啓吾選手（FW）加瀬直輝選手（MF）が9月26日（土）試合中に負傷しました。\n渡邊啓吾選手\n◆負傷状況\n右大腿二頭筋肉離れ\n加瀬直輝選手\n◆負傷状況\n右足関節外側靭帯損傷'
  results=app.extract(body,title,'湘南')
  self.assertEqual([(x['player'],x['diagnosis']) for x in results],[('渡邊啓吾','右大腿二頭筋肉離れ'),('加瀬直輝','右足関節外側靭帯損傷')])

 def test_gamba_article_uses_article_heading_not_navigation(self):
  title='荒木 琉偉選手の怪我について｜ガンバ大阪オフィシャルサイト'
  body='荒木 琉偉選手の怪我について\n大量のナビゲーション\n荒木 琉偉選手の怪我について\n標記の件\n◇受傷日\n10/9（金）鹿島戦\n◇診断名\n左尺骨肘頭骨折\n関連ニュース\n別の記事'
  result=app.extract(body,title,'Ｇ大阪')
  self.assertEqual(len(result),1)
  self.assertEqual(result[0]['diagnosis'],'左尺骨肘頭骨折')
  self.assertEqual(result[0]['start_raw'],'10/9')
  self.assertNotIn('大量のナビゲーション',result[0]['excerpt'])

 def test_antlers_article_excerpt_starts_at_dated_article(self):
  title='安西 幸輝選手 負傷のお知らせ\n icon_home'
  body='安西 幸輝選手 負傷のお知らせ\nメニュー\n安西 幸輝選手 負傷のお知らせ\n2026.07.21(火)\n安西 幸輝選手が7月18日に負傷しました。\n診断名\n左膝前十字靭帯損傷\nicon_home\nニュース'
  result=app.extract(body,title,'鹿島')
  self.assertEqual(result[0]['diagnosis'],'左膝前十字靭帯損傷')
  self.assertNotIn('メニュー',result[0]['excerpt'])

 def test_archive_page_discovery_and_host_restriction(self):
  sagan='https://www.sagan-tosu.net/news/team/_/'
  links='<a href="/news/team/2026_9/">2026年9月</a><a href="https://evil.example/news/team/2026_8/">偽</a>'
  self.assertEqual(app.discover_archive_pages(sagan,links),[{'url':'https://www.sagan-tosu.net/news/team/2026_9/','label':'2026年9月'}])
  self.assertEqual(app.checked_list_url(sagan,'https://www.sagan-tosu.net/news/team/2026_9/'),'https://www.sagan-tosu.net/news/team/2026_9/')
  with self.assertRaises(ValueError):app.checked_list_url(sagan,'https://evil.example/news/team/2026_9/')
  with self.assertRaises(ValueError):app.checked_list_url(sagan,'https://www.sagan-tosu.net/admin/')

 def test_antlers_and_gamba_next_pages_are_restricted(self):
  antlers='https://www.antlers.co.jp/ja-world/blogs/news'
  self.assertEqual(app.discover_archive_pages(antlers,'<a href="?page=2">次へ</a>'),[{'url':antlers+'?page=2','label':'2ページ'}])
  self.assertEqual(app.checked_list_url(antlers,antlers+'?page=2'),antlers+'?page=2')
  with self.assertRaises(ValueError):app.checked_list_url(antlers,antlers+'?tag=other')
  gamba='https://www.gamba-osaka.net/news/index/c/1/'
  body='<select id="year"><option value="2026" selected>2026</option></select><select id="month"><option value="10" selected>10</option></select>'
  page='https://www.gamba-osaka.net/news/append/c/1/year/2026/month/10/p/1'
  self.assertEqual(app.discover_archive_pages(gamba,body),[{'url':page,'label':'2026年10月・続き1'}])
  self.assertEqual(app.discover_archive_pages(page,'<li>記事</li>'),[{'url':page[:-1]+'2','label':'2026年10月・続き2'}])
  self.assertEqual(app.discover_archive_pages(page,'<li>記事</li><!--end-->'),[])
  with self.assertRaises(ValueError):app.checked_list_url(gamba,'https://www.gamba-osaka.net/admin/')

 def test_gamba_article_urls_share_one_canonical_identity(self):
  expected='https://www.gamba-osaka.net/news/index/no/21103/'
  self.assertEqual(app.canonical('https://www.gamba-osaka.net/news/index/c/0/no/21103/'),expected)
  self.assertEqual(app.canonical('https://www.gamba-osaka.net/news/index/no/21103/c/1/year/2026/month/10/'),expected)

 def test_reysol_article_and_page_discovery(self):
  source='https://www.reysol.co.jp/news/topteam/'
  page='https://www.reysol.co.jp/news/topteam/index_2.html'
  body='<a href="post-1131.html">馬場 晴也選手の負傷について</a><a href="index_2.html">2</a>'
  self.assertEqual(app.discover_articles(source,body)[0]['url'],'https://www.reysol.co.jp/news/topteam/post-1131.html')
  self.assertEqual(app.discover_archive_pages(source,body),[{'url':page,'label':'2ページ'}])
  self.assertEqual(app.checked_list_url(source,page),page)
  title='馬場 晴也選手の負傷について｜お知らせ情報'
  article='馬場 晴也選手が、10月9日（金）の神戸戦で負傷し「右膝前十字靭帯断裂、外側半月板損傷」と診断されましたのでお知らせいたします。'
  extracted=app.extract(article,title,'柏')
  self.assertEqual((extracted[0]['player'],extracted[0]['diagnosis'],extracted[0]['start_raw']),('馬場 晴也','右膝前十字靭帯断裂、外側半月板損傷','10月9日'))

 def test_hiroshima_collection_excludes_regina_articles(self):
  source='https://www.sanfrecce.co.jp/news?news_category_id=1'
  body='<a href="/news/team/12626">浅野拓磨選手の負傷について</a><a href="/news/regina/12998">塩田満彩選手の怪我について</a>'
  self.assertEqual(app.discover_articles(source,body),[{'url':'https://www.sanfrecce.co.jp/news/team/12626','title':'浅野拓磨選手の負傷について'}])
  with app.db() as c:
   with self.assertRaises(ValueError):app.ingest(c,'https://www.sanfrecce.co.jp/news/regina/12998')

 def test_hiroshima_month_navigation_and_surgery_are_review_candidates(self):
  base='https://www.sanfrecce.co.jp/news?news_category_id=1'
  body='<select name="year"><option value="2026" selected="selected">2026年</option></select><select name="month"><option value="10" selected="selected">10月</option></select>'
  september='https://www.sanfrecce.co.jp/news?news_category_id=1&month=9&year=2026'
  self.assertEqual(app.discover_archive_pages(base,body),[{'url':september,'label':'2026年9月'}])
  self.assertEqual(app.checked_list_url(base,september),september)
  self.assertEqual(app.discover_archive_pages(september,''),[{'url':'https://www.sanfrecce.co.jp/news?news_category_id=1&month=8&year=2026','label':'2026年8月'}])
  with self.assertRaises(ValueError):app.checked_list_url(base,'https://www.sanfrecce.co.jp/news?news_category_id=9&month=9&year=2026')
  text='山﨑大地選手の手術について\n2026.09.10チーム\n山﨑大地選手が、左膝の手術を行いました。\n手術名\n前十字靭帯再建術\n全　治\n10ヶ月'
  extracted=app.extract(text,'山﨑大地選手の手術について','広島')
  self.assertEqual((extracted[0]['kind'],extracted[0]['player'],extracted[0]['duration_min']),('surgery','山﨑大地',10))
  self.assertEqual(app.possible_name_key('山﨑大地'),app.possible_name_key('山崎大地'))
  self.assertEqual(app.extract('大迫敬介選手が海外移籍準備後に再合流','大迫敬介選手 チーム再合流のお知らせ','広島'),[])

 def test_reysol_national_team_withdrawal_is_found_without_guessing_diagnosis(self):
  source='https://www.reysol.co.jp/news/topteam/'
  body='<a href="post-1125.html">熊坂 光希選手 日本代表を離脱</a>'
  self.assertEqual(app.discover_articles(source,body)[0]['url'],'https://www.reysol.co.jp/news/topteam/post-1125.html')
  article='熊坂 光希選手 日本代表を離脱\n日本代表に参加していた熊坂 光希選手が、9月28日（月）の試合で負傷し、代表チームを離脱することになりました。'
  result=app.extract(article,'熊坂 光希選手 日本代表を離脱｜お知らせ情報','柏')
  self.assertEqual((result[0]['player'],result[0]['start_raw'],result[0]['diagnosis']),('熊坂 光希','9月28日',''))

 def test_coverage_counts_only_observed_pages(self):
  source='https://www.reysol.co.jp/news/topteam/'
  page=source+'index_2.html'
  with app.db() as c:
   c.execute("INSERT INTO source_runs(source_id,list_url,started_at,finished_at,status,details_json) VALUES(?,?,?,?,?,?)",(11,source,app.now(),app.now(),'success',json.dumps({'archive_pages':[{'url':page,'label':'2ページ'}]})))
   summary=app.state_data(c)['source_coverage']['11']
   self.assertEqual((summary['checked_pages'],summary['found_unchecked_pages']),(1,1))
   self.assertEqual(summary['period_status'],'more_pages')
   c.execute("INSERT INTO source_runs(source_id,list_url,started_at,finished_at,status,details_json) VALUES(?,?,?,?,?,?)",(11,page,app.now(),app.now(),'success','{}'))
   summary=app.state_data(c)['source_coverage']['11']
   self.assertEqual((summary['checked_pages'],summary['found_unchecked_pages']),(2,0))
   self.assertEqual(summary['period_status'],'unverified_end')

 def test_coverage_shows_year_boundary_and_oldest_2026_date(self):
  source='https://www.zelvia.co.jp/news-category/topteam/'
  page=source+'page/16/'
  with app.db() as c:
   rid=c.execute('INSERT INTO source_runs(source_id,list_url,started_at,finished_at,status,details_json) VALUES(?,?,?,?,?,?)',(19,page,app.now(),app.now(),'success',json.dumps({'min_year':2026,'archive_year_stop':True,'published_dates':{'https://www.zelvia.co.jp/news/news-123/':'2026-01-04','https://www.zelvia.co.jp/news/news-122/':'2025-12-30'}}))).lastrowid
   for aid in (123,122):
    eid=c.execute('INSERT INTO list_entries(source_id,article_url,title) VALUES(?,?,?)',(19,f'https://www.zelvia.co.jp/news/news-{aid}/',f'記事{aid}')).lastrowid
    c.execute('INSERT INTO list_entry_sightings(entry_id,run_id,list_url) VALUES(?,?,?)',(eid,rid,page))
   summary=app.state_data(c)['source_coverage']['19']
   self.assertEqual((summary['period_status'],summary['oldest_publication_date'],summary['found_unchecked_pages']),('year_boundary','2026-01-04',0))

 def test_run_source_records_page_and_article_outcome(self):
  source='https://www.sagan-tosu.net/news/team/_/'
  archive='https://www.sagan-tosu.net/news/team/2026_9/'
  article='https://www.sagan-tosu.net/news/p/999999/'
  pages={archive:f'<a href="{article}">山田太郎選手の負傷について</a>',article:'<title>山田太郎選手の負傷について</title><h1>山田太郎選手の負傷について</h1><p>診断名</p><p>右膝損傷</p>'}
  with patch.object(app,'fetch',side_effect=lambda url:pages[url]):
   with app.db() as c:
    result=app.run_source(c,5,list_url=archive)
    self.assertEqual(result['status'],'success')
    self.assertEqual(result['found'],1)
    self.assertEqual(c.execute('SELECT list_url FROM source_runs').fetchone()[0],archive)
    self.assertEqual(c.execute('SELECT count(*) FROM candidates').fetchone()[0],1)

 def test_jleague_prognosis_article_keeps_range_and_unknown_year(self):
  title='【公式】MF知念が全治6〜8週間の負傷【横浜FM】 | Ｊリーグ公式サイト'
  body='横浜Ｆ・マリノスは23日、MF知念 慶が右足リスフラン関節損傷で全治6〜8週間の診断を受けたことを発表しました。\n知念は21日に行われた試合で負傷していました。\n関連リンク'
  result=app.extract(body,title,'J1')
  self.assertEqual(len(result),1)
  self.assertEqual((result[0]['team'],result[0]['player'],result[0]['diagnosis']),('横浜FM','知念 慶','右足リスフラン関節損傷'))
  self.assertEqual((result[0]['start_raw'],result[0]['start_date']),('21日',''))
  self.assertEqual((result[0]['duration_min'],result[0]['duration_max'],result[0]['duration_unit']),(6,8,'週'))

 def test_news_card_with_empty_anchor_text_is_discovered(self):
  body='''<article><div><h4>山田太郎選手の負傷について</h4><a href="https://www.v-varen.com/news/123.html"></a></div></article>'''
  found=app.discover_articles('https://www.v-varen.com/topteam_news',body)
  self.assertEqual(found,[{'url':'https://www.v-varen.com/news/123.html','title':'山田太郎選手の負傷について'}])

 def test_mito_injury_keeps_injury_day_separate_from_publication_day(self):
  title='鳥海芳樹選手の負傷について | 水戸ホーリーホック公式サイト'
  body='鳥海芳樹選手の負傷について\nトップチーム | 2026/10/18\n鳥海芳樹選手が、10月11日（日）の試合にて負傷しました。\n■診断名\n左半腱様筋肉離れ\nこのニュースをシェアする'
  found=app.extract(body,title,'水戸')
  self.assertEqual(len(found),1)
  self.assertEqual((found[0]['player'],found[0]['diagnosis'],found[0]['start_raw'],found[0]['start_date']),('鳥海芳樹','左半腱様筋肉離れ','10月11日',''))
  listing='<a href="/news/p=55378/">鳥海芳樹選手の負傷について</a>'
  self.assertEqual(app.discover_articles('https://www.mito-hollyhock.net/news_cat/topteam/',listing)[0]['url'],'https://www.mito-hollyhock.net/news/p=55378/')

 def test_nagoya_injury_uses_injury_field_instead_of_surgery_or_publication_date(self):
  title='浅野 雄也選手のけがについて｜ニュース｜名古屋グランパス公式サイト'
  body='2026.9.17\n◇受傷日\n9月6日（日）町田戦\n◇手術日\n9月7日（日）\n◇診断名\n右アキレス腱断裂\nカテゴリ\n'
  found=app.extract(body,title,'名古屋')
  self.assertEqual((found[0]['player'],found[0]['diagnosis'],found[0]['start_raw'],found[0]['start_date']),('浅野 雄也','右アキレス腱断裂','9月6日',''))
  source='https://nagoya-grampus.jp/news/pressrelease/'
  self.assertEqual(app.checked_list_url(source,source+'index_2.php'),source+'index_2.php')
  with self.assertRaises(ValueError):app.checked_list_url(source,'https://nagoya-grampus.jp/news/pressrelease/2026/0917post-2830.php')

 def test_iwata_manual_article_keeps_surgery_day_out_of_injury_date(self):
  self.assertEqual(app.source_for('https://jubilo-iwata.co.jp/news/topteam20261012infoM8q3Z'),('ジュビロ磐田','磐田'))
  title='上夷 克典選手の負傷について｜ジュビロ磐田'
  body='上夷 克典選手の負傷について\n上夷 克典選手が、右大腿直筋腱損傷により、10月8日(木)に手術を行いました。\n診断名\n右大腿直筋腱損傷\nトレーニング合流まで\n術後3～4ヶ月程度見込み\n一覧に戻る'
  found=app.extract(body,title,'磐田')
  self.assertEqual((found[0]['player'],found[0]['diagnosis'],found[0]['start_raw']),('上夷 克典','右大腿直筋腱損傷',''))

 def test_yamagata_article_uses_explicit_injury_date(self):
  title='熊本 雄太選手の負傷について | モンテディオ山形 オフィシャルサイト'
  body='公開日 2026.08.18\n熊本 雄太選手の負傷について\n受傷日：\n2026年8月14日（金）\nトレーニング中\n診断名：\n左大腿二頭筋肉離れ\n#チーム'
  found=app.extract(body,title,'山形')
  self.assertEqual((found[0]['player'],found[0]['diagnosis'],found[0]['start_raw'],found[0]['start_date']),('熊本 雄太','左大腿二頭筋肉離れ','2026年8月14日',''))
  source='https://www.montedioyamagata.jp/news/2026/team/'
  self.assertEqual(app.checked_list_url(source,source+'3/'),source+'3/')

 def test_toyama_article_keeps_approximate_injury_date_raw(self):
  title='深澤壯太選手の怪我について – カターレ富山公式ウェブサイト'
  body='深澤壯太選手の怪我について\nDF4 深澤壯太選手\n■診断名：両肩関節唇損傷\n■受傷日：9月下旬のトレーニング及び試合にて\n■全治：約6ヶ月\n※10月26日（月）に手術が終了しています。'
  found=app.extract(body,title,'富山')
  self.assertEqual((found[0]['player'],found[0]['diagnosis'],found[0]['start_raw'],found[0]['start_date']),('深澤壯太','両肩関節唇損傷','9月下旬のトレーニング及び試合にて',''))
  self.assertEqual((found[0]['duration_min'],found[0]['duration_unit']),(6,'ヶ月'))
  lower='https://www.kataller.co.jp/all/topteam/%e6%b7%b1%e6%be%a4/'
  upper='https://www.kataller.co.jp/all/topteam/%E6%B7%B1%E6%BE%A4/'
  self.assertEqual(app.canonical(lower),app.canonical(upper))

 def test_jleague_single_player_prognosis_uses_approximate_date_without_guessing_day(self):
  title='【公式】DF深澤が全治6か月の負傷【富山】 | Ｊリーグ公式サイト'
  body='カターレ富山は28日、DF深澤 壯太が両肩関節唇損傷で全治約6か月の診断を受けたことを発表しました。\n深澤は9月下旬に負傷し、10月26日に手術を行っています。'
  found=app.extract(body,title,'J1')
  self.assertEqual(len(found),1)
  self.assertEqual((found[0]['team'],found[0]['player'],found[0]['diagnosis'],found[0]['start_raw'],found[0]['start_date']),('富山','深澤 壯太','両肩関節唇損傷','9月下旬',''))
  self.assertEqual((found[0]['duration_min'],found[0]['duration_unit']),(6,'か月'))

 def test_batch_collection_continues_after_one_source_fails(self):
  with patch.object(app,'run_source',side_effect=[{'status':'failed','error':'offline','found':0,'attempted':0},{'status':'success','found':2,'attempted':2}] ) as runner:
   summary=app.collect_sources([1,2],pause=0)
  self.assertEqual((summary['sources'],summary['success'],summary['failed'],summary['found'],summary['attempted']),(2,1,1,2,2))
  self.assertEqual([call.args[1] for call in runner.call_args_list],[1,2])

 def test_archive_collection_follows_new_pages_and_ignores_other_hosts(self):
  source='https://www.v-varen.com/topteam_news'
  page2='https://www.v-varen.com/topteam_news/page/2/'
  page3='https://www.v-varen.com/topteam_news/page/3/'
  with app.db() as c:
   c.execute('INSERT INTO source_runs(source_id,list_url,started_at,status,details_json) VALUES(?,?,?,?,?)',(6,source,app.now(),'success',json.dumps({'archive_pages':[{'url':page2},{'url':'https://example.com/topteam_news/page/2/'}]})))
  def fake_run(c,sid,limit,list_url,min_year=None):
   further=[{'url':page3}] if list_url==page2 else []
   c.execute('INSERT INTO source_runs(source_id,list_url,started_at,status,details_json) VALUES(?,?,?,?,?)',(sid,list_url,app.now(),'success',json.dumps({'archive_pages':further})))
   return {'status':'success','list_url':list_url,'found':0,'attempted':0}
  with patch.object(app,'run_source',side_effect=fake_run) as runner:
   summary=app.collect_archives([6],max_pages=2,pause=0)
  self.assertEqual((summary['pages'],summary['success'],summary['failed']),(1,1,0))
  self.assertEqual([call.kwargs['list_url'] for call in runner.call_args_list],[page2])
  self.assertEqual(summary['results'][0]['remaining_discovered'],0)

 def test_archive_year_boundary_skips_old_month_and_undated_pages(self):
  self.assertEqual(app.archive_url_year('https://www.sagan-tosu.net/news/team/2025_12/'),2025)
  self.assertEqual(app.archive_url_year('https://www.sanfrecce.co.jp/news?news_category_id=1&month=12&year=2026'),2026)
  self.assertEqual(app.list_entry_year({'title':'2025年12月29日 土屋 巧選手 復帰','article_url':'https://www.reysol.co.jp/news/topteam/post-1024.html'}),2025)
  with app.db() as c:
   sid=c.execute("SELECT id FROM sources WHERE club='鳥栖'").fetchone()[0]
   src=c.execute('SELECT url FROM sources WHERE id=?',(sid,)).fetchone()[0]
   c.execute('INSERT INTO source_runs(source_id,list_url,started_at,status,details_json) VALUES(?,?,?,?,?)',(sid,src,app.now(),'success',json.dumps({'archive_pages':[{'url':'https://www.sagan-tosu.net/news/team/2025_12/'},{'url':'https://www.sagan-tosu.net/news/team/2026_1/'}]})))
   self.assertEqual([x['url'] for x in app.archive_queue(c,sid)],['https://www.sagan-tosu.net/news/team/2026_1/'])

 def test_vvaren_article_card_published_date_is_kept_separate_from_title(self):
  page='<article><aside>2026.06.28</aside><h4>例選手の負傷について</h4><a href="https://www.v-varen.com/news/243069.html"></a></article>'
  entries=app.discover_list_entries('https://www.v-varen.com/topteam_news/page/6/',page)
  self.assertEqual((entries[0]['title'],entries[0]['published_date']),('例選手の負傷について','2026-06-28'))
  self.assertEqual(app.list_entry_year(entries[0]),2026)

 def test_vvaren_2025_article_is_excluded_on_mixed_year_page(self):
  source='https://www.v-varen.com/topteam_news/page/14/'
  old='<article><aside>2025.12.30</aside><h4>旧選手の負傷について</h4><a href="https://www.v-varen.com/news/233000.html"></a></article>'
  new='<article><aside>2026.01.04</aside><h4>新選手の負傷について</h4><a href="https://www.v-varen.com/news/233001.html"></a></article>'
  entries=app.discover_list_entries(source,old+new)
  self.assertEqual([(x['url'],app.list_entry_year(x)) for x in entries],[('https://www.v-varen.com/news/233000.html',2025),('https://www.v-varen.com/news/233001.html',2026)])
  with patch.object(app,'fetch_source_page',return_value=old+new),patch.object(app,'ingest',return_value={'extracted':0,'candidates_created':0}) as fetch_article:
   with app.db() as c:result=app.run_source(c,6,limit=50,list_url=source,min_year=2026)
  self.assertEqual((result['found'],result['attempted'],result['status']),(1,1,'success'))
  self.assertEqual(fetch_article.call_args.args[1],'https://www.v-varen.com/news/233001.html')

 def test_zelvia_archive_uses_article_datetime_and_next_page(self):
  source='https://www.zelvia.co.jp/news-category/topteam/'
  page='<article id="post-123"><h2><a href="/news/news-123/">例選手の負傷について</a></h2><time datetime="2026-09-01 10:00">2026年9月1日</time></article>'
  entry=app.discover_list_entries(source,page)[0]
  self.assertEqual((entry['published_date'],app.list_entry_year(entry)),('2026-09-01',2026))
  self.assertEqual(app.discover_archive_pages(source,page)[0]['url'],source+'page/2/')
  self.assertEqual(app.discover_archive_pages(source+'page/2/',page)[0]['url'],source+'page/3/')
  self.assertEqual(app.checked_list_url(source,source+'page/2/'),source+'page/2/')
  self.assertEqual(app.checked_list_url(source,source+'page/10/'),source+'page/10/')

 def test_gamba_archive_uses_article_year_over_append_url_year(self):
  old={'title':'25.10.7［チーム］選手の怪我について','url':'https://www.gamba-osaka.net/news/index/no/19147/'}
  self.assertEqual((app.list_entry_date(old),app.list_entry_year(old)),('2025-10-07',2025))
  url='https://www.gamba-osaka.net/news/append/c/1/year/2026/month/10/p/47'
  self.assertEqual(app.archive_url_year(url),2026)
  with app.db() as c:
   rid=c.execute('INSERT INTO source_runs(source_id,list_url,started_at,status,details_json) VALUES(?,?,?,?,?)',(9,url,app.now(),'success',json.dumps({'archive_pages':[{'url':'https://www.gamba-osaka.net/news/append/c/1/year/2026/month/10/p/48'}]}))).lastrowid
   eid=c.execute('INSERT INTO list_entries(source_id,article_url,title) VALUES(?,?,?)',(9,old['url'],old['title'])).lastrowid
   c.execute('INSERT INTO list_entry_sightings(entry_id,run_id,list_url) VALUES(?,?,?)',(eid,rid,url))
   self.assertEqual(app.archive_queue(c,9),[])
  page='<a href="https://www.gamba-osaka.net/news/index/no/19147/">25.10.7［チーム］選手の怪我について</a>'
  with patch.object(app,'fetch_source_page',return_value=page),patch.object(app,'ingest') as ingest_article:
   with app.db() as c:result=app.run_source(c,9,limit=50,list_url=url,min_year=2026)
  self.assertEqual((result['found'],result['attempted']),(0,0))
  ingest_article.assert_not_called()

 def test_two_digit_archive_page_is_allowed(self):
  cases=[('https://nagoya-grampus.jp/news/pressrelease/','https://nagoya-grampus.jp/news/pressrelease/index_10.php'),('https://www.reysol.co.jp/news/topteam/','https://www.reysol.co.jp/news/topteam/index_10.html'),('https://www.fctokyo.co.jp/news/','https://www.fctokyo.co.jp/news/page/10/')]
  for source,page in cases:self.assertEqual(app.checked_list_url(source,page),page)

 def test_gamba_second_diagnosis_line_is_preserved(self):
  body='半田 陸選手の怪我について\n◇受傷日\n4/11（土）セレッソ大阪戦\n◇診断名\n左膝前十字靱帯損傷\n外側半月板損傷'
  found=app.extract(body,'半田 陸選手の怪我について','Ｇ大阪')
  self.assertEqual(found[0]['diagnosis'],'左膝前十字靱帯損傷、外側半月板損傷')

 def test_nagoya_duplicate_diagnosis_label_uses_medical_line(self):
  body='和泉 竜司選手のけがについて\n2026.2.12\n◇診断名\n2月8日（日）清水戦\n◇診断名\n右ハムストリング肉離れ\n◇検査内容\nMRI'
  found=app.extract(body,'和泉 竜司選手のけがについて','名古屋')
  self.assertEqual((found[0]['diagnosis'],found[0]['start_raw']),('右ハムストリング肉離れ','2月8日'))

 def test_reysol_injury_with_diagnosis_received_form(self):
  title='大久保 智明選手の負傷について｜お知らせ情報'
  body='2026年05月30日\n大久保 智明選手の負傷について\n大久保 智明選手が、5月27日（水）のトレーニング中に負傷し、「右アキレス腱断裂」の診断を受け、手術を行いましたのでお知らせいたします。'
  found=app.extract(body,title,'柏')
  self.assertEqual(len(found),1)
  self.assertEqual((found[0]['player'],found[0]['diagnosis'],found[0]['start_raw']),('大久保 智明','右アキレス腱断裂','5月27日'))


if __name__=='__main__': unittest.main()
