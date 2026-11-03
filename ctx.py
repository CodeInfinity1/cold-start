"""Loading the input, plus the small text and time helpers every stage shares.

Standard library only. Nothing here knows any name from the data: everything is derived from the
input folder (chats.jsonl, messages.jsonl, seed.json).
"""
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
MEDIA_ONLY = re.compile(r"^\[(photo|video|document|audio|sticker|gif|image|voice)[^\]]*\]$")
MENTION = re.compile(r"@(\d{5,})")


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def clean(text):
    """Lowercase, invisible/format characters and stray combining marks removed, whitespace collapsed."""
    text = "".join(ch for ch in (text or "") if unicodedata.category(ch) not in ("Cf", "Mn"))
    return re.sub(r"\s+", " ", text).strip().lower()


def words(text):
    return re.findall(r"[a-z0-9]+", clean(text))


def has_word(pattern, text):
    """True when a regex alternation matches as whole words in already-cleaned text."""
    return re.search(r"(?<![a-z0-9])(?:" + pattern + r")(?![a-z0-9])", text) is not None


def local(ts):
    return datetime.fromtimestamp(ts, IST)


def is_media_only(text):
    """text is a cleaned body."""
    return MEDIA_ONLY.match(text) is not None


class Ctx:
    """The input, indexed the ways the stages need it."""

    def __init__(self, folder):
        folder = Path(folder)
        self.chats = read_jsonl(folder / "chats.jsonl")
        self.messages = sorted(read_jsonl(folder / "messages.jsonl"), key=lambda m: (m["ts"], m["id"]))
        seed_path = folder / "seed.json"
        self.seed = json.loads(seed_path.read_text(encoding="utf-8")) if seed_path.exists() else {}

        self.chat = {c["chat_id"]: c for c in self.chats}
        self.msg = {m["id"]: m for m in self.messages}
        self.text = {m["id"]: clean(m.get("body")) for m in self.messages}  # cleaned once, used everywhere
        self.by_chat = defaultdict(list)
        for m in self.messages:
            if m["chat_id"] in self.chat:
                self.by_chat[m["chat_id"]].append(m)
        self.pos = {}
        for msgs in self.by_chat.values():
            for i, m in enumerate(msgs):
                self.pos[m["id"]] = i

        # People are the chat participants (the checker only accepts those ids).
        self.people = sorted({p for c in self.chats for p in c.get("participants", [])} - {"ME"})
        self.dm_of = {}
        self.groups_of = defaultdict(list)
        for c in self.chats:
            others = [p for p in c.get("participants", []) if p != "ME"]
            if not c.get("is_group") and len(others) == 1:
                self.dm_of.setdefault(others[0], c["chat_id"])
            elif c.get("is_group"):
                for p in others:
                    self.groups_of[p].append(c["chat_id"])

        self.sent = Counter(m["sender_id"] for m in self.messages)
        self.sent_in = defaultdict(Counter)  # chat -> sender -> count
        sender_names = defaultdict(Counter)
        for m in self.messages:
            self.sent_in[m["chat_id"]][m["sender_id"]] += 1
            sender_names[m["sender_id"]][m.get("sender_name") or ""] += 1

        # Every name we have for a person: how they appear as a sender, and what their 1:1 chat is called.
        self.names = {}
        for p in self.people:
            names = [n for n, _ in sender_names[p].most_common() if n]
            dm = self.dm_of.get(p)
            if dm and self.chat[dm].get("name"):
                names.append(self.chat[dm]["name"])
            self.names[p] = names
        self.label = {p: clean(" | ".join(self.names[p])) for p in self.people}

        me_names = sender_names["ME"]
        self.me_name = me_names.most_common(1)[0][0] if me_names else ""
        toks = words(self.me_name)
        self.me_first = toks[0] if toks else ""
        self.me_surname = toks[-1] if len(toks) >= 2 else ""

        self.handle_owner = self._mention_handles()
        self.me_handles = {h for h, p in self.handle_owner.items() if p == "ME"}
        self.start_ts = self.messages[0]["ts"] if self.messages else 0
        self.end_ts = self.messages[-1]["ts"] if self.messages else 0

    def _mention_handles(self):
        """Map @12345 mention handles to a person: the only participant common to every chat where the
        handle appears, leaving out whoever typed it (people don't @mention themselves)."""
        where, writers = defaultdict(set), defaultdict(set)
        for m in self.messages:
            for h in MENTION.findall(m.get("body") or ""):
                where[h].add(m["chat_id"])
                writers[h].add(m["sender_id"])
        owner = {}
        for h, chat_ids in where.items():
            common = None
            for cid in chat_ids:
                parts = set(self.chat[cid].get("participants", [])) if cid in self.chat else set()
                common = parts if common is None else common & parts
            common = (common or set()) - writers[h]
            if len(common) == 1:
                owner[h] = next(iter(common))
        return owner

    def other(self, chat_id):
        """The other person in a 1:1 chat, else None."""
        c = self.chat[chat_id]
        others = [p for p in c.get("participants", []) if p != "ME"]
        return others[0] if not c.get("is_group") and len(others) == 1 else None

    def addresses_me(self, m):
        """Does a message mention Arjun, by @handle or first name?"""
        body = m.get("body") or ""
        if any(h in self.me_handles for h in MENTION.findall(body)):
            return True
        return bool(self.me_first) and has_word(re.escape(self.me_first), self.text[m["id"]])
