# 接口基线（自动生成）

- 生成时间：2026-10-26T19:17:06
- DSH 版本：0.2.1-alpha.1
- 工作台 profile：bench
- 组装行数：292（禁用 45）

## profile 分层（每个 bundle 产出的行）

| 层 | 行数 | 插件 id |
|---|---|---|
| @deepseek-ai/dsh-base | 92 | ~~tool-plugin-manager~~, plugin-manager, timer, hmr, llm, deepseek-llm-api-extensions, session, session-log-deepseek, typert, typert-loader, typert-gateway, session-title, session-title-llm, user-questions, agent, ~~plugin-package-inventory-deepseek~~, agent-default-model, jobs, llm-retry, config-editor, settings, authorization, credentials, llm-pi-ai, session-persistence-jsonl, attachment-local, session-query-sqlite, session-projection, storage, storage-json, storage-domain, session-projection-cache, otel, session-telemetry-otel, subprocess, sandbox, sandbox-policy, bash-sandbox, pwsh-sandbox, approval, permission, shell-env, ~~tool-bash~~, ~~tool-pwsh~~, ~~tool-jobs~~, ~~fs-observation-policy~~, ~~tool-fs~~, ~~tool-fs-search~~, ~~agent-instructions~~, skill, ~~skill-filesystem~~, ~~skill-badge~~, ~~tool-skill~~, commands, command-feedback, goal, goal-round-driver, ~~command-goal~~, ~~plan-mode~~, token-meter, ~~compaction-basic~~, ~~command-compact~~, subagent, subagent-spawn-in-process, subagent-fork-in-process, ~~tool-subagent-control~~, ~~tool-subagent-list-agents~~, ~~tool-subagent~~, ~~tool-subagent-fork~~, ptc-runtime, ~~workflow-ptc~~, ~~tool-workflow~~, timeout-policy, spill-local, spill-policy, session-checkpoint-policy, ~~tool-result-pruner~~, image-offload, ~~tool-todo~~, ~~tool-goal~~, ~~tool-ralph~~, repeat-tool-reminder, web, web-search-deepseek, web-fetch-http, ~~tool-web~~, mcp-resources, tools, system-prompt, ~~agent-loop~~, fs-sandbox, llm-deepseek |
| @deepseek-ai/dsh-web-app | 200 | ~~desktop-product-telemetry~~, product-analytics, subagent-model-selection-settings, ~~message-feedback~~, session-log-download, open-in-app, ui-open-in-app, workspace, session-reference, file-reference-local, session-stats, session-turn-outline, directory-picker, plugin-inventory, session-controller, job-controller, terminal-controller, workspace-files, schedule, ui-settings-account, account-controller, settings-controller, workspace-controller, cordis-host-runner, cordis-inspect-providers, web-startup, webserver, web-runtime, client-hmr, modules, connection, file-upload, api-remotes, cordis-client-runner, ui-theme, locale, shortcuts, ui-shortcuts, ui-layout, ui-renderer, ui-session, resources, ui-sidebar, ui-sidebar-right, office-to-pdf, ui-sidebar-documentpreview, ui-sidebar-browser, ui-sidebar-terminal, ui-sidebar-files, ui-settings, ui-session-context, ui-settings-general, ui-settings-models, ui-plugin-manager, ui-settings-plugin-inventory, ui-conversation, ui-approval, ui-chat, ui-brand-official, ui-attachment, ui-tool, ui-cordis, ui-deliverables, workspace-changes, ui-workspace, ui-workflow-run, ui-input-trigger, ui-commands, ui-skill, ui-subagent, ui-reference, ui-jobs, ui-schedule, ui-goal, ~~ui-message-feedback~~, ui-model-selection, ui-permission, ui-agent-preset, ~~ui-settings-session-log~~, ui-settings-plugins, ui-settings-shell, ui-settings-agent-loop, ui-settings-subagent, ui-settings-web-search, ui-plan, ui-user-questions, ui-trajectory, agent-preset-registry, preset-standard, persona, agent-instructions, time-context, tool-bash, tool-pwsh, tool-fs, tool-fs-search, tool-jobs, skill-filesystem, tool-skill, command-goal, tool-goal, planning, plan-mode, compaction, compaction-basic, command-compact, tool-result-pruner, delegation, tool-subagent-control, tool-subagent-list-agents, tool-subagent, tool-subagent-fork, ~~tool-subagent-codex~~, ~~tool-subagent-claude-code~~, workflow-ptc, tool-workflow, ~~tool-ralph~~, tool-ask-user, tool-todo, tool-web, present, ~~tool-plugin-manager~~, preset-ptc, persona, agent-instructions, time-context, tool-bash, tool-pwsh, tool-fs, tool-fs-search, tool-jobs, skill-filesystem, tool-skill, command-goal, tool-goal, planning, plan-mode, compaction, compaction-basic, command-compact, tool-result-pruner, delegation, tool-subagent-control, tool-subagent-list-agents, tool-subagent, tool-subagent-fork, ~~tool-subagent-codex~~, ~~tool-subagent-claude-code~~, ~~workflow-ptc~~, ~~tool-workflow~~, ~~tool-ralph~~, tool-ask-user, tool-todo, tool-web, tool-presentation, present, ~~tool-plugin-manager~~, preset-minimal, persona, persistent-shell, pty, terminal-bash, persistent-bash, terminal-pwsh, persistent-pwsh, preset-cordis, persona, agent-instructions, time-context, tool-bash, tool-pwsh, tool-fs, tool-fs-search, tool-jobs, command-goal, tool-goal, planning, plan-mode, compaction, compaction-basic, command-compact, tool-result-pruner, delegation, tool-subagent-control, tool-subagent-list-agents, tool-subagent, tool-subagent-fork, ~~tool-subagent-codex~~, ~~tool-subagent-claude-code~~, workflow-ptc, tool-workflow, ~~tool-ralph~~, tool-ask-user, tool-todo, tool-web, tool-cordis, skill-filesystem, tool-skill, present, tool-plugin-manager |

## 活体接口（版本 0.2.1-alpha.1）

- 宿主服务 **91** 个（`ctx.<key>`）
- 前端槽位 **92** 个

### 常用挂载点

| 槽位 | 类型 | 作用 |
|---|---|---|
| `main` | keyed | Central panel selected by sidebar entry id. |
| `sidebar.panellist` | list | Global panel icons. |
| `sidebar.footer.action` | list | Optional actions beside Settings at the sidebar foot. |
| `settings.section` | list | One settings page per list entry. |
| `settings.general.item` | list | One preference row inside the General section — the additive seat for a single setting that needs no page of i |
| `shell.overlay` | list | Frame-wide floating layer, above every column and outside their scroll containers. |
| `conversation.input.right` | list | Compact controls before the composer submit action. |
| `conversation.input.left` | list | Compact controls at the left of the composer tool row. |
| `plugins.detail.section` | list | Sections under a detail page's own content: after the rows on a bundle's page, after the configuration on a ro |
| `conversation.view` | list | Registered Conversation target Views, rendered one at a time. |
| `conversation.chat.node` | keyed | Final Chat node renderer, keyed by `ChatNodeKind`. |
| `conversation.composer.dock` | list | Ambient entries below the composer card. |

### 宿主服务（前 30）

| key | 说明 |
|---|---|
| `agentDefaultModel` | Owns the default model selection independently of any Host or transport. |
| `agentLoop` | Concrete agent factory and driver service. |
| `agentPresets` | Registry of YAML-declared presets and the revisions live Agents retain. |
| `agents` | Agent service (`ctx.agents`): tracks live agents and carries the initiating Agent through  |
| `agentTeams` | Agent Teams service backed by the exact live Lead Session log. |
| `approval` | Approval service that applies session policy before answerers and logs every ask/outcome p |
| `attachments` | Immutable binary attachment service. |
| `authorization` | `ctx.authorization`: a registry of credential-obtaining flows, one attempt at a time per k |
| `browserUse` | Owns one optional provider registration in the shared browser-use service. |
| `claudeCodeMods` | The bridge service: loaded mods, their hooks, and the harness listeners that raise their e |
| `clientModules` | The web plugin table service: incremental `dsh.client` scan + wire composition + bundle ro |
| `commands` | Human-command registry. |
| `compaction` | Abstract compaction service. |
| `computerUse` | Owns one optional provider registration in the shared computer-use service. |
| `configEditor` | Persist complete raw configs and apply them through the normal Loader path. |
| `connection` | Host `ctx.connection` members consumed by transport-independent adapters. |
| `credentials` | Abstract credential service over two key spaces that answer two questions. |
| `credentialsController` | Host service backing the generated `ctx.remote.credentials` namespace. |
| `deepseekAccount` | Account operations; only Host consumers can obtain a request credential. |
| `deepseekLlmApiExtensions` | Registry of independently owned top-level fields for official DeepSeek requests. |
| `directoryPicker` | Abstract directory-picking service. |
| `directoryPickerController` | Host service backing the generated `ctx.remote.directoryPicker` namespace. |
| `fileReferences` | Host capability for cancellable file-reference discovery. |
| `fileUploads` | Host service owning upload storage and receipts keyed by each receiving Agent's exact Sess |
| `fs` | Abstract filesystem provider. |
| `goals` | Goal service (`ctx.goals`) backed exclusively by the owning session log. |
| `hmr` | Hot reload service with Cordis-compatible module configuration and events. |
| `inspector` | Shared Host/Client service façade over the realm's source publisher. |
| `jobController` | Host service backing the generated `ctx.remote.job` namespace. |
| `jobs` | Abstract background job registry. |
