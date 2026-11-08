# Write-up

## What I focused on, and why

The hidden set is six new weeks with every name changed, and loops are scored on its last two, so I aimed to
generalise rather than fit the dev answers:

1. **Rules that survive renaming, at no cost**: seeded org names and acronyms, words in contact names ("Home",
   "Office", "Mamaji"), shared surnames, group membership, @mentions, and phrasing in English and Hinglish.
2. **The asymmetric penalties.** A wrong "done", or `assist`/`remind` where the key says `leave`, costs a
   point: status defaults to open, help to leave unless Arjun owns the loop.
3. **No model in the graded run.** An optional model step for loops and goals (`llm_layer.py`) runs only
   with `COLDSTART_USE_MODEL=1`. Tried on dev with real models, it gave no clear gain (see costs).

## My approach

**Orgs and chats** (`people.py`). Seeded names and acronyms claim the groups that mention them, as do groups
sharing a distinctive word with them or mostly made of their members. Unclaimed "X operations" or "X team"
groups start a company X; household groups form Home. 1:1 chats go to the person,
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

Goals and help are unlabelled on dev (worked example: 50.6/74). In-sample: I tuned on dev, whose loop labels
are from Xpert's system ("misses some"); the hidden set is labelled by hand.

## What it costs

**Graded mode, measured: $0.** No model calls (a local listener set as `LLM_BASE_URL` received none); it runs
with networking disabled, in under a second on dev.

**Optional model step, measured on dev (not graded).** With `gemini-3.1-flash-lite` it scored 27.2/56 against
the rules' 27.6, using 152,685 tokens per run: $0.049 at Google's paid price ($0.25 in / $1.50 out per million;
[Google](https://ai.google.dev/gemini-api/docs/pricing), checked 8 Nov 2026), or $0.011 per 1,000 messages.
`gpt-oss-120b` on Groq's free tier scored 27.9 but reached only 46 of 125 chats. As written, it also breaks on
Groq (no User-Agent header) and on reasoning models (thinking fills its 2,500-token cap, and a cut-off reply
reads as "no loops").

## Where it's wrong

**Measured on dev** (rules only):

- **Circles: 10 of 41 wrong.** Six people with no usable signal default to friend (one client, two
  colleagues, two partners, one staff member). Three family members become "relative" from their surname alone
  (a parent, two siblings). One person with a company tag in their contact name is labelled a relative.
- **Orgs:** two of seven are missed because nothing names them. The key ties about a sixth of scored 1:1 chats
  to an org; I tie them to the person.
- **Loops:** precision 18% (38/215), recall 51% (38/74). Misses: implicit asks (a bare item, photo or time)
  and invitations. False alarms: chit-chat questions, repeat reminders.
- **Status:** of 38 matched loops, 14 done ones stay open; 2 open ones are called done. Dev's key marks 32 of
  33 past-due loops done with no closing message; copying that would add a point on dev, but the task
  wants the message that shows it, so I didn't.

**Hidden-set estimates** (not measured; basis in brackets):

- **Circles: 25–35% wrong** [dev: 24%, in-sample; no cue still means friend].
- **Loops: most found loops wrong, half or more missed** [dev: 82% and 49%, threshold tuned there; hand
  labels may credit loops the dev system missed].
- **Help: mostly `remind` where the key says `leave`** [owned loops default to remind].
- **Goals: one or two of my six match** [keyword-picked evidence strays: the dev health goal's is mostly work].
- **`looks_after`** (unscored): misses care that never names the person [no dev cases].
