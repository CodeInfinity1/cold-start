"""A local stand-in for an OpenAI-compatible endpoint, for testing plumbing only (dev tool, not used by run.sh).

usage: python3 mock_llm.py <port> <mode> <stats.json>
modes: ok | error500 | badjson | reject_json | mixed | junk_ids | bad_dates
It answers loop prompts by flagging lines with '?' or 'pls', goal prompts with two goals, and records
request sizes so prompt volume can be measured.
"""
import json
import random
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT, MODE, STATS = int(sys.argv[1]), sys.argv[2], sys.argv[3]
lock = threading.Lock()
stats = {"requests": 0, "prompt_chars": 0, "completion_chars": 0, "loop_calls": 0, "goal_calls": 0,
         "max_prompt_chars": 0, "bodies_with_response_format": 0, "bodies_with_temperature": 0}
rng = random.Random(7)


def answer(body):
    system = body["messages"][0]["content"]
    user = body["messages"][1]["content"]
    if "goals he is pursuing" in system:
        ids = re.findall(r"^(\S+) \|", user, flags=re.M)
        if MODE == "junk_ids":
            return {"goals": [{"title": "x", "area": "nonsense", "type": "habit", "horizon": "3mo", "evidence": ["NOPE"]}]}
        return {"goals": [
            {"title": "Grow the business", "area": "work", "type": "milestone", "horizon": "1yr", "evidence": ids[:3]},
            {"title": "Stay fit", "area": "health", "type": "habit", "horizon": "3mo", "evidence": ids[3:5] + ["BAD"]}]}
    main = user.split("--- later (context only) ---")[0]
    later = user.split("--- later (context only) ---")[1] if "--- later" in user else ""
    loops = []
    for mid, sender, text in re.findall(r"^(\S+) \| [^|]+\| (\S+): (.*)$", main, flags=re.M):
        if "?" in text or "pls" in text.lower():
            loops.append({"source": mid if MODE != "junk_ids" else "ZZZ", "title": text[:40], "type": "question",
                          "owner": "ME" if sender != "ME" else "P_UNKNOWN", "due": "2026-09-0X",
                          "status": "done" if rng.random() < 0.3 else "open",
                          "closed_by": None, "help": {"action": rng.choice(["assist", "remind", "leave", "bogus"])}})
    later_ids = re.findall(r"^(\S+) \|", later, flags=re.M)
    if loops and later_ids:
        loops[0]["status"], loops[0]["closed_by"] = "done", later_ids[0]
    if MODE == "bad_dates":  # impossible or malformed dates and times, as a careless model might write them
        bad_due = ["2026-02-30", "2026-13-01", "tomorrow", 20260905, "0000-00-00", None, "2026-09-31"]
        bad_at = ["2026-09-31T10:00:00+05:30", "soon", 12345, "2026-02-30T09:00:00Z", "2026-09-05T10:00:00", None]
        for i, l in enumerate(loops):
            l["due"] = bad_due[i % len(bad_due)]
            l["status"], l["closed_by"] = "open", None
            l["help"] = {"action": "remind", "remind_at": bad_at[i % len(bad_at)]}
    return {"loops": loops}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))
        prompt_chars = sum(len(m["content"]) for m in body["messages"])
        with lock:
            stats["requests"] += 1
            stats["prompt_chars"] += prompt_chars
            stats["max_prompt_chars"] = max(stats["max_prompt_chars"], prompt_chars)
            stats["bodies_with_response_format"] += "response_format" in body
            stats["bodies_with_temperature"] += "temperature" in body
            if "goals he is pursuing" in body["messages"][0]["content"]:
                stats["goal_calls"] += 1
            else:
                stats["loop_calls"] += 1
        mode = MODE
        if mode == "mixed":
            mode = rng.choice(["ok", "ok", "ok", "error500", "badjson"])
        if mode == "error500":
            self.send_response(500); self.end_headers(); self.wfile.write(b"boom"); return
        if mode == "reject_json" and "response_format" in body:
            self.send_response(400); self.end_headers(); self.wfile.write(b"response_format unsupported"); return
        if self.headers.get("Authorization") != "Bearer test-key":
            self.send_response(401); self.end_headers(); return
        content = "Sure! here you go: " + json.dumps(answer(body)) + " hope this helps" if mode != "badjson" else "no json here"
        with lock:
            stats["completion_chars"] += len(content)
            json.dump(stats, open(STATS, "w"))
        out = {"choices": [{"message": {"role": "assistant", "content": content}}],
               "usage": {"prompt_tokens": prompt_chars // 4, "completion_tokens": len(content) // 4}}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
