# CoCo Agent API Demo

A minimal Streamlit chat app that calls the Snowflake **Cortex Agents REST API** (`POST /api/v2/cortex/agent:run`) with the `code_toolset_all` tool — the Cortex Code (CoCo) coding agent. No SDK, no CLI: plain HTTP + Server-Sent Events streaming.

Snowflake provisions a sandbox, the agent runs tools (bash, read/write files, SQL, web search) against your account, and the response streams back into the chat.

## Prerequisites

- Snowflake account with Cortex Agents and the Coding Agent (`code_toolset_all`) enabled
- A [Programmatic Access Token (PAT)](https://docs.snowflake.com/en/user-guide/programmatic-access-tokens) for your user
- Python 3.10+

## Setup

1. Add a connection to `~/.snowflake/connections.toml`:

   ```toml
   [coco_api]
   account = "<org>-<account>"
   token   = "<your PAT>"
   ```

2. Install dependencies and run:

   ```bash
   pip install -r requirements.txt
   streamlit run app.py
   ```

3. Open the app, pick a quick-start prompt (or type your own), and watch the agent work.

The connection name can be changed in the sidebar (default `coco_api`).

## How it works

`app.py` builds an `agent:run` request with:

- `tools`: `code_toolset_all`
- `tool_resources.code_toolset_all.permission_policy`: `always_allow`
- `workspace_mounts`: your personal workspace (`USER$.PUBLIC.DEFAULT$`) at `/workspace`

It authenticates with the PAT (`Authorization: Bearer ...`, token type `PROGRAMMATIC_ACCESS_TOKEN`) and renders `response.text.delta` SSE events as they arrive.

> Note: `always_allow` lets the agent execute tools without approval, using your role's privileges. Use a least-privilege role for demos. The app binds to `localhost` only.
