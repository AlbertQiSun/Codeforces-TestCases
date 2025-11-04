import os
import sys
import signal
import time
import json
from typing import List, Tuple

import multiprocessing as mp
import requests
from rich.console import Console

import CF_TC
from contest_fetch import fetch_problem_html, parse_problem_markdown


console = Console()
console._log_render.omit_repeated_times = False


def get_all_finished_contests() -> List[int]:
    url = "https://codeforces.com/api/contest.list?gym=false"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "OK":
        raise RuntimeError("contest.list returned non-OK status")
    contests = [c for c in data.get("result", []) if c.get("phase") == "FINISHED"]
    contests.sort(key=lambda c: c.get("id"))  # oldest first
    return [c.get("id") for c in contests]


def get_contest_problems(contest_id: int) -> List[str]:
    url = f"https://codeforces.com/api/contest.standings?contestId={contest_id}&from=1&count=1"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "OK":
        return []
    return [p.get("index") for p in data.get("result", {}).get("problems", [])]


def ensure_dir(path: str) -> None:
    if not os.path.exists(path):
        os.makedirs(path)


def problem_dir(base_dir: str, contest_id: int, problem_index: str) -> str:
    return os.path.join(base_dir, "contests", str(contest_id), problem_index)


def already_done(path_dir: str) -> bool:
    # Done if statement exists and at least one system tc exists
    stm = os.path.join(path_dir, "statement.md")
    tests_root = os.path.join(path_dir, "tests", "system")
    if not os.path.exists(stm):
        return False
    if not os.path.exists(tests_root):
        return False
    for name in os.listdir(tests_root):
        if name.startswith("tc"):
            return True
    return False


def save_statement(path_dir: str, markdown: str) -> None:
    ensure_dir(path_dir)
    with open(os.path.join(path_dir, "statement.md"), "w", encoding="utf-8") as f:
        f.write(markdown)


def save_tests(path_dir: str, testcases: List[Tuple[str, str]]) -> None:
    tests_root = os.path.join(path_dir, "tests", "system")
    ensure_dir(tests_root)
    for i, (inp, out) in enumerate(testcases, 1):
        tc_dir = os.path.join(tests_root, f"tc{i}")
        ensure_dir(tc_dir)
        with open(os.path.join(tc_dir, "input.txt"), "w", encoding="utf-8") as fi:
            fi.write(inp)
        with open(os.path.join(tc_dir, "output.txt"), "w", encoding="utf-8") as fo:
            fo.write(out)


def worker(task_queue: mp.Queue, out_root: str):
    pvcodes = CF_TC.CF_TC()
    while True:
        item = task_queue.get()
        if item is None:
            break
        cid, idx = item
        try:
            pdir = problem_dir(out_root, cid, idx)
            # tests
            try:
                tc_res = pvcodes.get_testcases(cid, idx)
                if tc_res[0] and tc_res[1]:
                    save_tests(pdir, tc_res[1])
            except Exception:
                pass
            # statement
            try:
                html = fetch_problem_html(str(cid), idx)
                if html:
                    md = parse_problem_markdown(html)
                    save_statement(pdir, md)
            except Exception:
                pass
        except Exception:
            pass


stop_requested = False


def _sigint_handler(signum, frame):
    global stop_requested
    stop_requested = True
    console.log("Stop requested. Draining queue and shutting down workers…")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Parallel downloader for all Codeforces contests")
    parser.add_argument("--out", default="data", help="Output directory root (default: data)")
    parser.add_argument("--from_id", type=int, default=None, help="Start from this contest id (inclusive)")
    parser.add_argument("--max", type=int, default=None, help="Max number of contests to process")
    parser.add_argument("--only", type=str, default=None, help="Comma-separated problem indices to include (e.g., A,B)")
    parser.add_argument("--workers", type=int, default=max(2, mp.cpu_count() // 2), help="Number of parallel browsers/workers")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _sigint_handler)

    out_root = args.out
    ensure_dir(out_root)

    contests = get_all_finished_contests()
    if args.from_id is not None:
        contests = [c for c in contests if c >= args.from_id]
    if args.max is not None:
        contests = contests[: args.max]

    only_set = None
    if args.only:
        only_set = {x.strip() for x in args.only.split(",") if x.strip()}

    # Build tasks list
    tasks: List[Tuple[int, str]] = []
    for cid in contests:
        probs = get_contest_problems(cid)
        if only_set:
            probs = [p for p in probs if p in only_set]
        for idx in probs:
            pdir = problem_dir(out_root, cid, idx)
            if already_done(pdir):
                continue
            tasks.append((cid, idx))

    console.log(f"Total tasks: {len(tasks)} (workers={args.workers})")

    # Start workers
    task_queue: mp.Queue = mp.Queue(maxsize=args.workers * 4)
    procs: List[mp.Process] = []
    for _ in range(args.workers):
        p = mp.Process(target=worker, args=(task_queue, out_root))
        p.daemon = True
        p.start()
        procs.append(p)

    # Feed tasks; stop gracefully on Ctrl+C
    try:
        for t in tasks:
            if stop_requested:
                break
            task_queue.put(t)
    finally:
        # Send sentinels
        for _ in procs:
            task_queue.put(None)
        # Join workers
        for p in procs:
            p.join()

    console.log("Done.")


if __name__ == "__main__":
    main()


