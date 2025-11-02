import json
import time
from typing import List, Tuple, Optional

import requests
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import Select

# For terminal beatify
from rich.console import Console

console = Console()


class CF_TC:
    def __init__(self):
        options = uc.ChromeOptions()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        # Remove headless to allow manual interaction if needed
        # options.add_argument("--headless")
        self.driver = uc.Chrome(options=options, version_main=None)
        self.base_url = "https://codeforces.com/"
        self.close = self.driver.close

    def _isProblemExists(self, contest_id, problem_index):
        url = f"{self.base_url}api/contest.standings?contestId={contest_id}&from=1&count=1"
        r = requests.get(url)
        r = r.json()
        # r = json.loads(r)

        if r["status"] != "OK":
            x = str(
                input("Codeforces API is down.\nDo you still want to continue (y/n): ")
            )
            if x == "n":
                return (None, "Codeforces API is down")

        for i in r["result"]["problems"]:
            if str(problem_index) == i["index"]:
                return (True, "Problem found")

        return (None, "Problem does not exists")

        # https://codeforces.com/api/contest.standings?contestId=566&from=1&count=1

    def _getSubmissionID(self, contest_id, problem_index):
        # Get to the contest submission page
        self.driver.get(f"{self.base_url}contest/{contest_id}/status")

        # Wait longer for Cloudflare to pass
        time.sleep(10)
        # Check if still on challenge page
        if "Just a moment" in self.driver.title or "Verify you are human" in self.driver.page_source:
            console.log("Still on Cloudflare challenge, waiting longer...")
            time.sleep(20)

        # Debug: print page title
        console.log(f"Page title: {self.driver.title}")

        # applying filters for the problem and verdict to be `accepted`
        if self.wait_till_load('//*[@id="frameProblemIndex"]', 10):
            select = Select(
                self.driver.find_element(By.XPATH, '//*[@id="frameProblemIndex"]')
            )

            select.select_by_index(ord(problem_index) - ord("A") + 1)
            console.log("Problem filter applied")

        else:
            console.log("frameProblemIndex not found, trying alternatives")
            # Try alternative XPaths
            alternatives = [
                '//*[@name="frameProblemIndex"]',
                '//select[@id="frameProblemIndex"]',
                '//select[contains(@id, "problem")]',
            ]
            for alt in alternatives:
                if self.wait_till_load(alt, 5):
                    select = Select(self.driver.find_element(By.XPATH, alt))
                    select.select_by_index(ord(problem_index) - ord("A") + 1)
                    console.log(f"Used alternative XPath: {alt}")
                    break
            else:
                return (None, "Error while filtering problem index")

        if self.wait_till_load('//*[@id="verdictName"]', 10):
            verdict = Select(
                self.driver.find_element(By.XPATH, '//*[@id="verdictName"]')
            )

            verdict.select_by_index(1)
            console.log("Verdict filter applied")

            # Try multiple ways to find the apply button
            apply_found = False
            for xpath in [
                "/html/body/div[6]/div[4]/div[1]/div[4]/div[2]/form/div[2]/input[1]",
                "//input[@value='Apply']",
                "//input[@type='submit']",
                "//button[contains(text(), 'Apply')]",
            ]:
                if self.wait_till_load(xpath, 5):
                    apply_btn = self.driver.find_element(By.XPATH, xpath)
                    apply_btn.click()
                    time.sleep(3)
                    console.log(f"Apply button clicked using {xpath}")
                    apply_found = True
                    break
            if not apply_found:
                console.log("Apply button not found with any XPath")
                return (None, "Error while clicking apply button")
        else:
            console.log("verdictName not found")
            return (None, "Error while filtering problem verdict")

        # Wait a bit more for the page to update after filtering
        time.sleep(5)

        # Try multiple XPaths for submission link
        link_found = False
        xpaths = [
            "/html/body/div[6]/div[4]/div[2]/div[2]/div[6]/table/tbody/tr[1]/td[1]/a",  # Try tr[1]
            "/html/body/div[6]/div[4]/div[2]/div[2]/div[6]/table/tbody/tr[2]/td[1]/a",
            "//table//tbody//tr[1]//td[1]//a",
            "//table//tbody//tr[2]//td[1]//a",
            "//a[contains(@href, '/submission/')]",
            "//td[@class='id']//a",  # Common class for ID column
        ]
        for xpath in xpaths:
            if self.wait_till_load(xpath, 5):
                content = self.driver.find_element(By.XPATH, xpath)
                console.log(f"Found submission ID: {content.text} using {xpath}")
                return (True, content.text)
        console.log("Submission link not found with any XPath")
        # Debug: print some page source
        try:
            table = self.driver.find_elements(By.XPATH, "//table//tbody//tr")
            console.log(f"Found {len(table)} table rows")
            if table:
                first_row = table[0].text
                console.log(f"First row text: {first_row[:100]}...")
        except Exception as e:
            console.log(f"Error checking table: {e}")
        return (None, "Error while finding Submission ID ")

    def get_testcases(self, contest_id, problem_num):
        problem_exist = self._isProblemExists(contest_id, problem_num)
        if not problem_exist[0]:
            return problem_exist

        console.log("Found the problem")

        submission_id = self._getSubmissionID(contest_id, problem_num)

        if not submission_id[0]:
            return submission_id

        self.driver.get(
            f"https://codeforces.com/contest/{contest_id}/submission/{submission_id[1]}"
        )

        # Wait for Cloudflare
        time.sleep(10)
        if "Just a moment" in self.driver.title or "Verify you are human" in self.driver.page_source:
            console.log("Still on Cloudflare challenge for submission, waiting longer...")
            time.sleep(20)

        # Try multiple ways to find the "Tests" button
        tests_found = False
        for xpath in [
            "/html/body/div[6]/div[4]/div/div[4]/div[2]/a",
            "//a[contains(text(), 'Tests')]",
            "//a[contains(@href, '#tests')]",
            "//div[@class='tests']//a",
        ]:
            if self.wait_till_load(xpath, 5):
                click_btn = self.driver.find_element(By.XPATH, xpath)
                click_btn.click()
                console.log(f"Clicked Tests button using {xpath}")
                time.sleep(3)
                tests_found = True
                break
        if not tests_found:
            console.log("Tests button not found, trying to find tests directly")

        if self.wait_till_load("/html/body/div[6]/div[4]/div/div[4]/div[3]", 10):
            input = self.driver.find_elements(By.CLASS_NAME, "input")
            output = self.driver.find_elements(By.CLASS_NAME, "output")
            console.log(f"Found {len(input)} input elements, {len(output)} output elements")

            tc = []
            for i in range(len(input)):
                tc.append((input[i].text, output[i].text))
            tc = tc[1:] if len(tc) > 1 else tc  # Skip first if more than one
            console.log(f"Total test cases found : {len(tc)}")
            return (True, tc)
        else:
            console.log("Tests div not found")

        return (None, "Error while finding test cases")

    def wait_till_load(self, xpath_value, delay=3):
        try:
            myElem = WebDriverWait(self.driver, delay).until(
                EC.presence_of_element_located((By.XPATH, xpath_value))
            )
            # print("Page is ready!")
            return 1
        except TimeoutException:
            # print("Loading took too much time!")
            return 0
