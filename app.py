"""
CoCo Agent API demo — Coding Agent via REST API
Calls POST /api/v2/cortex/agent:run with code_toolset_all directly.
No SDK — pure HTTP + SSE streaming against the Cortex Agents API.
"""

import json
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib

import requests
import streamlit as st

CONNECTION_NAME = "coco_api"
CONNECTIONS_TOML = Path.home() / ".snowflake" / "connections.toml"

st.set_page_config(
    page_title="CoCo Agent API — Coding Agent REST API",
    page_icon=":material/api:",
    layout="wide",
)

DEFAULT_PROMPTS = {
    "Explore my data": (
        "List all databases and schemas I have access to using SQL. "
        "Then pick the most interesting database that has real data (not system tables), "
        "show me the tables, row counts, and a few sample rows from the key tables. "
        "Summarize what the data is about."
    ),
    "Query & analyze": (
        "Run SHOW DATABASES, then SHOW SCHEMAS in each database. Find tables with real data. "
        "Write and run a SQL query that joins or aggregates data from the most interesting tables. "
        "Show the results and explain what you found."
    ),
    "Build a report": (
        "Explore the databases I have access to using SQL. Find the most interesting dataset. "
        "Write a Python script that queries Snowflake using snowflake.connector, "
        "analyzes the data with pandas, and produces a summary report. "
        "Save the report to /workspace/report.md and show me the output."
    ),
}

st.title(":material/api: Coding Agent — REST API")
st.caption(
    "Direct `POST /api/v2/cortex/agent:run` with `code_toolset_all` — no SDK, pure HTTP + SSE"
)

# --- Sidebar ---
with st.sidebar:
    st.header(":material/settings: Configuration")
    connection_name = st.text_input("Snowflake connection", value=CONNECTION_NAME)
    st.divider()
    if st.button("Clear chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
    st.divider()
    st.markdown("**How it works**")
    st.markdown(
        "This app calls the **Cortex Agents REST API** directly with "
        "`code_toolset_all`. Snowflake provisions a sandbox, executes tools "
        "(bash, read, write, SQL, web search), and streams SSE events back. "
        "No SDK, no CLI — just HTTP."
    )

# --- Session state ---
if "messages" not in st.session_state:
    st.session_state.messages = []
if "running" not in st.session_state:
    st.session_state.running = False


@st.cache_resource
def get_connection_config(_conn_name: str) -> dict:
    """Read PAT and account from connections.toml."""
    with open(CONNECTIONS_TOML, "rb") as f:
        config = tomllib.load(f)
    profile = config[_conn_name]
    # Underscores are not valid in TLS hostnames; Snowflake accepts hyphens instead
    account = profile["account"].replace("_", "-").lower()
    return {
        "pat": profile["token"],
        "account_url": f"https://{account}.snowflakecomputing.com",
    }


def build_request_body(conversation: list[dict]) -> dict:
    """Build the agent:run request body — send only the latest user message."""
    # Find the last user message
    last_user_msg = None
    for msg in reversed(conversation):
        if msg["role"] == "user":
            last_user_msg = msg["content"]
            break

    api_messages = [
        {"role": "user", "content": [{"type": "text", "text": last_user_msg}]},
    ]
    return {
        "models": {"orchestration": "auto"},
        "instructions": {
            "system": (
                "You are a data analyst agent connected to a live Snowflake account. "
                "You have access to real databases and tables via the snowflake_sql_execute tool. "
                "Always query the actual Snowflake data — never generate dummy or synthetic data. "
                "Use SHOW DATABASES, SHOW SCHEMAS, SHOW TABLES, and SELECT queries to explore and analyze. "
                "When asked to write Python scripts, use snowflake.connector to query real data."
            ),
        },
        "messages": api_messages,
        "tools": [
            {"tool_spec": {"type": "code_toolset_all", "name": "code_toolset_all"}}
        ],
        "tool_resources": {
            "code_toolset_all": {
                "permission_policy": {"type": "always_allow"},
                "workspace_mounts": [
                    {
                        "name": "USER$.PUBLIC.DEFAULT$",
                        "type": "workspace",
                        "mount_path": "/workspace",
                    }
                ],
            }
        },
    }


def stream_agent_response(conversation: list[dict], conn_name: str):
    """Call agent:run and yield text chunks from SSE stream."""
    cfg = get_connection_config(conn_name)
    body = build_request_body(conversation)

    resp = requests.post(
        f"{cfg['account_url']}/api/v2/cortex/agent:run",
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {cfg['pat']}",
            "X-Snowflake-Authorization-Token-Type": "PROGRAMMATIC_ACCESS_TOKEN",
        },
        json=body,
        stream=True,
    )

    if resp.status_code != 200:
        yield f"**API Error {resp.status_code}:** {resp.text[:500]}"
        return

    collected = []
    current_event_type = None
    for line in resp.iter_lines(decode_unicode=True):
        if not line:
            continue
        # Track event type from "event:" lines
        if line.startswith("event:"):
            current_event_type = line.split(":", 1)[1].strip()
            continue
        if not line.startswith("data:"):
            continue
        data_str = line.split("data:", 1)[1].strip()
        if data_str == "[DONE]":
            break
        try:
            event = json.loads(data_str)
        except json.JSONDecodeError:
            continue

        # Error events
        if "error_code" in event or ("message" in event and "code" in event and "request_id" in event):
            yield f"**API Error:** {event.get('message', str(event))}"
            return

        # Only yield from delta events — skip "response.text" and "response" (duplicates)
        if current_event_type == "response.text.delta":
            text = event.get("text", "")
            if text:
                collected.append(text)
                yield text


# --- Display chat history ---
for msg in st.session_state.messages:
    avatar = ":material/api:" if msg["role"] == "assistant" else None
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])

# --- Quick-start buttons (only before first message) ---
if not st.session_state.messages:
    st.markdown("**Try one of these:**")
    cols = st.columns(len(DEFAULT_PROMPTS))
    for col, (label, prompt_text) in zip(cols, DEFAULT_PROMPTS.items()):
        if col.button(label, use_container_width=True):
            st.session_state.messages.append(
                {"role": "user", "content": prompt_text}
            )
            st.rerun()

# --- Handle user input ---
if prompt := st.chat_input(
    "Ask the coding agent anything…",
    disabled=st.session_state.running,
):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    st.session_state.running = True

    with st.chat_message("assistant", avatar=":material/api:"):
        with st.spinner("Coding agent running in Snowflake sandbox…"):
            try:
                response = st.write_stream(
                    stream_agent_response(
                        st.session_state.messages, connection_name
                    )
                )
            except Exception as e:
                response = f":red[Agent error:] `{e}`"
                st.error(response)

    st.session_state.messages.append(
        {"role": "assistant", "content": response}
    )
    st.session_state.running = False
    st.rerun()
