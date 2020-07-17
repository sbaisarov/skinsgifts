import shelve
import re
import csv
import os
import collections
import datetime

import requests

# the average skins sale rate isn't much precise
# because the price list database is read in different periods of time

db_path = r'C:\Users\sham\Desktop\python\skinsgifts\automation\steam_bot\data\goods_db'

with shelve.open(db_path) as db:
	goods_db = dict(db)

date = datetime.datetime.today().strftime("%m/%y")
skins_rates = goods_db['average_rate'][date]
average = sum(skins_rates) / len(skins_rates)
average_nocommission = average / 1.15

def main():
	revenue = int(input('Выручка?: '))
	cost_price = 0
	cur_rate = float(requests.get('http://api.fixer.io/latest?base=NOK').json()['rates']['EUR'])
	games_sold = collections.defaultdict(int)
	report = [file for file in os.listdir()
			  if file.startswith('report')]
	if not report or len(report) > 1:
		raise Exception('Не найден отчет либо его количество превышает 1')
	ctr = 0
	with open(report[0]) as csvfile:
		reader = csv.DictReader(csvfile)
		for row in reader:
			if not row['Type'] == 'Product':
				continue
			if 'RU/CIS' in row['Name']:
				continue
			try:
				gname = re.search(r'(.+?) (STEAM|EARLY|DLC)', row['Name']).group(1)
			except AttributeError:
				print(row['Name'])
			games_sold[gname] += 1
			ctr += 1

	for key, value in games_sold.items():
		try:
			cost_price += goods_db['goods'][key] * value
		except KeyError:
			print(key)

	cost_price *= cur_rate * average

	cost_price *= 1.02 # qiwi wm exchange
	revenue *= 0.99 # including withdraw commission

	print('\nС начала месяца было заработано:', revenue - cost_price)
	print('Вложено: ', cost_price)
	print('Товаров продано:', ctr)
	print('Список рейтов от всех используемых аккаунтов:',  list(map(lambda x: x / 1.15, skins_rates)))
	print('Средний рейт с комиссией:', average)
	print('Средний рейт без комиссии:', average_nocommission)

main()
