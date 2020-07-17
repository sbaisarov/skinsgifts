import pymysql
import xml.etree.ElementTree as ET

sg_db = pymysql.connect(host = 'gladys.timeweb.ru', db = 'ca20857_db', port = 3306,
						passwd = '0K5KIfRd', user = 'ca20857_db', charset = 'utf8')
cursor = sg_db.cursor()
cursor.execute('SELECT url_name FROM goods')
url_names = {i[0] for i in cursor.fetchall()}
ET.register_namespace('', "http://www.sitemaps.org/schemas/sitemap/0.9")
sitemap = ET.parse('sitemap.xml')
root = sitemap.getroot()
for url in url_names:
	element = ET.fromstring('<url>\n\t\t<loc>http://skinsgifts.com/product/{0}/</loc>\n\t</url>\n'.format(url))
	root.append(element)
sitemap.write('sitemap.xml', encoding='utf-8')
sg_db.close()