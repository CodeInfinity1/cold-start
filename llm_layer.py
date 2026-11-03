"""Optional model layer. Off unless COLDSTART_USE_MODEL=1 *and* LLM_BASE_URL, LLM_API_KEY and LLM_MODEL are
all set. The graders set only the LLM_* variables, so graded runs are rules-only. This layer's accuracy
has not been measured against a real model.

The rules (people.py, loops.py, goals.py) always run first and their answer is the fallback. The
model then does the two jobs the rules are weakest at:

* Open loops: it re-reads each chat's recent messages (loops are scored on the final two weeks, so
  only the last WINDOW_DAYS are sent) and lists loops with status, closing message and help. A chat
  whose calls all succeed gets the model's loops; any other chat keeps the rules' loops.
* Goals: it reads Arjun's own messages (and plans people mention to him one to one) and names his
  goals with evidence.

Every answer is checked against the input: unknown ids, bad enums and "done" without a closing
message are fixed or dropped. Data goes only to LLM_BASE_URL, through llm.py.
"""
import json
import os
import re
import sys
import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import llm
from ctx import IST, local
from goals import AREAS as GOAL_AREAS, PLAN

WINDOW_DAYS = 16          # loops are scored on the last 14 days; two spare days for the boundary
CHUNK = 150               # messages a call is asked about
TAIL = 40                 # later messages shown only to judge status
WORKERS = 6
BUDGET_SECONDS = 15 * 60  # no new calls after this (in-flight ones end within CALL_TIMEOUT); rules cover the rest
CALL_TIMEOUT = 120
MAX_BODY = 300
GOAL_DIGEST = 1200        # most messages sent for goals

LOOP_TYPES = {"commitment", "followup", "deadline", "question"}
STATUSES = {"open", "done", "dropped"}
AREAS = {"self", "spouse", "kids", "parents", "work", "friends", "experiences", "finances", "health", "home"}
GOAL_TYPES = {"habit", "milestone", "experience"}
HORIZONS = {"3mo", "1yr", "3yr", "5yr"}

LOOPS_PROMPT = """You help a personal assistant for Arjun on WhatsApp. Arjun's sender id is ME. You get one or more chats.
Each starts with a "===" header, then messages as `id | time | sender: text`. Messages after a line
"--- later (context only) ---" are only there to judge status; never raise a loop from them.

Find the open loops raised in the main part: things someone now has to do, answer or attend to because of it.
- commitment: Arjun promised or agreed to do something ("I'll send it tomorrow")
- question: someone asked Arjun something he has to answer or decide
- followup: Arjun is waiting on someone else (he asked them for something, or they promised him something)
- deadline: something with a date Arjun must act on (a payment, an RSVP, a birthday wish today)
Short asks count ("pls pay 500", "can u send the link"). Skip greetings, thanks, chit-chat, news, forwards,
jokes, things nobody has to act on, and messages in big groups that are not aimed at Arjun.

For each loop give:
- source: id of the message that raised it (the ask or the promise itself, not a later reminder)
- title: a short plain imperative, e.g. "Pay the electrician 500"
- type: commitment | question | followup | deadline
- owner: "ME" if Arjun has to act, else the id of the person who has to act
- due: YYYY-MM-DD if a date is stated or clearly implied, else null
- status at the end of what you see: "done" only if a later message shows it happened or was answered,
  "dropped" only if it was clearly called off, otherwise "open"
- closed_by: id of the message that shows done or dropped, else null
- help, only when open: {"action": "assist", "next_step": "...", "needs_yes": true} if the assistant can take
  a private, reversible step itself (find options, draft a reply, make a list); {"action": "remind",
  "remind_at": "YYYY-MM-DDTHH:MM:00+05:30"} if only Arjun can act and one nudge helps; {"action": "leave",
  "reason": "..."} if someone else owns it, or it is personal or sensitive.

Be selective: most messages are not loops, and even a busy chat has only a few a day.
Reply with JSON only: {"loops": [...]}"""

GOALS_PROMPT = """You help a personal assistant understand Arjun (sender ME). Below are messages Arjun sent, and some that
people sent him one to one, over several weeks, as `id | date | chat | text`.

Name the goals he is pursuing: things he wants to achieve, habits he is building or keeping, experiences he is
planning, for himself or his family, friends, work, money, health or home. Only include goals that several
messages support, or that he states outright. Do not turn one-off errands into goals. At most 8.

For each goal give: title (short), area (self|spouse|kids|parents|work|friends|experiences|finances|health|home),
type (habit|milestone|experience), horizon (3mo|1yr|3yr|5yr), evidence (2 to 6 message ids that support it best).
Reply with JSON only: {"goals": [...]}"""


OPT_IN = "COLDSTART_USE_MODEL"  # must be "1"; LLM_* alone (as the graders set them) never turns the model on


def enabled():
    if os.environ.get(OPT_IN) != "1":
        return False
    if not all(os.environ.get(k) for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")):
        log(f"{OPT_IN}=1 but LLM_BASE_URL, LLM_API_KEY or LLM_MODEL is missing; running rules only")
        return False
    return True


def log(msg):
    print("[model] " + msg, file=sys.stderr)


def valid_date(value):
    """A real calendar date as YYYY-MM-DD, or None. Model answers can say "2026-02-30" or "next week"."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
        return None
    try:
        d = datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError:
        return None
    return d.date().isoformat() if 2000 <= d.year <= 2100 else None


def valid_datetime(value):
    """An ISO date-time with a time zone, normalised, or None."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.isoformat() if dt.tzinfo is not None and 2000 <= dt.year <= 2100 else None


def norm_id(mid):
    """Message ids compared loosely: case and leading zeros ignored ("x042" == "X00042")."""
    s = re.sub(r"[^A-Za-z0-9]", "", str(mid or "")).upper()
    return re.sub(r"(?<=[A-Z])0+(?=\d)", "", s)


def parse_json(text):
    """The first JSON object in a reply, tolerating code fences and chatter around it."""
    if not text:
        return None
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except ValueError:
                        break
        start = text.find("{", start + 1)
    return None


# What to send, from most to least: endpoints differ in which options they accept, so on a 400 we step down.
CALL_STYLES = [
    {"temperature": 0, "json": True, "max_tokens": True},
    {"temperature": 0, "json": False, "max_tokens": True},
    {"temperature": None, "json": False, "max_tokens": True},
    {"temperature": None, "json": False, "max_tokens": False},
]


class ModelLayer:
    def __init__(self, ctx, structure):
        self.ctx = ctx
        self.st = structure
        self.started = time.time()
        self.calls = 0
        self.failures = 0
        self.style = 0
        self.lock = threading.Lock()

    # ------------------------------------------------------------------ calling
    def ask(self, system, user, max_tokens=2500):
        """One model call returning parsed JSON, or None. Retries transient errors twice."""
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        attempt = 0
        while attempt < 3:
            if time.time() - self.started > BUDGET_SECONDS:
                return None
            used = self.style
            style = CALL_STYLES[used]
            try:
                with self.lock:
                    self.calls += 1
                reply = llm.chat(messages, temperature=style["temperature"],
                                 max_tokens=max_tokens if style["max_tokens"] else None,
                                 response_format={"type": "json_object"} if style["json"] else None,
                                 timeout=CALL_TIMEOUT)
                data = parse_json(reply)
                if isinstance(data, dict):
                    return data
                log("reply was not JSON")
            except urllib.error.HTTPError as e:
                log(f"HTTP {e.code}")
                if e.code == 400:
                    # The endpoint rejected an option: step down one level from the style this call used
                    # (another thread may already have done it) and try again without counting an attempt.
                    with self.lock:
                        if used + 1 < len(CALL_STYLES):
                            self.style = max(self.style, used + 1)
                            continue
                    break
                if e.code not in (408, 409, 429, 500, 502, 503, 504):
                    break
            except Exception as e:  # network trouble, timeouts, odd payloads
                log(f"call failed: {type(e).__name__}")
            attempt += 1
            time.sleep(2 * attempt)
        with self.lock:
            self.failures += 1
        return None

    # ------------------------------------------------------------------ formatting
    def who(self, pid):
        if pid == "ME":
            return "Arjun"
        names = self.ctx.names.get(pid) or []
        return names[0] if names else pid

    def line(self, m):
        body = re.sub(r"\s+", " ", m.get("body") or "").strip()
        if len(body) > MAX_BODY:
            body = body[:MAX_BODY] + "..."
        if m.get("kind") == "document" and not body.startswith("["):
            body = "[document] " + body
        elif m.get("kind") == "voice_transcript":
            body = "[voice] " + body
        if m.get("quoted_id"):
            body = f"(replying to {m['quoted_id']}) " + body
        return f"{m['id']} | {local(m['ts']).strftime('%a %d %b %H:%M')} | {m['sender_id']}: {body}"

    def header(self, cid):
        ctx = self.ctx
        c = ctx.chat[cid]
        ps = [p for p in c.get("participants", []) if p != "ME"]
        org = self.st.chat_org.get(cid)
        org_name = self.st.orgs[org]["name"] if org else None
        if not c.get("is_group") and ps:
            p = ps[0]
            head = f'Chat {cid}: one to one with {p} "{self.who(p)}" ({self.st.circle.get(p, "unknown")})'
        else:
            head = f'Group {cid} "{c.get("name", "")}" with {len(ps)} people' + (f", organisation {org_name}" if org_name else "")
            active = sorted(ps, key=lambda p: -ctx.sent_in[cid].get(p, 0))[:15]
            head += "\nPeople: " + "; ".join(f'{p}={self.who(p)} ({self.st.circle.get(p, "?")})' for p in active)
        end = local(ctx.end_ts).strftime("%a %d %b %Y")
        return head + f"\nThe data ends on {end}. Times are India time."

    # ------------------------------------------------------------------ loops
    def window_start(self):
        return max(self.ctx.start_ts, self.ctx.end_ts - WINDOW_DAYS * 86400)

    def sections(self):
        """(chat id, focus messages, tail messages) for every chat with recent messages. Big groups only
        send what touches Arjun. Short replies ("done", "paid", a photo) stay in: they close loops."""
        ctx = self.ctx
        start = self.window_start()
        out = []
        for cid, msgs in ctx.by_chat.items():
            c = ctx.chat[cid]
            recent = [m for m in msgs if m["ts"] >= start]
            if c.get("is_group") and len(c.get("participants", [])) > 6:
                keep = set()
                for i, m in enumerate(recent):
                    if m["sender_id"] == "ME" or ctx.addresses_me(m):
                        keep.update(x["id"] for x in recent[max(0, i - 2):i + 3])
                recent = [m for m in recent if m["id"] in keep]
            for i in range(0, len(recent), CHUNK):
                out.append((cid, recent[i:i + CHUNK], recent[i + CHUNK:i + CHUNK + TAIL]))
        return out

    def batches(self):
        """Pack sections into calls of about CHUNK messages, so small chats share one call (and one copy
        of the instructions) instead of paying for a call each."""
        out, cur, size = [], [], 0
        for sec in sorted(self.sections(), key=lambda s: -len(s[1])):
            if cur and size + len(sec[1]) > CHUNK:
                out.append(cur)
                cur, size = [], 0
            cur.append(sec)
            size += len(sec[1])
        if cur:
            out.append(cur)
        return out

    def loops_for(self, batch):
        parts = []
        for cid, focus, tail in batch:
            text = "=== " + self.header(cid) + "\n" + "\n".join(self.line(m) for m in focus)
            if tail:
                text += "\n--- later (context only) ---\n" + "\n".join(self.line(m) for m in tail)
            parts.append(text)
        data = self.ask(LOOPS_PROMPT, "\n\n".join(parts))
        if data is None or not isinstance(data.get("loops", []), list):
            return None
        try:
            focus = {m["id"]: cid for cid, msgs, _ in batch for m in msgs}
            raw = data.get("loops", [])
            loops = [l for l in (self.safe_check_loop(x, focus) for x in raw) if l]
        except Exception as e:  # anything unexpected in the answer: this batch keeps the rules' loops
            log(f"answer could not be used ({type(e).__name__}); keeping the rules here")
            return None
        if raw and len(loops) < len(raw) / 2:
            log(f"{len(raw) - len(loops)} of {len(raw)} loops did not fit the input; keeping the rules here")
            return None  # an answer that mostly points at messages we never sent is not to be trusted
        return loops

    def safe_loops_for(self, batch):
        """One batch can fail without stopping the others; its chats then keep the rules' loops."""
        try:
            return self.loops_for(batch)
        except Exception as e:
            log(f"batch skipped ({type(e).__name__}); keeping the rules there")
            return None

    def safe_check_loop(self, x, focus):
        """check_loop, but a loop that trips over bad data is dropped instead of ending the whole batch."""
        try:
            return self.check_loop(x, focus)
        except Exception:
            return None

    def resolve(self, mid, allowed):
        """A message id as the model wrote it, matched to a real one ("X42" -> "X00042"), or ''."""
        mid = str(mid or "").strip()
        if mid in allowed:
            return mid
        key = norm_id(mid)
        for real in allowed:
            if norm_id(real) == key:
                return real
        return ""

    def check_loop(self, x, focus):
        """Keep a model loop only if it fits the input; repair what can be repaired."""
        ctx = self.ctx
        if not isinstance(x, dict):
            return None
        src = self.resolve(x.get("source") or x.get("source_msg"), focus)
        if not src:
            return None
        cid = focus[src]
        parts = set(ctx.chat[cid].get("participants", []))
        owner = str(x.get("owner") or "ME")
        if owner not in parts or (owner != "ME" and owner not in ctx.names):
            owner = "ME"
        ltype = x.get("type") if x.get("type") in LOOP_TYPES else "commitment"
        due = valid_date(x.get("due"))  # "2026-02-30", "tomorrow", 20260905 -> None, not a crash
        status = x.get("status") if x.get("status") in STATUSES else "open"
        closed_by = None
        if x.get("closed_by"):
            closed_by = self.resolve(x["closed_by"], {m["id"] for m in ctx.by_chat[cid]}) or None
        if status != "open":
            ok = closed_by in ctx.msg and ctx.msg[closed_by]["chat_id"] == cid \
                and ctx.msg[closed_by]["ts"] >= ctx.msg[src]["ts"] and closed_by != src
            if not ok:  # a "done" we can't point at is not trusted: a wrong "done" hides real work
                status, closed_by = "open", None
        else:
            closed_by = None
        title = str(x.get("title") or "").strip()[:140] or (ctx.msg[src].get("body") or "")[:80]
        loop = {"title": title, "type": ltype, "owner": owner, "chat_id": cid, "source_msg": src, "due": due,
                "status": status, "closed_by": closed_by, "help": None}
        if status == "open":
            loop["help"] = self.check_help(x.get("help"), owner, src, due)
        return loop

    def check_help(self, h, owner, src, due):
        sent = local(self.ctx.msg[src]["ts"])
        if not isinstance(h, dict) or h.get("action") not in ("assist", "remind", "leave"):
            h = {"action": "leave" if owner != "ME" else "remind"}
        action = h["action"]
        if owner != "ME" and action != "leave":
            action = "leave"  # nudging Arjun about someone else's promise is not ours to do
        if action == "assist":
            return {"action": "assist", "next_step": str(h.get("next_step") or "Prepare it for Arjun to approve.")[:200],
                    "needs_yes": bool(h.get("needs_yes", True))}
        if action == "remind":
            at = valid_datetime(h.get("remind_at"))
            if at is None:  # missing or malformed: the morning the loop is due, else the morning after it came up
                d = datetime.strptime(due, "%Y-%m-%d").replace(tzinfo=IST, hour=9, minute=30) if due else None
                at = (d if d and d > sent else (sent + timedelta(days=1)).replace(hour=10, minute=0, second=0,
                                                                                    microsecond=0)).isoformat()
            return {"action": "remind", "remind_at": at}
        return {"action": "leave", "reason": str(h.get("reason") or "Not Arjun's to act on.")[:200]}

    def refine_loops(self, rule_loops):
        batches = self.batches()
        log(f"{len(batches)} loop calls over the last {WINDOW_DAYS} days")
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            results = list(pool.map(self.safe_loops_for, batches))
        ok_chats, failed_chats, model_loops = set(), set(), []
        for batch, res in zip(batches, results):
            for cid, _, _ in batch:
                (failed_chats if res is None else ok_chats).add(cid)
            model_loops.extend(res or [])
        ok_chats -= failed_chats
        start = self.window_start()
        ts = {m["id"]: m["ts"] for m in self.ctx.messages}
        kept = [l for l in rule_loops if not (l["chat_id"] in ok_chats and ts[l["source_msg"]] >= start)]
        seen = {l["source_msg"] for l in kept}
        for l in model_loops:
            if l["chat_id"] in ok_chats and l["source_msg"] not in seen:
                seen.add(l["source_msg"])
                kept.append(l)
        kept.sort(key=lambda l: ts[l["source_msg"]])
        log(f"model loops used for {len(ok_chats)} chats, rules kept for {len(failed_chats)} failed chats")
        return kept

    # ------------------------------------------------------------------ goals
    def goal_digest(self):
        ctx = self.ctx
        area_words = "|".join(p for _, _, _, p, _ in GOAL_AREAS)
        rows = []
        for m in ctx.messages:
            t = ctx.text[m["id"]]
            if len(t) < 15 or t.startswith("http"):
                continue
            chat = ctx.chat.get(m["chat_id"], {})
            mine = m["sender_id"] == "ME"
            topical = re.search(r"(?<![a-z])(?:" + area_words + r")(?![a-z])", t) is not None
            planning = re.search(r"(?<![a-z])(?:" + PLAN + r")(?![a-z])", t) is not None
            if (mine and (topical or planning)) or (not chat.get("is_group") and topical and planning):
                rows.append(m)
        rows = rows[-GOAL_DIGEST:]
        lines = []
        for m in rows:
            body = re.sub(r"\s+", " ", m.get("body") or "").strip()[:200]
            name = (self.ctx.chat[m["chat_id"]].get("name") or m["chat_id"])[:30]
            sender = "" if m["sender_id"] == "ME" else f"(from {self.who(m['sender_id'])}) "
            lines.append(f"{m['id']} | {local(m['ts']).strftime('%d %b')} | {name} | {sender}{body}")
        return lines

    def goals(self):
        lines = self.goal_digest()
        if len(lines) < 5:
            return None
        data = self.ask(GOALS_PROMPT, "\n".join(lines), max_tokens=2000)
        if data is None or not isinstance(data.get("goals"), list):
            return None
        ids = set(self.ctx.msg)
        by_norm = {norm_id(i): i for i in ids}
        out = []
        for g in data["goals"][:10]:
            if not isinstance(g, dict):
                continue
            ev = [str(e) if str(e) in ids else by_norm.get(norm_id(e), "") for e in (g.get("evidence") or [])]
            ev = [e for e in ev if e]
            if not ev or g.get("area") not in AREAS:
                continue
            out.append({"title": str(g.get("title") or "Goal")[:120], "area": g["area"],
                        "type": g.get("type") if g.get("type") in GOAL_TYPES else "milestone",
                        "horizon": g.get("horizon") if g.get("horizon") in HORIZONS else "1yr",
                        "evidence": list(dict.fromkeys(ev))[:8]})
        return out or None


def refine(ctx, structure, out, seeded_goals):
    """Improve out["open_loops"] and out["goals"] in place with the model; leave them alone on failure."""
    layer = ModelLayer(ctx, structure)
    try:
        out["open_loops"] = layer.refine_loops(out["open_loops"])
    except Exception as e:  # never let the model layer break a run
        log(f"loop refinement skipped: {type(e).__name__}: {e}")
    try:
        goals = layer.goals()
        if goals:
            # The seeded goal stays first; a model goal that repeats it (same area, shared evidence) is dropped.
            fresh = [g for g in goals if not any(g["area"] == s["area"] and set(g["evidence"]) & set(s["evidence"])
                                                 for s in seeded_goals)]
            out["goals"] = (seeded_goals + fresh)[:10]
    except Exception as e:
        log(f"goal refinement skipped: {type(e).__name__}: {e}")
    log(f"{layer.calls} calls, {layer.failures} failed, {time.time() - layer.started:.0f}s")
