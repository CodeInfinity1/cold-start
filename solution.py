#!/usr/bin/env python3
"""Cold Start: read a WhatsApp history and write output.json (see schema.json).

    python3 solution.py <input_dir> <output.json>

By default this is rules only (people.py, loops.py, goals.py): standard library, no network, even when
LLM_BASE_URL, LLM_API_KEY and LLM_MODEL are set. That default is what runs when graded. The optional
model step (llm_layer.py, unmeasured) runs only with COLDSTART_USE_MODEL=1 as well, and keeps the rules'
answer wherever a call fails.
"""
import json
import sys
import time
from pathlib import Path

import llm_layer
from ctx import Ctx
from goals import Goals
from loops import Loops
from people import Structure


def build(input_dir):
    ctx = Ctx(input_dir)
    structure = Structure(ctx).run()
    people, orgs, chats = structure.output()
    goals = Goals(ctx)
    out = {"people": people, "organisations": orgs, "chats": chats, "goals": goals.run(),
           "open_loops": Loops(ctx, structure).run()}
    if llm_layer.enabled():
        llm_layer.refine(ctx, structure, out, goals.seeded())
    for loop in out["open_loops"]:
        loop.pop("_score", None)
    return out


def main(input_dir, output_path):
    started = time.time()
    out = build(input_dir)
    Path(output_path).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {output_path}: {len(out['people'])} people, {len(out['organisations'])} organisations, "
          f"{len(out['goals'])} goals, {len(out['open_loops'])} loops in {time.time() - started:.1f}s", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
