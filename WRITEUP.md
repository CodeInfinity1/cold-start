# Write-up

## What I focused on, and why

The hidden set is six new weeks with every name changed, and loops are scored on its last two, so I aimed to
generalise rather than fit the dev answers:

1. **Rules that survive renaming, at no cost**: seeded org names and acronyms, words in contact names ("Home",
   "Office", "Mamaji"), shared surnames, group membership, @mentions, and phrasing in English and Hinglish.
2. **The asymmetric penalties.** A wrong "done", or `assist`/`remind` where the key says `leave`, costs a
   point, so status defaults to open and help to leave unless Arjun owns the loop.
3. **No unmeasured model in the graded run.** An optional model step for loops and goals
   (`llm_layer.py`), untested with a real model, runs only with `COLDSTART_USE_MODEL=1`.

## My approach

**Orgs and chats** (`people.py`). Seeded names and acronyms claim the groups that mention them, as do groups
sharing a distinctive word with them or mostly made of their members. Unclaimed "X operations" or "X team"
groups start a company X; kitchen, carpool and flat-number groups form Home. 1:1 chats go to the person,
other groups to their most active member.

**Circles.** First match wins: seed; staff, business or kinship words in the contact name; spouse (busiest 1:1
chat); how they address each other; Arjun's surname; work; family groups and surnames; clients (outsiders in
org groups); the 1:1 chat's topic; otherwise friend. `looks_after` needs two of a staff member's care messages
(pick-up, drop, feeding, medicine) about one person, at least one naming them.

**Open loops** (`loops.py`). A hand-set score from asks, imperatives, dates, promises ("I'll", "bhej dunga"),
quick replies and mentions of Arjun; the best message per turn opens a loop at 2.3 or more. **Done** needs
evidence, such as Arjun's reply to a plain question or the doer's "done/paid/kar diya" nearby. **Help**:
someone else's or personal → leave; dated → remind; order, book, find or draft → assist; otherwise → remind.

**Goals** (`goals.py`). Per life area, Arjun's messages are scored by area and planning words; areas with
several strong messages become goals, with their best eight messages as evidence.

## Measured on dev (rules only, the graded mode)

| Circles | Orgs | Chats | Loops found | Loops closed | Total |
|---|---|---|---|---|---|
| 0.76 (9.1/12) | 0.50 (4.0/8) | 0.89 (7.1/8) | 0.26 (3.7/14) | 0.27 (3.8/14) | **27.6 / 56** |

Goals and help are unlabelled on dev; the worked example, which labels them, scores 50.6/74. All in-sample: I
tuned the threshold and word lists on dev, whose loop labels come from Xpert's current system ("misses
some"). The hidden set is labelled by hand.

## What it costs

**Graded mode, measured: $0.** No model calls (a local listener set as `LLM_BASE_URL` received none); it runs
with networking disabled, in under a second on dev.

**Optional model step, estimated (not graded).** A local mock recorded 18 calls and 373k characters on dev.
Assuming 3–4 characters per token, 5–15k output tokens per run, and GPT-4.1 mini at $0.40 in / $1.60 out per
million tokens ([OpenAI](https://developers.openai.com/api/docs/models/gpt-4.1-mini), checked 3 Nov 2026;
marked deprecated), that is an estimated $0.010–0.016 per 1,000 dev messages, not measured spend.

## Where it's wrong

**Measured on dev** (rules only):

- **Circles: 10 of 41 wrong.** Six people with no usable signal default to friend (one client, two
  colleagues, two partners, one staff member). Three family members become "relative" from their surname alone
  (a parent, two siblings). One person with a company tag in their contact name is labelled a relative.
- **Orgs:** two of seven are missed because nothing names them. The key ties about a sixth of scored 1:1 chats
  to an org; I tie them to the person.
- **Loops:** precision 18% (38/215), recall 51% (38/74). Misses: implicit asks (a bare item, photo or time)
  and invitations. False alarms: chit-chat questions, repeat reminders.
- **Status:** of 38 matched loops, 14 done ones stay open; 2 open ones are called done.

**Hidden-set estimates** (not measured; basis in brackets):

- **Circles: 25–35% wrong** [dev: 24%, in-sample; no cue still means friend].
- **Loops: most found loops wrong, half or more of real ones missed** [dev: 82% and 49%, threshold tuned
  there; hand labels may credit loops the dev system missed].
- **Help: most errors will be `remind` where the key says `leave`** [owned loops default to remind; no dev
  labels].
- **Goals: one or two of my six match** [no dev labels; keyword-picked evidence strays: most of the dev health
  goal's eight messages are work talk].
- **`looks_after`** (unscored): misses care that never names the person ("the kids") [needs a first name;
  no dev cases].
