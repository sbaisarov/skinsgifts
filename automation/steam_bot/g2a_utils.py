import re
import time
import logging
import json
import math
import shelve
import requests
import sqlite3
from win32crypt import CryptUnprotectData
from bs4 import BeautifulSoup

# some g2a game names are different from the ones from Steam

logger = logging.getLogger(__name__)

class FailedSessionException(Exception): pass

class AutomatedG2A:

	# user agent must always be updated for a proper work with g2a
	USER_AGENT = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
	'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/57.0.2987.133 Safari/537.36'}

	G2A_CATEGORIES = (
	'steam cd-key global',
	'cd-key steam global',
	'early access steam cd-key global',
	'steam early access cd-key global',
	'dlc steam cd-key global',
	'early access dlc steam cd-key global',
	'steam cd-key preorder global'
	)

	def __init__(self, db_path):
		self.g2a_db = shelve.open(db_path)
		self.session = self._create_session()
		self.current_sales = self.get_current_sales()

	def find_profitable_gifts(self, wallet_amount, is_final_purchase=False):
		total_cost = 0
		items_ctr = 0
		profitable_gifts = []
		steam_items = self._steam_games_generator(is_final_purchase)

		while True:
			try:
				cur_rate = requests.get('http://api.fixer.io/latest?base=NOK').json()['rates']
				break
			except json.decoder.JSONDecodeError as err:
				print('currency api error:', err)

		for gname, steam_price, app in steam_items:
			# stop searching if 24 or less amount of money left
			# or amount of items reached 8
			if wallet_amount - total_cost < 24 or items_ctr == 8:
				break

			if total_cost + steam_price > wallet_amount:
				continue

			item_id, item_name = self._get_g2a_appid(gname)
			if not item_id:
				logger.info("couldn't find the game on g2a: " + gname)
				continue

			is_cheapest_region = self._assure_norway_is_cheapest(
										app, steam_price, cur_rate)
			if not is_cheapest_region:
				logger.info('The price in the norwegian region is not the cheapest: ' + gname)
				continue

			g2a_min_price = self.get_lowest_price(item_id) # convert to nok
			if not g2a_min_price:
				logger.info('No sales found for: ' + gname)
				continue
			g2a_min_price /= cur_rate['EUR']
			if g2a_min_price > steam_price * 1.05:
				profitable_gifts.append((app, steam_price))
				total_cost += steam_price
				items_ctr += 1

		return profitable_gifts, total_cost


	def get_lowest_price(self, item_id):
		g2a_min_price = None
		while True:
			try:
				resp = requests.get('https://www.g2a.com/marketplace/product/auctions/?id=' + item_id,
									headers=self.USER_AGENT, cookies={'currency': 'EUR'}).json()
				break
			except json.decoder.JSONDecodeError:
				pass
		if not resp.get('a', None):
			return g2a_min_price
		try:
			g2a_min_price, seller = min((float(i['f'].replace(',', '.').rstrip(' €')), i.get('cname', None))
							     		 for i in resp['a'].values() if i['tr'] > 100)
			if seller == 'Skinsgifts':
				# add 0.11 to avoid self overbidding
				g2a_min_price += 0.11

		except ValueError:
			logger.info('there are no sellers with a high rating')

		return g2a_min_price


	def upload_gifts(self, gname, keys):
		keys = '\n'.join(keys)
		self._assure_vpn_disabled(self.session)
		link_endpoint = 'updateproduct'
		id, item_name = self.g2a_db[gname]
		price = self.get_lowest_price(id) - 0.11
		auction_id = self.current_sales.get(id, None)
		payload = {'id': auction_id, 'key': keys, 'price': str(price), 'sell_globally': 'yes',
				   'period': '14', 'active': '1', 'visibility': 'retail',
				   'reg': '1', 'steam-gift': '1'}

		if not auction_id:
			link_endpoint = 'saveproduct'
			del payload['id']
			payload['product_name'] = item_name
			payload['product_id'] = id

		resp = self.session.post('https://www.g2a.com/marketplace/wholesale/' + link_endpoint,
						  		 files={'files[]': ''}, data=payload)
		if not 'My Account' in resp.text:
			raise FailedSessionException('The session had dropped before the gift was uploaded')

		if not auction_id:
			soup = BeautifulSoup(resp.text, 'html.parser')
			auction_id = soup.find(class_='gate-auction-controls').find_all('a')[1]['data-product']
			self.current_sales[id] = auction_id

	def get_current_sales(self):
		"""a set of ids of items being sold on g2a"""
		sales = {}
		self._assure_vpn_disabled(self.session)
		link = 'https://www.g2a.com/marketplace/wholesale/products/?limit=20&p='
		resp = self.session.get(link + '1')
		assert 'My Account' in resp.text, 'Invalid session. The account data is not available'
		json_data = json.loads(re.search(r'marketPlaceProducts = (.+?);', resp.text).group(1))
		item_ids = {item['label']: item['value'] for item in json_data}

		s = BeautifulSoup(resp.text, 'html.parser')
		amount_of_items = int(s.find(class_='pager').p.strong.text.rstrip(' Item(s)'))
		amount_of_pages = math.ceil(amount_of_items / 20)
		for num in range(amount_of_pages):
			num += 1
			resp = self.session.get(link + str(num))
			s = BeautifulSoup(resp.text, 'html.parser')
			for element in s.find_all('tr', class_='row-steam'):
				id = item_ids[element.h2.text]
				sales[id] = element.find(class_='gate-auction-controls').find_all('a')[1]['data-product']

		return sales


	@staticmethod
	def _assure_norway_is_cheapest(app, nok_price, cur_rate):
		cc_currencies = {'nz': 'NZD', 'ca': 'CAD', 'jp': 'JPY', 'kr': 'KRW',
						 'gb': 'GBP', 'ch': 'CHF', 'ee': 'EUR', 'us': 'USD'}
		app_type, appid = app
		if app_type == 'app':
			endpoint = 'appdetails/?appids='
		else:
			endpoint = 'packagedetails/?packageids='
		endpoint += appid
		for code, currency in cc_currencies.items():
			price = 0
			while True:
				try:
					resp = requests.get('http://store.steampowered.com/api/{0}'
										'&l=english&v=1&cc={1}&filters=price_overview'
										.format(endpoint, code)).json()
					price = resp[appid]['data']['price_overview']['final'] / 100 / cur_rate[currency]
					break
				except KeyError:
					logger.info('No prices for the app: ' + appid)
					return False
				except json.decoder.JSONDecodeError as err:
					print(err)
			if not price:
				continue
			# the nok price must not be 2% greater than any other regional price
			if price * 1.02 < nok_price:
				return False
			if code in ('ee', 'us'):
				# the eur and usd prices must be at least 10% greater than the nok price
				if price < nok_price * 1.1:
					return False
		return True


	def _steam_games_generator(self, final_purchase):
		categories_classes = (
		('data-ds-packageid', 'sub'),
		('data-ds-bundleid', 'bundle'),
		('data-ds-appid', 'app')
		)

		page_range = 3
		if final_purchase:
			page_range = 50

		for page_num in range(page_range):
			page_num += 1
			r = requests.get('http://store.steampowered.com/search',
							 params={'filter':'globaltopsellers', 'cc':'no', 'page': str(page_num)})
			s = BeautifulSoup(r.text, 'html.parser')
			rows = s.find_all(class_='responsive_search_name_combined')
			for row in rows:
				# find games only with discounted prices
				price_element = row.find(class_='col search_price discounted responsive_secondrow')
				if not price_element:
					continue
				steam_price = (float(price_element.span.nextSibling.text
									 .replace(',', '.').rstrip(' kr\t')))
				# miss game if it costs less than 24 or more than 200
				if not 24 < steam_price <= 200:
					continue

				gname = row.find(class_='title').text.strip()
				for category_class, category in categories_classes:
					appid = row.parent.get(category_class, None)
					if appid:
						app = (category, appid)
						break

				yield gname, steam_price, app


	def _get_g2a_appid(self, gname_orig):
		def strip_gname(gname):
			gname = re.sub('[®™]', '', gname)
			gname = gname.replace('- ', '')
			gname = gname.replace(': ', ' ')
			return gname

		gname = strip_gname(gname_orig).lower()
		item_id, g2a_gname = self.g2a_db.get(gname_orig, (None, None))
		if not item_id:
			params = {
			'search': gname,
			'includeOutOfStock': 'true',
			'rows': '12',
			'minPrice': '0.0',
			'MaxPrice': '639',
			'cat': '0',
			'genre': '0',
			'sortOrder': 'popularity+desc',
			'start': '0',
			'stock': 'all',
			}

			resp = requests.get('https://www.g2a.com/lucene/search/filter?', headers=self.USER_AGENT,
								params=params).json()
			for item in resp['docs']:
				g2a_gname = strip_gname(item['name'].lower())
				gname_reformed = ''
				for category in self.G2A_CATEGORIES:
					if category in g2a_gname:
						gname_reformed = gname + ' ' + category
				if g2a_gname == gname_reformed:
					item_id = str(item['id'])
					self.g2a_db[gname_orig] = (item_id, item['name'])
					self.g2a_db.sync()
					break

		return item_id, g2a_gname


	def _create_session(self):
		path = r'C:\Users\sham\AppData\Local\Google\Chrome\User Data\Default\Cookies'
		session = requests.Session()
		conn = sqlite3.connect(path)
		cursor = conn.cursor()
		cursor.execute("SELECT name, encrypted_value FROM cookies WHERE name='g2aSSO'")
		try:
			key, binary_value = cursor.fetchone()
		except TypeError as err:
			print('The g2aSSO cookie was not found')
			quit()
		value = CryptUnprotectData(binary_value, None, None, None, 0)[1].decode('utf-8')
		session.cookies[key] = value
		session.cookies['store'] = 'english'
		session.headers.update(self.USER_AGENT)
		self._assure_vpn_disabled(session)
		session.get('https://id.g2a.com')
		conn.close()
		return session

	@staticmethod
	def _assure_vpn_disabled(session):
		# delete the function when the script is run on a VPS
		resp = session.get('http://ip-api.com/json').json()
		assert resp['city'] == 'Grozny', 'VPN is enabled. Disable the VPN to proceed.'

if __name__ == '__main__':
	pass
