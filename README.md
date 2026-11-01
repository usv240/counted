# Counted

**No disaster death goes uncounted.** Counted interviews a grieving family after a hurricane, winter storm or heat wave, checks FEMA and National Weather Service records, finds the disaster hidden inside the death using CDC certification guidance, and drafts the statement a medical examiner signs. That signed statement is what gets the death counted, and it is what FEMA requires before it pays funeral assistance.

Hurricane Maria's official toll was 64 until a government-commissioned study found 2,975. The study blamed certification rules that counted only *direct* deaths. Counted is built to find the indirect ones: the oxygen machine that stopped, the dialysis center that closed, the generator in the garage.

**Try it:** https://co-435ce50e27c4441da1f6e8104db5cb23.ecs.us-east-1.on.aws (live demo, API docs at `/docs`, MCP at `/mcp/`, A2A at `/a2a/`)

## Results (all labels from Texas DSHS and the CDC, not from us)

| Test set | Cases | Direct-only convention | Keyword rules | One LLM call | **Counted** |
|---|---|---|---|---|---|
| Hurricane Irma replay (CDC MMWR) | 129 | 9% | 91% | 53% | **100%** |
| Winter Storm Uri replay (Texas DSHS) | 246 | 60% | 92% | 70% | **93%** (ceiling 93%) |
| CDC's own worked scenarios | 22 | 36% | 59% | 77% | **91%** (2 declined, 0 wrong) |
| Deaths with no disaster link | 8 | 0 false links | 2 false links | 0 | **0 false links** |
| Same deaths, relative pushing for a link | 8 | 0 | 2 | 0 | **0** |

- **Irma:** the CDC counted 126 storm-related deaths. The direct-only convention finds 11 of them; Counted finds all 126 and declines the 3 the CDC marked only "possible".
- **Ceiling:** some official circumstance rows split across labels (Uri hypothermia: 146 direct, 10 indirect, 2 possible), so no reader of the circumstances can reproduce every label. The ceiling is reported beside each score.
- **Honest limit:** replay accounts are generated from the official tables. The labels are the government's; the wording is ours, from templates that never contain a label word (checked by `evals/build_cases.py`). On template wording, plain keyword rules come within 1 point of Counted on Uri. On CDC's written scenarios they collapse to 59%.

### Every run, not just the best one

We changed rules and prompts between evaluation runs. All runs are kept in `evals/results/`, and every change came from a definition in the sources (never from a case's label):

| Run | What changed | Irma | Uri | CDC scenarios | False links (16 no-link deaths) |
|---|---|---|---|---|---|
| full-v1 | first run | 100% | 90.6% | 95.5% | 0 |
| full-v2 | drowning in a winter storm is a crash/fall (indirect), per Texas DSHS; flood-water infection category added | 99.2% | 87.4% | 95.5% | 0 |
| **full-v3 (current)** | examiner prompt states CDC's rule that hypothermia in a winter storm is direct even after a power outage (the rules engine already did) | **100%** | **93.1%** (= ceiling) | 90.9% (2 declined) | **0** |

Interview simulation (Strands Evals ActorSimulator, 16 relatives, 4 temperaments): first version reached a determination in 2/14 because it interrogated relatives who had said they didn't know; after rewriting the interview flow, 16/16 reached one and 16/16 matched the official label, median 6 exchanges, Spanish 4/4.

Rerun everything: `uv run python -m evals.build_cases && uv run python -m evals.run`. Predictions for every case are in `evals/results/<tag>/predictions.jsonl`.

## How it works

```
family / caseworker
      │  interview (EN/ES), one question at a time
      ▼
Interviewer agent ─ steering: holds back until the interview is complete
      │            ─ intervention: every recorded quote must be the family's own words
      │            ─ Cedar policy: no determination before records are checked; only certifiers sign
      ▼
Public records ─ Amazon Location (→ US Census backup) → OpenFEMA declarations → NWS warnings archive
      ▼
Examiner panel (Strands Graph)
      ├─ CDC decision tree (deterministic code)
      ├─ Claude Sonnet examiner        ┐ parallel, independent
      ├─ Amazon Nova examiner          ┘
      └─ Claude Opus adjudicator  ← conditional edge: only if the three disagree
      ▼
Documents (templates, no model): certifier statement draft · FEMA family packet (EN/ES) · surveillance record
```

| Piece | Where |
|---|---|
| Interviewer, tools, steering, verbatim-quote intervention | `src/counted/agents/interviewer.py` |
| Examiner panel (Graph + conditional edge + ModelRouter failover) | `src/counted/agents/panel.py` |
| CDC decision tree | `src/counted/rules.py` |
| Cedar policy + interventions (consent, redaction, certifying language) | `src/counted/policy/` |
| OpenFEMA, NWS, Amazon Location, Census | `src/counted/tools/facts.py` |
| Documents | `src/counted/documents.py` |
| REST API, API keys, MCP server, A2A server, website | `src/counted/service/` |
| AgentCore Runtime entrypoint + Memory | `src/counted/agentcore_app.py` |
| Replay evals, simulated-relative interview evals | `evals/` |
| Ground truth extracted from CDC, Texas DSHS, MMWR | `data/` (see `data/SOURCES.md`) |

## Run it

```bash
uv sync
aws configure            # Bedrock access in us-east-1: Claude Haiku 4.5, Sonnet 4.6, Opus 4.6, Amazon Nova 2 Lite
uv run counted-api       # http://localhost:8080  (site, /docs, /v1, /mcp, /a2a)
```

Use it as a service:

```bash
curl -X POST localhost:8080/v1/keys -H "content-type: application/json" -d '{"name":"my org"}'
curl -X POST localhost:8080/v1/assess -H "x-api-key: ct_..." -H "content-type: application/json" \
  -d '{"account":"My mother, 78, lived at 4602 Kiam St, Houston, TX. During Winter Storm Uri the power went out Feb 15 and her oxygen machine stopped. She died at home on 2021-02-17."}'
```

MCP client config: `{"mcpServers": {"counted": {"type": "http", "url": "https://co-435ce50e27c4441da1f6e8104db5cb23.ecs.us-east-1.on.aws/mcp/"}}}` (or `http://localhost:8080/mcp/` locally)

The public demo runs this image (`Dockerfile`) on Amazon ECS Express Mode (Fargate behind HTTPS), with a task role limited to Bedrock invoke, Amazon Location geocoding and the API-key table, and a daily cap on model runs (`COUNTED_DAILY_RUNS`).

Deploy to Amazon Bedrock AgentCore Runtime (entrypoint `src/counted/agentcore_app.py`):

```bash
npm install -g @aws/agentcore
agentcore create --name counted --template agent-python-strands   # then point the entrypoint at counted.agentcore_app
agentcore add memory                                              # set COUNTED_MEMORY_ID to the created memory
agentcore deploy
agentcore invoke --payload '{"action":"assess","account":"..."}'
```

## What it will never do

Sign anything (Cedar allows `sign_certifier_statement` only for a certifier principal) · record words the family did not say · invent a disaster link under pressure · write "may have been caused by" (FEMA rejects it) · decide without the family's consent.

Counted prepares drafts for qualified certifiers. It is not a death certificate, and not medical or legal advice. FEMA decides eligibility.

## Sources

CDC/NCHS, *A Reference Guide for Certification of Deaths in the Event of a Natural, Human-induced, or Chemical/Radiological Disaster* (2017) · Texas DSHS, *February 2021 Winter Storm-Related Deaths* (2021) · CDC MMWR 2018;67(30):829–832, Hurricane Irma deaths · FEMA, *Help with Funerals and Burials* (July 2025) · Milken Institute SPH, GWU, Hurricane Maria mortality (2018) · NAME position paper on disaster-related deaths · NPR and Boston University heat-death investigation (2026). Pictures: NOAA/NASA/CIRA and NASA public domain; David Kitto, CC0 (credits in `web/assets/credits.json`).

Licence: Apache-2.0.
