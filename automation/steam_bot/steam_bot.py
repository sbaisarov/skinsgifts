import sys, traceback
import re
import shelve
import string
import random
import logging
import json
import time
import threading
import requests
from tkinter import *
from decimal import *

from flask import Flask, request
from bs4 import BeautifulSoup
from imaplib import IMAP4, IMAP4_SSL

from steampy.client import SteamClient, TradeOfferState
from steampy.utils import GameOptions, update_session
from steampy import guard

from selenium import webdriver
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from g2a_utils import AutomatedG2A

def organise_logs():
	# disable requests info logs
	logging.getLogger("requests").setLevel(logging.ERROR)

	root_logger = logging.getLogger()

	formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')

	handler = logging.FileHandler('./data/steambot.log', 'w', encoding='utf-8')
	handler.setFormatter(formatter)
	root_logger.addHandler(handler)
	root_logger.setLevel(logging.INFO)

	return root_logger

logger = organise_logs()

pricelist_path = (r'C:\Users\sham\Desktop\python\skinsgifts\automation'
				  '\skype_bot\skypebot_buyer\data\pricelist')

auto_g2a = AutomatedG2A('./data/g2a_appids')
skins_nameids = shelve.open('./data/skins_nameids')
db = shelve.open('./data/goods_db', writeback=True)
active_accs = {}
app = Flask(__name__)
proxy_host = '185.125.169.59' # proxy Norway TorGuard
proxy = {
'http': 'http://user6190828:LeJekgAi@{}:6060'.format(proxy_host),
'https': 'http://user6190828:LeJekgAi@{}:6060'.format(proxy_host)
}

@app.route('/', methods=['POST'])
def main():
	data = json.loads(request.data.decode('utf-8'))
	login, passwd, api_key = data['acc_data'][:3]
	volume = int(data['acc_data'][4])
	active_accs.setdefault(login, {})
	mafile = data['mafile']
	proxy_id = data['proxy_id']
	steam_client = active_accs[login].get('steam_client')
	if not steam_client:
		steam_client = SteamClient(api_key, proxy=proxy)
		r = steam_client.session.get('http://httpbin.org/ip')
		logger.info(r.text)
		steam_client.login(login, passwd, mafile)
		active_accs[login]['steam_client'] = steam_client

	offers = steam_client.get_trade_offers()['response']['trade_offers_received']
	if offers:
		while True:
			resp = steam_client.accept_trade_offer(offers[0]['tradeofferid'], proxy_id)
			logger.info(str(resp))
			error = resp.get('strError', None)
			if error:
				if '(28)' in error:
					time.sleep(3)
					continue
				elif '(25)' in error:
					return '25'
			break

	sellm_thread = active_accs[login].get('sellm_thread')
	if not sellm_thread:
		sellm_thread = threading.Thread(target=sell_market, args=(steam_client, volume))
		active_accs[login]['sellm_thread'] = True
		sellm_thread.start()

	buygifts_thread = active_accs[login].get('buygifts_thread')
	if not buygifts_thread:
		buygifts_thread = threading.Thread(target=buy_gifts, args=(steam_client, volume))
		active_accs[login]['buygifts_thread'] = True
		buygifts_thread.start()

	return 'OK'

def buy_gifts(steam_client, volume):
	def browse_gifts(driver, wait, apps, email_addr):
		games_data = {}
		try:
			# a workaround to make phantomjs stop hanging
			# while opening pages with adult content
			driver.set_page_load_timeout(5)
			for app, price in apps:
				item_category, appid = app
				try:
					driver.get('http://store.steampowered.com/{}/{}/'.format(item_category, appid))
				except TimeoutException:
					pass
				js_id = driver.find_element_by_name('subid').get_attribute('value')
				try:
					gname = driver.find_element_by_class_name('apphub_AppName').text
				except NoSuchElementException:
					gname = driver.find_element_by_class_name('pageheader').text
				games_data[gname] = price
				driver.execute_script('javascript:addToCart({});'.format(js_id))
				wait.until(EC.title_is('Shopping Cart'))
			driver.set_page_load_timeout(15) # reset the page load timeout
			driver.get('http://store.steampowered.com/checkout/?purchasetype=gift')
			while True:
				try:
					email_input = wait.until(EC.visibility_of_element_located((By.ID, 'email_input')))
					email_input.send_keys(email_addr)
					driver.execute_script("javascript:SubmitGiftDeliveryForm()")
					wait.until(EC.visibility_of_element_located((By.CLASS_NAME, 'gift_note_form_area')))
					inputs =  (driver.find_element_by_id("gift_recipient_name"),
					driver.find_element_by_id("gift_message_text"),
					driver.find_element_by_id("gift_signature"))
					for input_ in inputs:
						input_.send_keys('`')
					driver.execute_script("javascript:SubmitGiftNoteForm()")
					wait.until(EC.visibility_of_element_located((By.ID, "purchase_confirm_ssa")))
					break
				except TimeoutException as err:
					if 'form name="logon"' in driver.page_source:
						logger.info('The session has dropped')
						username_input = driver.find_element_by_id('input_username')
						username_input.clear(); username_input.send_keys(steam_client.login_name)
						driver.find_element_by_id('input_password').send_keys(steam_client.password)
						driver.find_element_by_xpath("//button[@type='submit']").click()
						twofactor_entry = wait.until(EC.visibility_of_element_located((
											By.ID, 'twofactorcode_entry')))
						timestamp = int(time.time())
						one_time_code = guard.generate_one_time_code(
											steam_client.mafile['shared_secret'], timestamp)
						twofactor_entry.send_keys(one_time_code)
						code_form = driver.find_element_by_id('login_twofactorauth_buttonset_entercode')
						code_form.find_element_by_class_name('auth_button_h3').click()
					elif 'a lot of purchases' in driver.page_source:
						logger.info('Steam responded with excessive purchases')
						time.sleep(3800)
						driver.get('http://store.steampowered.com/checkout/?purchasetype=gift')
					elif 'There seems to have been an error' in driver.page_source:
						logger.info('transaction error while buying gifts, waiting for 5 minutes')
						time.sleep(300)
						driver.get('http://store.steampowered.com/checkout/?purchasetype=gift')
					else:
						raise err

			driver.find_element_by_id('accept_ssa').click()
			driver.execute_script("javascript:FinalizeTransaction()")
			wait.until(EC.visibility_of_element_located((By.ID, "receipt_area")))
		except Exception:
			print(traceback.format_exc())
			print('error occured while buying gifts')
			driver.save_screenshot('test.png')
			with open('html_error.txt', 'w', encoding='utf-8') as f:
				f.write(driver.page_source)
			quit()

		return games_data

	def generate_email():
		headers = {'PddToken': '2FP4AA6TRC7JXUSKU7KK72SQJNDF6F73EPKFHXMPPXEIJV4F4KVA'}
		while True:
			try:
				email_addr = ''.join(random.choice(string.ascii_lowercase) for _ in range(8))
				data = {'domain': 'bubblemail.xyz', 'login': email_addr, 'password': 'shamal1995'}
				r = requests.post('https://pddimp.yandex.ru/api2/admin/email/add',
								  headers=headers, data=data)
				logger.info(r.text)
				if r.json()['success'] == 'error':
					continue
				return email_addr + '@bubblemail.xyz'
			except imaplib.error as err:
				print(err)

	def make_purchase(amount, is_final_purchase=False):
		profitable_gifts, total_cost = auto_g2a.find_profitable_gifts(amount, is_final_purchase)
		logger.info('profitable gifts: ' + str(profitable_gifts))
		if profitable_gifts:
			driver, wait = init_webdriver(steam_client)
			while amount >= total_cost:
				email_addr = generate_email()
				games_data = browse_gifts(driver, wait, profitable_gifts, email_addr)
				fetch_links(steam_client, games_data, email_addr)
				amount -= total_cost
			driver.quit()
		else:
			logger.info('No profitable gifts found. Waiting...')
			if is_final_purchase:
				time.sleep(3600)

		return amount

	driver = None
	while True:
		items_being_sold, amount = get_community_data(steam_client)[:2]
		if amount >= 200:
			make_purchase(amount)
		elif not items_being_sold and volume >= 1000:
			my_skins = steam_client.get_my_inventory(game=GameOptions.CS)
			offers = steam_client.get_trade_offers()['response']['trade_offers_received']
			if not offers and not my_skins:
				# make purchases until the wallet is devastated to less than 24
				while amount > 24:
					amount = make_purchase(amount, is_final_purchase=True)
				logger.info('Account with login {} has finished buying gifts'.format(steam_client.login_name))
				quit()

		time.sleep(1200)

def init_webdriver(steam_client):
	webdriver.DesiredCapabilities.PHANTOMJS['phantomjs.page.customHeaders.Accept-Language'] = 'en-US'
	webdriver.DesiredCapabilities.PHANTOMJS['phantomjs.page.settings.userAgent'] = (
			'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
			'Chrome/54.0.2840.71 Safari/537.36')
	service_args = [
	'--proxy={}:6060'.format(proxy_host),
	'--proxy-type=http',
	'--proxy-auth=user6190828:LeJekgAi'
	]
	driver = webdriver.PhantomJS('./data/phantomjs', service_args=service_args,
								 service_log_path='./data/phantomjs.log')
	driver = add_cookies(driver, steam_client)
	wait = WebDriverWait(driver, 30)
	return driver, wait

def add_cookies(driver, steam_client):
	new_cookies = {'strResponsiveViewPrefs': 'desktop', 'mature_content': '1', 'birthtime': '757378801'}
	steam_client.session.cookies.update(new_cookies)
	session_cookies = steam_client.session.cookies.get_dict()
	cookies = ['steamLogin', 'sessionid', 'steamLoginSecure'] + list(new_cookies)
	driver.get('http://store.steampowered.com/')
	for cookie in cookies:
		driver.execute_script('document.cookie = "{}={}; path=/;"'.format(
								cookie, session_cookies[cookie]))
	return driver

def fetch_price(market_name, nameid, average_price, acc_cur, unpopular=False):
	currencies = {'kr': '9', 'pуб': '5', 'usd': '1'}
	params = {
		'language': 'english',
		'currency': currencies[acc_cur],
		'item_nameid': nameid,
		'two_factor': '0'
	}
	r = requests.get('http://steamcommunity.com/market/itemordershistogram',
					 params=params)
	# post запрос для выставления скина на тп требует
	# указать цену без учета комиссии и без десятичного разделителя
	# if unpopular:
	# 	fetched_price = int(r.json()['buy_order_graph'][0][0] * 86.95)
	# 	return fetched_price

	ctr = 0
	average_price *= currency_rate # convert to nok
	while True:
		try:
			price_init = r.json()['sell_order_graph'][ctr][0]
		except IndexError:
			break
		if average_price / price_init > 1.01 and price_init > 1:
			ctr += 1
			continue
		break
	if ctr:
		logger.info('the average price is greater than the current one more than 1%: ' + market_name)
	subtract = Decimal(price_init) - Decimal(0.1)
	price_final = int((float(subtract) * 86.95))
	if price_final <= 0:
		price_final = 3
	return price_final

def get_community_data(steam_client):
	r = steam_client.session.get('http://steamcommunity.com/market/')
	if not 'marketWalletBalanceAmount' in r.text:
		logger.info("couldn't find the purse element")
		update_session(steam_client)
		r = steam_client.session.get('http://steamcommunity.com/market/')

	s = BeautifulSoup(r.text, 'html.parser')
	purse_element = s.find(id='marketWalletBalanceAmount')

	items_being_sold = 0
	purse_element = purse_element.text.split()
	elements = s.find_all(id=re.compile('mylisting_'))
	if elements:
		items_being_sold = set(
			(i['id'].lstrip('mylisting_')
			 for i in s.find_all(id=re.compile('mylisting_\d+$')))
		)

	amount = float(purse_element[0].replace('.', '').replace(',', '.'))
	currency = purse_element[1].strip('.')
	return items_being_sold, amount, currency

def sell_market(steam_client, volume):
	def cancel_items(items_sold):
		headers = {
		'X-Prototype-Version': '1.7',
		'X-Requested-With': 'XMLHttpRequest',
		'Referer': 'http://steamcommunity.com/market/',
		'Origin': 'http://steamcommunity.com',
		'Host': 'steamcommunity.com'
		}
		sessionid = steam_client.get_session_id()
		url = 'https://steamcommunity.com/market/removelisting/'
		for skin_id in items_sold:
			resp = steam_client.session.post(url + skin_id, data={'sessionid': sessionid},
											 headers=headers)
			logger.info('cancel item response: ' + resp.text)

	def get_average_rate():
		import datetime
		date = datetime.datetime.today().strftime("%m/%y")

		rate_dict = db.setdefault('average_rate', {})
		ctr = 0
		market_sales_value = 0
		skins_costprice = 0
		while True:
			market_json = steam_client.session.get(
				'http://steamcommunity.com/market/myhistory/render/?query=&start=' + str(ctr)).json()
			if not market_json['success']:
				print('no success in getting the market history')
				continue
			if not market_json['assets']:
				break

			ctr += 10
			ids = set(re.findall("730, '2', '(.+)'", market_json['hovers']))
			for i in ids:
				hash_name = market_json['assets']['730']['2'][i]['market_hash_name']
				skins_costprice += float(price_list[hash_name]['7_days']['average_price']) * currency_rate

			s = BeautifulSoup(market_json['results_html'], 'html.parser')
			# парсит продажи на тп только в кронах, с учетом комиссии
			valid_elements = (element for element in s.find_all(
							  class_='market_listing_row market_recent_listing_row')
							  if 'Buyer' in element.text)
			market_values = (float(i.find(class_='market_listing_price').text
							 	   .strip('kr\r\n\t ').replace('.', '').replace(',', '.'))
							 for i in valid_elements)
			for market_value in market_values:
				market_sales_value += market_value

		rates_list = rate_dict.setdefault(date, [])
		rates_list.append(skins_costprice * 0.72 / market_sales_value)
		db.sync()

	currency = get_community_data(steam_client)[-1]
	re_pattern = re.compile('Market_LoadOrderSpread\( ((\d)+) \)')
	getcontext().prec = 10
	while True:
		with open(pricelist_path, 'r', encoding='utf-8') as infile:
			price_list = json.load(infile)
		flag = False
		my_skins = steam_client.get_my_inventory(game=GameOptions.CS, merge=True)
		for skin_id, skin_descr in my_skins.items():
			try:
				market_name = skin_descr['market_hash_name']
			except KeyError as err:
				print('{0} {1}'.format(err, skin_descr))
				continue
			item_volume = int(price_list[market_name]['7_days']['volume'])
			average_price = float(price_list[market_name]['safe_price'])
			nameid = skins_nameids.get(market_name)
			if not nameid:
				r = requests.get('http://steamcommunity.com/market/listings/730/{}'.format(market_name))
				nameid = re_pattern.search(r.text).group(1)
				skins_nameids[market_name] = nameid
				skins_nameids.sync()
			if item_volume < 5:
				current_price = fetch_price(market_name, nameid, average_price,
											currency, unpopular=True)
			else:
				current_price = fetch_price(market_name, nameid, average_price, currency)
			resp = steam_client.create_market_listing(int(skin_id), current_price, 730)
			logger.info(str(resp))
			if not flag and resp['success']:
				flag = True

		if flag:
			steam_client.confirm_transactions()

		time.sleep(900)
		items_sold = get_community_data(steam_client)[0]
		if not items_sold and volume >= 1000:
			my_skins = steam_client.get_my_inventory(game=GameOptions.CS)
			if not my_skins:
				logger.info('Account with login {} has finished selling skins'.format(steam_client.login_name))
				get_average_rate()
				quit()

		if items_sold:
			cancel_items(items_sold)
			time.sleep(10)
			# wait until all of the cancelled items are returned to the inventory
			# items_amount = 0
			# while items_amount != len(items_sold):
			# 	print('not all of the items has been returned to the inventory')
			# 	items = steam_client.get_my_inventory(game=GameOptions.CS)
			# 	items_amount = len(items)

def fetch_links(steam_client, games_data, email_addr):
	sessionid = steam_client.session.cookies.get('sessionid', domain='store.steampowered.com')
	gname_pattern = 'the game (<b>)?(.+?)(<\/b>)? on Steam'
	link_pattern = 'https?:\/\/store\.steampowered\.com\/account\/ackgift\/.+?\.(ru|com|org|xyz)'
	# sometimes the log in process on yandex imap service takes
	# a long time and then it gets aborted for being idle
	while True:
		try:
			server = IMAP4_SSL('imap.yandex.ru')
			server.login(email_addr, 'shamal1995')
			server.select()
			break
		except (IMAP4.abort, IMAP4.error, ConnectionResetError) as err:
			print(err)
			time.sleep(5)
			continue
	time.sleep(10)
	for num, _ in enumerate(games_data, start=1):
		while True:
			try:
				mail_body = server.fetch(str(num), '(UID BODY[TEXT])')[1][0][1].decode('utf-8')
				break
			except TypeError:
				logger.info('No email was found.')
				server.select()
				time.sleep(5)
				continue
			except IMAP4.abort as err:
				print(err)
				time.sleep(5)
				continue

		link = re.search(link_pattern, mail_body).group()
		gname = re.search(gname_pattern, mail_body).group(2)
		logger.info('{0} {1}'.format(gname, link))
		with open('./gifts/{}.txt'.format(re.sub('[{}]'.format(
			re.escape('/\:*?"<>|')), '', gname)), 'a+', encoding='utf-8') as f:
			f.write(link + '\n')
		items = db.setdefault('goods', {})
		items.update(games_data)
		db.sync()
		auto_g2a.upload_gifts(gname, [link])
	server.logout()

def update_currency_rate():
	while True:
		cur_rate_req = requests.get('http://api.fixer.io/latest?base=USD')
		global currency_rate
		currency_rate = cur_rate_req.json()['rates']['NOK']
		time.sleep(3600)


threading.Thread(target=update_currency_rate).start()
app.run(port=5000)
