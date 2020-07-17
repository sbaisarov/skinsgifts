import re
from time import sleep

import requests
import logging

from payments import WmPayment, QiwiPayment

def main():
	keys_path = r'C:\Users\sham\Desktop\python\skinsgifts\skype_bot\data'
	wmpm = WmPayment(keys_path)

	logging.basicConfig(filename=r'C:\Users\sham\Desktop\error_log.txt', level=logging.ERROR, 
	                    format='\n%(asctime)s %(levelname)s %(name)s %(message)s')
	logger=logging.getLogger()

	s = requests.Session()
	s.headers.update({
		'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
						'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/55.0.2883.87 Safari/537.36')})
	main_page = s.get('http://smartwm.ru/').text
	crsf_token = re.search('"_csrf_token" value="(.+?)"', main_page).group(1)
	s.headers['Accept'] = 'application/json, text/javascript, */*; q=0.01'
	xmlhttp_headers = {
	'Host': 'smartwm.ru',
	'Origin': 'https://smartwm.ru',
	'Referer': 'https://smartwm.ru/',
	'X-Requested-With': 'XMLHttpReques'
	}
	exchange_issue_data = {
	'exchange_authorize_form[user][lastname]': 'Байсаров',
	'exchange_authorize_form[user][firstname]': 'Шамиль',
	'exchange_authorize_form[user][middlename]': 'Абубакарович',
	'exchange_authorize_form[agree_reglament]': '1',
	'exchange_authorize_form[wallet_from]': 'R394380159465',
	'exchange_authorize_form[wallet_to]': '79659660934',
	'exchange_authorize_form[accept_agreement_terms]': '1',
	'exchange_authorize_form[user][invitedBy]': ''
	}
	resp = s.post('https://smartwm.ru/login_check',
				   data={
				   '_username': 'spike2@list.ru',
				   '_password': 'UAhyf$DE09;C',
				   '_csrf_token': crsf_token,
			 	   '_target_path': ''
			 	   },
			 	   headers=xmlhttp_headers)

	while True:
		rate = float(s.post('https://smartwm.ru/exchange/rate', data={
			'classFrom': 'wmr',
			'classTo': 'qiwi'},
			headers=xmlhttp_headers).json()['rates']['direct']['rate'] \
			.partition(' WMR')[0])
		print('current rate:', rate)

		if rate >= 1.03:
			print('rate is too high, waiting 1 hour')
			sleep(3600)
			continue

		wm_balance = float(wmpm.get_balance()) * 0.99
		amount_init = min(14000, wm_balance)
		amount = amount_init
		if amount <= 2000:
			print('low amount of funds on Webmoney, waiting for 1 hour')
			sleep(3600)
			continue

		while True:
			resp = s.post('https://smartwm.ru/exchange/check', 
					data={'classFrom': 'wmr',
					'classTo': 'qiwi',
					'amountFrom': str(amount)}).json()
			if not resp['error']:
				break
			else:
				amount -= 1000

			if amount <= 2000:
				print('no exchange is available, waiting')
				amount = amount_init
				sleep(600)

			sleep(3)

		resp = s.post('https://smartwm.ru/exchange/prepare', data=exchange_issue_data)
		form = s.post( 'https://smartwm.ru/exchange/authorize', data=exchange_issue_data)\
			 	.json()['data']['result']['form']
		tid = re.search('name="LMI_PAYMENT_NO" value="(.+?)"', form).group(1)
		purse = re.search('name="LMI_PAYEE_PURSE" value="(.+?)"', form).group(1)
		wmpm.init_payment(purse, amount, tid)

main()
'''
try:
	main()
except Exception as err:
	print(err)
	logger.exception(err)
	quit()'''