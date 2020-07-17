#столбцы в db: new, popular
import pymysql
from bs4 import BeautifulSoup
import requests
from requests.exceptions import ConnectionError
import datetime

sg_db = pymysql.connect(host = 'gladys.timeweb.ru', db = 'ca20857_db', port = 3306,
	                         passwd = '0K5KIfRd', user = 'ca20857_db', charset = 'utf8')
cursor = sg_db.cursor()
cursor.execute('SELECT name,reliz,popular,id FROM goods')
data = cursor.fetchall()
top_games = []
for i in range(5):
	r = requests.get('http://store.steampowered.com/search/?filter=topsellers&page={0}&cc=ru'.format(i))
	s = BeautifulSoup(r.text, 'html.parser')
	container = s.find(id = 'search_result_container')
	items = container.find_all(class_= 'title')
	for item in items:
		top_games.append(item.text)
for tpl in data:
	db_gname = tpl[0]
	popular = tpl[2]
	id = tpl[3]
	if db_gname not in top_games and popular == 1:
		cursor.execute("UPDATE goods SET popular='0' WHERE id='{0}' LIMIT 1".format(id))
		continue
	if db_gname in top_games:
		cursor.execute("UPDATE goods SET popular='1' WHERE id='{0}' LIMIT 1".format(id))
for tpl in data:
	db_reliz = tpl[1]
	id = tpl[3]
	if not db_reliz:
		continue
	db_reliz_spl = [int(i) for i in db_reliz.split('.')]
	db_reliz_obj = datetime.date(db_reliz_spl[2], db_reliz_spl[1], db_reliz_spl[0])
	delta = datetime.date.today() - db_reliz_obj
	if delta.days < 30:
		cursor.execute("UPDATE goods SET new='1' WHERE id='{0}' LIMIT 1".format(id))
sg_db.commit()
sg_db.close()