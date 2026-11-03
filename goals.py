"""Goals, from what Arjun keeps talking about and planning, area by area.

Each message Arjun sends (or receives in a 1:1 chat) is scored for each life area by the area's words
plus planning language ("want to", "book", "by March"). An area becomes a goal only when several
messages support it; its evidence is the best few messages. The seeded goal is carried through with
the messages that match its title. Goals are not labelled on the dev set, so none of this is tuned.
"""
import re
from collections import Counter

from ctx import has_word, words

PLAN = (r"plan|planning|planned|want to|wanna|going to|gonna|will|next week|next month|next year|this month|"
        r"this year|this quarter|target|goal|aim|start|started|join|joined|book|booked|register|sign up|"
        r"finish|complete|launch|build|building|buy|save|invest|by (?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|"
        r"dec)[a-z]*|every day|daily|weekly|routine|habit|regularly")

# area, goal type, horizon, words, title
AREAS = [
    ("health", "habit", "3mo",
     r"yoga|gym|workout|work out|run|runs|running|marathon|half marathon|10k|5k|pickle ?ball|table tennis|"
     r"badminton|tennis|squash|swim|swimming|walk|walking|steps|diet|weight|fitness|exercise|sugar|sleep|"
     r"meditation|cycling|trek|trekking|protein|physio", "Keep up {kw}"),
    ("experiences", "experience", "3mo",
     r"trip|travel|vacation|holiday|holidays|tour|flight|flights|tickets|hotel|homestay|resort|safari|"
     r"itinerary|getaway|beach|mountains|concert|festival|picnic|retreat|cruise", "Plan the {kw}"),
    ("kids", "milestone", "1yr",
     r"kids|kid|son|daughter|school|exam|exams|tuition|piano|guitar|teacher|coaching|practice|homework|"
     r"admission|tutor|olympiad|swimming class|classes", "Kids: {kw}"),
    ("home", "milestone", "3mo",
     r"renovation|renovate|interior|interiors|tiles|tile|marble|paint|painting|carpenter|furniture|sofa|"
     r"carpet|rug|lights|light|fan|fans|curtains|studio|bathroom|wallpaper|panelling|flooring|speakers|"
     r"home theatre|ac|wardrobe|kitchen|farmhouse|farm", "Home: {kw}"),
    ("finances", "milestone", "1yr",
     r"shares|share price|stock|stocks|invest|investment|investments|portfolio|mutual fund|sip|broker|demat|"
     r"tax|itr|fd|gold|loan|emi|savings|returns|equity", "Finances: {kw}"),
    ("work", "milestone", "1yr",
     r"clients?|launch|product|revenue|hiring|hire|fundraise|fundraising|investors?|pitch|deck|pilot|sales|"
     r"growth|mvp|demo|customers?|brands?|partnership|roadmap|ai agents?", "Work: {kw}"),
    ("self", "habit", "1yr",
     r"learn|learning|course|reading|journal|journaling|skill|certification|meditate", "Self: {kw}"),
    ("friends", "experience", "3mo",
     r"reunion|get together|meetup|game night|poker|catch up|friends trip", "Friends: {kw}"),
]
MAX_GOALS = 6
EVIDENCE = 8


def word_hits(pattern, text):
    return re.findall(r"(?<![a-z0-9])(?:" + pattern + r")(?![a-z0-9])", text)


class Goals:
    def __init__(self, ctx):
        self.ctx = ctx

    def pool(self):
        """Messages that speak for Arjun: his own, and what people tell him one to one."""
        ctx = self.ctx
        for m in ctx.messages:
            t = ctx.text[m["id"]]
            if len(t) < 12 or "http" in t[:8]:
                continue
            chat = ctx.chat.get(m["chat_id"], {})
            if m["sender_id"] == "ME" or not chat.get("is_group"):
                yield m, t

    def seeded(self):
        out = []
        for g in self.ctx.seed.get("goals") or []:
            if not isinstance(g, dict) or not g.get("title"):
                continue
            key = {w for w in words(g["title"]) if len(w) >= 4}
            scored = sorted(((len(key & set(words(t))), -m["ts"], m["id"]) for m, t in self.pool()), reverse=True)
            evidence = [mid for n, _, mid in scored[:EVIDENCE] if n >= 2]
            if evidence:
                out.append({"title": g["title"], "area": g.get("area", "work"), "type": g.get("type", "milestone"),
                            "horizon": g.get("horizon", "1yr"), "evidence": evidence})
        return out

    def run(self):
        goals = self.seeded()
        taken = {g["area"] for g in goals}
        ranked = []
        for area, gtype, horizon, pattern, title in AREAS:
            if area in taken:
                continue
            scored, kw = [], Counter()
            for m, t in self.pool():
                hits = word_hits(pattern, t)
                if not hits:
                    continue
                plan = has_word(PLAN, t)
                mine = m["sender_id"] == "ME"
                s = len(set(hits)) + 1.5 * plan + 1.0 * mine + 0.5 * ("?" in t and not mine)
                if plan or mine or "?" in t:
                    scored.append((s, m["ts"], m["id"]))
                    kw.update(sorted(set(hits)))
            scored.sort(reverse=True)
            strong = [x for x in scored if x[0] >= 3.0]
            if len(strong) >= max(2, len(self.ctx.messages) // 2500):
                top_kw = ", ".join(k for k, _ in kw.most_common(3))
                ranked.append((sum(x[0] for x in scored[:15]), {
                    "title": title.format(kw=top_kw), "area": area, "type": gtype, "horizon": horizon,
                    "evidence": [mid for _, _, mid in scored[:EVIDENCE]]}))
        ranked.sort(key=lambda x: -x[0])
        goals += [g for _, g in ranked[:max(0, MAX_GOALS - len(goals))]]
        return goals[:10]
