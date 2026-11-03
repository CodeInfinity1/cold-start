"""Dev-only: sweep the loop threshold against an answer key. usage: python3 dev/eval_loops.py <solution_dir> <data_dir> [thresholds...]"""
import json
import sys
from collections import Counter

sys.path.insert(0, sys.argv[1])
from ctx import Ctx  # noqa: E402
from people import Structure  # noqa: E402
from loops import Loops  # noqa: E402
import check  # noqa: E402

d = sys.argv[2]
ths = [float(x) for x in sys.argv[3:]] or [2.0, 2.3, 2.6, 3.0, 3.4, 3.8]
ctx = Ctx(d)
st = Structure(ctx).run()
ans = json.load(open(d + "/answers/answers.json"))
L = Loops(ctx, st)
src = {s for a in ans["open_loops"] for s in a["source_msgs"]}
for th in ths:
    loops = L.run(threshold=th)
    out = {"people": [], "organisations": [], "chats": [], "goals": [], "open_loops": loops}
    s = check.score(out, ans, {}, ctx.messages)
    hit = Counter(); tot = Counter()
    for l in loops:
        k = "?"
        tot[l["type"]] += 1
        if l["source_msg"] in src:
            hit[l["type"]] += 1
    st_conf = Counter()
    used = set()
    for l in loops:
        for j, a in enumerate(ans["open_loops"]):
            if j not in used and l["source_msg"] in a["source_msgs"]:
                used.add(j); st_conf[(a["status"], l["status"])] += 1; break
    print(f"th={th:4.1f} n={len(loops):4d} matched={len(used):3d} found={s['loops_found']:.3f} closed={s['loops_closed']:.3f} "
          f"pts={14*s['loops_found']+14*s['loops_closed']:.1f}  status(true,pred)={dict(st_conf)}  hits/type={dict(hit)} tot/type={dict(tot)}")
