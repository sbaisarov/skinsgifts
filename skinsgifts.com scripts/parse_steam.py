#заменить словарь значений на простой вызов функции в кортеже VALUES

import requests
from requests.exceptions import ConnectionError
from requests.utils import cookiejar_from_dict
import pymysql
from bs4 import BeautifulSoup
import io
import ftplib
import re

session = requests.session()
cj = cookiejar_from_dict({'mature_content': '/app/381210', 'birthtime': '662670001', 'Steam_Language': 'russian'})
session.cookies = cj
ROMAN_NUMS = ('II', 'III','IV','V','VI','VII','VIII','IX')
ARAB_NUMS = ('2', '3', '4', '5', '6', '7', '8', '9')

def main():
	COLUMNS = ('name', 'url_name', 'activation', 'img', 'screenshot', 'description', 
				'region', 'preorder', 'preorder_bonus', 
				'dlc', 'dlc_main', 'reliz', 'genre', 'language', 'rrp', 
				'platform', 'rezhim', 'youtube', 'title', 'desc_seo', 'keywords', 
				'includes', 'operac', 'proc', 'memory', 'hdd', 'video',
           		'operac_mac', 'proc_mac', 'memory_mac', 'hdd_mac', 'video_memory_mac', 
           		'operac_linux', 'proc_linux', 'memory_linux', 'hdd_linux', 
           		'video_memory_linux', 'ea_comms', 'pack_comps')
	sg_db, cursor = sql_connect()
	ftp_session = ftp_connect()
	cursor.execute('SELECT name FROM goods')
	db_gnames = set((i[0] for i in cursor.fetchall()))
	added_games = set()
	try:
		for i in range(1, 50):
			r = request(session = session, link = 'http://store.steampowered.com/search/?filter=topseller&page={0}&cc=ru'.format(i))
			s = BeautifulSoup(r.text, 'html.parser')
			try:
				container = s.find(id = 'search_result_container').find_all('div')[1]
			except IndexError:
				container = s.find(id = 'search_result_container').find_all('div')[0]
			items = container.find_all('a')
			for item in items:
				link = item['href']
				gname = item.find(class_ = 'title').text
				url_gname = convert_romans(gname).replace(" ", "-")
				if gname in (db_gnames or added_games):
					continue
				price = get_price(item)
				if not price:
					continue
				print(gname)
				r = request(session = session, link = link)
				s = BeautifulSoup(r.text, 'html.parser')
				main_img, screenshot = get_imgs(ftp_session, gname, s)
				if not main_img:
					continue
				region = 'РФ + СНГ'
				desc_seo = ('Купить ключ игры {0} по низкой цене и с мгновенной доставкой. '
							'{1} - скриншоты, описание, видео, отзывы.'.format(gname, gname ))
				title = 'Купить ключ игры {0} дешево в интернет-магазине Skinsgifts.com'.format(gname)
				keywords = 'купить ключ {0}, купить игру {1}'.format(gname, gname)
				data = parse_item(s)
				video = youtube_req(gname)
				values = (gname, url_gname, 'Steam', main_img, screenshot, data.get('description', ''), region, data.get('preorder', ''), data.get('preorder_bonus', ''), data.get('dlc', ''), data.get('dlc_main', ''), 
						  data.get('date_release', ''), data.get('genre', ''), data.get('language', ''), price, data.get('platforms', ''), data.get('modes', ''),
						  video, title, desc_seo, keywords, data.get('tags', ''), data['sys_reqs']['Windows'].get('OS', ''), 
						  data['sys_reqs']['Windows'].get('processor', ''), data['sys_reqs']['Windows'].get('memory', ''), data['sys_reqs']['Windows'].get('hdisk', ''),
						  data['sys_reqs']['Windows'].get('videocard', ''), data['sys_reqs']['Mac'].get('OS', ''), data['sys_reqs']['Mac'].get('processor', ''), 
						  data['sys_reqs']['Mac'].get('memory', ''), data['sys_reqs']['Mac'].get('hdisk', ''), data['sys_reqs']['Mac'].get('videocard', ''), 
						  data['sys_reqs']['Linux'].get('OS', ''), data['sys_reqs']['Linux'].get('processor', ''), data['sys_reqs']['Linux'].get('memory', ''),
						  data['sys_reqs']['Linux'].get('hdisk', ''), data['sys_reqs']['Linux'].get('videocard', ''), data.get('ea_comms', ''), data.get('pack_comps', ''))
				statement = 'INSERT INTO goods ({0}) VALUES ({1})'.format(', '.join(COLUMNS), ', '.join(('%s' for i in range(39))))
				while True:
					try:
						cursor.execute(statement, values)
						break
					except pymysql.err.OperationalError:
						sg_db, cursor = sql_connect()
						continue
				added_games.add(gname)
				sg_db.commit()
	finally:
		sg_db.close()


def parse_item(s):
	data = {}
	data['pack_comps'] = get_pack(s)
	data['language'] = get_lang(s)
	data['genre'] = get_genre(s)
	data['date_release'] = correct_date(s)
	if s.find(class_ = 'glance_tags popular_tags'):
		data['tags'] = ';'.join([tag.text.strip()  \
						for tag in s.find(class_ = 'glance_tags popular_tags').find_all('a')][:5])
	else:
		data['tags'] = ''
	data['modes'], data['controller'] = get_modes(s)
	data['description'] = get_description(s)
	data['platforms'] = get_platforms(s)
	data['sys_reqs'] = get_sysreqs(s, data['platforms'])
	data['preorder'], data['preorder_bonus'] = get_preorder(s)
	data['dlc'], data['dlc_main'] = get_dlc(s)
	data['ea_comms'] = get_ea(s)
	data['pack_comps'] = get_pack(s)
	return data

def get_price(item):
	free_games = ('Бесплатно','Free to Play','Играйте бесплатно!', 'Бесплатная игра')
	price = ''
	elem = item.find(class_= 'col search_price responsive_secondrow')
	if not elem:
		elem = item.find(class_= 'col search_price discounted responsive_secondrow').strike
	if elem.text.strip() not in free_games:
		price = elem.text.strip().strip(' .pуб')
	return price

def correct_date(s):
	corrected_date = ''
	date = None
	element = s.find(class_ = 'date')
	if element:
		date = element.text
	else:
		element = s.find('b', text='Дата выхода:')
		if element:
			date = element.parent.find('b', text='Дата выхода:').nextSibling.strip()
	if not date:
		return ''
	str_months = ('янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек')
	int_months = ('01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11', '12')
	date_lst = date.split()
	if len(date_lst) > 1:
		if date_lst[1].strip('.') in str_months:
			date_lst[1] = int_months[str_months.index(date_lst[1].strip('.'))]
			corrected_date = '.'.join(date_lst)
	return corrected_date

def get_modes(s):
	controller = ''
	modes = []
	elements = set((elem.find_all('a')[1].text for elem in s.find_all(class_ = 'game_area_details_specs')))
	if 'Для одного игрока' in elements:
		modes.append('Сингл')
	if not {'Для нескольких игроков','Online Multi-Player'}.isdisjoint(elements):
		modes.append('Мультиплеер')
	if 'Совместное прохождение' in elements:
		modes.append('Кооператив')
	if not {'Контроллер (частично)', 'Контроллер (полностью)'}.isdisjoint(elements):
		controller = '1'
	modes = ', '.join(modes)
	return modes, controller

def get_lang(s):
	details = []
	talbe = s.find(class_ = 'game_language_options')
	if not talbe:
		return ''
	rus_lang_table = s.find_all('tr')[1]
	if rus_lang_table.find_all('td')[1].text.strip() == 'Не поддерживается':
		return 'Английский'
	checkcols = rus_lang_table.find_all('td')
	if checkcols[1].img:
		details.append('интерфейс')
	if checkcols[2].img:
		details.append('озвучка')
	if checkcols[3].img:
		details.append('cубтитры')
	language = 'Русский ({0})'.format(', '.join(details[:2]))
	return language

def get_platforms(s):
	platforms = []
	if s.find(attrs = {'data-os': 'win'}):
		platforms.append('Windows')
	if s.find(attrs = {'data-os': 'mac'}):
		platforms.append('Mac')
	if s.find(attrs = {'data-os': 'linux'}):
		platforms.append('Linux')
	platforms  = ', '.join(platforms)
	return platforms

def get_description(s):
	description = ''
	descr_area = s.find(id = 'game_area_description')
	if descr_area:
		foo = [str(i) for i in descr_area.contents[2:]]
		description = ''.join(foo)
	return description

def get_preorder(s):
	preorder = ''
	preorder_bonus = ''
	if s.find(class_ = 'game_area_comingsoon game_area_bubble'):
		preorder = '1'
		area = s.find(class_= 'game_area_description')
		if area.h2.text == 'Специальное предложение при предзаказе':
			preorder_bonus = str(area.p)
	return preorder, preorder_bonus

def get_dlc(s):
	dlc = ''
	dlc_main = ''
	element = s.find(class_ = 'game_area_dlc_bubble game_area_bubble')
	if element:
		dlc = '1'
		dlc_main = element.a.text
	return dlc, dlc_main

def get_ea(s):
	ea_comms = ''
	if s.find(class_='early_access_header'):
		app_id = ''.join(filter(lambda x: x.isdigit(), s.find(id='ReportAppBtn')['onclick']))
		ea_comms = ("http://steamcommunity.com/app/{0}/reviews/"
				    "?browsefilter=trendmonth&filterLanguage=russian".format(app_id))
	return ea_comms

def get_pack(s):
	pack_comps = []
	if s.find(id = 'package_header_container'):
		gnames = s.find_all(class_ = 'tab_item_name')
		for i in gnames:
			pack_comps.append(i.text)
		return ';'.join(pack_comps)
	else:
		return ''

def get_genre(s):
	genre = ''
	genre_block = s.find('b', text='Жанр:')
	if genre_block:
		genre = genre_block.parent.a.text.replace('Приключенческие игры', 'Приключения') or genre_block.parent.find('b', text='Жанр:').nextSibling.nextSibling.text.replace('Приключенческие игры', 'Приключения')
	return genre

def get_sysreqs(s, platforms):

	def parse_table(reqs):
		platform = {}
		OS = reqs.find('strong', text = 'ОС:') or \
		          reqs.find('strong', text = 'OS:')
		processor = reqs.find('strong', text = 'Процессор:') or \
				  reqs.find('strong', text = 'Processor:')
		memory = reqs.find('strong', text = 'Оперативная память:') or \
				  reqs.find('strong', text = 'Memory:')
		videocard = reqs.find('strong', text = 'Видеокарта:') or \
				  reqs.find('strong', text = 'Graphics:')
		hdisk = reqs.find('strong', text = 'Место на диске:') or \
				  reqs.find('strong', text = 'Hard Drive:')
		if OS:
			platform['OS'] = OS.parent.contents[1].strip()
		if processor:
			platform['processor'] = processor.parent.contents[1].strip()
		if memory:
			platform['memory'] = memory.parent.contents[1].strip()
		if videocard:
			platform['videocard'] = videocard.parent.contents[1].strip()
		if hdisk:
			platform['hdisk'] = hdisk.parent.contents[1].strip()
		return platform

	windows = {}
	mac = {}
	linux = {}
	sysreq_html = s.find(class_ = 'sysreq_contents')
	if 'Windows' in platforms:
		reqs = sysreq_html.find(attrs = {'data-os' : 'win'})
		windows = parse_table(reqs)
	if 'Mac' in platforms:
		reqs = sysreq_html.find(attrs = {'data-os' : 'mac'})
		mac = parse_table(reqs)
	if 'Linux' in platforms:
		reqs = sysreq_html.find(attrs = {'data-os' : 'linux'})
		linux = parse_table(reqs)
	return {'Windows': windows, 'Mac': mac, 'Linux': linux}

def get_screenshot(s, ftp_session):
	screenshot = ''
	imgs_area = s.find_all(class_ = 'highlight_screenshot_link')
	if imgs_area:
		imgs = []
		for i in imgs_area[:8]:
			imgs.append(i['href'])
		screenshot = ftp(ftp_session, gname, imgs)
	return screenshot

def get_imgs(ftp_session, gname, s):
	main_img = ''
	screenshot = ''
	elem = s.find(class_ =  'game_header_image_full')
	if not elem:
		elem = s.find(class_ = 'package_header')
	if elem:
		main_img = ftp(ftp_session, gname, elem['src'])
	imgs_area = s.find_all(class_ = 'highlight_screenshot_link')
	if imgs_area:
		imgs = []
		for i in imgs_area[:8]:
			imgs.append(i['href'])
		screenshot = ftp(ftp_session, gname, imgs)
	return main_img, screenshot

def convert_romans(gname):
	if "'" in gname or "’" in gname:
		gname = re.sub(r"['’]", '', gname) # избавиться от ковычек без оставления пробела
	gname_spl = re.sub("[{0}]".format(re.escape("®:'-–;_/.*«»|[]+&,’™")), ' ', gname).split()
	for n, num in enumerate(ROMAN_NUMS):
	  if num in gname_spl:
	     gname_spl[gname_spl.index(num)] = ARAB_NUMS[n]
	return ' '.join(gname_spl).lower()

def ftp(session, gname, images):
   def storbin(session, link, descriptor):
      while True:
         try:
            r = requests.get(link, stream = True, timeout = 60)
            break
         except TimeoutError or EnvironmentError:
            continue

      r.encoding = 'UTF-8'
      f = io.BytesIO(r.content)
      link = '{0}_{1}.jpg'.format(gname.replace(' ', '_').lower(), descriptor)

      while True:
	      try:
	      	session.storbinary('STOR {0}'.format(link), f)
	      	break
	      except ftplib.error_temp:
	      	session = ftp_connect()
	      	continue
      return link

   for char in gname:
         if ord(char) not in range(0, 127) or char == "'" or char == '/': # символ ковычки некорректно читается в sql запросах в php программах
            gname = gname.replace(char, '')
            
   if type(images) == str: # если строка то одна картинка
         link = storbin(session, images, 'main')
         return '/upload/images/' + link
   elif type(images) == tuple or type(images) == list: # если кортеж то картинок несколько
      images_skinsgifts = set()
      for n, link in enumerate(images):
         link = storbin(session, link, n)
         images_skinsgifts.add('/upload/images/' + link)
      return ';'.join(images_skinsgifts)
   else:
      return ''

def youtube_req(gname):
	gname_spl = convert_romans(gname).split()
	video = ''
	req = request(link = r'https://www.googleapis.com/youtube/v3/search', params = {'q': '{0} обзор игры'.format(gname), 'part': 'snippet', 'key': 'AIzaSyCFBCs-Y7nm9sQYmDuxItcpwDwmzzroBGw',
			                                                                                             'maxResults': 10, 'type': 'video', 'relevanceLanguage': 'ru'})

	if req.json().get('items') is not None:
		statistics = []
		videoids = ','.join((elem['id']['videoId'] for elem in req.json()['items']))
		req2 = request(link = 'https://www.googleapis.com/youtube/v3/videos', 
			                params = {'key': 'AIzaSyCFBCs-Y7nm9sQYmDuxItcpwDwmzzroBGw', 'part': 'statistics', 'id': '{0}'.format(videoids)})
		for i in req2.json()['items']:
			vcount = int(i['statistics']['viewCount'])
			try:
				likes = int(i['statistics']['likeCount'])
				dislikes = int(i['statistics']['dislikeCount'])
			except KeyError:
				likes = 0
				dislikes = 0
			statistics.append((vcount, likes, dislikes))
		for elem in sorted(zip(req.json()['items'], statistics), key = lambda elem: elem[1][0], reverse = True) :
			item = elem[0]
			likes = elem[1][1]
			dislikes = elem[1][2]
			total = likes + dislikes
			if total == 0:
				continue
			else:
				if dislikes/(likes+dislikes) >= 0.3:
					continue
			yb_vid = item['id']['videoId']
			yb_vid_spl = convert_romans(item['snippet']['title']).split()
			lang_relev = {'обзор', 'геймплей'}.isdisjoint(set(yb_vid_spl))
			if lang_relev:
				lang_relev = {'review', 'gameplay'}.isdisjoint(set(yb_vid_spl))
			if set(gname_spl).issubset(set(yb_vid_spl)) and not lang_relev:
				video = yb_vid
	return video

def request(session = None, link = None, params = None):
	while True:
		try:
			if params:
				r = requests.get(link, params)
			else:
				r = session.get(link)
			break
		except ConnectionError:
			continue
	return r

def sql_connect():
	sg_db = pymysql.connect(host = 'gladys.timeweb.ru', db = 'ca20857_db', port = 3306,
							passwd = '0K5KIfRd', user = 'ca20857_db', charset = 'utf8')
	cursor = sg_db.cursor()
	return sg_db, cursor

def ftp_connect():
	ftp_session = ftplib.FTP('176.57.209.92', 'ca20857', 'g5~}CFOS8[GH')
	ftp_session.cwd(r'/public_html/upload/images')
	return ftp_session

main()