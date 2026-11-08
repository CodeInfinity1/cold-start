# Cold Start: solution

```bash
./run.sh data/dev out.json            # rules only: no model calls, even if LLM_* are set
python3 check.py data/dev out.json
```

Python 3.9 or later, standard library only; nothing to install. To run on the dev set, unzip the data ZIP
inside this folder; it makes `data/dev/`, which is git-ignored. See `WRITEUP.md` for how the solution works,
what it costs and where it is wrong.

**Modes.** The default is rules only, and that is what runs when graded. The graders set `LLM_BASE_URL`,
`LLM_API_KEY` and `LLM_MODEL` and count every token, but by default nothing calls them, so a graded run uses
no tokens. An optional model step for loops and goals runs only when you also set `COLDSTART_USE_MODEL=1`.
Tried on dev with real models, it gave no clear gain over the rules; `WRITEUP.md` has the numbers.

| File | What it does |
|---|---|
| `run.sh` | The one command: `./run.sh <input_dir> <output.json>` (unchanged from the starter kit) |
| `solution.py` | Entry point: runs the rules, then the optional model step if enabled, and writes the output |
| `ctx.py` | Loads the input; text and time helpers |
| `people.py` | Organisations, circles, links, `looks_after` and chat ties |
| `loops.py` | Open loops: detection, due dates, status, where to help |
| `goals.py` | Goals with evidence |
| `llm_layer.py` | Optional, off unless `COLDSTART_USE_MODEL=1`: a model re-reads the last 16 days for loops, and Arjun's messages for goals. Answers are validated, and the rules' answer is kept on any failure |
| `llm.py` | OpenAI-compatible client adapted from the starter's: it leaves out `temperature` when it is `None`, and a failed write to `usage.jsonl` (or `$LLM_USAGE_LOG`) no longer loses the reply. Only the optional model step uses it, and it sends only to `LLM_BASE_URL` |
| `check.py`, `schema.json`, `example/` | The starter kit's checker, output schema and worked example (unchanged) |
| `dev/` | Development-only tools: a local mock endpoint and a loop-threshold sweep. `run.sh` never uses them |
| `WRITEUP.md`, `ai-logs/` | The write-up, and AI session transcripts |

To measure the optional model step on dev with your own key (it is the only part that sends data anywhere,
and only to `LLM_BASE_URL`):

```bash
./run.sh data/dev out-rules.json && python3 check.py data/dev out-rules.json
COLDSTART_USE_MODEL=1 LLM_BASE_URL=... LLM_API_KEY=... LLM_MODEL=... ./run.sh data/dev out-model.json \
  && python3 check.py data/dev out-model.json
```

Outputs quote message text in loop titles, so `out*.json` is git-ignored along with `data/`.

---

## Reference: input, output and scoring (from the starter kit)

The challenge is on https://goals.xpert.chat/w/intern. `data/dev` is the first two weeks with their answers.
The code is run on the six weeks after, which are never shown, with every name changed again. Open loops are
scored on the last two of those weeks.

### The input

```
chats.jsonl      chat_id, name, is_group, participants (person ids; Arjun is "ME")
messages.jsonl   id, chat_id, sender_id, sender_name, ts (unix seconds), kind, body, quoted_id
seed.json        what the person told us at signup: some circles, some organisation names, a goal
answers/         dev set only: answers.json
```

`kind` is `text`, `voice_transcript`, `image_caption` or `document`. `quoted_id` is the message
being replied to, or null.

### The output

See `schema.json`, and the challenge page for what each part means. In short:

```json
{
  "people":        [{"id": "P03", "circle": "staff", "links": [{"organisation": "home", "link": "supports"}], "looks_after": ["P04"]}],
  "organisations": [{"id": "home", "name": "Home", "type": "residence", "side": "home", "role": "owner"}],
  "chats":         [{"chat_id": "C03", "organisation": "home"}, {"chat_id": "C01", "person": "P01"}],
  "goals":         [{"title": "Run the half marathon in January", "area": "health", "type": "milestone", "horizon": "3mo", "evidence": ["M026"]}],
  "open_loops":    [{"title": "Decide whether to take Zest", "type": "question", "owner": "ME", "chat_id": "C04",
                     "source_msg": "M016", "due": "2026-10-26", "status": "open", "closed_by": null,
                     "help": {"action": "remind", "remind_at": "2026-10-25T10:00:00+05:30"}}]
}
```

(The ids above come from the starter kit's made-up worked example in `example/`.)

### How the checker scores

The same rules are used on the hidden set. They cover 74 of the 100 points.

- **Circles (12):** share of people with the right circle. People whose circle is in `seed.json`
  don't count.
- **Organisations (8):** organisations are paired with the answer key's by overlap of the chats and
  people attached to each. Extra or missing organisations lower the score.
- **Chats (8):** share of chats tied to the right person, or to an organisation paired with the key's.
- **Goals (8):** a goal matches when the area is the same and at least one evidence message is shared.
  The score balances precision and recall. The goal in `seed.json` doesn't count.
- **Open loops found (14):** a loop matches when its `source_msg` is one of the messages accepted for
  it. The score balances precision and recall.
- **Open loops closed right (14):** for each loop found, the right status counts 1. Calling a loop done
  or dropped when it's still open costs 1. Divided by all of the key's loops.
- **Where to help (10):** for each labelled open loop, the right action counts 1. Saying `assist` or
  `remind` where the key says `leave` costs 1.

Cost (12), the write-up (7) and runs with one command (7) are scored by the organisers.

### The answers format

`answers/answers.json` has the same shape as the output, with three differences in `open_loops`
(and, on the hidden set, a `loops_scored_from` time: loops raised before it are not scored):
`source_msgs` lists every message accepted as the source, `closing_msgs` lists the messages that
show it closed, and `help` is just the action, with a `why`.
