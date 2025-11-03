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

    def _wait_until_ready(self, expected_xpath: str, total_timeout: int = 90, poll: float = 1.5) -> bool:
        """
        Waits until Cloudflare challenge is gone and the expected element appears.
        Returns True if the expected element is present before timeout.
        """
        start = time.time()
        while time.time() - start < total_timeout:
            title = self.driver.title or ""
            page = self.driver.page_source or ""
            if ("Just a moment" in title) or ("Verify you are human" in page):
                time.sleep(poll)
                continue
            try:
                WebDriverWait(self.driver, poll).until(
                    EC.presence_of_element_located((By.XPATH, expected_xpath))
                )
                return True
            except Exception:
                time.sleep(poll)
        return False

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

        # Wait until the filter select is available (Cloudflare passed + page ready)
        if not self._wait_until_ready('//*[@id="frameProblemIndex"]', total_timeout=120, poll=2.0):
            console.log("Timed out waiting for status page to be ready")
            return (None, "Status page not ready")

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

        # Wait a bit more for the table to update after filtering (or re-render)
        self._wait_until_ready("//table", total_timeout=30, poll=1.0)

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

        # Try to wait for Cloudflare challenge to clear, but proceed regardless
        _ = self._wait_until_ready("//a[contains(@href, '#tests')]", total_timeout=60, poll=2.0)
        console.log(f"Submission page title: {self.driver.title}")

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
        # Fallback to sample tests from problem statement
        console.log("Falling back to sample tests from problem page")
        samples = self._fetch_sample_tests_via_selenium(contest_id, problem_num)
        if samples[0] and samples[1]:
            return (True, samples[1])
        return (None, "Error while finding test cases")

    def _fetch_sample_tests_via_selenium(self, contest_id: str, problem_index: str) -> Tuple[Optional[bool], List[Tuple[str, str]]]:
        urls = [
            f"{self.base_url}contest/{contest_id}/problem/{problem_index}",
            f"{self.base_url}problemset/problem/{contest_id}/{problem_index}",
        ]
        for url in urls:
            try:
                self.driver.get(url)
                if not self._wait_until_ready("//div[contains(@class,'sample-test')]", total_timeout=60, poll=1.5):
                    continue
                # Gather sample inputs/outputs
                inputs = self.driver.find_elements(By.CSS_SELECTOR, "div.sample-test div.input pre, div.sample-tests div.input pre")
                outputs = self.driver.find_elements(By.CSS_SELECTOR, "div.sample-test div.output pre, div.sample-tests div.output pre")
                tc: List[Tuple[str, str]] = []
                for i, o in zip(inputs, outputs):
                    tc.append((i.text, o.text))
                if tc:
                    console.log(f"Total sample test cases found: {len(tc)}")
                    return (True, tc)
            except Exception:
                continue
        return (None, ["No sample tests found"]) 

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
