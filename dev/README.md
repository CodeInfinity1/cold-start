Development tools. `run.sh` never uses them.

- `mock_llm.py`: a local stand-in for an OpenAI-compatible endpoint. It tests the optional model step's
  plumbing and fallbacks without a key and without sending data anywhere. Its answers are deliberately
  dumb, so scores from it say nothing about model accuracy. It only shows that the output stays valid, and
  how many requests and characters would be sent:
  `python3 dev/mock_llm.py 8765 ok /tmp/stats.json &` then
  `COLDSTART_USE_MODEL=1 LLM_BASE_URL=http://127.0.0.1:8765/v1 LLM_API_KEY=test-key LLM_MODEL=mock ./run.sh data/dev out-mock.json`.
  Modes: `ok`, `error500`, `badjson`, `reject_json`, `mixed`, `junk_ids`, `bad_dates` (impossible
  dates and times in the answer).
- `eval_loops.py`: sweeps the loop threshold on a labelled folder: `python3 dev/eval_loops.py . data/dev 2.0 2.3 2.6`.
