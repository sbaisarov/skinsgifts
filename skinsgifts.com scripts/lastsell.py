import datetime
import re
import pymysql
import requests
from requests.utils import cookiejar_from_dict
from bs4 import BeautifulSoup

#куки непостоянны, отсюда сессия сбивается. Попробовать https://api.digiseller.ru/Help/Api/POST-api-login

sg_db = pymysql.connect(host = 'gladys.timeweb.ru', db = 'ca20857_db', port = 3306,
						passwd = '0K5KIfRd', user = 'ca20857_db', charset = 'utf8')
cursor = sg_db.cursor()
cursor.execute('SELECT time FROM lastsell')
time_set = tuple((float(i[0]) for i in cursor.fetchall()))
session = requests.session()
session.cookies = cookiejar_from_dict({'ASPSESSIONIDASDRTTRQ': 'OPGHFCADPCOMKHKCKBLGFPCK'})
r = session.get('https://my.digiseller.ru/inside/account.asp', auth = ('Shamanovsky', 'C9149CDFDC'))
r.encoding = 'windows-1251'
s = BeautifulSoup(r.text, 'html.parser')
rows = s.find_all('tr')

for i in rows:
	break
	partner_sale = i.find(string= re.compile('\s*партнерские начисления\s*'))
	if partner_sale:
		columns = i.find_all('td')
		gname = columns[1].text.strip()
		d = [int(i) for i in columns[3].text.strip().replace(':', '.').replace(' ','.').split('.')]
		datetime_obj = datetime.datetime(d[2], d[1], d[0], hour = d[3], minute = d[4], second = d[5])
		date = datetime.datetime.timestamp(datetime_obj)
		if date not in time_set:
			statement = "SELECT id_goods FROM goods WHERE name_digi = %s LIMIT 1"
			cursor.execute(statement, gname)
			id_goods = cursor.fetchone()
			print(gname)
			print(id_goods)
			if id_goods:
				cursor.execute("INSERT INTO lastsell (id_goods, time) VALUES ('{0}', '{1}')".format(id_goods[0], date))
				sg_db.commit()
sg_db.close()