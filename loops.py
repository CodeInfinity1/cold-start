"""Open loops: find them, decide whether they closed, and say where the assistant should help.

A loop starts at one message: someone asks Arjun for something, Arjun promises something, Arjun asks
someone else for something, or someone promises Arjun something. Each message gets a score from the
words it uses, who sent it and where; one message per conversational turn is kept if it scores high
enough. Status comes from what happens later in the same chat, and defaults to "open" because a
wrong "done" hides real work.
"""
import re
from datetime import datetime, timedelta

from ctx import IST, MENTION, has_word, is_media_only, local

# ------------------------------------------------------------------ word lists
# English plus the romanised Hindi that Indian WhatsApp mixes in ("bhej dunga", "kab tak", "kar diya").
POLITE = r"pls|plz|please|pl|kindly|request|requesting|kripya"
ASK = (r"can (?:u|you|we|i)|could (?:u|you)|would (?:u|you)|will (?:u|you)|did (?:u|you)|have (?:u|you)|"
       r"possible to|are (?:u|you) able|do (?:u|you) (?:have|know)|any (?:update|news|plans?|idea|thoughts)|"
       r"what do (?:u|you) think|should (?:we|i)|shall (?:we|i)|let me know|lmk|tell me|need your help|"
       r"kab tak|kab|kaise|kitna|kitne|kahan|batao|bata do|bataiye|bataye")
ACTION = (r"send|share|order|buy|get|book|pay|call|transfer|arrange|fix|confirm|check|tell|update|reply|revert|"
          r"review|approve|sign|forward|discuss|meet|bring|give|provide|organi[sz]e|remind|ask|find|make|"
          r"prepare|reimburse|deposit|pick|drop|collect|schedule|reschedule|join|come|visit|talk|"
          r"bhej|bhejo|bhejna|bhejiye|de do|dedo|dena|dijiye|kar do|kardo|karo|karna|kijiye|lana|le lo|lelo|"
          r"bolo|bol do|dekh lo|dekho")
NEED = r"need|needs|needed|required|require|urgent|urgently|asap|must|have to|has to|pending|due|reminder|chahiye"
TIMEREF = (r"today|tonight|tomorrow|tmrw|tmr|kal|parso|aaj|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
           r"mon|tue|tues|wed|thu|thurs|fri|sat|sun|weekend|next week|this week|eod|\d{1,2}(?::\d{2})? ?(?:am|pm)|"
           r"\d{1,2}(?:st|nd|rd|th)|\d{1,2} ?baje|baje")
COMMIT = (r"i'?ll|i will|i shall|we'?ll|we will|i am on it|i'?m on it|on it|will get back|get back to (?:you|u)|"
          r"reverting|will (?:do|send|share|check|call|revert|update|complete|finish|discuss|connect|book|pay|order|"
          r"get|ask|buy|try|look|see|arrange|fix|confirm|transfer|let|come|reach|join|speak|talk|review|sort|"
          r"handle|organi[sz]e|plan|make|prepare|reply|incorporate|evaluate|issue|give|bring|meet|visit|pick|drop|"
          r"submit|deliver|deposit|inform)|ill (?:do|send|share|check|call|buy|get|ask|book|pay|order|be|come|"
          r"reach|try|see|look|let|update|revert|speak|talk|fix|arrange|discuss|give)|let me (?:check|see|know|get|"
          r"do|ask|find|try|look|confirm|update|revert)|by (?:today|tomorrow|tmrw|tonight|eod|mon|tue|wed|thu|fri|"
          r"sat|sun)\w*|[a-z]+(?:unga|ungi|oonga|enge)")
BDAY = re.compile(r"(?:happy|happiest|hbd|many happy returns)[^.!?\n]{0,30}?(?:birthday|bday|b'day|returns|"
                  r"anniversary)|happy \d+(?:st|nd|rd|th)(?![a-z])|(?<![a-z])hbd(?![a-z])")
DONE = (r"done|paid|sent|ordered|booked|transferred|shared|called|spoke|completed|delivered|bought|purchased|"
        r"placed|confirmed|scheduled|fixed|sorted|resolved|added|emailed|mailed|forwarded|replied|deposited|"
        r"submitted|uploaded|issued|received|got it|reached|attached|ho gaya|ho gya|kar diya|kar dia|bhej diya|"
        r"bhej dia|de diya|de dia|mil gaya|chhod diya|chod diya|le liya|kar liya|ho chuka|aa gaya|aa gya")
THANKS = r"thanks|thank you|thank u|thx|tx|ty|received|got it|perfect|great|awesome"
CALLED_OFF = re.compile(r"(?:ok |oh |acha |achha |arre |actually )?(?:never ?mind|nvm|forget it|leave it|cancel it|"
                        r"cancel that|skip it|"
                        r"(?:no need|not needed|not required|don'?t need it|dont need it|no longer needed)"
                        r"(?: now| anymore| any more| then| it| thanks| thank you)*[\s.!🙏👍]*$)")
SENSITIVE = (r"hospital|sick|unwell|fever|chemo|surgery|doctor|died|passed away|funeral|condolence|stressed|"
             r"upset|sad|cry|crying|hard time|fight|angry|sorry|hurt|discuss \w+|talk about|need to talk")
ASSISTABLE = (r"order|buy|get me|find|book|search|look for|compare|draft|prepare|shortlist|options|link|address|"
              r"details|invite|ticket|tickets|quote|quotation|list")
ACK = set("""ok okay okk okkk k kk done yes yeah yep ya yaa haan ha han hmm hmmm no nope sure thanks thank thankyou
thx tx ty great cool nice good noted fine perfect right correct gotit welcome np lol haha hahaha wow super awesome
amazing ji okji theekhai thikhai accha acha achha alright bye gn gm""".split())
GREETING = re.compile(r"^(?:hi+|hello|hey+|hii+|good (?:morning|afternoon|evening|night)|gm|gn)\b[\s,!.]*\w*[\s!.]*$")

WEEKDAY = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
MONTH = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

THRESHOLD = 2.3       # minimum score for a message to open a loop
TURN_GAP = 10 * 60    # messages from one sender closer than this are one turn
CLOSE_WINDOW = 4 * 86400


def has(pattern, text):
    return has_word(pattern, text)


def core_words(text):
    return re.sub(r"[^a-z0-9 ]", "", text).split()


def trivial(text):
    """Acknowledgements, greetings, bare links and media: never a loop on their own."""
    if not text or is_media_only(text) or GREETING.match(text):
        return True
    ws = core_words(text)
    if not ws:
        return True
    if all(w in ACK for w in ws) and len(ws) <= 4:
        return True
    if re.fullmatch(r"(?:https?://\S+\s*)+", text):
        return True
    return False


# ------------------------------------------------------------------ dates
def parse_due(text, ts):
    """A due date (YYYY-MM-DD) mentioned in a message, relative to when it was sent; None if there isn't one."""
    now = local(ts)
    day = now.date()

    def ok(d):
        return d if day - timedelta(days=1) <= d <= day + timedelta(days=120) else None

    m = re.search(r"(?<![a-z0-9])(\d{1,2})(?:st|nd|rd|th)?[ \-/]*(?:of )?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*", text)
    if not m:
        m2 = re.search(r"(?<![a-z])(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* (\d{1,2})(?:st|nd|rd|th)?(?![0-9])", text)
        if m2:
            m = (m2.group(2), m2.group(1))
    else:
        m = (m.group(1), m.group(2))
    if m:
        try:
            d = datetime(now.year, MONTH[m[1]], int(m[0])).date()
            if d < day - timedelta(days=180):
                d = datetime(now.year + 1, MONTH[m[1]], int(m[0])).date()
            if ok(d):
                return ok(d).isoformat()
        except ValueError:
            pass
    m = re.search(r"(?<![0-9/])(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?(?![0-9/])", text)
    if m:
        try:
            year = int(m.group(3)) if m.group(3) else now.year
            year = year + 2000 if year < 100 else year
            d = datetime(year, int(m.group(2)), int(m.group(1))).date()
            if ok(d):
                return d.isoformat()
        except ValueError:
            pass
    if has(r"day after tomorrow|parso", text):
        return (day + timedelta(days=2)).isoformat()
    if has(r"tomorrow|tmrw|tmr|tomorow|kal", text):
        return (day + timedelta(days=1)).isoformat()
    if has(r"today|tonight|eod|aaj", text):
        return day.isoformat()
    m = re.search(r"(?<![a-z])(mon|tue|wed|thu|fri|sat|sun)(?:day|s|sday|nesday|rsday|urday|r|rs)?(?![a-z])", text)
    if m:  # whole weekday words only: "month", "wedding" or "sunset" are not days
        ahead = (WEEKDAY[m.group(1)] - now.weekday()) % 7 or 7
        if has(r"next " + re.escape(m.group(0)), text) and ahead < 7:
            ahead += 7
        return (day + timedelta(days=ahead)).isoformat()
    return None


# ------------------------------------------------------------------ finding
IMPERATIVE = re.compile(r"^(?:pls |please |plz |pl |kindly )?(?:send|share|order|pay|get|book|call|buy|give|tell|check|"
                        r"confirm|text|transfer|arrange|ask|bring|make|find|fix|reply|update|add|take|keep|put|move|"
                        r"remind|discuss|come)(?![a-z])")


def imperative(text):
    return IMPERATIVE.match(text) is not None


class Loops:
    def __init__(self, ctx, structure):
        self.ctx = ctx
        self.st = structure
        volume = sorted(((len(ctx.by_chat.get(cid, [])), cid) for cid in ctx.dm_of.values()), reverse=True)
        self.busiest_dm = volume[0][1] if volume else None

    def name(self, pid):
        names = self.ctx.names.get(pid) or [pid]
        return names[-1] if names else pid

    def replied_soon(self, m, by_me):
        """Did the other side answer within three hours (within the next few messages)?"""
        msgs = self.ctx.by_chat[m["chat_id"]]
        i = self.ctx.pos[m["id"]]
        for x in msgs[i + 1:i + 6]:
            if (x["sender_id"] == "ME") == by_me and x["ts"] - m["ts"] < 3 * 3600:
                return True
        return False

    def score(self, m, chat):
        """(score, kind) for one message; kind says who owes what. Weights were set by hand and checked
        against a regularised logistic fit on the dev labels; they reward asks, promises and dates."""
        ctx = self.ctx
        t = ctx.text[m["id"]]
        if trivial(t):
            return 0.0, None
        in_dm = not chat.get("is_group")
        small = len(chat.get("participants", [])) <= 6   # a small group talks to Arjun more directly
        mine = m["sender_id"] == "ME"
        s = 0.0
        if mine:
            commit = has(COMMIT, t)
            request = has(POLITE, t) or has(ASK, t)
            s += 2.4 * commit + 1.6 * request + 0.8 * ("?" in t) + 0.6 * has(ACTION, t) + 0.5 * has(TIMEREF, t)
            s -= (0.0 if in_dm else 0.3 if small else 0.8) + 0.8 * (len(t) < 25) + 0.5 * self.replied_soon(m, False)
            kind = "me_commit" if commit or not (request or "?" in t) else "me_request"
        else:
            if BDAY.search(t):
                return (3.0 if not in_dm else 0.0), "birthday"
            to_me = ctx.addresses_me(m)
            asks = has(POLITE, t) or has(ASK, t) or imperative(t) or "?" in t
            s += (1.4 * has(POLITE, t) + 1.2 * has(ASK, t) + 1.0 * has(ACTION, t) + 1.0 * imperative(t)
                  + 0.7 * has(NEED, t) + 0.8 * ("?" in t) + 0.6 * has(TIMEREF, t)
                  + 0.8 * self.replied_soon(m, by_me=True) + 0.5 * (m["chat_id"] == self.busiest_dm))
            kind = "ask_me"
            if has(COMMIT, t) and not asks:
                kind, s = "their_commit", s + 1.6   # they promised Arjun something
            if not in_dm:
                s += 1.2 if to_me else (-0.8 if small else -1.6)
        if len(t) > 500:
            s -= 1.0
        if "http" in t and len(re.sub(r"https?://\S+", "", t).strip()) < 15:
            s -= 1.5
        return s, kind

    def candidates(self):
        """Every message scored, best message of each turn kept."""
        ctx = self.ctx
        out = []
        for cid, msgs in ctx.by_chat.items():
            chat = ctx.chat[cid]
            turn, last = [], None
            for m in msgs + [None]:
                new_turn = (m is None or last is None or m["sender_id"] != last["sender_id"]
                            or m["ts"] - last["ts"] > TURN_GAP)
                if new_turn and turn:
                    best = max(turn, key=lambda x: (x[0], -x[2]))
                    if best[0] > 0:
                        out.append({"score": best[0], "kind": best[1], "msg": best[3]})
                    turn = []
                if m is None:
                    break
                s, kind = self.score(m, chat)
                turn.append((s, kind, len(turn), m))
                last = m
        # Birthday wishes: one loop per group per day, the first wish. And when Arjun answers an ask with a
        # promise ("Did you look at Coorg?" / "I'll book it this week"), that is one loop, not two.
        seen, kept, last_ask = set(), [], {}
        for c in sorted(out, key=lambda c: c["msg"]["ts"]):
            m = c["msg"]
            if c["kind"] == "birthday":
                key = (m["chat_id"], local(m["ts"]).date())
                if key in seen:
                    continue
                seen.add(key)
            prev = last_ask.get(m["chat_id"])
            if c["kind"] == "me_commit" and prev and m["ts"] - prev["msg"]["ts"] <= 3 * 3600 \
                    and prev["score"] >= THRESHOLD:
                prev["answered_with_promise"] = m
                continue
            if c["kind"] == "ask_me":
                last_ask[m["chat_id"]] = c
            elif m["sender_id"] != "ME":
                last_ask.pop(m["chat_id"], None)
            kept.append(c)
        return kept

    # ------------------------------------------------------------------ describing
    def owner(self, c):
        m = c["msg"]
        if c["kind"] in ("ask_me", "me_commit", "birthday"):
            return "ME"
        if c["kind"] == "their_commit":
            return m["sender_id"]
        # Arjun asked someone: the person in a 1:1 chat, else whoever he @mentioned, else whoever spoke last.
        other = self.ctx.other(m["chat_id"])
        if other:
            return other
        for h in MENTION.findall(m.get("body") or ""):
            if self.ctx.handle_owner.get(h, "ME") != "ME":
                return self.ctx.handle_owner[h]
        msgs = self.ctx.by_chat[m["chat_id"]]
        for prev in reversed(msgs[:self.ctx.pos[m["id"]]]):
            if prev["sender_id"] != "ME" and prev["sender_id"] in self.ctx.names:
                return prev["sender_id"]
        return "ME"

    def loop_type(self, c, due):
        t = self.ctx.text[c["msg"]["id"]]
        if c["kind"] == "birthday":
            return "deadline"
        if c["kind"] in ("me_request", "their_commit"):
            return "followup"
        if c["kind"] == "ask_me" and "?" in t and not has(POLITE, t):
            return "question"
        return "deadline" if due else "commitment"

    def title(self, c, owner):
        m = c["msg"]
        body = re.sub(r"\s+", " ", (m.get("body") or "")).strip()
        snippet = body if len(body) <= 90 else body[:87].rsplit(" ", 1)[0] + "..."
        who = self.name(m["sender_id"]) if m["sender_id"] != "ME" else None
        if c["kind"] == "birthday":
            return "Send birthday wishes in " + (self.ctx.chat[m["chat_id"]].get("name") or "the group")
        if c["kind"] == "ask_me":
            return f"{who} asked: {snippet}"
        if c["kind"] == "their_commit":
            return f"{who} said: {snippet}"
        if c["kind"] == "me_request":
            return f"Waiting on {self.name(owner)}: {snippet}"
        return f"Arjun said: {snippet}"

    # ------------------------------------------------------------------ closing
    def status(self, c, owner):
        """('open'|'done'|'dropped', closing message id or None). 'done' needs evidence."""
        ctx = self.ctx
        m = c["msg"]
        msgs = ctx.by_chat[m["chat_id"]]
        start = c.get("answered_with_promise") or m   # if Arjun promised, look for closure after the promise
        later = [x for x in msgs[ctx.pos[start["id"]] + 1:] if x["ts"] - m["ts"] <= CLOSE_WINDOW]
        t = ctx.text[m["id"]]
        asker = m["sender_id"]
        # Called off: whoever it was for says so within two days, and that is the point of the message.
        for x in later:
            xt = ctx.text[x["id"]]
            for_them = x["sender_id"] != owner and (x["sender_id"] == asker or owner == asker)
            if for_them and x["ts"] - m["ts"] <= 2 * 86400 and len(xt) < 100 and CALLED_OFF.match(xt):
                return "dropped", x["id"]
        if c["kind"] == "birthday":
            for x in later:
                if x["sender_id"] == "ME" and x["ts"] - m["ts"] <= 86400:
                    return "done", x["id"]
            return "open", None
        # A plain question to Arjun is closed by his reply, unless the reply is a promise to do something.
        if c["kind"] == "ask_me" and "?" in t and not has(POLITE + "|" + ACTION, t) \
                and not c.get("answered_with_promise"):
            for x in later:
                if x["sender_id"] == "ME" and x["ts"] - m["ts"] <= 12 * 3600:
                    if not has(COMMIT, ctx.text[x["id"]]):
                        return "done", x["id"]
                    break
        doer = "ME" if owner == "ME" else owner
        for k, x in enumerate(later):
            xt = ctx.text[x["id"]]
            age = x["ts"] - m["ts"]
            # A reply that quotes the loop's own message is about it for sure.
            if x.get("quoted_id") == m["id"] and x["sender_id"] == doer and "?" not in xt \
                    and (has(DONE, xt) or (c["kind"] == "ask_me" and "?" in t)):
                return "done", x["id"]
            if "?" in xt:
                continue
            if age > 6 * 3600 and k > 20:
                break  # in a busy chat a later "done" is about something else
            if x["sender_id"] == doer and age <= 2 * 86400 and has(DONE, xt) and not has(r"not|nahi|didn'?t|haven'?t", xt):
                return "done", x["id"]
            if x["sender_id"] == doer and x["kind"] in ("image_caption", "document") and age <= 86400 \
                    and has(r"pay|send|share|bill|invoice|receipt|screenshot|photo|pic|copy|details|link", t):
                return "done", x["id"]
            if asker != "ME" and x["sender_id"] == asker and doer == "ME" and age <= 6 * 3600 and k <= 10 \
                    and len(xt) < 60 and has(THANKS, xt) and any(y["sender_id"] == "ME" for y in later[:k]):
                return "done", x["id"]
        return "open", None

    # ------------------------------------------------------------------ helping
    def help(self, c, owner, ltype, due):
        m = c["msg"]
        t = self.ctx.text[m["id"]]
        if c.get("answered_with_promise"):
            t += " " + self.ctx.text[c["answered_with_promise"]["id"]]
        if owner != "ME":
            return {"action": "leave", "reason": f"{self.name(owner)} owns this; Arjun is waiting, not acting."}
        if has(SENSITIVE, t) and c["kind"] != "birthday":
            return {"action": "leave", "reason": "Personal; better left to Arjun."}
        sent = local(m["ts"])
        if due:
            d = datetime.fromisoformat(due).replace(tzinfo=IST)
            at = (d - timedelta(days=1)).replace(hour=18, minute=0) if d.date() > sent.date() + timedelta(days=1) \
                else d.replace(hour=9, minute=30)
            if at <= sent:
                at = sent + timedelta(hours=2)
            return {"action": "remind", "remind_at": at.isoformat()}
        if has(ASSISTABLE, t) and ltype != "question":
            return {"action": "assist", "next_step": "Shortlist options and draft it for Arjun to approve: " +
                    re.sub(r"\s+", " ", m.get("body") or "")[:80], "needs_yes": True}
        at = (sent + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
        return {"action": "remind", "remind_at": at.isoformat()}

    def run(self, threshold=THRESHOLD):
        loops = []
        for c in self.candidates():
            if c["score"] < threshold:
                continue
            m = c["msg"]
            owner = self.owner(c)
            if owner != "ME" and owner not in self.ctx.names:
                owner = "ME"
            if c["kind"] == "birthday":  # wishes are due the day they start
                due = local(m["ts"]).date().isoformat()
            else:
                due = parse_due(self.ctx.text[m["id"]], m["ts"])
            ltype = self.loop_type(c, due)
            status, closed_by = self.status(c, owner)
            loop = {"title": self.title(c, owner), "type": ltype, "owner": owner, "chat_id": m["chat_id"],
                    "source_msg": m["id"], "due": due, "status": status, "closed_by": closed_by,
                    "help": self.help(c, owner, ltype, due) if status == "open" else None}
            loop["_score"] = c["score"]
            loops.append(loop)
        # A message that closes one loop ("Proofs attached, please check") does not open another.
        closers = {l["closed_by"] for l in loops if l["closed_by"]}
        loops = [l for l in loops if l["source_msg"] not in closers]
        loops.sort(key=lambda l: self.ctx.msg[l["source_msg"]]["ts"])
        return loops
