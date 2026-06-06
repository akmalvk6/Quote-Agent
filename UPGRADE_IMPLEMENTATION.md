# Smart Quoting Agent Upgrade Implementation

This repository now includes a concrete upgrade path for the requested AI quoting architecture.

## What Changed

- Historical quotes now flow through chunking, deterministic embeddings, a persisted local vector index, and a retriever tool in `aef-samples/google-adk/rag_retriever.py`.
- The quote workflow has an explicit multi-agent pipeline in `aef-samples/google-adk/multi_agent_quote.py`:
  `SupervisorAgent -> RetrieverAgent -> PricingAgent -> ValidationAgent -> QuoteGeneratorAgent`.
- Product storage is PostgreSQL-ready through `aef-samples/google-adk/quote_storage.py`. If `DATABASE_URL` is not set, the app keeps using CSV/JSON fallback storage.
- Generated quotes are now placed in a human approval queue before sending. Approval moves quotes into the approved output directory.
- Customer memory is stored in `data/customer_memory.json` by default or in the `customers` table when PostgreSQL is enabled.
- Guardrails check prompt injection, invalid quantities, unauthorized discounts, missing products, financial thresholds, and quote item schema.
- Observability logs JSONL events for agent spans, tool calls, latency, and failures.
- `test_cases.json` and `evaluate_quotes.py` provide a basic evaluation framework for quote accuracy, hallucination rate, tool selection accuracy, and latency.

## Run the Evaluation

```bash
cd aef-samples/google-adk
python evaluate_quotes.py
```

The report is written to:

```text
aef-samples/google-adk/data/evaluation_report.json
```

## Enable PostgreSQL

Start PostgreSQL with Docker Compose:

```bash
docker compose up -d postgres
```

Then set:

```bash
DATABASE_URL=postgresql://quote_agent:quote_agent@localhost:5432/quote_agent
```

When `psycopg` is installed, `QuoteRepository.initialize_postgres()` creates:

- `products`
- `customers`
- `quotes`
- `discount_rules`

## Human Approval

Pending quotes are saved to:

```text
aef-samples/google-adk/approval_queue/
```

Approved quotes are moved to:

```text
aef-samples/google-adk/quotes/
```

The Streamlit sidebar now shows pending approvals with Approve and Reject actions.
