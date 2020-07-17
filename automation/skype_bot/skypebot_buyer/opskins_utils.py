import statistics
import shelve
import logging
import json
import threading
import time
from datetime import datetime

import requests

from steampy.client import SteamClient
from steampy.utils import GameOptions

logger = logging.getLogger(__name__)

class OpSkins:

    def __init__(self, api_key):
        self.api_key = api_key
        self.api_base = 'https://api.opskins.com/{0}/{1}/{2}/'
        threading.Thread(target=self._update_pricehistory_db).start()


    def calculate_prices(self, items):
        today = datetime.today()
        prices_db = shelve.open('./data/pricehistory.dat')
        result = dict.fromkeys(items, 0)
        for skin_name in items:
            try:
                stats = opskins_pricehistory[skin_name]
            except KeyError:
                logger.info('no history for: %s', skin_name)
                continue

            average_price, volume = self._get_average_price(stats, today)
            if not average_price:
                logger.info('sales volume is too low for: %s', skin_name)
                continue

            rate = 0.89 if volume >= 7 else 0.84
            place_to_round_to = 2 if average_price != 2 else 4
            purchase_price = round(average_price * rate / 100, place_to_round_to)
            # avg. price is in cents, purchase price is in dollars
            prices_db[skin_name] = (average_price, purchase_price)
            result[skin_name] = purchase_price
            logger.info('%s %s %s', purchase_price, volume, skin_name)

        prices_db.close()
        return result


    def _get_average_price(self, stats, current_day):
        average_price = 0
        volume = 0
        nearest_prices = {}
        for date, item in stats.items():
            date = datetime.strptime(date, '%Y-%m-%d')
            # subtract 1 to align with the usa time zone
            # subtract 1 because the last timestamp is the day before yesterday
            delta_days = (current_day - date).days
            if delta_days <= 9:
                nearest_prices[delta_days] = item['normalized_mean']
                volume += 1

        if volume < 5:
            return None, None

        average_price = statistics.mean(nearest_prices.values())

        calc_average_price_again = False
        for delta_days, price in nearest_prices.items():
            coef = price / average_price
            if coef <= 0.5 or coef >= 2:
                del nearest_prices[delta_days]
                if not calc_average_price_again:
                    calc_average_price_again = True
        if calc_average_price_again:
            average_price = statistics.mean(nearest_prices.values())

        average_trend = self._determine_trend(nearest_prices, average_price)
        logger.info('average trend: %s', average_trend)
        if average_trend < 1:
            average_price *= average_trend

        return average_price, volume


    @staticmethod
    def _determine_trend(nearest_prices, average_price):
        average_trend = 1
        logger.info('nearest_prices: %s', nearest_prices)
        trend_prices = []
        trend_days = 3
        while not trend_prices:
            for delta_days, price in nearest_prices.items():
                if delta_days < trend_days:
                    trend_prices.append(price)
            trend_days += 3

        if trend_prices:
            average_trend = statistics.mean(
                (price / average_price for price in trend_prices))

        return average_trend


    def _update_pricehistory_db(self):
        global opskins_pricehistory
        while True:
            current_time = datetime.today()
            db = shelve.open('./data/opskins_pricehistory.dat', writeback=True)
            try:
                days_delta = (current_time - datetime.fromtimestamp(db['time'])).days
            except KeyError:
                days_delta = 1

            if days_delta >= 1:
                resp = self.get_pricelist()
                db.update(resp)
            opskins_pricehistory = db['response']
            # the prices database is updated nighlty on opskins
            update_time = 24 - datetime.fromtimestamp(db['time']).hour + 2 * 60
            db.close()

            time.sleep(update_time)


    def get_pricelist(self):
        resp = requests.get(self.api_base.format('IPricing', 'GetPriceList', 'v2'),
                            params={'appid': '730'})
        return resp.json()


    def list_items(self, items):
        data = {
            'key': self.api_key,
            'items': json.dumps(items[start:end])
        }
        resp = requests.post(self.api_base.format('ISales', 'ListItems', 'v1'),
                             data=data).json()
        if resp['status'] != 1:
            raise Exception(resp)
        return resp['response']

    def get_listing_limit(self):
        resp = requests.get(self.api_base.format('ISales', 'GetListingLimit', 'v1'),
                            params={'key': self.api_key})
        return resp.json()['response']['listing_limit']


    def resend_offer(self, item_id):
        url = self.api_base.format(USER_ENDPOINT, self.api_key, 'ResendTrade')
        resp = requests.get(url + '&item_id=%s' % item_id)
        logger.info('resend offer response: %s', resp.text)


    def bump_items(self, items):
        resp = requests.post(self.api_base.format('ISales', 'BumpItems', 'v1'),
                             data={'key': self.api_key, 'items': items})
        logger.info('bump item response: %s', resp.text)


    def get_sales(self, type_='2'):
        resp = requests.get(self.api_base.format('ISales', 'GetSales', 'v1'),
                            params={'key': self.api_key, 'type': type_})
        return resp.json()['response']


    def edit_price_multi(self, items):
        resp = requests.post(self.api_base.format('ISales', 'EditPriceMulti', 'v1'),
                             data={'key': self.api_key, 'items': items})
        logger.info('edit item response: %s', resp.text)


    def get_lowest_sale_prices(self):
        resp = requests.get(self.api_base.format('IPricing', 'GetAllLowestListPrices', 'v1'),
                            params={'appid': '730'})
        return resp.json()['response']

if __name__ == '__main__':
    logger.setLevel(level=logging.INFO)
    file_handler = logging.FileHandler('data/skypebot.log', encoding='utf-8')
    formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    ops = OpSkins('e4f2d89cdbac56b132b68cef2c53e5')
    steam_client = SteamClient()
    steam_client.login('immunepzw', 'arigold4172409', r'C:\Users\sham\Desktop\sda\maFiles\76561198177211015.maFile')
    my_skins = steam_client.get_my_inventory(game=GameOptions.CS)
    items = []
    lowest_prices = ops.get_lowest_sale_prices()
    prices_db = shelve.open('./data/pricehistory.dat')
    box_classids = (
        '520025252', '2048553988', '1544067968',
        '1432174707', '1293508920', '926978479',
        '1690096482', '991959905', '1797256701',
        '1923037342'
    )
    for id_, skin_descr in my_skins.items():
        if not skin_descr['tradable'] or skin_descr['classid'] in box_classids:
            continue
        skin_name = skin_descr['market_hash_name']
        lowest_price = lowest_prices[skin_name]['price']
        if lowest_price != 2: # lowest price on opskins is 2 cents
            lowest_price -= 1
        # average_price = prices_db[skin_name][0]
        # if lowest_price / average_price < 0.99:
        #     lowest_prices = average_price * 0.99
        #     logger.info('lowest price is 1 perc. and more less than purchase one: %s', skin_name)
        item = {
            'appid': 730,
            'assetid': id_,
            'contextid': 2,
            'price': lowest_price
        }
        items.append(item)
    prices_db.close()
    end = ops.get_listing_limit()
    start = 0
    while True:
        items_slice = items[start:end]
        resp = ops.list_items(items)
        if resp['tradeoffer_error']:
            time.sleep(10)
            continue
        steam_client.accept_trade_offer(resp['tradeoffer_id'], resp['bot_id64'])
        start, end = end, end + 50
