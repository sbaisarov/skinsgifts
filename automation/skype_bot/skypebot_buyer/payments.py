from time import sleep, time
import traceback
import threading
import requests
from webmoney_api import ApiInterface, WMLightAuthInterface

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException


class QiwiPayment:

	def __init__(self, driver):
		self.req_headers = {
		'Accept': 'application/json, text/javascript, */*; q=0.01',
		'Host': 'qiwi.com',
		'Origin': 'https://qiwi.com',
		'Referer': 'https://qiwi.com/main.action',
		'User-Agent':('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
					  '(KHTML, like Gecko) Chrome/56.0.2924.87 Safari/537.36'),
		'X-Requested-With': 'XMLHttpRequest'
		}
		self.driver = driver
		self.driver.maximize_window()
		self.wait = WebDriverWait(self.driver, 15)
		self.lock = threading.Lock()
		self._login()

		threading.Thread(target=self._refresh).start()


	def get_balance(self):
		balance = None
		with self.lock:
			cookies = self._get_cookies()
		try:
			resp = requests.post('https://qiwi.com/person/state.action', cookies=cookies,
							   	 headers=self.req_headers)
			balance = resp.json()['data']['balances']['RUB']
		except Exception:
			print(resp.text)
			print("Couldn't get the balance")
			print(traceback.format_exc())

		return balance


	def init_payment(self, purse, amount):
		error = None
		self.lock.acquire()
		try:
			self.driver.get('https://qiwi.com/payment/form.action?provider=99')
			self.wait.until(EC.visibility_of_element_located(
							(By.CLASS_NAME, 'account_current_amount')))
			self.wait.until(EC.visibility_of_element_located(
							(By.XPATH, '//div[text()="Перевод дойдет мгновенно. "]')))
			self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
			number_input = (self.driver.find_element_by_xpath('//div[@data-name="account"]')
							.find_element_by_tag_name('input'))
			sleep(2)
			number_input.click()
			number_input.send_keys(purse); sleep(2)
			amount_input = self.driver.find_element_by_xpath('//input[@placeholder="0.00"]')
			amount_input.click(); amount_input.send_keys(str(amount)); sleep(3)
			self.driver.find_element_by_xpath('//div[text()="Оплатить"]').click()
			accept_element = self.wait.until(EC.visibility_of_element_located(
								(By.XPATH, '//div[text()="Подтвердить"]')))
			accept_element.click()
			try:
				self.wait.until(EC.visibility_of_element_located(
								(By.CLASS_NAME, 'payment-success')))
			except TimeoutException:
				error = self.driver.find_element_by_css_selector('div.ui-dialog-content.ui-widget-content').text
				return (False, error)
		except Exception:
			print(traceback.format_exc())
			return (False, None)

		self.lock.release()
		return (True, None)

	def deposit_in_steam_account(self, account_name, amount):
		error = None
		self.lock.acquire()
		try:
			self.driver.get('https://qiwi.com/payment/form.action?provider=25549')
			self.wait.until(EC.visibility_of_element_located(
							(By.CLASS_NAME, 'qiwi-payment-amount-control')))
			self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
			name_input = (self.driver.find_element_by_xpath('//div[@data-name="account"]')
							.find_element_by_tag_name('input'))
			sleep(2)
			name_input.click()
			number_input.send_keys(account_name); sleep(2)
			amount_input = self.driver.find_element_by_xpath('//input[@placeholder="0.00"]')
			amount_input.click(); amount_input.send_keys(str(amount)); sleep(3)
			self.driver.find_element_by_xpath('//div[text()="Оплатить"]').click()
			accept_element = self.wait.until(EC.visibility_of_element_located(
								(By.XPATH, '//div[text()="Подтвердить"]')))
			accept_element.click()
			try:
				self.wait.until(EC.visibility_of_element_located(
								(By.CLASS_NAME, 'payment-success')))
			except TimeoutException:
				error = self.driver.find_element_by_css_selector('div.ui-dialog-content.ui-widget-content').text
				return (False, error)
		except Exception:
			print(traceback.format_exc())
			return (False, None)

		self.lock.release()
		return (True, None)

	def _login(self):
		while True:
			try:
				self.driver.get('https://qiwi.com/main.action')
				self.driver.find_element_by_class_name("signinBtn").click()
				login_element = self.wait.until(EC.visibility_of_element_located(
								(By.XPATH, '//input[@type="tel"]')))
				login_element.clear()
				login_element.send_keys('+79659660934')
				break
			except (NoSuchElementException, TimeoutException):
				pass
		passwd_element=  self.driver.find_element_by_class_name('qw-auth-form-password-remind-input')
		passwd_element.send_keys('/nCc0WvwmyqH')
		self.driver.find_element_by_class_name('qw-auth-form-button').click()
		try:
			self.wait.until(EC.visibility_of_element_located((By.CLASS_NAME, 'account_current_amount')))
		except TimeoutException:
			self.driver.refresh()
		self._get_cookies(update_node_cookie=True)


	def _refresh(self):
		ctr = 0
		while True:
			sleep(500)
			self.lock.acquire()
			try:
				self.driver.refresh()
				self.wait.until(EC.visibility_of_element_located((By.CLASS_NAME, 'account_current_amount')))
			except TimeoutException as err:
				print(err)

			self._get_cookies(update_node_cookie=True)
			ctr += 1
			if ctr == 8:
				self.driver.find_element_by_class_name('logout').click()
				sleep(5)
				self._login()
				ctr = 0

			self.lock.release()


	def _get_cookies(self, update_node_cookie=False):
		cookies = {cookie['name']: cookie['value'] for cookie in self.driver.get_cookies()
				   								   if cookie['domain'] == 'qiwi.com'}
		if update_node_cookie == True:
			requests.post('https://qiwi.com/person/state.action',
						  cookies=cookies, headers=self.req_headers)
		return cookies


class WmPayment:

	def __init__(self, keys_path):
		self.api = ApiInterface(WMLightAuthInterface(
			keys_path + "/crt.pem", keys_path + "/key.pem"))


	def get_balance(self):
		WMR, WMZ = 0, 1
		response = self.api.x9(wmid="552106941804", reqn=str(int(time())))
		try:
			purses = response['response']['purse']
		except KeyError:
			return 'Произошла ошибка. Не удалось определить баланс.'
		return purses[WMR]['amount'], purses[WMZ]['amount']


	def init_payment(self, purse, amount, desc=""):
		token = str(int(time()))
		pursesrc = 'R399262875875' if purse.startswith('R') else 'Z379170664340'
		response = self.api.x2(pursesrc=pursesrc, pursedest=purse, reqn=token,
			   			  	   tranid=token, amount=str(amount), period="0", desc=desc,
			   			  	   onlyauth="0", wmb_denomination="0", wminvid="0")

		return response


if __name__ == '__main__':
	wm = WmPayment('data')
	resp = wm.init_payment('R100798908509', 5, 'invoice[990143168525325]')
	print(resp)
