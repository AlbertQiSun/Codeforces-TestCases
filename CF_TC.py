import json
import time
from typing import List, Tuple, Optional

import cloudscraper
import requests
from bs4 import BeautifulSoup

# For terminal beatify
from rich.console import Console

console = Console()


class CF_TC:
    def __init__(self):
        self.base_url = "https://codeforces.com/"
        self.scraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "darwin", "mobile": False})

    def _isProblemExists(self, contest_id, problem_index):
        url = f"{self.base_url}api/contest.standings?contestId={contest_id}&from=1&count=1"
        try:
            r = self.scraper.get(url)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            return (None, f"Failed to query Codeforces API: {e}")

        if data.get("status") != "OK":
            return (None, "Codeforces API returned non-OK status")

        for problem in data.get("result", {}).get("problems", []):
            if str(problem_index) == problem.get("index"):
                return (True, "Problem found")

        return (None, "Problem does not exist")

    def _get_accepted_submission_id(self, contest_id: str, problem_index: str) -> Tuple[Optional[bool], str]:
        # Use Codeforces API to find an OK verdict submission for the problem
        # Iterate pages of 100 submissions up to a sensible limit
        from_offset = 1
        page_size = 100
        max_checks = 10
        for _ in range(max_checks):
            url = f"{self.base_url}api/contest.status?contestId={contest_id}&from={from_offset}&count={page_size}"
            try:
                r = self.scraper.get(url)
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                return (None, f"Failed to query submissions: {e}")

            if data.get("status") != "OK":
                return (None, "Codeforces API returned non-OK status for submissions")

            submissions = data.get("result", [])
            if not submissions:
                break

            # Prefer newest OK submission for this problem
            for sub in submissions:
                problem = sub.get("problem", {})
                verdict = sub.get("verdict")
                if problem.get("index") == str(problem_index) and verdict == "OK":
                    return (True, str(sub.get("id")))

            from_offset += page_size

        return (None, "No accepted submissions found for this problem")

    def _parse_tests_from_submission_html(self, html: str) -> List[Tuple[str, str]]:
        soup = BeautifulSoup(html, "lxml")

        # Try a few plausible containers where tests may appear
        tests: List[Tuple[str, str]] = []

        # 1) Common pattern: paired divs with classes input/output (as used on CF pages)
        input_divs = soup.select("div.input pre")
        output_divs = soup.select("div.output pre")
        if input_divs and output_divs and len(input_divs) == len(output_divs):
            for i_pre, o_pre in zip(input_divs, output_divs):
                in_text = i_pre.get_text("\n", strip=False)
                out_text = o_pre.get_text("\n", strip=False)
                tests.append((in_text, out_text))
            return tests

        # 2) Alternative layout: elements with class names 'input'/'output' directly
        input_divs = soup.select(".input")
        output_divs = soup.select(".output")
        if input_divs and output_divs and len(input_divs) == len(output_divs):
            for i_div, o_div in zip(input_divs, output_divs):
                in_text = i_div.get_text("\n", strip=False)
                out_text = o_div.get_text("\n", strip=False)
                tests.append((in_text, out_text))
            return tests

        return tests

    def _fetch_tests_from_submission(self, contest_id: str, submission_id: str) -> Tuple[Optional[bool], List[Tuple[str, str]]]:
        url = f"{self.base_url}contest/{contest_id}/submission/{submission_id}"
        try:
            r = self.scraper.get(url)
            r.raise_for_status()
        except Exception as e:
            return (None, [f"Failed to load submission page: {e}"])

        tests = self._parse_tests_from_submission_html(r.text)
        if tests:
            return (True, tests)

        return (None, ["No tests visible on submission page (may require login or unavailable)"])

    def _fetch_sample_tests_from_problem(self, contest_id: str, problem_index: str) -> Tuple[Optional[bool], List[Tuple[str, str]]]:
        # Try both contest and problemset paths
        urls = [
            f"{self.base_url}contest/{contest_id}/problem/{problem_index}",
            f"{self.base_url}problemset/problem/{contest_id}/{problem_index}",
        ]

        last_error = None
        for url in urls:
            try:
                r = self.scraper.get(url)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "lxml")
                sample = soup.select_one("div.sample-test")
                if not sample:
                    continue
                input_blocks = sample.select("div.input pre")
                output_blocks = sample.select("div.output pre")
                tests: List[Tuple[str, str]] = []
                # Some problems may have unequal numbers; pair by min length
                for i_pre, o_pre in zip(input_blocks, output_blocks):
                    in_text = i_pre.get_text("\n", strip=False)
                    out_text = o_pre.get_text("\n", strip=False)
                    tests.append((in_text, out_text))
                if tests:
                    return (True, tests)
            except Exception as e:
                last_error = str(e)
                continue

        if last_error:
            return (None, [f"Failed to load problem page: {last_error}"])
        return (None, ["No sample tests found on problem page"]) 

    def get_testcases(self, contest_id, problem_num):
        problem_exist = self._isProblemExists(contest_id, problem_num)
        if not problem_exist[0]:
            return problem_exist

        console.log("Found the problem")

        sub_res = self._get_accepted_submission_id(contest_id, problem_num)
        if sub_res[0]:
            submission_id = sub_res[1]
            console.log(f"Found accepted submission: {submission_id}")
            tests_res = self._fetch_tests_from_submission(contest_id, submission_id)
            if tests_res[0] and tests_res[1]:
                console.log(f"Total test cases found from submission: {len(tests_res[1])}")
                return (True, tests_res[1])

        # Fallback to sample tests from the problem statement
        console.log("Falling back to sample tests from problem page")
        samples_res = self._fetch_sample_tests_from_problem(contest_id, problem_num)
        if samples_res[0] and samples_res[1]:
            console.log(f"Total sample test cases found: {len(samples_res[1])}")
            return (True, samples_res[1])

        # If nothing worked, return a consolidated error
        return (None, "Unable to retrieve test cases from submission or problem page")
