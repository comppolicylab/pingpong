import time
import atexit

from pingpong.scripts.qualtrics.vars import AIRTABLE_WEBHOOK_URL, QUALTRICS_BASE_URL
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

if not QUALTRICS_BASE_URL:
    raise ValueError("Missing Qualtrics Base URL in environment.")
else:
    _QUALTRICS_BASE_URL = QUALTRICS_BASE_URL

if not AIRTABLE_WEBHOOK_URL:
    raise ValueError("Missing Airtable Webhook for automation in environment.")
else:
    _AIRTABLE_WEBHOOK = AIRTABLE_WEBHOOK_URL


class QualtricsWebDriver:
    def __init__(self, email: str):
        self.email = email
        self.qualtrics_base = _QUALTRICS_BASE_URL
        self.airtable_webhook = _AIRTABLE_WEBHOOK

        self.driver = webdriver.Firefox()
        self.wait = WebDriverWait(self.driver, timeout=60)
        self.logged_in = False

        atexit.register(self.cleanup)

    def cleanup(self):
        print("Cleaning up...")
        self.driver.quit()

    def login(self):
        self.driver.get(f"{self.qualtrics_base}/homepage/ui")
        input = self.wait.until(
            EC.visibility_of_element_located((By.XPATH, "//input[@id='identifier']"))
        )
        input.send_keys(self.email)
        button = self.driver.find_element(By.XPATH, "//button[@type='submit']")
        button.click()
        input = self.wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(.,'Security Key')]")
            )
        )
        input.click()
        self.wait.until(
            EC.visibility_of_element_located((By.XPATH, "//h1[contains(., 'Home')]"))
        )
        self.logged_in = True

    def enable_survey_workflow(self, survey_id: str):
        if not self.logged_in:
            self.login()
        self.driver.get(
            f"{self.qualtrics_base}/workflows/ui/{survey_id}/{survey_id}/list"
        )
        checkbox_label = self.wait.until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, "label._lOeMA._IyuND"))
        )
        input = checkbox_label.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
        input.click()

    def enable_response_collection(self, survey_id: str):
        if not self.logged_in:
            self.login()
        self.driver.get(
            f"{self.qualtrics_base}/app/comms-navigator/surveys/{survey_id}/anonymous-links"
        )
        input = self.wait.until(
            EC.element_to_be_clickable(
                (
                    By.CSS_SELECTOR,
                    "div._13uaN:nth-child(2) > div:nth-child(2) > button:nth-child(1)",
                )
            )
        )
        input.click()

    def create_survey_workflow(self, survey_id: str):
        if not self.logged_in:
            self.login()
        self.driver.get(
            f"{self.qualtrics_base}/workflows/ui/{survey_id}/{survey_id}/list"
        )
        input = self.wait.until(
            EC.visibility_of_element_located(
                (By.XPATH, "//button[contains(.,'Create a workflow')]")
            )
        )
        input.click()
        input = self.wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//div[div[text()='Started when an event is received']]")
            )
        )
        input.click()
        self.wait.until(
            EC.frame_to_be_available_and_switch_to_it(
                (By.ID, "extension-selector-iframe")
            )
        )
        input = self.wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//span[text()='Survey response']/ancestor::div[@class='extension-tile-container']//div[@class='extension-tile-contents']",
                )
            )
        )
        input.click()
        self.driver.switch_to.default_content()
        input = self.wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[div[div[text()='Finish']]]")
            )
        )
        input.click()
        input = self.wait.until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, 'svg[data-icontype="AddItem"][role="button"]')
            )
        )
        input.click()
        input = self.wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "div._dTvz3:nth-child(1)"))
        )
        input.click()
        input = self.wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//div[contains(@class, 'extensionTile-c7ef7e1b') and .//div[text()='WebService']]",
                )
            )
        )
        input.click()
        input = self.wait.until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "div.pluginContainer-e78dfd2b11181bd3:nth-child(2)")
            )
        )
        input.click()
        input = self.wait.until(
            EC.element_to_be_clickable((By.XPATH, "//button[@id='next']"))
        )
        input.click()
        self.wait.until(
            EC.frame_to_be_available_and_switch_to_it((By.ID, "plugin-iframe"))
        )
        input = self.wait.until(
            EC.element_to_be_clickable((By.XPATH, "//button[span[text()='GET']]"))
        )
        input.click()
        input = self.wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "div._83Z1J:nth-child(2)"))
        )
        input.click()
        input = self.wait.until(
            EC.visibility_of_element_located((By.XPATH, "//input[@id='url-input']"))
        )
        input.send_keys(
            "https://hooks.airtable.com/workflows/v1/genericWebhook/appkYePjv3xImn60Z/wfloOsBiJNdfR5oBP/wtr9a2iX7SHaWxJAD"
        )
        add_key_value_pair_btn = self.wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button._-mZir:nth-child(12)"))
        )
        add_key_value_pair_btn.click()
        input = self.wait.until(
            EC.visibility_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "div.body-key-value-table > div:nth-child(2) > div:nth-child(1) > div:nth-child(1) > div:nth-child(1) > div:nth-child(1) > input:nth-child(1)",
                )
            )
        )
        input.send_keys("airtable_class_id")
        input = self.wait.until(
            EC.visibility_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "div.body-key-value-table > div:nth-child(2) > div:nth-child(1) > div:nth-child(2) > div:nth-child(1) > div:nth-child(1) > input:nth-child(1)",
                )
            )
        )
        input.send_keys("${e://Field/pp_airtable_class_RID}")
        input = self.wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[span[contains(.,'Translation')]]")
            )
        )
        input.click()
        input = self.wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "div._83Z1J:nth-child(4)"))
        )
        input.click()
        add_key_value_pair_btn.click()
        input = self.wait.until(
            EC.visibility_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "div.row:nth-child(2) > div:nth-child(1) > div:nth-child(1) > div:nth-child(1) > input:nth-child(1)",
                )
            )
        )
        input.send_keys("airtable_student_id")
        input = self.wait.until(
            EC.visibility_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "div.row:nth-child(2) > div:nth-child(2) > div:nth-child(1) > div:nth-child(1) > input:nth-child(1)",
                )
            )
        )
        input.send_keys("${e://Field/__js_airtable_student_RID}")
        input = self.wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[span[contains(.,'Translation')]]")
            )
        )
        input.click()
        input = self.wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "div._83Z1J:nth-child(4)"))
        )
        input.click()
        add_key_value_pair_btn.click()
        input = self.wait.until(
            EC.visibility_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "div.row:nth-child(3) > div:nth-child(1) > div:nth-child(1) > div:nth-child(1) > input:nth-child(1)",
                )
            )
        )
        input.send_keys("class_id")
        input = self.wait.until(
            EC.visibility_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "div.row:nth-child(3) > div:nth-child(2) > div:nth-child(1) > div:nth-child(1) > input:nth-child(1)",
                )
            )
        )
        input.send_keys("${e://Field/pp_class_id}")
        input = self.wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[span[contains(.,'Translation')]]")
            )
        )
        input.click()
        input = self.wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "div._83Z1J:nth-child(4)"))
        )
        input.click()
        add_key_value_pair_btn.click()
        input = self.wait.until(
            EC.visibility_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "div.row:nth-child(4) > div:nth-child(1) > div:nth-child(1) > div:nth-child(1) > input:nth-child(1)",
                )
            )
        )
        input.send_keys("completed_at")
        input = self.wait.until(
            EC.visibility_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "div.row:nth-child(4) > div:nth-child(2) > div:nth-child(1) > div:nth-child(1) > input:nth-child(1)",
                )
            )
        )
        input.send_keys("${rm://Field/EndDate}")
        input = self.wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[span[contains(.,'Translation')]]")
            )
        )
        input.click()
        input = self.wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "div._83Z1J:nth-child(4)"))
        )
        input.click()
        add_key_value_pair_btn.click()
        input = self.wait.until(
            EC.visibility_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "div.row:nth-child(5) > div:nth-child(1) > div:nth-child(1) > div:nth-child(1) > input:nth-child(1)",
                )
            )
        )
        input.send_keys("response_id")
        input = self.wait.until(
            EC.visibility_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "div.row:nth-child(5) > div:nth-child(2) > div:nth-child(1) > div:nth-child(1) > input:nth-child(1)",
                )
            )
        )
        input.send_keys("${rm://Field/ResponseID}")
        input = self.wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[span[contains(.,'Translation')]]")
            )
        )
        input.click()
        input = self.wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "div._83Z1J:nth-child(4)"))
        )
        input.click()
        add_key_value_pair_btn.click()
        input = self.wait.until(
            EC.visibility_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "div.row:nth-child(6) > div:nth-child(1) > div:nth-child(1) > div:nth-child(1) > input:nth-child(1)",
                )
            )
        )
        input.send_keys("response_url")
        input = self.wait.until(
            EC.visibility_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "div.row:nth-child(6) > div:nth-child(2) > div:nth-child(1) > div:nth-child(1) > input:nth-child(1)",
                )
            )
        )
        input.send_keys("${srr://SingleResponseReportLink?ttl=0}")
        input = self.wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[span[contains(.,'Translation')]]")
            )
        )
        input.click()
        input = self.wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "div._83Z1J:nth-child(4)"))
        )
        input.click()
        add_key_value_pair_btn.click()
        input = self.wait.until(
            EC.visibility_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "div.row:nth-child(7) > div:nth-child(1) > div:nth-child(1) > div:nth-child(1) > input:nth-child(1)",
                )
            )
        )
        input.send_keys("student_email")
        input = self.wait.until(
            EC.visibility_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "div.row:nth-child(7) > div:nth-child(2) > div:nth-child(1) > div:nth-child(1) > input:nth-child(1)",
                )
            )
        )
        input.send_keys("${q://QID3/ChoiceTextEntryValue}")
        input = self.wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[span[contains(.,'Translation')]]")
            )
        )
        input.click()
        input = self.wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "div._83Z1J:nth-child(4)"))
        )
        input.click()
        add_key_value_pair_btn.click()
        input = self.wait.until(
            EC.visibility_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "div.row:nth-child(8) > div:nth-child(1) > div:nth-child(1) > div:nth-child(1) > input:nth-child(1)",
                )
            )
        )
        input.send_keys("student_name")
        input = self.wait.until(
            EC.visibility_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "div.row:nth-child(8) > div:nth-child(2) > div:nth-child(1) > div:nth-child(1) > input:nth-child(1)",
                )
            )
        )
        input.send_keys("${q://QID2/ChoiceTextEntryValue}")
        input = self.wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[span[contains(.,'Translation')]]")
            )
        )
        input.click()
        input = self.wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "div._83Z1J:nth-child(4)"))
        )
        input.click()
        self.driver.switch_to.default_content()
        input = self.wait.until(
            EC.element_to_be_clickable((By.XPATH, "//button[@id='save']"))
        )
        input.click()
        time.sleep(5)
        input = self.wait.until(
            EC.visibility_of_element_located(
                (By.CSS_SELECTOR, ".input-c51b87277f8bbe8a")
            )
        )
        input.send_keys(Keys.CONTROL + "a")
        input.send_keys(Keys.DELETE)
        input.send_keys("Send student responses to Airtable")
        input = self.wait.until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, ".closeButton-c51b87277f8bbe8a")
            )
        )
        input.click()
