# gRPC Migration Plan for the KSP Crime Intelligence Chatbot

## Executive Summary

Your application is **not network-bound**. Most latency comes from: 1.
LLM inference 2. SQL execution 3. Database I/O

Replacing browser-facing REST with gRPC would add complexity for very
little gain.

The optimal architecture is:

``` text
React
   │ REST / SSE
   ▼
FastAPI API Gateway
   │
   ├── gRPC → Chat Service
   ├── gRPC → LLM Service
   ├── gRPC → SQL Service
   ├── gRPC → Conversation Service
   ├── gRPC → Analytics Service
   ├── gRPC → Graph Service
   ├── gRPC → Media Service
   ├── gRPC → Voice Service
   └── gRPC → Report Service
```

------------------------------------------------------------------------

# Priority Ranking

## 1. LLM Service ⭐⭐⭐⭐⭐ (Highest Impact)

Current:

Pipeline → call_llm()

Proposed:

Pipeline → gRPC → LLM Service → QuickML

Why: - Centralizes all LLM logic - Connection reuse - Streaming
support - Easier scaling

RPCs: - GenerateSQL() - FormatAnswer() - RouteIntent() -
GenerateDirectAnswer() - GenerateCaseSummary()

Implementation: - Extract llm/ into a standalone FastAPI + grpcio
service. - Keep the gateway unaware of QuickML.

Expected latency improvement: - Small for one user. - Large under
concurrent load due to pooling and parallelism.

------------------------------------------------------------------------

## 2. SQL Service ⭐⭐⭐⭐⭐

Current:

Pipeline → execute_query()

Proposed:

Pipeline → gRPC → SQL Service → MySQL

Responsibilities: - Connection pooling - Prepared statements - Query
timeout - Retry - Metrics - Cache

RPCs: - ExecuteSelect() - ExecuteAnalytics()

Implementation: - Move db/connection.py into SQL Service. - Gateway only
sends SQL text.

Benefits: - Simplifies backend. - Independent scaling.

------------------------------------------------------------------------

## 3. Conversation Service ⭐⭐⭐⭐☆

Current:

Pipeline → History → NoSQL

Proposed:

Pipeline → gRPC → Conversation Service

RPCs: - SaveTurn() - LoadHistory() - SaveSession() - GetSession()

Benefits: - Removes storage logic from gateway. - Easier migration
later.

------------------------------------------------------------------------

## 4. Analytics Service ⭐⭐⭐⭐☆

Move: - trend_analytics.py - risk_scoring.py - similar_cases.py -
case_timeline.py

RPCs: - CrimeTrend() - RiskScore() - Timeline() - SimilarCases()

Benefits: - CPU-heavy analytics isolated. - Easier horizontal scaling.

------------------------------------------------------------------------

## 5. Graph Service ⭐⭐⭐⭐☆

Move: - network_builder.py

RPC: - BuildGraph()

Reason: Graph payloads serialize efficiently with Protocol Buffers.

------------------------------------------------------------------------

## 6. Voice Service ⭐⭐⭐☆☆

Browser → REST upload

Gateway → gRPC Voice Service

RPCs: - Transcribe() - Speak() - Translate()

------------------------------------------------------------------------

## 7. Media Service ⭐⭐⭐☆☆

Move media resolution.

RPC: - ResolveEvidence()

------------------------------------------------------------------------

## 8. Report Service ⭐⭐⭐☆☆

Move report parsing.

RPC: - AnalyzeReport()

------------------------------------------------------------------------

## 9. Authentication Service ⭐⭐☆☆☆

Keep browser REST.

Optional internal gRPC later if multiple applications consume
authentication.

------------------------------------------------------------------------

## 10. Export Service ⭐☆☆☆☆

Keep REST.

Rare operation.

------------------------------------------------------------------------

# Do NOT Replace

Keep REST/SSE for: - Login - Chat endpoint - Session listing - Session
messages - Report upload - Export - Analytics HTTP endpoints - Browser
file uploads

Reason: Browsers naturally support REST.

------------------------------------------------------------------------

# Simplest Effective Migration Roadmap

## Phase 1

Only extract: - LLM Service - SQL Service

Everything else unchanged.

This yields \~80% of the architectural benefit with \~20% of the
engineering effort.

------------------------------------------------------------------------

## Phase 2

Extract: - Conversation - Analytics - Graph

------------------------------------------------------------------------

## Phase 3

Extract: - Voice - Media - Reports

------------------------------------------------------------------------

## Phase 4

Introduce: - Service discovery - Load balancing - Distributed tracing -
Circuit breakers

------------------------------------------------------------------------

# Final Recommended Architecture

``` text
React
    │
REST / SSE
    │
    ▼
+---------------------------+
| FastAPI API Gateway       |
+---------------------------+
    │
    ├──────────────┬──────────────┬─────────────┐
    │              │              │             │
 gRPC           gRPC           gRPC         gRPC
    ▼              ▼              ▼             ▼

LLM Service   SQL Service   Conversation   Analytics

                      │
                   MySQL

         Graph Service
         Media Service
         Voice Service
         Report Service
```

# Overall Recommendation

Priority order:

1.  LLM Service
2.  SQL Service
3.  Conversation Service
4.  Analytics Service
5.  Graph Service
6.  Voice Service
7.  Media Service
8.  Report Service
9.  Authentication Service
10. Export Service

This keeps browser compatibility while gaining the operational benefits
of gRPC exactly where they matter.
