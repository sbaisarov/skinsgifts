import json
import sys
import collections
import re
import statistics
import logging
import shelve
import threading
import requests
import urllib
import winsound
from time import sleep
from datetime import datetime

import grequests
from flask import Flask, request
from bs4 import BeautifulSoup
from steampy.client import SteamClient
from steampy.utils import account_id_to_steam_id

import skypebot_text
from payments import QiwiPayment, WmPayment
import opskins_utils

# disable flask and requests info logs
logging.getLogger('werkzeug').setLevel(logging.ERROR)
logging.getLogger("requests").setLevel(logging.ERROR)

logger = logging.getLogger()
logger.setLevel(level=logging.INFO)
file_handler = logging.FileHandler('./data/skypebot.log', 'a', encoding='utf-8')
formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

db = shelve.open('./data/clients', writeback=True)
app = Flask(__name__)
ops = opskins_utils.OpSkins('e4f2d89cdbac56b132b68cef2c53e5')

with open('./data/proxy_bot.txt', 'r', encoding='utf-8') as f:
    acc_data = [i.strip() for i in f.readlines()]

login, passwd, api_key, offer, value, my_steamid = acc_data
offer = offer.replace('&', '&amp;')

steam_client = SteamClient(api_key)
mafile_path = './data/proxy_bot.maFile'
steam_client.login(login, passwd, mafile_path)
qiwipm, wmpm = QiwiPayment(), WmPayment('./data')

def post_answer(answer, conv_id):
    url = 'https://apis.skype.com/v3/conversations/{}/activities'.format(conv_id)
    headers = {'Host': 'apis.skype.com', 'Authorization': 'Bearer ' + token}
    data = json.dumps({"type": "message/text", "text": answer})
    requests.post(url, headers=headers, data=data)

@app.route('/', methods=['GET', 'POST'])
def get_msgs():
    if 'id=' in request.url:
        return send_pricelist(request.url)

    data = json.loads(request.data.decode('utf-8'))
    client = ''
    if data['from'].get('name'):
        client = data['from']['name']
    msg = data.get('text')
    conv_id = data['conversation']['id']
    logger.info('{0} ({1}): {2}'.format(conv_id, client, msg))
    if data.get('action') == 'add':
        answer = skypebot_text.GREETING.format(client)
    if conv_id not in db:
        db[conv_id] = {}
        db[conv_id]['steam_profile'] = None
        db[conv_id]['client_name'] = client
        db[conv_id]['steamid'] = None
        db[conv_id]['purse'] = None
        db[conv_id]['offer_id'] = None
        db[conv_id]['confirm_data'] = False
        db[conv_id]['confirm_sell'] = False
        db[conv_id]['items_for_sale'] = {}
        db[conv_id]['debt'] = 0
        db.sync()
    if msg:
        answer = send_msg(msg.lower(), conv_id)
        logger.info(answer)
        post_answer(answer, conv_id)
    return 'OK'

def send_pricelist(url):
    query = urllib.parse.urlparse(url).query
    conv_id = urllib.parse.parse_qs(query)['id'][0]
    try:
        items = db[conv_id]['items_for_sale']
    except KeyError:
        return '<h1>400 Bad Request</h1>'
    return get_pricelist(items)

def send_msg(msg, conv_id):

    def get_accountid(link):
        r = requests.get('http://steamrep.com/search?q={}'.format(link))
        s = BeautifulSoup(r.text, 'html.parser')
        ids_elem = s.find(id='steamids')
        if not ids_elem:
            return None
        ids = ids_elem.text.strip()
        accountid = re.search(r'steam3ID: \[U:1:(.+)\]', ids).group(1)
        return accountid

    def get_items_price(accountid):
        ERROR, OFFER_ID, ITEMS, TOTAL_RUB, TOTAL_USD = range(5)
        result = ['', None, {}, 0, 0]
        while True:
            try:
                offers = steam_client.get_trade_offers()['response']['trade_offers_received']
                break
            except json.decoder.JSONDecodeError as err:
                logger.error(err)
                continue

        client_offer = [offer for offer in offers if offer['accountid_other'] == int(accountid)]
        if not client_offer:
            result[ERROR] = skypebot_text.NO_OFFER
            return result

        if len(client_offer) > 1:
            result[ERROR] = skypebot_text.MULTIPLE_OFFERS
            return result

        offer_data = client_offer[0]
        offer_id = offer_data['tradeofferid']
        result[OFFER_ID] = offer_id

        box_classids = (
            '520025252', '2048553988', '1544067968',
            '1432174707', '1293508920', '926978479',
            '1690096482', '991959905', '1797256701',
            '1923037342'
        )
        boxes_ctr = 0
        currency_rate = get_currency_rate()['RUB']
        items_noprice = set()
        items_amount = collections.defaultdict(int)
        items = []

        if not offer_data.get('items_to_receive'):
            steam_client.decline_trade_offer(offer_id)
            result[ERROR] = skypebot_text.NO_ITEMS
            return result

        if offer_data.get('items_to_give'):
            steam_client.decline_trade_offer(offer_id)
            result[ERROR] = skypebot_text.OFFER_SCAM
            return result

        for item_id in offer_data['items_to_receive']:
            item_appid = offer_data['items_to_receive'][item_id]['appid']
            if item_appid != 730:
                steam_client.decline_trade_offer(offer_id)
                result[ERROR] = skypebot_text.WRONG_ITEM
                return result

            if boxes_ctr > 30:
                steam_client.decline_trade_offer(offer_id)
                result[ERROR] = skypebot_text.MANY_BOXES
                return result

            item_name = offer_data['items_to_receive'][item_id]['market_hash_name']
            classid = offer_data['items_to_receive'][item_id]['classid']
            if classid in box_classids:
                boxes_ctr += 1

            items_amount[item_name] += 1
            if items_amount[item_name] == 1:
                items.append(item_name)

        prices = ops.calculate_prices(items)
        place_to_round_to = None
        for item_name, item_price_usd in prices:
            if not item_price_usd:
                items_noprice.add(item_name)
                continue
            if item_price_usd < 0.1:
                place_to_round_to = 2
            amount = items_amount[item_name]
            item_price_rub = round(item_price_usd * currency_rate, place_to_round_to)
            result[ITEMS][item_name] = (item_price_rub, item_price_usd)
            result[TOTAL_RUB] += item_price_rub * amount
            result[TOTAL_USD] += item_price_usd * amount

        if 0 < result[TOTAL_RUB] < 500:
            result[ERROR] += skypebot_text.LOW_VALUE + '\n'
        if items_noprice:
            result[ERROR] += skypebot_text.ITEMS_NOPRICE.format(', '.join(items_noprice)) + '\n'
        if result[ERROR]:
            steam_client.decline_trade_offer(offer_id)

        return result

    purse = db[conv_id]['purse']
    steam_profile = db[conv_id]['steam_profile']
    offer_id = db[conv_id]['offer_id']
    confirm_data = db[conv_id]['confirm_data']
    accountid = db[conv_id]['steamid']
    confirm_sell = db[conv_id]['confirm_sell']
    debt = db[conv_id]['debt']

    if msg == '-help':
        return skypebot_text.HELP

    elif msg.startswith('-profile'):
        new_profile = None
        new_accountid = None
        if 'http' in msg:
            pattern = re.compile('https?://steamcommunity.com/(id|profiles)/(.+)/?(?=")')
            search_result = pattern.search(msg)
            if search_result:
                new_profile = search_result.group().replace('https', 'http')
            else:
                return skypebot_text.WRONG_PROFILE_LINK
        else:
            msg_splitted = msg.split()
            if len(msg_splitted) != 2:
                return  skypebot_text.WRONG_PROFILE_ID

            id = msg_splitted[1]
            new_profile = 'http://steamcommunity.com/{0}/{1}'.format(
                'profiles' if id.isdigit() else 'id', id)
        new_accountid = get_accountid(new_profile)
        if not new_accountid:
            return skypebot_text.PROFILE_NOT_FOUND

        db[conv_id]['steam_profile'] = new_profile
        db[conv_id]['steamid'] = new_accountid
        db.sync()
        answer = 'Данные о стим профиле сохранены.'
        if purse:
            answer += ' Введи -data чтобы подтвердить данные'
        return answer

    elif msg.startswith('-purse'):
        new_purse = None
        pattern = re.compile(r'(r|z|\+)\d+', re.IGNORECASE)
        search_result = pattern.search(msg)
        if search_result:
            new_purse = search_result.group().upper()
        else:
            return skypebot_text.WRONG_NUMBER
        db[conv_id]['purse'] = new_purse
        db.sync()
        answer = 'Данные о номере кошелька сохранены.'
        if accountid:
            answer += ' Введи -data чтобы подтвердить данные'
        return answer

    elif msg == '-data':
        if purse is None and steam_profile is None:
            return skypebot_text.NO_PURSE + '\n\n' \
                   + skypebot_text.NO_PROFILE

        elif purse is None:
            return skypebot_text.NO_PURSE

        elif steam_profile is None:
            return skypebot_text.NO_PROFILE

        db[conv_id]['confirm_data'] = True
        return skypebot_text.CLIENT_DATA.format(steam_profile, purse, offer)

    elif msg == '-sell':
        if confirm_data:
            error, offer_id, items, price_rub, price_usd = get_items_price(accountid)
            price_usd = round(price_usd, 2)
            price_rub = round(price_rub)
            if error:
                return error

            if purse.startswith('+'):
                balance = qiwipm.get_balance()
                if not balance:
                    return skypebot_text.QIWI_WALLET_NOT_FOUND
                balance = round(balance * 0.99)
                price = price_rub
            elif purse.startswith('R'):
                balance = float(wmpm.get_balance()['WMR']) * 0.99
                price = price_rub
            elif purse.startswith('Z'):
                balance = float(wmpm.get_balance()['WMZ']) * 0.99
                price = price_usd

            db[conv_id]['items_for_sale'] = items
            pricelist_url = 'http://3f4bf5f0.ngrok.io/?id=' + conv_id
            answer = skypebot_text.OFFERED_PRICE.format(price_rub, price_usd,
                                                        pricelist_url)
            if balance < price:
                if price / balance <= 1.03:
                    answer = skypebot_text.OFFER_NEWPRICE.format(balance)
                else:
                    steam_client.decline_trade_offer(offer_id)
                    return skypebot_text.INSUFFICIENT_FUNDS.format(balance)

            db[conv_id]['offer_id'] = offer_id
            db[conv_id]['confirm_sell'] = True
            db[conv_id]['debt'] = price
            db.sync()
            return answer
        else:
            return 'Введи -data чтобы подтвердить данные'

    elif msg == '-accept':
        if confirm_data and confirm_sell:
            attempts = 0
            error_16 = (False,)
            while True:
                if attempts == 3:
                    return skypebot_text.OFFER_ERROR

                conf_trade = steam_client.accept_trade_offer(offer_id, db[conv_id]['steamid'])
                logger.info('confirmation trade response: ' + str(conf_trade))
                if conf_trade.get('tradeid') is None:
                    error = conf_trade.get('strError', '')
                    if '(16)' in error:
                        error_16 = (True, offer_id)
                        break
                    elif '(25)' in error:
                        steam_client.decline_trade_offer(offer_id)
                        return skypebot_text.OVERLOADED
                    elif '(11)' in error:
                        return skypebot_text.ERROR_ELEVEN
                    elif '(2)' in error:
                        return skypebot_text.ERROR_TWO
                    attempts += 1
                else:
                    break

            if purse.startswith('+'):
                success, error = qiwipm.init_payment(purse, debt)
            elif any(map(purse.startswith, 'RZ')):
                success = wmpm.init_payment(purse, debt)

            close_client_session(conv_id, debt)
            winsound.Beep(500, 1000)

            if success:
                return skypebot_text.CONFIRM_PAYMENT

            logger.info('payment failed: ' + purse + str(debt))
            if error:
                return skypebot_text.PAYMENT_ERROR.format(error)
            return skypebot_text.PAYMENT_FAILED

        elif not confirm_data:
            return 'Введи -data чтобы подтвердить данные.'
        else:
            return 'Введи -sell чтобы узнать нашу цену за ваши скины'

    elif msg == '-decline':
        if confirm_sell:
            close_client_session(conv_id, debt)
            resp = steam_client.decline_trade_offer(offer_id)
            logger.info(str(resp))
            return skypebot_text.DECLINE
        return 'Не зафиксировано какой-либо сделки, чтобы ее отклонять.'

    elif msg == '-balance':
        return get_balance()

    elif msg == '-rate':
        if not accountid:
            return skypebot_text.NO_PROFILE_LINK
        result = eval_rate(accountid)
        if not result:
            return skypebot_text.RATE_ERROR
        items, price_usd, price_rub, unpopular_items = result
        db[conv_id]['items_for_sale'] = items
        db.sync()
        pricelist_url = 'http://3f4bf5f0.ngrok.io/?id=' + conv_id
        answer = skypebot_text.RATE_RESULT.format(price_rub, price_usd, pricelist_url)
        if unpopular_items:
            answer += '\n\n' + skypebot_text.UNPOPULAR_ITEMS_WARNING.format(', '.join(unpopular_items))
        answer += '\n\n' + get_balance()
        return answer
    else:
        return 'Введи -help чтобы получить список команд.'

def get_balance():
    balance_qiwi = str(round(qiwipm.get_balance())) + ' QIWI RUB'
    wm_balances = wmpm.get_balance()
    balance_wmr = wm_balances['WMR'] + ' WMR'
    balance_wmz = wm_balances['WMZ'] + ' WMZ'
    balance_total = '\n'.join((balance_qiwi, balance_wmr, balance_wmz))
    return 'Резервы на данный момент:\n{}'.format(balance_total)

def eval_rate(accountid):
    currency_rate = get_currency_rate()['RUB']
    steamid = account_id_to_steam_id(accountid)
    # appids = fetch_appids(steamid)
    # if not appids:
    #     return

    attempts = 0
    resp = None
    while attempts < 3:
        try:
            resp = requests.get('http://steamcommunity.com/inventory/'
                                '{}/730/2?l=english&count=1000'.format(steamid)).json()
            break
        except json.decoder.JSONDecodeError as err:
            logger.error('%s %s' % (resp, err))
            attempts += 1

    if not resp:
        logger.info('inventory json response: %s' % resp)
        return

    assets_amount = collections.defaultdict(int)
    for asset in resp['assets']:
        classid = asset['classid']
        assets_amount[classid] += 1

    items = [item['market_hash_name'] for item in resp['descriptions']
             if item['tradable']]

    price_usd = 0
    price_rub = 0
    place_to_round_to = None
    result = {}
    unpopular_items = set()
    prices = ops.calculate_prices(items)
    for item_name, item_price_usd in prices.items():
        if not item_price_usd:
            unpopular_items.add(item_name)
            continue
        if item_price_usd < 0.1:
            place_to_round_to = 2
        item_price_rub = round(item_price_usd * currency_rate, place_to_round_to)
        amount = assets_amount[classid]
        price_usd += item_price_usd * amount
        price_rub += item_price_rub * amount
        result[item_name] = (item_price_rub, item_price_usd)

    return (result, round(price_usd, 2), round(price_rub), unpopular_items)

def get_currency_rate():
    while True:
        try:
            return requests.get('http://api.fixer.io/latest?base=USD').json()['rates']
        except json.decoder.JSONDecodeError as err:
            logger.error(err)

def fetch_appids(steamid):
    resp = requests.get('http://steamcommunity.com/profiles/{}/inventory/'.format(steamid))
    re_pattern = r'var g_rgAppContextData = (.+})'
    try:
        result = re.search(re_pattern, resp.text).group(1)
    except AttributeError:
        return
    appids = json.loads(result).keys()
    return appids

def close_client_session(conv_id, debt):
    db[conv_id]['confirm_data'] = False
    db[conv_id]['confirm_sell'] = False
    db[conv_id][debt] = 0
    db.sync()

def get_token():
    while True:
        global token
        payload = {
            'client_id': '8fa47e40-90f2-4a46-a3b7-0f64402234ff',
            'client_secret': 'DsaiXQWM3mRF0nDKySLAE3B',
            'grant_type': 'client_credentials',
            'response_mode':'query',
            'scope':'https://graph.microsoft.com/.default',
        }
        r = requests.post('https://login.microsoftonline.com/common/oauth2/v2.0/token',
                          headers={'Cache-Control': 'no-cache',
                                   'Content-Type': 'application/x-www-form-urlencoded'},
                          data=payload)
        token = r.json()['access_token']
        sleep(300)

def get_pricelist(items):
    with open('./data/pricelist.html', 'r') as f:
        html = f.read()

    data = ''
    for name, values in reversed(sorted(items.items(), key=lambda x: x[1][0])):
        data += '<tr>'
        item_price_rub, item_price_usd = values
        data += '\n\t\t<td>{}</td><td>{}₽</td><td>{}$</td>'.format(
            name, item_price_rub, item_price_usd)
        data += '</tr>\n'

    return html % data


def calculate_prices(responses):
    today = datetime.today()
    rates = ('1': 0.72, '3': 0.71, '7': 0.7)
    rate = 0.72
    result = []
    prices_db = shelve.open('pricehistory.dat')
    for resp in responses:
        query = urllib.parse.urlparse(resp.url).query
        parsed_qs = urllib.parse.parse_qs(query)
        skin_name = parsed_qs['market_hash_name'][0]
        resp = resp.json()
        average_price = None
        if not resp['success']:
            logger.info('%s %s' % (resp, skin_name))
            raise Exception('The steam pricehistory server responded with failure')
        stats = sort_statistics(resp['prices'], today)
        for timespan, stats in sorted(stats.items()):
            total_volume = sum((int(element[2]) for element in stats))
            if total_volume >= 5:
                prices = [i for element in stats for i in [element[1]] * int(element[2])]
                average_price = statistics.mean(prices)
                break

        if average_price is None:
            average_price = get_unpopular_itemprice(skin_name)
            average_price *= rate
            prices_db[skin_name] = average_price
            logger.info('%s %s' % average_price, skin_name)
            result.append((skin_name, average_price))
            continue

        calc_average_price_again = False
        for price in prices:
            coef = price / average_price
            if coef <= 0.5 or coef >= 2:
                prices.remove(price)
                if not calc_average_price_again:
                    calc_average_price_again = True
        if calc_average_price_again:
            average_price = statistics.mean(prices)

        average_trend = determine_trend(today, timespan, stats, average_price)
        if average_trend < 1:
            average_price *= average_trend
        average_price *= rate
        prices_db[skin_name] = average_price
        logger.info('%s %s %s %s' % (average_price, average_trend, timespan, skin_name))
        result.append((skin_name, average_price))

    prices_db.close()
    return result


def sort_statistics(stats, current_day):
    result = {'1': [], '3': [], '7': []}
    for item in stats:
        date, price = item[:2]
        date = datetime.strptime(date.replace(': +0', ''), '%b %d %Y %H')
        delta_days = (current_day - date).days
        if delta_days < 1:
            result['1'].append(item)
        if delta_days < 3:
            result['3'].append(item)
        if delta_days < 7 or price > 21000 and delta_days < 30:
            result['7'].append(item)

    return result

def determine_trend(current_day, timespan, stats, average_price):
    trend_timespan = {'1': 6, '3': 24, '7': 72}
    trend_hours = trend_timespan[timespan]
    trend_prices = []
    while not trend_prices:
        for item in stats:
            date, price, volume = item
            date = datetime.strptime(date.replace(': +0', ''), '%b %d %Y %H')
            delta_hours = (current_day - date).total_seconds() // 3600
            if delta_hours < trend_hours:
                for _ in range(int(volume)):
                    trend_prices.append(price)
        trend_hours += trend_hours

    average_trend = statistics.mean((price / average_price for price in trend_prices))
    return average_trend

def get_unpopular_itemprice(item_name):
    pass

threading.Thread(target=get_token).start()
app.run(port=3000)
