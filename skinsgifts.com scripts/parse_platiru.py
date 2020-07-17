import time
import datetime
import requests
import pymysql
import json
from requests.exceptions import ConnectionError
from xml.etree import ElementTree
import re

#скрипт пропускает uplay origin gog battle.net игры (только steam)

cur_year, cur_month = datetime.datetime.now().year, datetime.datetime.now().month
xml_selinfo = '''<digiseller.request>
  <guid_agent>DA536FD7C2E14445A6295D25B4F539AA</guid_agent>
  <lang>ru-RU</lang>
  <id_seller>{0}</id_seller>
</digiseller.request>'''
xml_myids = '''<digiseller.request>
  <category>
    <id>0</id>
  </category>
  <seller>
    <id>479531</id>
  </seller>
</digiseller.request>'''
BAD_SECTIONS = (21941, 22765, 22763, 22229, 21941, 22380, 22764)
ROMAN_NUMS = ('II', 'III','IV','V','VI','VII','VIII','IX')
ARAB_NUMS = ('2', '3', '4', '5', '6', '7', '8', '9')
episodes = r'\s[2-9](\s)?'

def main():
   ACCEPTABLE_WORDS = {'dlc', 'steam', 'gift', 'подарок', 'подарки', 'multilang', 'multi', 'reg', 'free', 'region', 'ru', 'cis',
                    'каждому', 'key', '/', 'бонус', 'акция', 'и', 'and', 'row', 'global', 'ua', 'глобал', 'activation', 'usa',
                    'активация', 'снг', 'по', 'акции', 'скидки', 'скидка', 'rucis', 'промо', 'код', '\\', 'multiplayer', 'eu',
                    'ключ', 'multilanguage', 'goty', 'россия', 'language', 'worldwide', 'дополнение', 'preorder', 'предзаказ',
                    'steamkey', 'regionfree', 'rus', 'бонусы', 'игра', 'за', 'отзыв', 'скидки', 'link', 'multilangs',
                    'активации', 'only', 'regfree', 'sale', 'game', 'of', 'the', 'year', 'vpn', 'steamgift'}
   sg_db, cursor = sql_connect()
   cursor.execute('SELECT name,id_goods,id,rrp FROM goods')
   tpls = cursor.fetchall()
   my_ids = get_myids(xml_myids)
   for tpl in tpls:
      game_accepted = False
      orig_gname = tpl[0]
      id_goods = int(tpl[1])
      id = tpl[2]
      rrp = tpl[3].replace(',', '.')
      if id_goods in my_ids: #проверить какой тип id-а возвращает xml
        continue
      gname = convert_romans(orig_gname)
      print('игра: ', orig_gname)
      r = request('get', orig_gname)
      try:
        items = r.json()['items']
      except json.decoder.JSONDecodeError:
        print('json error')
        items = None
      if not items:
        print('no items')
        if id_goods != 0:
          set_zero(cursor,id)
        continue
      for i in sorted(items, key = lambda i: float(i['price_rur'])):
        if i['section_id'] in BAD_SECTIONS:
          continue
        if i['price_rur'] >= float(rrp):
          continue
        #print(i['name'], i['partner_commiss'], i['price_rur'])
        gname_plati = convert_romans(i['name'])
        gname_plati = delabbr(gname, gname_plati)
        if '+' in gname_plati:                                                   # отделить основную игру от бонусов
          gname_plati = gname_plati.partition('+')[0]
        if re.search(episodes, gname) and  not re.search(episodes, gname_plati): # пропустить сразу же игры в которых эпизод ранее заданной игры. Пример: Arma 3 и Arma.
          continue
        reg_exp = re.search(r'(\d)+((\s)?in(\s)?|(\s)?в(\s)?)1', gname_plati)   # удалить словосочетания типа dig in dig
        if reg_exp:
          gname_plati = gname_plati.replace(reg_exp.group(), '')
        gname_set = set(gname.split())
        gname_plati_set = set(gname_plati.split())
        if not gname_plati_set.difference(gname_set).issubset((ACCEPTABLE_WORDS)):
          continue
        if float(i['partner_commiss']) >= 1:
          id_plati = i['url'].partition('=')[2]
          if int(id_plati) == id_goods:
            print('ids are equal, missing')
            game_accepted = True
            break
          else:
            print('Игра выбрана: ', i['name'], i['price_rur'])
            game_accepted = True
            while True:
              try:
                cursor.execute("UPDATE goods SET id_goods = '{0}' WHERE id = '{1}' LIMIT 1".format(id_plati, id))
                break
              except pymysql.err.OperationalError as err:
                print(err)
                sg_db, cursor = sql_connect()
                continue
            break
    
      if game_accepted == False:
        if id_goods != 0:
          set_zero(cursor,id)
      sg_db.commit()
   sg_db.close()

def set_zero(cursor, id):
  cursor.execute("UPDATE goods SET id_goods = '0' WHERE id = '{0}' LIMIT 1".format(id))

def convert_romans(gname):
  if "'" in gname or "’" in gname:
    gname = re.sub(r"['’]", '', gname) # избавиться от ковычек без оставления пробела
  gname_spl = re.sub("[{0}]".format(re.escape("-*.\\[]|,&/®™+()_:;!")), ' ', gname).split() # убрать лишние символы для сверки
  for n, num in enumerate(ROMAN_NUMS):
    if num in gname_spl:
        gname_spl[gname_spl.index(num)] = ARAB_NUMS[n]
  return ' '.join(gname_spl).lower()

def delabbr(gname, gname_plati):
  #удалить сокращения с названия игры
  gname_abbr = ''.join([i[0] for i in gname.split() if not i.isdigit()])
  for i in gname_plati.split():
    if re.search(i, gname_abbr):
      gname_plati = gname_plati.replace(i, '')
  return gname_plati

def seller_reg(p):
   tree = ElementTree.fromstring(p.text)
   for elem in tree.iter('date_registration'):
      reg = [int(n) for n in elem.text.split('.')]
   reg = list(reversed(reg))
   reg_year, reg_month = datetime.date(*reg).year, datetime.date(*reg).month
   return reg_year, reg_month
   
def request(method, data):
   while True:
      try:
         if method == 'get':
            r = requests.get('http://www.plati.com/api/search.ashx', params = {'query': data, 'response': 'json'})
         elif method == 'post':
            r = requests.post('http://www.plati.com/xml/seller_info.asp', headers = {'Content-Type': 'application/xml'},
                                    data = xml_selinfo.format(data))
         break
      except ConnectionError as err:
         print(err)
         continue
   return r

def sql_connect():
  sg_db = pymysql.connect(host = 'gladys.timeweb.ru', db = 'ca20857_db', port = 3306,
                          passwd = '0K5KIfRd', user = 'ca20857_db', charset = 'utf8')
  cursor = sg_db.cursor()
  return sg_db, cursor

def get_myids(xml_myids):
  dig_ids = []
  r = requests.post('http://shop.digiseller.ru/xml/shop_products.asp', headers={'Content-Type': 'application/xml'}, data=xml_myids)
  parsed_xml = ElementTree.fromstring(r.text)
  for child in parsed_xml[6][2:]:
    dig_ids.append(child[0].text)
  return dig_ids

main()

