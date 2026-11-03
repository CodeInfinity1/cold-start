"""People, organisations and chat ties.

Everything is inferred from structure that survives renaming: the seed's org names (and their
acronyms), words people use in contact names ("Home", "Office", "Traders", "Mamaji"), shared
surnames, who sits in which groups, and a few phrases in 1:1 chats. No names from any answer key.
"""
import re
from collections import Counter, defaultdict

from ctx import clean, has_word, words

CIRCLES = ["spouse", "child", "parent", "in-law", "sibling", "relative", "friend", "colleague", "client", "vendor",
           "partner", "staff"]

# Words in a contact's name (romanised Indian WhatsApp usage).
PARENT = r"mom|mum|mummy|mumma|mommy|mother|maa|papa|pappa|daddy|dad|father|pitaji|mataji"
INLAW = (r"sasur|sasurji|saas|saasu|father in law|mother in law|fil|mil|brother in law|sister in law|jiju|jija|"
         r"jijaji|jeeju|bhabhi|bhabi|bhabhiji|devar|devrani|jethani|nanad|nanand|samdhi|samdhan")
RELATIVE = (r"chacha|chachi|chachu|chachaji|chachiji|mama|mamaji|mami|mamiji|mausi|masi|mausa|mausaji|mousi|bua|"
            r"buaji|fufa|fufaji|phupha|phuphi|nana|nani|nanaji|naniji|dadaji|dadiji|dadi|dadu|tauji|taiji|cousin|"
            r"uncle|aunty|auntie|aunt|niece|nephew|bhanja|bhanji|bhatija|bhatiji|kaka|kaki|kakima|jethu|jethima|"
            r"pishi|pishimoni|mashi|masimoni|mesho|dida")
SIBLING = r"brother|sister"
SPOUSE = r"wife|wifey|hubby|husband"
CHILD = r"son|daughter"
STAFF = (r"driver|maid|cook|chef|guard|watchman|darwan|security|gardener|mali|helper|caretaker|care taker|nanny|"
         r"aaya|ayah|peon|housekeeping|housekeeper|cleaner|sweeper|attendant|servant|office boy|house help|househelp")
# A place word in a contact's name means "the person at that place", which for Arjun is staff.
PLACES = [
    ("home", "Home", "residence", "home", r"home|ghar"),
    ("office", "Office", "workspace", "work", r"office"),
    ("farm", "Farmhouse", "vacation home", "home", r"farm|farmhouse|farm house|bungalow|villa"),
]
VENDOR_STRONG = (r"traders?|trading|enterprises?|company|pvt|ltd|llp|services|solutions|agency|agencies|stores?|"
                 r"mart|industries|corporation|associates|consultants?|wholesale|distributors?|dealers?|suppliers?")
VENDOR_WEAK = (r"electricals?|electrician|plumber|carpenter|contractor|interiors?|decor|tiles|marble|tailor|"
               r"furniture|furnishings?|hardware|paints?|repairs?|courier|travels|tours|classes|tutor|tuition|teacher|"
               r"coach|yoga|gym|fitness|trainer|salon|parlou?r|spa|clinic|dr|doctor|dentist|physio|pharmacy|chemist|"
               r"medicals?|lawyer|advocate|broker|insurance|properties|realty|builders?|photography|photographer|"
               r"printers?|printing|caterers?|catering|florist|transport|logistics|packers|movers|pest|laundry|"
               r"water treatment|motors|garage|jewell?ers|boutique|fabrics|textiles|framing|frames|glass|sanitary|"
               r"lighting|modular|ca|sir")

# Words in group names.
GENERIC = set("""the and x of for with a an to in on at by our my your group grp groups team teams official
community circle circles forum connect connects network club chat chats ops operations update updates family
friends marketing ads ad targeting finance sales meta ai india kolkata delhi mumbai bangalore bengaluru chennai
pune hyderabad ahmedabad ncr new old core internal admin hq office management project projects work works only
all members alerts info announcements discussion discussions support help desk east west north south central
live news tech strategy growth hub labs pvt ltd co""".split())
OPS = r"operations|ops|team|staff|accounts|admin|hq|internal|management|core team"
HOME_GROUP = (r"kitchen|carpool|car pool|maid|maids|driver|drivers|cook|groceries|grocery|ration|society|residents|"
              r"resident|apartment|apartments|building|flat owners|rwa|maintenance|househelp|house help")
FLAT_NO = re.compile(r"(?<![a-z0-9])\d{1,3} ?[a-h](?![a-z0-9])")
HOME_GROUP_WEAK = r"home|ghar"
FAMILY_GROUP = (r"family|fam|famjam|parivar|parivaar|khandan|khandaan|siblings|sibs|cousins|bro|sis|brothers|"
                r"sisters|husbands|wives|in laws|inlaws|relatives")
FAMILY_CIRCLES = {"spouse", "child", "parent", "in-law", "sibling", "relative"}

# Phrases in a 1:1 chat that say what the person does for Arjun.
VENDOR_CUE = (r"quotation|quote|rates?|price|pricing|per kg|per sqft|sqft|sq ft|gst|invoice|bill|billing|advance|"
              r"deliver|delivery|dispatch|samples?|catalog|catalogue|measurements?|estimate|fees?|site visit|"
              r"installation|install|material|warranty|godown|payment")
COLLEAGUE_CUE = (r"on leave|sick leave|leave today|wfh|work from home|half day|salary|attendance|intern|internship|"
                 r"certificate|offer letter|joining date|resign|resignation|appraisal|backup|deploy|standup|sprint|"
                 r"able to (?:come|make it)|to the office today|to office today|in office today")
CLIENT_CUE = (r"campaign|campaigns|report|ad account|leads|roi|roas|results|dashboard|creatives?|our brand|"
              r"our stores?|our outlets?|purchase order|proposal|onboarding|catchment")
RESPECT = r"sir|madam|maam|ma'am|ji"


COMMUNITY = r"community|forum|circle|connect|network|club|marketers|founders|members"
# Elders call Arjun "beta" as a form of address ("ok beta", "beta, call me"), not "the beta is live".
CALLS_BETA = re.compile(r"^(?:beta|betu|bachha) ?[,!]|(?:ok|okay|haan|ha|hi|hello|thanks|thank you|bye|love you|"
                        r"god bless)[ ,!]+(?:beta|betu|bachha)(?![a-z])|(?<![a-z])(?:beta|betu|bachha)[ !.,🙏❤️]*$")
PLACE_IDS = {"home", "office", "farm", "personal"}
# What a driver, nanny or attendant says when looking after someone ("6 baje pick kar lunga", "X ko ghar chhod diya").
CARE = (r"pick|picks|picked|picking|pickup|pick up|drop|drops|dropped|dropping|chhod|chhoda|chhodi|chod|choda|"
        r"le aa\w*|le ja\w*|le gaya|le gayi|lene|lekar|pahuncha\w*|feed|fed|khilaya|khila\w*|nahla\w*|bathe|"
        r"bathed|medicine|dawai|dawa")


def addressed_as(texts, pattern):
    """Is the person called this word, as in "hi masiji ..." or "papa, please ..."? A bare word at the start
    ("Mom said the tickets are booked") is a topic, not an address, so it needs a greeting before or a comma after."""
    rx = re.compile(r"^(?:(?:hi|hello|hey|dear|good morning|gm)[ ,!.]+(?:" + pattern + r")(?![a-z0-9])"
                    r"|(?:" + pattern + r") ?[,!])")
    return any(rx.match(t) for t in texts)


def slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", clean(name)).strip("-")
    return s or "org"


def seed_org_tokens(name):
    """How a seeded organisation shows up in chat names: its name, squashed, and its acronym
    ("BlueMoonAds" -> "bma"), and the first word of a multi-word name. A two-letter acronym is too
    ambiguous in lowercase, so it is returned separately and only matched as an uppercase word."""
    toks, short = set(), set()
    n = clean(name)
    if n:
        toks.add(n)
    squashed = re.sub(r"[^a-z0-9]", "", n)
    if len(squashed) >= 3:
        toks.add(squashed)
    parts = re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", name or "")
    if len(parts) >= 2:
        acronym = "".join(p[0] for p in parts)
        if len(acronym) >= 3:
            toks.add(acronym.lower())
        elif len(acronym) == 2:
            short.add(acronym.upper())
    if " " in n:
        first = n.split()[0]
        if len(first) >= 4 and first not in GENERIC:
            toks.add(first)
    return toks, short


def org_position(raw, org):
    """Where an org is named in a raw (uncleaned) chat or contact name, else None."""
    pos = mentions(clean(raw), org.get("tokens") or set())
    for a in org.get("short") or ():
        m = re.search(r"(?<![A-Za-z0-9])" + re.escape(a) + r"(?![A-Za-z0-9])", raw or "")
        if m and (pos is None or m.start() < pos):
            pos = m.start()
    return pos


def mentions(text, tokens):
    """Position of the first token found in cleaned text, else None."""
    best = None
    for t in tokens:
        m = re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", text)
        if m and (best is None or m.start() < best):
            best = m.start()
    return best


def surnames(names):
    """Likely surnames: the last real word of each multi-word name, skipping descriptive words."""
    out = set()
    for n in names:
        ws = [w for w in words(n) if not w.isdigit()]
        while ws and (ws[-1] in GENERIC or re.fullmatch(
                "|".join([PARENT, INLAW, RELATIVE, STAFF, VENDOR_STRONG, VENDOR_WEAK, r"home|ghar|office|farm|ji|sir"]),
                ws[-1])):
            ws.pop()
        if len(ws) >= 2 and len(ws[-1]) >= 3:
            out.add(ws[-1])
    return out


class Structure:
    """Works out organisations, circles, links and chat ties. Call .run(), then .output()."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.orgs = {}          # id -> {id, name, type, side, role, tokens}
        self.chat_org = {}      # group chat id -> org id
        self.internal = defaultdict(set)   # org id -> internal group chat ids
        self.circle = {}
        self.why = {}           # person -> short reason (for debugging and the write-up)
        self.links = defaultdict(dict)     # person -> org id -> runs|supports
        self.place_of = {}      # staff person -> place org id
        self.looks_after = {}   # staff person -> people they look after
        self.gname = {c["chat_id"]: clean(c.get("name")) for c in ctx.chats}

    # ------------------------------------------------------------------ organisations
    def find_orgs(self):
        ctx = self.ctx
        groups = [c["chat_id"] for c in ctx.chats if c.get("is_group")]
        for name in ctx.seed.get("organisations") or []:
            if isinstance(name, dict):
                name = name.get("name") or ""
            if not name:
                continue
            oid = slug(name)
            if oid in PLACE_IDS or oid in self.orgs:
                oid = f"{oid}-{len(self.orgs) + 1}"
            toks, short = seed_org_tokens(name)
            self.orgs[oid] = {"id": oid, "name": name, "type": "company", "side": "work", "role": "owner",
                              "tokens": toks, "short": short}

        def assign_by_tokens(chat_ids, key):
            for cid in chat_ids:
                if cid in self.chat_org:
                    continue
                hits = []
                for oid, o in self.orgs.items():
                    if key == "tokens":
                        pos = org_position(ctx.chat[cid].get("name") or "", o)
                    else:
                        pos = mentions(self.gname[cid], o.get(key) or set())
                    if pos is not None:
                        hits.append((pos, oid))
                if hits:
                    self.chat_org[cid] = min(hits)[1]

        assign_by_tokens(groups, "tokens")

        # Distinctive words that keep appearing next to an org's name ("B2B" in "Acme B2B ...") also mark it.
        all_tokens = set().union(*(o["tokens"] for o in self.orgs.values())) if self.orgs else set()
        for oid, o in self.orgs.items():
            cnt = Counter(w for cid, x in self.chat_org.items() if x == oid for w in set(words(self.gname[cid])))
            o["expansion"] = {w for w, n in cnt.items() if n >= 2 and len(w) >= 3 and not w.isdigit()
                              and w not in GENERIC and w not in all_tokens}
        assign_by_tokens(groups, "expansion")

        # "<Name> operations" / "<Name> team": an organisation of its own.
        for cid in groups:
            if cid in self.chat_org or not has_word(OPS, self.gname[cid]) or self._family_group(cid):
                continue
            raw = re.findall(r"[A-Za-z0-9&']+", self.ctx.chat[cid].get("name") or "")
            rest = [w for w in raw if clean(w) not in GENERIC and not re.fullmatch(OPS, clean(w))]
            if not rest:
                continue
            name = " ".join(rest)
            oid = slug(name)
            if oid in PLACE_IDS:
                oid += "-co"
            if oid not in self.orgs:
                self.orgs[oid] = {"id": oid, "name": name, "type": "company", "side": "work", "role": "member",
                                  "tokens": {clean(name)}, "expansion": set()}
            self.chat_org[cid] = oid
        assign_by_tokens(groups, "tokens")

        # Internal groups: the org's name plus generic words only ("Acme Operations", "Acme: Finance"), and not
        # a community of outsiders ("... Community", "... Forum").
        for cid, oid in self.chat_org.items():
            own = self.orgs[oid]["tokens"] | {a.lower() for a in self.orgs[oid].get("short", ())}
            rest = [w for w in words(self.gname[cid]) if w not in GENERIC and w not in own and not re.fullmatch(OPS, w)]
            if not rest and not has_word(COMMUNITY, self.gname[cid]):
                self.internal[oid].add(cid)

        # A group mostly made of an org's internal people belongs to that org.
        core = {oid: {p for cid in cids for p in ctx.chat[cid]["participants"] if p != "ME"}
                for oid, cids in self.internal.items()}
        for cid in groups:
            if cid in self.chat_org:
                continue
            ps = set(ctx.chat[cid]["participants"]) - {"ME"}
            if len(ps) < 3:
                continue
            best = max(((len(ps & c) / len(ps), oid) for oid, c in core.items()), default=(0, None))
            if best[0] >= 0.5:
                self.chat_org[cid] = best[1]

        # Household groups: the kitchen, the carpool, the building, flat numbers like "9F".
        for cid in groups:
            if cid in self.chat_org:
                continue
            g = self.gname[cid]
            strong = has_word(HOME_GROUP, g) or FLAT_NO.search(g) is not None
            weak = has_word(HOME_GROUP_WEAK, g) and not self._family_group(cid)
            if strong or weak:
                self._ensure_place("home")
                self.chat_org[cid] = "home"

    def _ensure_place(self, key):
        for k, name, typ, side, pattern in PLACES:
            if k == key and key not in self.orgs:
                self.orgs[key] = {"id": key, "name": name, "type": typ, "side": side, "role": "owner",
                                  "tokens": set(), "expansion": set()}
        return key

    def _family_group(self, cid):
        """A family group by its name, or because most members share Arjun's surname or are seeded family."""
        g = self.gname[cid]
        if has_word(FAMILY_GROUP, g):
            return True
        sur = self.ctx.me_surname
        if sur and (has_word(re.escape(sur) + "s?", g)):
            return True
        ps = [p for p in self.ctx.chat[cid]["participants"] if p != "ME"]
        if not ps:
            return False
        seed = self.ctx.seed.get("circles") or {}
        fam = sum(1 for p in ps if seed.get(p) in FAMILY_CIRCLES or self.circle.get(p) in FAMILY_CIRCLES
                  or (sur and sur in surnames(self.ctx.names[p])))
        return fam >= 2 and fam / len(ps) >= 0.5

    def company_orgs(self):
        return [oid for oid, o in self.orgs.items() if o["type"] == "company"]

    # ------------------------------------------------------------------ circles
    def set(self, p, circle, why):
        if p not in self.circle:
            self.circle[p] = circle
            self.why[p] = why

    def find_circles(self):
        ctx = self.ctx
        seed = ctx.seed.get("circles") or {}
        for p, c in seed.items():
            if p in ctx.names and c in CIRCLES:
                self.set(p, c, "seed")

        # 1. What Arjun calls them.
        for p in ctx.people:
            lab = ctx.label[p]
            for key, name, typ, side, pattern in PLACES:
                if has_word(pattern, lab):
                    self.set(p, "staff", "place word in name")
                    self.place_of.setdefault(p, key)
            if has_word(STAFF, lab):
                self.set(p, "staff", "staff word in name")
                self.place_of.setdefault(p, "home")
            if has_word(VENDOR_STRONG, lab):
                self.set(p, "vendor", "business word in name")
            for pattern, circle in ((INLAW, "in-law"), (PARENT, "parent"), (RELATIVE, "relative"),
                                    (SPOUSE, "spouse"), (SIBLING, "sibling"), (CHILD, "child")):
                if has_word(pattern, lab):
                    self.set(p, circle, "kinship word in name")

        # 2. The spouse: by far the busiest 1:1 chat, usually with the same surname.
        if "spouse" not in self.circle.values():
            dm_volume = sorted(((len(ctx.by_chat.get(cid, [])), p) for p, cid in ctx.dm_of.items()), reverse=True)
            if dm_volume:
                top_n, top_p = dm_volume[0]
                second = dm_volume[1][0] if len(dm_volume) > 1 else 0
                same_surname = ctx.me_surname and ctx.me_surname in surnames(ctx.names[top_p])
                if top_p not in self.circle and top_n >= 100 and (same_surname or top_n >= 3 * max(second, 1)):
                    self.set(top_p, "spouse", "busiest 1:1 chat")

        # 3. How they address each other in their 1:1 chat ("hi masiji", "ok beta").
        for p, cid in ctx.dm_of.items():
            msgs = ctx.by_chat.get(cid, [])
            mine = [ctx.text[m["id"]] for m in msgs if m["sender_id"] == "ME"]
            theirs = [ctx.text[m["id"]] for m in msgs if m["sender_id"] == p]
            if addressed_as(mine, PARENT) or any(CALLS_BETA.search(t) for t in theirs):
                self.set(p, "parent", "addressed as a parent")
            if addressed_as(mine, INLAW):
                self.set(p, "in-law", "addressed as an in-law")
            if addressed_as(mine, RELATIVE):
                self.set(p, "relative", "addressed as a relative")

        # 4. Arjun's own surname.
        if ctx.me_surname:
            for p in ctx.people:
                if ctx.me_surname in surnames(ctx.names[p]):
                    self.set(p, "relative", "shares Arjun's surname")

        # 5. Work: named after one of the orgs, in its internal groups, or across several of its client groups.
        companies = set(self.company_orgs())
        org_groups = defaultdict(set)
        for cid, oid in self.chat_org.items():
            if not has_word(COMMUNITY, self.gname[cid]):
                org_groups[oid].add(cid)
        works_at = {}
        for p in ctx.people:
            named = [oid for oid in companies if any(org_position(n, self.orgs[oid]) is not None for n in ctx.names[p])]
            inside = [oid for oid in companies if set(ctx.groups_of[p]) & self.internal[oid]]
            many = [oid for oid in companies if len(set(ctx.groups_of[p]) & org_groups[oid]) >= 3]
            works_at[p] = (sorted(set(named + inside + many)), named)
            if works_at[p][0]:
                self.set(p, "colleague", "works at " + ",".join(works_at[p][0]))

        # 6. Family groups, then anyone sharing a (not too common) surname with family.
        for p in ctx.people:
            if any(self._family_group(cid) for cid in ctx.groups_of[p] if cid not in self.chat_org):
                self.set(p, "relative", "in a family group")
        holders = defaultdict(set)
        for p in ctx.people:
            for s in surnames(ctx.names[p]):
                holders[s].add(p)
        for s, ps in holders.items():
            fam = [p for p in ps if self.circle.get(p) in FAMILY_CIRCLES and self.circle.get(p) != "spouse"]
            if fam and len(ps) <= 8:
                for p in ps:
                    self.set(p, "relative", "shares a family surname")

        # 7. Outsiders in an org's groups are its clients.
        for p in ctx.people:
            if any(self.chat_org.get(cid) in companies for cid in ctx.groups_of[p]):
                self.set(p, "client", "in a client group")

        # 8. Service words in the name ("tuition classes", "plumbing works").
        for p in ctx.people:
            if has_word(VENDOR_WEAK, ctx.label[p]):
                self.set(p, "vendor", "service word in name")

        # 9. What the 1:1 chat is about.
        for p, cid in ctx.dm_of.items():
            if p in self.circle:
                continue
            msgs = ctx.by_chat.get(cid, [])
            theirs = " ".join(ctx.text[m["id"]] for m in msgs if m["sender_id"] == p)
            both = " ".join(ctx.text[m["id"]] for m in msgs)
            score = {
                "vendor": len(re.findall(r"(?<![a-z])(?:" + VENDOR_CUE + r")(?![a-z])", both)),
                "colleague": len(re.findall(r"(?<![a-z])(?:" + COLLEAGUE_CUE + r")(?![a-z])", both)),
                "client": len(re.findall(r"(?<![a-z])(?:" + CLIENT_CUE + r")(?![a-z])", both)),
            }
            if has_word(RESPECT, theirs):
                score["vendor"] += 1
                score["colleague"] += 1
            best = max(score.items(), key=lambda kv: kv[1])
            if best[1] >= 2:
                self.set(p, best[0], "1:1 chat talks like a " + best[0])

        # 10. Everyone else Arjun knows socially.
        for p in ctx.people:
            self.set(p, "friend", "default")

        # Links. Colleagues run the orgs they work at, but only the ones Arjun deals with directly (a 1:1 chat
        # or the seed): big internal groups are mostly people he has never placed.
        seed = ctx.seed.get("circles") or {}
        for p, (orgs, named) in works_at.items():
            if self.circle.get(p) == "colleague" and (p in ctx.dm_of or p in seed):
                for oid in orgs:
                    self.links[p][oid] = "runs"
        # Staff support the place they are named after.
        for p, key in self.place_of.items():
            if self.circle.get(p) == "staff":
                self._ensure_place(key)
                self.links[p][key] = "supports"

    def find_looks_after(self):
        """Staff -> the people they look after, only on repeated evidence: at least two of the staff member's
        own care messages (pick up, drop, feed, medicine) tied to that person, at least one naming them by a
        first name no one else in the data has. A care message tied by reply alone is not enough: whoever
        gives a driver instructions is not necessarily the one being driven."""
        ctx = self.ctx
        holders = defaultdict(set)
        for p in ctx.people:
            for n in ctx.names[p]:
                ws = [w for w in words(n) if not w.isdigit()]
                if ws and len(ws[0]) >= 3:
                    holders[ws[0]].add(p)
        stop = set(GENERIC) | {ctx.me_first}
        unique = {w: next(iter(ps)) for w, ps in holders.items() if len(ps) == 1 and w not in stop
                  and not re.fullmatch("|".join([CARE, STAFF, PARENT, RELATIVE, r"home|ghar|office|sir|madam|ji"]), w)}
        named, replied = defaultdict(Counter), defaultdict(Counter)
        for s in [p for p in ctx.people if self.circle.get(p) == "staff"]:
            chats = set(ctx.groups_of[s]) | ({ctx.dm_of[s]} if s in ctx.dm_of else set())
            for cid in chats:
                msgs = ctx.by_chat.get(cid, [])
                for i, m in enumerate(msgs):
                    t = ctx.text[m["id"]]
                    if m["sender_id"] != s or not has_word(CARE, t):
                        continue
                    for x in {unique[w] for w in words(t) if w in unique} - {s}:
                        named[s][x] += 1
                    prev = ctx.msg.get(m.get("quoted_id")) or (msgs[i - 1] if i else None)
                    if prev and prev["sender_id"] not in ("ME", s) and m["ts"] - prev["ts"] <= 3600:
                        replied[s][prev["sender_id"]] += 1
        for s in named:
            who = [x for x in named[s] if named[s][x] + replied[s][x] >= 2 and self.circle.get(x) != "staff"]
            if who:
                self.looks_after[s] = sorted(who)

    # ------------------------------------------------------------------ output
    def run(self):
        self.find_orgs()
        self.find_circles()
        self.find_looks_after()
        return self

    def tie(self, cid):
        ctx = self.ctx
        if cid in self.chat_org:
            return {"chat_id": cid, "organisation": self.chat_org[cid]}
        other = ctx.other(cid)
        if other:
            return {"chat_id": cid, "person": other}
        ps = [p for p in ctx.chat[cid].get("participants", []) if p != "ME"]
        if not ps:  # a chat with nobody else in it (notes to self): every chat must be tied to something
            self.orgs.setdefault("personal", {"id": "personal", "name": "Personal", "type": "other", "side": "home",
                                              "role": "owner", "tokens": set(), "expansion": set()})
            self.chat_org[cid] = "personal"
            return {"chat_id": cid, "organisation": "personal"}
        active = ctx.sent_in[cid]
        best = max(ps, key=lambda p: (active.get(p, 0), -ps.index(p)))
        return {"chat_id": cid, "person": best}

    def output(self):
        chats = []
        for c in self.ctx.chats:
            t = self.tie(c["chat_id"])
            if t:
                chats.append(t)
        used = set(self.chat_org.values()) | {o for ls in self.links.values() for o in ls}
        orgs = [{k: o[k] for k in ("id", "name", "type", "side", "role")} for oid, o in self.orgs.items()
                if oid in used]
        people = []
        for p in self.ctx.people:
            entry = {"id": p, "circle": self.circle.get(p, "friend")}
            links = [{"organisation": o, "link": l} for o, l in sorted(self.links.get(p, {}).items()) if o in used]
            if links:
                entry["links"] = links
            if self.looks_after.get(p):
                entry["looks_after"] = self.looks_after[p]
            people.append(entry)
        return people, orgs, chats
