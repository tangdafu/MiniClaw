# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

MiniClaw is a small AI-agent chat application with a FastAPI backend and Vue 3 frontend. The backend talks to an OpenAI-compatible Chat Completions API, streams agent events over WebSocket, executes local tools, and persists chat sessions as JSON files. The frontend is a Vite app that connects to the backend WebSocket and renders streaming text, reasoning, tool calls, and tool results.

## Development commands

### Backend

Run backend commands from `backend/`.

```bash
uv sync
uv run python main.py
```

The backend listens on `http://localhost:8000` and exposes:

- `GET /health`
- `WebSocket /ws/chat`

Configure model access by copying and editing `backend/.env.example`:

```bash
cp .env.example .env
```

Required/recognized variables:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `MINICLAW_CONTEXT_WINDOW_SIZE`

`OPENAI_BASE_URL` and `OPENAI_MODEL` default through `AgentConfig` to the OpenAI-compatible SDK behavior and `gpt-4o`; set them explicitly when using a non-OpenAI provider. `MINICLAW_CONTEXT_WINDOW_SIZE` defaults to 20 persisted messages and controls only model request assembly, not saved history.

No backend test or lint command is currently configured in the repo.

### Frontend

Run frontend commands from `frontend/`.

```bash
npm install
npm run dev
npm run build
npm run preview
```

`npm run dev` starts Vite on `http://localhost:5173`. The Vite dev server proxies `/ws` to `ws://localhost:8000` and `/health` to `http://localhost:8000`.

`npm run build` runs `vue-tsc` first, so it is also the frontend type-check command. No frontend test or lint command is currently configured in the repo.

## Architecture notes

### Backend layers

- `backend/main.py` is the FastAPI entry point. Its lifespan initializes one global `Claw` instance with an `Agent` and the tool list from `tools.get_tools()`. The `/ws/chat` endpoint accepts `{ session_id, message }` and streams serialized `Event` objects back to the client.
- `backend/miniclaw/claw.py` is the orchestration/session layer. `Claw.chat()` creates a session when needed, loads existing session messages, delegates the conversation loop to `Agent.chat()`, then saves the mutated message history through `SessionManager`.
- `backend/miniclaw/agent.py` is now a facade. It preserves the public `Agent.chat(messages, user_message)` interface, owns `AgentConfig` and the OpenAI-compatible client, and delegates the actual ReAct loop to `ReactRuntime`.
- `backend/miniclaw/react_runtime.py` is the internal ReAct orchestration loop. It appends the user message, builds model requests, calls the streaming Chat Completions API, emits ordered frontend events, appends assistant/tool messages to the same history list, and coordinates hook calls.
- `backend/miniclaw/context_assembler.py` builds model request messages from persisted history. It applies the configurable sliding window, keeps the optional system prompt outside the window, repairs leading tool-message boundaries, and strips empty `reasoning_content` fields.
- `backend/miniclaw/react_context.py` defines runtime data structures: `ReactContext`, `ModelRequest`, `ModelTurn`, and `ToolExecution`.
- `backend/miniclaw/stream.py` contains `StreamAccumulator` and `ToolCallParser`, which reconstruct text, reasoning content, and OpenAI-style streamed tool calls from deltas.
- `backend/miniclaw/tool_executor.py` owns tool lookup, JSON argument parsing, sync/async handler invocation, and conversion of tool failures into error strings.
- `backend/miniclaw/hooks.py` defines no-op lifecycle hooks and `HookManager` for future extensions around run start, message building, model calls, assistant turns, tool calls, iteration boundaries, saving, and errors.
- `backend/miniclaw/types.py` defines the Pydantic `Tool`, `Event`, and message-related models used by both orchestration and transport.
- `backend/tools.py` is now a compatibility entry point for built-in tools. It preserves `get_tools()`, `SkillManager`, and `execute_command` exports while delegating to `backend/miniclaw/tools/`.
- `backend/miniclaw/tools/registry.py` composes built-in tools into the flat `list[Tool]` expected by `Agent` and `ToolExecutor`.
- `backend/miniclaw/tools/skills.py` provides `SkillRepository` and the `read_skill_list`, `read_skill`, and `list_skill_files` tools. The repository indexes skills by frontmatter name and keeps path access inside the selected skill directory.
- `backend/miniclaw/tools/command.py` provides `CommandRunner` and the `execute_command` tool. It preserves the current permissive shell execution behavior while centralizing timeout, workdir, output formatting, and a future validation seam.
- `backend/miniclaw/tools/files.py` provides general file tools: `read_file`, `list_files`, `search_text`, `write_file`, and `replace_text`. Safety/confirmation governance is intentionally out of scope for the initial general toolset.

When adding built-in tools, prefer adding a focused module under `backend/miniclaw/tools/` and composing it from `registry.py`. Keep `backend/tools.py` as a compatibility shim rather than adding new tool logic there.

### Session persistence

Sessions are stored under `backend/sessions/<session_id>/chat.json`. `SessionManager.create_session()` uses a 12-character UUID prefix for the session ID. `Agent.chat()` delegates to `ReactRuntime.run()`, which mutates the loaded `messages` list in place, so callers should save that same list after the stream completes. Assistant messages that request tools must be saved with their reconstructed `tool_calls` field before corresponding `role: tool` messages.

### Skill system

Skills live under `backend/skills/<skill-name>/SKILL.md`. `SkillRepository` discovers skills by reading YAML-like frontmatter in `SKILL.md` and exposes three tools to the agent:

- `read_skill_list`
- `read_skill`
- `list_skill_files`

`read_skill` accepts a path relative to the selected skill directory and checks that the resolved target remains inside that directory.

### Frontend flow

- `frontend/src/main.ts` mounts `App.vue`.
- `frontend/src/App.vue` is the page shell.
- `frontend/src/components/ChatView.vue` owns WebSocket connection state, message state, session ID tracking, markdown rendering via `marked`, and the UI for folded reasoning and paired tool call/result displays.

The frontend sends only the current `session_id` and latest message. Conversation history is loaded and persisted on the backend.

## Important implementation details

- The API event types expected by the frontend are `session_created`, `text`, `reasoning`, `tool_call`, `tool_result`, `done`, and `error`.
- `Event.model_dump()` maps the internal `error_msg` field to an external `error` key; preserve this contract if changing error serialization.
- `ToolCallParser` reconstructs streamed OpenAI-style tool call deltas by index and accumulates function arguments as strings before JSON parsing. It lives in `backend/miniclaw/stream.py` and remains re-exported through `miniclaw.agent` for compatibility.
- `ReactRuntime` owns frontend event ordering. Hooks may inspect or mutate context/request objects, but they should not directly emit frontend events.
- The current `execute_command` implementation runs shell commands with a 30-second timeout and returns combined stdout/stderr text.
- `frontend/tsconfig.json` enables strict TypeScript plus `noUnusedLocals` and `noUnusedParameters`; unused symbols fail `npm run build`.
