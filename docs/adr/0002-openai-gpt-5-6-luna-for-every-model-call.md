# 0002 OpenAI GPT-5.6 Luna for every model call — superseded by 0003

All model calls — routing, answering, checking, graph building, PageIndex — use
OpenAI's cheapest model, GPT-5.6 Luna.

The owner prefers Claude, but the demo runs on $1 of existing OpenAI credit and
a Claude Pro subscription doesn't include API usage. LightRAG also supports
OpenAI directly but not Anthropic.

Open item: confirm the exact model id on the owner's account before the first
model call.
