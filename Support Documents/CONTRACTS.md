# Function Contracts

223 functions across 50 files.

---

## backend/auth/role_guard.py

### log_action
- **Takes:** officer_id (int) — EmployeeID performing the action, action (str) — action name, resource_type (str | None) — type of resource affected, resource_id (str | None) — ID of resource affected, details (str | None) — extra context, request (Request | None) — HTTP request for IP extraction
- **Returns:** nothing
- **Raises:** nothing (non-fatal, failures are logged to stderr)

### require_role
- **Takes:** *allowed_roles (str) — one or more role names that are permitted
- **Returns:** (Callable) — FastAPI dependency that checks the officer's role and returns the officer dict
- **Raises:** nothing (returned dependency raises HTTPException 403 on role mismatch)

---

## backend/auth/simple_auth.py

### _unauthorized
- **Takes:** detail (str) — error message for the 401 response
- **Returns:** (HTTPException) — configured 401 HTTP exception with WWW-Authenticate header
- **Raises:** nothing

### create_access_token
- **Takes:** officer_id (int) — EmployeeID, badge_number (str) — KGID identifier, role (str) — employee role
- **Returns:** (str) — signed JWT token with 24-hour expiry
- **Raises:** nothing

### get_current_officer
- **Takes:** credentials (HTTPAuthorizationCredentials | None) — Bearer token from Authorization header
- **Returns:** (dict) — decoded JWT payload for the authenticated officer
- **Raises:** HTTPException — when no credentials or token invalid (401)

### get_current_officer_sse
- **Takes:** request (Request) — the incoming HTTP request, credentials (HTTPAuthorizationCredentials | None) — Bearer token from header, token (str | None) — fallback JWT from query param
- **Returns:** (dict) — decoded JWT payload for the authenticated officer
- **Raises:** HTTPException — when no token found in header or query param (401)

### login
- **Takes:** badge_number (str) — employee KGID, password (str) — expected to be KGID+"123"
- **Returns:** (dict) — {"access_token": str, "officer": {...}} with JWT and officer info
- **Raises:** HTTPException — when credentials are invalid or employee not found (401)

### verify_token
- **Takes:** token (str) — JWT string to verify
- **Returns:** (dict) — decoded JWT payload
- **Raises:** HTTPException — when token is missing, invalid, or expired (401)

---

## backend/config/settings.py

### get
- **Takes:** key (str) — name of the environment variable to retrieve
- **Returns:** (str) — the environment variable's value
- **Raises:** ValueError — when the environment variable is not set or empty

### validate_settings
- **Takes:** nothing
- **Returns:** nothing
- **Raises:** ValueError — when any REQUIRED_VARS are missing from the environment

---

## backend/consolidate_cases.py

### _build_separator
- **Takes:** crime_no (str) — case Crime No for the separator header
- **Returns:** (str) — formatted separator string with equals-sign bars
- **Raises:** nothing

### _extract_crime_no
- **Takes:** content (str) — full case file content
- **Returns:** (str) — extracted Crime No string, or "Unknown" if not found
- **Raises:** nothing

### _normalise_category
- **Takes:** raw_sections (str) — raw SECTIONS line from a case file
- **Returns:** (str) — normalised primary crime category name
- **Raises:** nothing

### _parse_case_file
- **Takes:** filepath (Path) — path to a single case .txt file
- **Returns:** (tuple[str, str]) — (normalised crime category, full file content)
- **Raises:** OSError — when the file cannot be read

### consolidate
- **Takes:** input_dir (Path) — directory containing individual case_*.txt files, output_dir (Path) — target directory for consolidated files, max_size_kb (int) — max file size before splitting
- **Returns:** (dict[str, list[str]]) — mapping of output filename to list of Crime Nos included
- **Raises:** nothing (returns empty dict if no files found)

### main
- **Takes:** nothing
- **Returns:** nothing
- **Raises:** SystemExit — via argparse on invalid arguments

---

## backend/conversation/history.py

### _local_clear
- **Takes:** session_id (str) — session identifier to clear
- **Returns:** nothing
- **Raises:** nothing

### _local_get
- **Takes:** session_id (str) — session identifier
- **Returns:** (list[dict]) — last MAX_TURNS messages from in-memory store
- **Raises:** nothing

### _local_set
- **Takes:** session_id (str) — session identifier, turns (list[dict]) — messages to store
- **Returns:** nothing
- **Raises:** nothing

### _log
- **Takes:** msg (str) — message to log
- **Returns:** nothing
- **Raises:** nothing

### _migrate_messages
- **Takes:** turns (list[dict]) — raw message dicts from storage, possibly missing message_id/timestamp
- **Returns:** (list[dict]) — fresh list of message dicts with message_id and timestamp guaranteed
- **Raises:** nothing

### _new_message_id
- **Takes:** nothing
- **Returns:** (str) — unique message ID prefixed with 'm-'
- **Raises:** nothing

### _now_iso
- **Takes:** nothing
- **Returns:** (str) — current UTC time as ISO 8601 string
- **Raises:** nothing

### _sync_session_metadata
- **Takes:** session_id (str) — session identifier, user_message (str) — first user message text, had_prior_messages (bool) — whether session had prior history, messages_added (int) — count of messages just persisted, now (str) — ISO timestamp of the save
- **Returns:** nothing
- **Raises:** nothing (never raises, logs failures internally)

### clear_history
- **Takes:** session_id (str) — session identifier to delete history for
- **Returns:** nothing
- **Raises:** nothing (never raises)

### get_history
- **Takes:** session_id (str) — session identifier to fetch history for
- **Returns:** (list[dict]) — last MAX_TURNS messages with message_id and timestamp fields
- **Raises:** nothing (falls back to in-memory store on failure)

### init_nosql_table
- **Takes:** nothing
- **Returns:** nothing
- **Raises:** nothing (never raises, logs warning on failure)

### save_turn
- **Takes:** session_id (str) — session identifier, user_message (str) — the user's question, assistant_message (str) — the assistant's response, assistant_sql (str | None) — SQL generated for this turn, assistant_table (list[dict] | None) — query result snapshot for follow-ups
- **Returns:** nothing
- **Raises:** nothing (never raises, failures are logged)

---

## backend/conversation/session_store.py

### _local_get
- **Takes:** session_id (str) — session identifier
- **Returns:** (dict | None) — session metadata document from in-memory store, or None
- **Raises:** nothing

### _local_list
- **Takes:** officer_id (int | None) — optional filter for a specific officer's sessions
- **Returns:** (list[dict]) — all matching session documents from in-memory store
- **Raises:** nothing

### _local_set
- **Takes:** session_id (str) — session identifier, document (dict) — metadata to store
- **Returns:** nothing
- **Raises:** nothing

### _log
- **Takes:** msg (str) — message to log
- **Returns:** nothing
- **Raises:** nothing

### create_session
- **Takes:** document (dict) — full session_metadata document with id, officer_id, title, timestamps, message_count
- **Returns:** (dict) — the stored document
- **Raises:** ValueError — when document lacks an 'id' field

### generate_title
- **Takes:** message (str) — the first user message in a session
- **Returns:** (str) — short human-readable title (≤60 chars) for the session
- **Raises:** nothing

### get_session
- **Takes:** session_id (str) — session identifier to look up
- **Returns:** (dict | None) — session metadata document or None if not found
- **Raises:** nothing (never raises, falls back to in-memory)

### list_sessions
- **Takes:** officer_id (int) — EmployeeID to filter sessions by
- **Returns:** (list[dict]) — session metadata documents sorted by updated_at descending
- **Raises:** nothing (never raises, falls back to in-memory)

### update_session
- **Takes:** session_id (str) — session to update, updates (dict) — key-value pairs to merge
- **Returns:** (dict | None) — merged document or None if session not found
- **Raises:** nothing (never raises, failures are logged)

---

## backend/db/chat_store.py

### _log
- **Takes:** msg (any) — message to log to stderr
- **Returns:** nothing
- **Raises:** nothing

### _serialize
- **Takes:** obj (any) — object that json.dumps cannot serialize natively
- **Returns:** (str | float) — ISO string for dates/times, float for Decimals
- **Raises:** TypeError — when the object type is not handled

### create_session
- **Takes:** session_id (str) — unique session identifier,; officer_id (int) — ID of the officer who owns the session,; title (str) — display title for the session (truncated to 60 chars)
- **Returns:** (bool) — True on success, False on failure
- **Raises:** nothing (catches all exceptions internally)

### get_messages_for_session
- **Takes:** session_id (str) — session whose messages to retrieve
- **Returns:** (list[dict]) — ordered list of message dicts with parsed table_data and follow_ups
- **Raises:** nothing (catches all exceptions, returns empty list on failure)

### get_sessions_for_officer
- **Takes:** officer_id (int) — ID of the officer whose sessions to retrieve,; limit (int) — maximum number of sessions to return
- **Returns:** (list[dict]) — list of session metadata dicts ordered by most recently updated
- **Raises:** nothing (catches all exceptions, returns empty list on failure)

### save_message_pair
- **Takes:** session_id (str) — session to save messages to,; question (str) — the user's question text,; answer_text (str) — the assistant's answer text,; sql_generated (str) — SQL query that was generated (empty if none),; has_table (bool) — whether the response includes tabular data,; has_media (bool) — whether the response includes media attachments,; graph_available (bool) — whether a graph visualization is available,; table_data (list[dict]) — raw query result rows to persist,; media_attachments (list[dict]) — media references for the response,; assistant_follow_ups (list | None) — suggested follow-up questions
- **Returns:** (int | None) — the assistant message's row ID, or None on failure
- **Raises:** nothing (catches all exceptions internally)

### update_session_timestamp
- **Takes:** session_id (str) — session to update,; increment_count (bool) — whether to also increment message_count by 2
- **Returns:** nothing
- **Raises:** nothing (catches all exceptions internally)

### verify_session_owner
- **Takes:** session_id (str) — session to verify ownership of,; officer_id (int) — expected owner's ID
- **Returns:** (bool) — True if the officer owns the session, False otherwise
- **Raises:** nothing (catches all exceptions, returns False on failure)

### get_evidence_trail_for_message
- **Takes:** message_id (int) — message row ID to look up, officer_id (int) — EmployeeID of the requesting officer
- **Returns:** (dict | None) — evidence trail row scoped to the requesting officer, or None if not found/not owned/no trail
- **Raises:** nothing (catches all exceptions, returns None on failure)

---

## backend/db/connection.py

### _normalize_bit_fields
- **Takes:** row (dict) — a single database row with potential BIT field bytes
- **Returns:** (dict) — the row with single-byte BIT fields converted to booleans
- **Raises:** nothing

### close_pool
- **Takes:** nothing
- **Returns:** nothing
- **Raises:** nothing

### create_pool
- **Takes:** nothing; aiomysql.Error — when database connection fails
- **Returns:** (aiomysql.Pool) — newly created MySQL connection pool
- **Raises:** ValueError — when required DB env vars are not set,

### execute_query
- **Takes:** sql (str) — SELECT query to execute,; params (tuple) — parameterized query values; ValueError — when sql is not a SELECT statement,; TimeoutError — when query exceeds 5-second timeout
- **Returns:** (list[dict]) — list of row dicts (column_name → value)
- **Raises:** RuntimeError — when pool has not been created,

### execute_write
- **Takes:** sql (str) — INSERT or UPDATE statement to execute,; params (tuple) — parameterized query values; ValueError — when sql is a SELECT statement,; TimeoutError — when write exceeds 5-second timeout
- **Returns:** (int) — lastrowid for INSERT, rowcount for UPDATE
- **Raises:** RuntimeError — when pool has not been created,

### get_pool
- **Takes:** nothing
- **Returns:** (aiomysql.Pool) — the existing global connection pool
- **Raises:** RuntimeError — when pool has not been created yet

---

## backend/db/nosql_client.py

### _get_base_project_url
- **Takes:** nothing
- **Returns:** (str) — base project URL with /nosql suffix stripped if present
- **Raises:** ValueError — when NOSQL_BASE_URL env var is not set

### _nosql_headers
- **Takes:** nothing
- **Returns:** (dict) — authorization and content-type headers for Catalyst NoSQL API calls
- **Raises:** ValueError — when required env vars are not set

### delete_document
- **Takes:** table_name (str) — NoSQL table containing the document,; document_id (str) — primary key value of the document to delete,; timeout (float) — HTTP request timeout in seconds,; key_name (str) — name of the primary key attribute
- **Returns:** (bool) — True on successful deletion
- **Raises:** NoSQLError — when the API returns a non-success status

### deserialize_from_catalyst
- **Takes:** c_val (dict) — Catalyst-typed value wrapper to deserialize
- **Returns:** (any) — native Python value extracted from the typed wrapper
- **Raises:** nothing

### deserialize_item
- **Takes:** item_data (dict) — raw Catalyst NoSQL item with typed attribute values
- **Returns:** (dict) — deserialized item with native Python values
- **Raises:** nothing

### get_document
- **Takes:** table_name (str) — NoSQL table to fetch from,; document_id (str) — primary key value of the document,; timeout (float) — HTTP request timeout in seconds,; key_name (str) — name of the primary key attribute
- **Returns:** (dict | None) — deserialized document, or None if not found
- **Raises:** NoSQLError — when the API returns a non-success/non-404 status

### insert_document
- **Takes:** table_name (str) — NoSQL table to insert into,; document_id (str) — primary key value for the new document,; document_data (dict) — key-value pairs to store in the document,; timeout (float) — HTTP request timeout in seconds,; key_name (str) — name of the primary key attribute
- **Returns:** (bool) — True on successful insert
- **Raises:** NoSQLError — when the API returns a non-success status

### list_documents
- **Takes:** table_name (str) — NoSQL table to list documents from,; timeout (float) — HTTP request timeout in seconds
- **Returns:** (list[dict]) — list of deserialized documents from the table
- **Raises:** NoSQLError — when the API returns a non-success/non-404 status

### serialize_to_catalyst
- **Takes:** val (any) — Python value to serialize into Catalyst NoSQL typed format
- **Returns:** (dict) — Catalyst-typed wrapper (e.g. {"S": ...}, {"N": ...}, {"BOOL": ...})
- **Raises:** nothing

### update_document
- **Takes:** table_name (str) — NoSQL table containing the document,; document_id (str) — primary key value of the document to update,; updates (dict) — key-value pairs to update on the document,; timeout (float) — HTTP request timeout in seconds,; key_name (str) — name of the primary key attribute
- **Returns:** (bool) — True on successful update
- **Raises:** NoSQLError — when the API returns a non-success status

---

## backend/db/schema_catalog.py

### _format_table
- **Takes:** name (str) — table name to format,; meta (dict) — table metadata with description and columns,; max_col_chars (int | None) — optional max length to truncate column descriptions
- **Returns:** (str) — formatted multi-line table block for LLM prompt injection
- **Raises:** nothing

### get_few_shot_examples
- **Takes:** table_names (list[str]) — selected table names to score examples against
- **Returns:** (str) — formatted string with up to 3 relevant NL->SQL example pairs
- **Raises:** nothing

### get_schema_for_tables
- **Takes:** table_names (list[str]) — list of table names to include in the schema
- **Returns:** (str) — compact schema string suitable for LLM prompt injection
- **Raises:** nothing

---

## backend/export_cases_for_rag.py

### main
- **Takes:** nothing
- **Returns:** nothing
- **Raises:** Exception — when DB pool creation or query execution fails

---

## backend/graph/network_builder.py

### _fetch_co_accused_links
- **Takes:** case_master_id (int) — CaseMasterID to find co-accused within
- **Returns:** (list[dict]) — rows with AccusedMasterID and AccusedName of other accused in the same case
- **Raises:** Exception — when DB query fails

### _fetch_repeat_appearances
- **Takes:** accused_name (str) — name to search for across all cases
- **Returns:** (list[dict]) — rows with CaseMasterID, CrimeNo, AccusedMasterID for matching accused
- **Raises:** Exception — when DB query fails

### _fetch_similar_pattern_cases
- **Takes:** crime_minor_head_id (int) — crime type ID, police_station_id (int) — station ID, case_master_id (int) — ID to exclude from results
- **Returns:** (list[dict]) — up to 10 rows with CaseMasterID and CrimeNo of pattern-similar cases
- **Raises:** Exception — when DB query fails

### build_graph_for_accused
- **Takes:** accused_id (int) — AccusedMasterID to build the graph around
- **Returns:** (dict) — vis.js-compatible graph with "nodes" and "edges" lists
- **Raises:** nothing (returns empty graph on missing accused)

### build_graph_for_fir
- **Takes:** fir_id (int) — CaseMasterID to build the graph around
- **Returns:** (dict) — vis.js-compatible graph with "nodes" and "edges" lists
- **Raises:** nothing (returns empty graph on missing case)

---

## backend/kb_sync.py

### _get_env
- **Takes:** key (str) — environment variable name, required (bool) — whether to exit on missing value
- **Returns:** (str) — environment variable value
- **Raises:** SystemExit — when required=True and the variable is not set

### _update_env_var
- **Takes:** env_path (Path) — path to the .env file to update, key (str) — variable name, value (str) — new value
- **Returns:** nothing
- **Raises:** OSError — when file cannot be read or written

### list_kb_documents
- **Takes:** project_id (str) — Catalyst project ID, org_id (str) — Catalyst org ID, token (str) — OAuth access token
- **Returns:** (list[dict]) — list of document metadata dicts with at least document_id
- **Raises:** nothing (returns empty list on failure)

### main
- **Takes:** nothing
- **Returns:** nothing
- **Raises:** SystemExit — via argparse on invalid arguments or missing env vars

### refresh_token
- **Takes:** env_path (Path) — path to .env file to write the new token to
- **Returns:** (str) — the new access token
- **Raises:** SystemExit — when refresh token env vars are missing or response lacks access_token

---

## backend/llm/answer_formatter.py

### _log
- **Takes:** msg (str) — message to log
- **Returns:** nothing
- **Raises:** nothing

### format_answer
- **Takes:** question (str) — the user's natural-language question,; results (list[dict]) — raw rows from the DB query,; media_attachments (list[dict]) — resolved media references for the response,; history (list[dict] | None) — prior conversation turns for context
- **Returns:** (str) — natural-language answer formatted from the query results
- **Raises:** LLMError — when the LLM call fails (non-payload-size errors)

### generate_direct_answer
- **Takes:** question (str) — the user's natural-language question,; history (list[dict] | None) — prior conversation turns for context,; recent_table (list[dict] | None) — most recent query result rows for grounding
- **Returns:** (str) — natural-language answer generated without running SQL
- **Raises:** LLMError — when the underlying LLM call fails

### route_intent
- **Takes:** question (str) — the user's natural-language question,; history (list[dict] | None) — prior conversation turns for context,; has_recent_data (bool) — whether the session has recent query results available
- **Returns:** (str) — routing decision, either "SQL" or "DIRECT"
- **Raises:** nothing (catches all exceptions, defaults to "SQL")

---

## backend/llm/client.py

### _extract_response_text
- **Takes:** data (dict) — raw JSON response body from a GLM chat completion endpoint
- **Returns:** (str) — extracted assistant response text, or empty string if not found
- **Raises:** nothing

### _llm_headers
- **Takes:** nothing
- **Returns:** (dict) — authorization and content-type headers for Catalyst QuickML API calls
- **Raises:** ValueError — when required env vars (CATALYST_API_TOKEN, CATALYST_ORG_ID) are not set

### call_llm
- **Takes:** model_key (str) — env var name resolving to the model identifier (e.g. "MODEL_SQL"),; prompt (str) — user/task prompt to send to the model,; system_prompt (str) — system instruction for the model,; max_tokens (int) — maximum tokens to generate in the response
- **Returns:** (str) — the model's non-empty response text
- **Raises:** LLMError — on network failure, bad HTTP status, invalid JSON, or empty response

### ping_model
- **Takes:** model_key (str) — environment variable name that resolves to the model identifier
- **Returns:** (bool) — True if model responded with non-empty 200, False otherwise
- **Raises:** nothing (catches all exceptions internally)

---

## backend/llm/prompts.py

### _format_history_for_prompt
- **Takes:** history (list[dict]) — conversation history turns, max_turns (int) — max user/assistant pairs to include, max_chars (int) — max chars per assistant answer
- **Returns:** (str) — compressed history block for prompts, or "" if empty
- **Raises:** nothing

### _format_history_for_sql_prompt
- **Takes:** history (list[dict]) — conversation history with optional sql field, max_turns (int) — max pairs, max_answer_chars (int) — max chars per answer
- **Returns:** (str) — history block including prior SQL for follow-up preservation, or ""
- **Raises:** nothing

### _format_officer_for_prompt
- **Takes:** officer (dict | None) — authenticated employee info with officer_id and badge_number
- **Returns:** (str) — identity block for SQL prompt resolving first-person references, or ""
- **Raises:** nothing

### _summarize_media
- **Takes:** media_refs (list[dict]) — media attachment dicts with media_type fields
- **Returns:** (str) — human-readable summary like "3 attachment(s): 2 image, 1 video"
- **Raises:** nothing

### _truncate_for_answer
- **Takes:** results (list[dict]) — query results to trim, max_rows (int) — row cap, max_field_chars (int) — per-field char cap
- **Returns:** (list[dict]) — trimmed results with long string fields clipped
- **Raises:** nothing

### build_answer_prompt
- **Takes:** question (str) — officer's question, results (list[dict]) — query results, media_refs (list[dict]) — media attachments, history (list[dict] | None) — conversation history, max_rows (int) — result row cap, max_field_chars (int) — per-field char cap
- **Returns:** (tuple[str, str]) — (system_prompt, user_prompt) for answer-formatting LLM call
- **Raises:** nothing

### build_correction_prompt
- **Takes:** original_sql (str) — the invalid SQL, error (str) — error message, schema (str) — DB schema text, officer (dict | None) — authenticated officer identity
- **Returns:** (tuple[str, str]) — (system_prompt, user_prompt) for the SQL correction LLM call
- **Raises:** nothing

### build_direct_answer_prompt
- **Takes:** question (str) — officer's question, history (list[dict] | None) — conversation history, recent_table (list[dict] | None) — most recent query result set
- **Returns:** (tuple[str, str]) — (system_prompt, user_prompt) for direct conversational answer
- **Raises:** nothing

### build_router_prompt
- **Takes:** question (str) — officer's latest message, history (list[dict] | None) — conversation history, has_recent_data (bool) — whether recent query results are in context
- **Returns:** (tuple[str, str]) — (system_prompt, user_prompt) for intent router classification
- **Raises:** nothing

### build_sql_prompt
- **Takes:** question (str) — user question, schema (str) — DB schema text, few_shots (str) — example queries, history (list[dict] | None) — conversation history, officer (dict | None) — authenticated officer identity
- **Returns:** (tuple[str, str]) — (system_prompt, user_prompt) for the SQL generation LLM call
- **Raises:** nothing

### build_case_summary_prompt
- **Takes:** case_row (dict) — case facts from CaseMaster/CrimeSubHead/CaseStatusMaster/Unit join, accused_rows (list[dict]) — accused persons with AccusedName and AgeYear, victim_rows (list[dict]) — victims with VictimName and AgeYear
- **Returns:** (tuple[str, str]) — (system_prompt, user_prompt) for case summary LLM call
- **Raises:** nothing

---

## backend/llm/rag_client.py

### _is_negative_claim
- **Takes:** response_text (str) — RAG response text to check for negative/absence claims
- **Returns:** (bool) — True if the response matches a negative claim pattern
- **Raises:** nothing

### _node_supports_response
- **Takes:** node_content (str) — text content of a retrieved RAG node,; response_phrases (set) — significant phrases extracted from the RAG response
- **Returns:** (bool) — True if the node shares at least one significant phrase with the response
- **Raises:** nothing

### _query_rag_once
- **Takes:** query (str) — the search query to send to the RAG endpoint,; document_ids (list[str]) — document IDs to scope the retrieval; httpx.HTTPStatusError — when the RAG API returns a non-2xx status
- **Returns:** (RagResult) — grounding status, response text, and filtered source references
- **Raises:** RuntimeError — when CATALYST_API_TOKEN env var is not set,

### _significant_phrases
- **Takes:** text (str) — text to extract multi-word capitalized phrases and long numbers from
- **Returns:** (set) — lowercased significant phrases and long numeric strings found in the text
- **Raises:** nothing

### normalize_query
- **Takes:** query (str) — raw user query potentially containing filler/hedging language
- **Returns:** (str) — cleaned query with filler patterns removed and whitespace normalized
- **Raises:** nothing

### query_rag
- **Takes:** query (str) — the user's search query,; document_ids (list[str]) — document IDs to scope the retrieval; httpx.HTTPStatusError — when the RAG API returns a non-2xx status
- **Returns:** (RagResult) — grounding status, response text, and filtered source references
- **Raises:** RuntimeError — when CATALYST_API_TOKEN env var is not set,

### to_dict
- **Takes:** nothing
- **Returns:** (dict) — dictionary with grounded, response, and sources fields
- **Raises:** nothing

---

## backend/llm/rag_session.py

### _build_contextual_query
- **Takes:** resolved_query (str) — reference-resolved user query
- **Returns:** (str) — query with prior conversation context prepended for RAG
- **Raises:** nothing

### _convert_history
- **Takes:** raw_history (list[dict]) — raw conversation history with role/content fields
- **Returns:** (list[dict]) — list of {"query": ..., "response": ...} turn pairs
- **Raises:** nothing

### _extract_primary_entity
- **Takes:** text (str) — text to extract a primary named entity from
- **Returns:** (str | None) — first multi-word capitalized name found, or None
- **Raises:** nothing

### _generate_follow_ups
- **Takes:** case_context (str) — latest RAG response text to generate follow-ups from
- **Returns:** (list[str]) — up to 3 suggested follow-up questions for the investigator
- **Raises:** nothing (catches LLMError internally)

### _resolve_references
- **Takes:** query (str) — user query potentially containing pronoun references
- **Returns:** (str) — query with pronoun references replaced by the last known entity name
- **Raises:** nothing

### ask
- **Takes:** query (str) — the user's raw question; httpx.HTTPStatusError — when the RAG API returns a non-2xx status
- **Returns:** (dict) — response dict with grounded, response, sources, resolved_query, suggested_follow_ups
- **Raises:** RuntimeError — when CATALYST_API_TOKEN is not set,

---

## backend/llm/sql_generator.py

### _log
- **Takes:** msg (str) — message to log
- **Returns:** nothing
- **Raises:** nothing

### correct_sql_after_execution_error
- **Takes:** original_sql (str) — the SQL query that caused a MySQL execution error,; db_error (str) — the MySQL error message from execution,; table_names (list[str]) — candidate table names for schema context,; officer (dict | None) — officer metadata for role-based filtering; LLMError — when the underlying LLM API call fails
- **Returns:** (str) — sanitized and validated corrected SQL query
- **Raises:** SQLGenerationError — when corrected SQL is empty, fails validation, or is CANNOT_ANSWER,

### generate_sql
- **Takes:** question (str) — natural-language question from the user,; table_names (list[str]) — candidate table names for schema scope,; history (list[dict] | None) — prior conversation turns for context,; officer (dict | None) — officer metadata for role-based filtering; SQLGenerationError — when validation fails on all attempts,; LLMError — when the underlying LLM API call fails
- **Returns:** (tuple[str, int]) — sanitized SQL query and number of LLM attempts consumed
- **Raises:** CannotAnswerError — when the model signals the question cannot be answered from the DB,

---

## backend/main.py

### lifespan
- **Takes:** app (FastAPI) — the FastAPI application instance
- **Returns:** nothing (async context manager yields after startup, runs shutdown after)
- **Raises:** nothing (DB/NoSQL failures are logged as warnings, never crash startup)

---

## backend/pipeline/media_resolver.py

### _dummy_media_url
- **Takes:** media_type (str | None) — type of media (image/video/audio), stratus_file_id (str | None) — Stratus file identifier
- **Returns:** (str | None) — a public placeholder URL for the media, or None if no file ID
- **Raises:** nothing

### _stable_seed_value
- **Takes:** value (str) — input string to derive a numeric seed from
- **Returns:** (int) — deterministic integer derived from SHA-256 hash of the input
- **Raises:** nothing

### collect_case_master_ids
- **Takes:** results (list[dict]) — query result rows potentially containing CaseMasterID keys
- **Returns:** (list[int]) — deduplicated list of valid integer CaseMasterIDs in order of first appearance
- **Raises:** nothing

### resolve_media
- **Takes:** results (list[dict]) — query result rows containing CaseMasterID keys
- **Returns:** (list[dict]) — media attachment dicts with media_type, url, description, case_master_id
- **Raises:** nothing (DB errors propagate but callers catch)

---

## backend/pipeline/query_pipeline.py

### _check_graph_available
- **Takes:** case_master_ids (list[int]) — list of CaseMasterIDs to check
- **Returns:** (bool) — True if any case IDs are present (graph derivable on demand)
- **Raises:** nothing

### _get_kb_document_ids
- **Takes:** nothing
- **Returns:** (list[str]) — KB document IDs loaded from .env, cached until file changes
- **Raises:** nothing

### _has_case_master_id
- **Takes:** results (list[dict]) — query result rows to check
- **Returns:** (bool) — True if the first result row contains a CaseMasterID key
- **Raises:** nothing

### _log
- **Takes:** msg (str) — message to log
- **Returns:** nothing
- **Raises:** nothing

### _most_recent_table
- **Takes:** history (list[dict]) — conversation history turns
- **Returns:** (list[dict]) — the table snapshot from the most recent assistant turn, or []
- **Raises:** nothing

### _run_direct
- **Takes:** question (str) — user question, history (list[dict]) — conversation history, recent_table (list[dict]) — last result set
- **Returns:** (PipelineResponse) — answer generated without SQL, with error handling
- **Raises:** nothing (never raises, errors surfaced in response fields)

### run_pipeline
- **Takes:** question (str) — user question, history (list[dict] | None) — conversation history, officer (dict | None) — authenticated officer JWT payload
- **Returns:** (PipelineResponse) — full pipeline result with answer, table data, media, graph flag
- **Raises:** nothing (never raises, all failures surfaced via error/answer_text fields)

---

## backend/pipeline/risk_scoring.py

### _empty_score
- **Takes:** accused_id (int) — AccusedMasterID for which no data was found
- **Returns:** (dict) — zeroed-out risk score dict with empty factors
- **Raises:** nothing

### compute_risk_for_accused
- **Takes:** accused_id (int) — AccusedMasterID to compute risk score for
- **Returns:** (dict) — risk assessment with accused_id, risk_score, risk_tier, contributing_factors
- **Raises:** nothing (catches all exceptions internally, returns empty score)

### get_cached_risk_score
- **Takes:** accused_id (int) — AccusedMasterID to look up cached score for
- **Returns:** (dict | None) — cached risk score dict or None if not found
- **Raises:** Exception — when DB read fails

### recompute_all_risk_scores
- **Takes:** nothing
- **Returns:** (int) — count of accused persons whose risk scores were recomputed
- **Raises:** Exception — when DB operations fail

### save_risk_score
- **Takes:** result (dict) — computed risk score dict with accused_id, risk_score, risk_tier, contributing_factors
- **Returns:** nothing
- **Raises:** Exception — when DB write fails

---

## backend/pipeline/schema_linker.py

### _keyword_matches
- **Takes:** question_lower (str) — lowercased user question, keyword (str) — keyword to match against
- **Returns:** (bool) — True if the keyword is present in the question respecting word boundaries
- **Raises:** nothing

### select_relevant_tables
- **Takes:** question (str) — natural language question from the user
- **Returns:** (list[str]) — relevant table names, CaseMaster always first, capped at 5
- **Raises:** nothing

---

## backend/pipeline/similar_cases.py

### find_similar_cases
- **Takes:** case_master_id (int) — CaseMasterID of the source case, limit (int) — max results to return
- **Returns:** (list[dict]) — similar cases ranked by match_score with match_reasons
- **Raises:** nothing (returns empty list on missing source case)

---

## backend/pipeline/case_timeline.py

### build_case_timeline
- **Takes:** case_master_id (int) — CaseMasterID of the case to build a timeline for
- **Returns:** (list[dict]) — chronologically ordered events [{"date": str, "event": str, "detail": str}, ...], empty list if case doesn't exist
- **Raises:** nothing (returns empty list on missing case)

---

## backend/pipeline/case_summary.py

### generate_case_summary
- **Takes:** case_master_id (int) — CaseMasterID of the case to summarize
- **Returns:** (dict) — {"summary": str, "error": None} on success, or {"summary": None, "error": str} on failure
- **Raises:** nothing (never raises, errors surfaced in return dict)

---

## backend/pipeline/evidence_trail.py

### _log
- **Takes:** msg (str) — message to log
- **Returns:** nothing
- **Raises:** nothing

### save_evidence_trail
- **Takes:** message_id (int | None) — assistant message row ID from chat_messages, sql_generated (str | None) — SQL query that was executed, table_data (list[dict] | None) — raw query result rows
- **Returns:** nothing
- **Raises:** nothing (non-fatal, failures are logged to stderr)

---

## backend/pipeline/sql_validator.py

### _extract_cte_names
- **Takes:** sql (str) — SQL string to extract CTE names from
- **Returns:** (list[str]) — lowercase CTE names defined in WITH clauses
- **Raises:** nothing

### extract_tables
- **Takes:** sql (str) — SQL string to extract table references from
- **Returns:** (list[str]) — table names found after FROM/JOIN keywords
- **Raises:** nothing

### sanitize_sql
- **Takes:** sql (str) — raw LLM output potentially with markdown fences and backticks
- **Returns:** (str) — cleaned SQL string ready for validation
- **Raises:** nothing

### validate_sql
- **Takes:** sql (str) — sanitized SQL to validate, allowed_tables (list[str] | None) — whitelist of permitted table names
- **Returns:** (ValidationResult) — validation outcome with is_valid flag and optional error message
- **Raises:** nothing

---

## backend/pipeline/trend_analytics.py

### get_crime_type_by_location
- **Takes:** station_unit_id (int) — UnitID of the police station to drill into
- **Returns:** (list[dict]) — rows with crime_type and count for that station
- **Raises:** Exception — when DB query fails

### get_modus_operandi_clusters
- **Takes:** min_occurrences (int) — minimum case count threshold for a cluster to be returned
- **Returns:** (list[dict]) — rows with crime_type, station, and count for clusters meeting the threshold
- **Raises:** Exception — when DB query fails

### get_seasonal_pattern
- **Takes:** nothing
- **Returns:** (list[dict]) — rows with month_num, month_name, and count of crimes per calendar month
- **Raises:** Exception — when DB query fails

### get_status_breakdown
- **Takes:** nothing
- **Returns:** (list[dict]) — rows with status name and count of cases
- **Raises:** Exception — when DB query fails

### get_trend_by_crime_type
- **Takes:** nothing
- **Returns:** (list[dict]) — rows with crime_type and count, ordered by count descending
- **Raises:** Exception — when DB query fails

### get_trend_by_location
- **Takes:** limit (int) — maximum number of stations to return
- **Returns:** (list[dict]) — rows with unit_id, station name, and crime count, ordered by count descending
- **Raises:** Exception — when DB query fails

### get_trend_by_month
- **Takes:** months_back (int) — number of months to look back from current date
- **Returns:** (list[dict]) — rows with month (YYYY-MM) and count of crimes
- **Raises:** Exception — when DB query fails

---

## backend/routers/auth.py

### _log
- **Takes:** msg (str) — message to log
- **Returns:** nothing
- **Raises:** nothing

---

## backend/routers/analytics.py

### mo_clusters
- **Takes:** min_occurrences (int) — minimum cluster size threshold (1-100), officer (dict) — authenticated officer from token
- **Returns:** (dict) — {"clusters": list[dict]} with repeated crime-type/station patterns
- **Raises:** HTTPException — when authentication fails (401)

### seasonal_pattern
- **Takes:** officer (dict) — authenticated officer from token
- **Returns:** (dict) — {"pattern": list[dict]} with monthly seasonal crime counts
- **Raises:** HTTPException — when authentication fails (401)

### station_breakdown
- **Takes:** unit_id (int) — police station UnitID to drill into, officer (dict) — authenticated officer from token
- **Returns:** (dict) — {"unit_id": int, "breakdown": list[dict]} with crime types for that station
- **Raises:** HTTPException — when authentication fails (401)

### status_breakdown
- **Takes:** officer (dict) — authenticated officer from token
- **Returns:** (dict) — {"breakdown": list[dict]} with case status counts
- **Raises:** HTTPException — when authentication fails (401)

### trends_crime_type
- **Takes:** officer (dict) — authenticated officer from token
- **Returns:** (dict) — {"trend": list[dict]} with crime type counts
- **Raises:** HTTPException — when authentication fails (401)

### trends_monthly
- **Takes:** months_back (int) — number of months to look back (1-60), officer (dict) — authenticated officer from token
- **Returns:** (dict) — {"trend": list[dict]} with monthly crime counts
- **Raises:** HTTPException — when authentication fails (401)

### trends_stations
- **Takes:** limit (int) — maximum number of stations to return (1-50), officer (dict) — authenticated officer from token
- **Returns:** (dict) — {"trend": list[dict]} with station case counts
- **Raises:** HTTPException — when authentication fails (401)

---

## backend/routers/chat.py

### _authorize_session_write
- **Takes:** session_id (str) — session to authorize, officer_id (int) — EmployeeID of the requesting officer
- **Returns:** (bool) — True if session exists and is owned by this officer, False if session does not exist yet
- **Raises:** HTTPException — when session exists but belongs to another officer (404)

### _log
- **Takes:** msg (str) — message to log
- **Returns:** nothing
- **Raises:** nothing

### _persist_turn
- **Takes:** session_id (str) — session to persist turn to, officer (dict) — authenticated officer, question (str) — user question, result (PipelineResponse) — pipeline output, session_exists (bool) — whether session row already exists
- **Returns:** nothing
- **Raises:** nothing (never raises, failures are logged)

### _sse
- **Takes:** event (dict) — SSE event payload to serialize
- **Returns:** (str) — formatted SSE message string ending with blank line
- **Raises:** nothing

### _tokenize
- **Takes:** text (str) — answer text to split into streaming tokens
- **Returns:** (list[str]) — space-preserving tokens for token-by-token SSE streaming
- **Raises:** nothing

### message_evidence_trail
- **Takes:** message_id (int) — message row ID, officer (dict) — authenticated officer from token
- **Returns:** (dict) — evidence trail row with trail_id, message_id, sql_executed, tables_queried, row_count, case_ids_referenced, created_at
- **Raises:** HTTPException — when message not found, not owned by officer, or has no evidence trail (404)

---

## backend/routers/decision_support.py

### similar_cases
- **Takes:** case_id (int) — CaseMasterID to find similar cases for, limit (int) — max results (default 5), officer (dict) — authenticated officer from token
- **Returns:** (dict) — {"case_id": int, "similar_cases": list[dict]} with match_score and match_reasons
- **Raises:** HTTPException — when authentication fails (401)

### case_timeline
- **Takes:** case_id (int) — CaseMasterID to build timeline for, officer (dict) — authenticated officer from token
- **Returns:** (dict) — {"case_id": int, "timeline": list[dict]} with chronologically ordered events
- **Raises:** HTTPException — when authentication fails (401)

### case_summary
- **Takes:** case_id (int) — CaseMasterID to summarize, officer (dict) — authenticated officer from token
- **Returns:** (dict) — {"case_id": int, "summary": str | None, "error": str | None}
- **Raises:** HTTPException — when authentication fails (401)

---

## backend/routers/export.py

### _build_html
- **Takes:** officer_name (str) — officer's display name, badge_number (str) — KGID, title (str) — session title, messages (list) — message dicts with content and optional table_data
- **Returns:** (str) — complete HTML document string for export
- **Raises:** nothing

### _escape
- **Takes:** value (Any) — value to HTML-escape for safe rendering
- **Returns:** (str) — HTML-escaped string representation
- **Raises:** nothing

### _merge_history_tables
- **Takes:** messages (list) — message dicts from DB, history (list) — conversation history with table snapshots
- **Returns:** (list) — messages with table_data hydrated from history where missing
- **Raises:** nothing

---

## backend/routers/reports.py

### _decode_file
- **Takes:** data_base64 (str) — base64-encoded file content
- **Returns:** (bytes) — decoded raw file bytes
- **Raises:** HTTPException — when base64 is invalid (400) or file exceeds 5 MB (413)

### _decode_text
- **Takes:** raw (bytes) — raw file bytes to decode as text
- **Returns:** (str) — decoded text content using best-effort encoding detection
- **Raises:** nothing

### _extract_docx_text
- **Takes:** raw (bytes) — raw .docx file bytes (zip archive)
- **Returns:** (str) — extracted paragraph text from the document body
- **Raises:** nothing (returns "" on parse failure)

### _extract_html_text
- **Takes:** text (str) — HTML content string
- **Returns:** (str) — plain text with tags and script/style content removed
- **Raises:** nothing

### _log
- **Takes:** msg (str) — message to log
- **Returns:** nothing
- **Raises:** nothing

### _persist_report_turn
- **Takes:** session_id (str) — chat session ID, officer (dict) — authenticated officer, question (str) — user prompt, answer (str) — LLM response, session_exists (bool) — whether session row exists
- **Returns:** nothing
- **Raises:** nothing (never raises, failures are logged)

### build_report_prompt
- **Takes:** officer_prompt (str) — officer's analysis request, file_name (str) — uploaded filename, extracted_text (str) — text extracted from the file, history (list[dict]) — recent chat context
- **Returns:** (tuple[str, str]) — (system_prompt, user_prompt) for report analysis LLM call
- **Raises:** nothing

### extract_report_text
- **Takes:** raw (bytes) — raw file bytes, file_name (str) — original filename for type detection, mime_type (str) — MIME type hint
- **Returns:** (str) — extracted and cleaned text, capped at MAX_EXTRACTED_CHARS
- **Raises:** UnsupportedReportFormat — when file type cannot be text-extracted (PDF, unknown)

---

## backend/routers/voice.py

### _log
- **Takes:** msg (str) — message to log
- **Returns:** nothing
- **Raises:** nothing

---

## backend/voice/zia_voice.py

### _extract_transcript
- **Takes:** payload (dict) — raw STT API response
- **Returns:** (str) — extracted transcript text, or empty string if not found
- **Raises:** nothing

### _extract_translation
- **Takes:** payload (dict) — raw Translation API response
- **Returns:** (str) — extracted translated text, or empty string if not found
- **Raises:** nothing

### _log
- **Takes:** msg (str) — message to log
- **Returns:** nothing
- **Raises:** nothing

### _normalize_for_speech
- **Takes:** text (str) — text containing abbreviations TTS engines mispronounce
- **Returns:** (str) — text with abbreviations expanded to phonetic spellings
- **Raises:** nothing

### _numbers_to_words
- **Takes:** text (str) — text containing standalone digit sequences
- **Returns:** (str) — text with digits replaced by spoken English words
- **Raises:** nothing

### _strip_markdown_for_speech
- **Takes:** text (str) — markdown-containing answer text
- **Returns:** (str) — text with table pipes, headers, and markdown symbols removed
- **Raises:** nothing

### _unwrap
- **Takes:** data (dict) — raw Catalyst API response
- **Returns:** (dict) — inner data object unwrapped from the Catalyst envelope
- **Raises:** nothing

### _zia_headers
- **Takes:** extra (dict | None) — additional headers to merge
- **Returns:** (dict) — HTTP headers with Catalyst OAuth token and org ID
- **Raises:** nothing

### synthesize_speech
- **Takes:** text (str) — text to synthesize into speech, language (str) — language code for TTS
- **Returns:** (bytes) — raw audio bytes (MP3/WAV)
- **Raises:** VoiceError — when TTS is not configured, text is empty, request fails, or response is empty

### transcribe_audio
- **Takes:** audio_bytes (bytes) — recorded audio data, language (str) — language code of the audio
- **Returns:** (str) — transcription text
- **Raises:** VoiceError — when STT is not configured, request fails, or transcript is empty

### translate_to_english
- **Takes:** text (str) — text to translate, source_language (str) — ISO language code of source text
- **Returns:** (str) — English translation, or original text on any failure
- **Raises:** nothing (degrades gracefully, never raises)

---

## frontend/src/api/auth.js

### clearToken
- **Takes:** nothing
- **Returns:** nothing
- **Raises:** never

### getOfficer
- **Takes:** nothing
- **Returns:** (object|null) — the authenticated officer's profile object
- **Raises:** never

### getToken
- **Takes:** nothing
- **Returns:** (string|null) — the current JWT access token held in memory
- **Raises:** never

### isLoggedIn
- **Takes:** nothing
- **Returns:** (boolean) — true if a token is currently held in memory
- **Raises:** never

### setToken
- **Takes:** token (string|null) — JWT access token to store, officer (object|null) — officer profile to store
- **Returns:** nothing
- **Raises:** never

---

## frontend/src/api/analytics.js

### authHeaders
- **Takes:** nothing
- **Returns:** (object) — headers object with Authorization bearer token if available
- **Raises:** never

### fetchCrimeTypeTrend
- **Takes:** nothing
- **Returns:** (Promise<object>) — {"trend": array} with crime type counts
- **Raises:** AuthError — when session expired, Error — when request fails

### fetchMoClusters
- **Takes:** minOccurrences (number) — minimum cluster size threshold (default 2)
- **Returns:** (Promise<object>) — {"clusters": array} with repeated crime-type/station patterns
- **Raises:** AuthError — when session expired, Error — when request fails

### fetchMonthlyTrend
- **Takes:** monthsBack (number) — number of months to look back (default 12)
- **Returns:** (Promise<object>) — {"trend": array} with monthly crime counts
- **Raises:** AuthError — when session expired, Error — when request fails

### fetchSeasonalPattern
- **Takes:** nothing
- **Returns:** (Promise<object>) — {"pattern": array} with monthly seasonal crime counts
- **Raises:** AuthError — when session expired, Error — when request fails

### fetchStationBreakdown
- **Takes:** unitId (number) — police station UnitID to drill into
- **Returns:** (Promise<object>) — {"unit_id": number, "breakdown": array} with crime types for that station
- **Raises:** AuthError — when session expired, Error — when request fails

### fetchStationTrend
- **Takes:** limit (number) — maximum number of stations to return (default 10)
- **Returns:** (Promise<object>) — {"trend": array} with station case counts
- **Raises:** AuthError — when session expired, Error — when request fails

### fetchStatusBreakdown
- **Takes:** nothing
- **Returns:** (Promise<object>) — {"breakdown": array} with case status counts
- **Raises:** AuthError — when session expired, Error — when request fails

### get
- **Takes:** path (string) — relative API path to fetch from
- **Returns:** (Promise<object>) — parsed JSON response from the analytics endpoint
- **Raises:** AuthError — when session has expired (401), Error — when request fails

---

## frontend/src/api/chat.js

### authHeaders
- **Takes:** extra (object) — additional headers to merge
- **Returns:** (object) — headers object with Authorization bearer token if available
- **Raises:** never

### handleFrame
- **Takes:** frame (string) — raw SSE frame text, callbacks (object) — event handler callbacks
- **Returns:** nothing
- **Raises:** never

---

## frontend/src/components/ChatWindow.jsx

### newMessageId
- **Takes:** nothing
- **Returns:** (string) — a new unique message identifier
- **Raises:** never

### newSessionId
- **Takes:** nothing
- **Returns:** (string) — a new unique session identifier (UUID or fallback random string)
- **Raises:** never

### readSidebarCollapsed
- **Takes:** nothing
- **Returns:** (boolean) — true if sidebar was previously collapsed by the user
- **Raises:** never

### readSidebarWidth
- **Takes:** nothing
- **Returns:** (number) — persisted sidebar width in pixels, clamped to min/max bounds
- **Raises:** never

---

## frontend/src/components/MediaViewer.jsx

### getMediaType
- **Takes:** url (string) — media file URL, mediaType (string|undefined) — optional MIME-based type hint
- **Returns:** (string) — one of 'unavailable', 'image', 'audio', 'video', or 'document'
- **Raises:** never

---

## frontend/src/components/MessageBubble.jsx

### firstFirId
- **Takes:** tableData (Array<object>|any) — structured table rows from the chat response
- **Returns:** (number|null) — the first valid CaseMasterID as a number, or null if none found
- **Raises:** never

### stripMarkdownTable
- **Takes:** text (string|null) — markdown prose that may contain embedded markdown tables
- **Returns:** (string|null) — text with markdown table blocks stripped out
- **Raises:** never

---

## frontend/src/components/SessionItem.jsx

### formatRelativeTimestamp
- **Takes:** iso (string|null) — ISO 8601 timestamp to format
- **Returns:** (string) — human-friendly relative time label (e.g. "12:30 PM", "Yesterday", "Monday", "Jan 15")
- **Raises:** never

---

## frontend/src/components/TableRenderer.jsx

### formatCell
- **Takes:** value (any) — raw cell value from a table row
- **Returns:** ({text: string, full: string}) — formatted display text and full value for tooltip (empty if not truncated)
- **Raises:** never

---

## frontend/src/context/LangContext.jsx

### useLang
- **Takes:** nothing
- **Returns:** (object) — {lang, setLang, t} language state, setter, and translation helper
- **Raises:** Error — when used outside a LangProvider

---

## frontend/src/hooks/useAuth.js

### useAuth
- **Takes:** nothing
- **Returns:** (object) — {isAuthenticated, officer, isLoading, error, login, logout} auth state and actions
- **Raises:** never

---

## frontend/src/api/profiling.js

### authHeaders
- **Takes:** nothing
- **Returns:** (object) — headers object with Authorization bearer token if available
- **Raises:** never

### fetchRiskScore
- **Takes:** accusedId (number|string) — unique identifier of the accused person
- **Returns:** (Promise<object|null>) — parsed JSON risk score data, or null if not found (404)
- **Raises:** AuthError — when session expired (401), Error — when request fails

---

## frontend/src/api/decisionSupport.js

### authHeaders
- **Takes:** nothing
- **Returns:** (object) — headers object with Authorization bearer token
- **Raises:** never

### get
- **Takes:** path (string) — API sub-path to append to the decision-support base URL
- **Returns:** (Promise<object>) — parsed JSON response body
- **Raises:** AuthError — when session expired (401), Error — when request fails

### fetchCaseTimeline
- **Takes:** caseId (number|string) — unique identifier of the case
- **Returns:** (Promise<object>) — {case_id, timeline: list[dict]}
- **Raises:** AuthError — when session expired (401), Error — when request fails

### fetchCaseSummary
- **Takes:** caseId (number|string) — unique identifier of the case
- **Returns:** (Promise<object>) — {case_id, summary, error}
- **Raises:** AuthError — when session expired (401), Error — when request fails

### fetchSimilarCases
- **Takes:** caseId (number|string) — unique identifier of the case, limit (number) — max results (default 5)
- **Returns:** (Promise<object>) — {case_id, similar_cases: list[dict]}
- **Raises:** AuthError — when session expired (401), Error — when request fails

---

## frontend/src/api/evidenceTrail.js

### authHeaders
- **Takes:** nothing
- **Returns:** (object) — headers object with Authorization bearer token
- **Raises:** never

### fetchEvidenceTrail
- **Takes:** messageId (string|number) — unique identifier of the chat message
- **Returns:** (Promise<object|null>) — parsed JSON evidence trail, or null if not found/not owned/DIRECT-path
- **Raises:** AuthError — when session expired (401), Error — when request fails

---

## frontend/src/components/MessageBubble.jsx

### firstAccusedId
- **Takes:** tableData (Array<object>|any) — structured table rows from the chat response
- **Returns:** (number|null) — the first valid AccusedMasterID as a number, or null if none found
- **Raises:** never

---
