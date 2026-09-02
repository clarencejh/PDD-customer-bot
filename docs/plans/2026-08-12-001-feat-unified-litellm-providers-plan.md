---
title: Unified LiteLLM Provider Configuration - Plan
type: feat
date: 2026-08-12
topic: unified-litellm-providers
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-brainstorm
execution: code
---

# Unified LiteLLM Provider Configuration - Plan

## Goal Capsule

- **Objective:** 修复 GitHub Issue #27，并让 Customer-Agent 通过 LiteLLM 使用 DeepSeek、火山引擎、OpenAI-compatible、Kimi/Moonshot、智谱/Z.AI 和 Qwen/DashScope。
- **Product authority:** 本计划同时约束请求兼容性、供应商选择、配置启用和工具调用能力；现有 Customer-Agent 工具循环、会话行为和 API Key 加密规则继续有效。
- **Work unit:** Issue #27 修复与多供应商支持属于同一个工作单元，因为它们共同改变 LLM 连接配置和请求传输边界。
- **Open blockers:** 没有需要用户在规划前解决的产品阻塞项；LiteLLM 调用边界、能力检测实现和旧配置迁移细节留给实施规划确定。

## Product Contract

### Summary

Customer-Agent 将使用 LiteLLM 作为统一的 LLM 传输层，让用户从设置页选择内置供应商并手动填写模型名、API Key 和必要的 Base URL。
默认请求保持跨供应商便携，供应商专属参数不再以全局默认值泄漏到 DeepSeek 或其他自定义端点。

**Existing-consumer boundary:** The shared transport applies to Customer-Agent and the existing `ProductSyncService` because both read the active `llm` profile. ProductSync remains compatibility work for its existing text/image input, JSON extraction, and fallback behavior; it does not add a new user-facing provider capability.

### Problem Frame

Issue #27 报告 DeepSeek 因收到 `logprobs: false` 和 `top_logprobs: 0` 而返回 HTTP 400；移除这些字段后，同一请求可以成功。

当前 `Agent/CustomerAgent/custom/llm_client.py` 已允许自定义 `api_base`，但请求会经过 `utils/volcengine_models.py` 中带有火山引擎命名和非空供应商默认值的模型，再将全部非空字段发送出去。

当前设置页只保存模型名、API Key 和 Base URL，默认值仍以火山引擎/Doubao 为中心，因此“OpenAI-compatible”目前主要是连接地址可编辑，而不是完整的供应商选择能力。

### Key Decisions

- **LiteLLM 作为统一传输边界：** 使用 LiteLLM Python SDK 负责六类供应商的路由、参数适配和统一响应；应用层不再维护一套把火山引擎字段当作通用字段的请求契约。
- **便携请求优先：** 默认只发送当前 Customer-Agent 必需的通用字段；这是 Issue #27 中“移除不兼容默认字段”方向，相比只删除两个字段更能避免同类回归。（session-settled: user-directed — chosen over only patching current defaults: removes the broader provider-default compatibility risk） Governs R5, R6, R7.
- **显式供应商路由：** 用户选择决定 LiteLLM 的 provider 路由，不根据 URL 或模型名猜测供应商。规划时应保持以下用户概念与 LiteLLM 路由的一致映射：DeepSeek → `deepseek/`，火山引擎 → `volcengine/`，OpenAI-compatible → `openai/`，Kimi → `moonshot/`，智谱 → `zai/`，Qwen → `dashscope/`。
- **工具能力不得静默失效：** 已知所选模型不支持工具调用时，保存/启用必须被阻止并给出明确原因，而不是让运行时以通用 AI 错误失败。（session-settled: user-approved — chosen over allowing unsupported models to activate: prevents silent runtime failure） Governs R13-R16.
- **单一当前连接：** 本次保留应用已有的单一活动 LLM 配置；多连接档案、运行时切换和模型发现属于后续范围。

### Requirements

**Provider selection and connection configuration**

- R1. 设置页必须提供六个内置供应商选项：DeepSeek、火山引擎、OpenAI-compatible、Kimi/Moonshot、智谱/Z.AI 和 Qwen/DashScope。
- R2. 每个供应商都必须支持用户手动填写模型标识和 API Key，并允许按供应商需要填写或覆盖 Base URL。
- R3. 选定的供应商和模型必须通过 LiteLLM 直接发起聊天请求，不要求用户配置环境变量或运行独立的 LiteLLM Proxy 服务。
- R4. OpenAI-compatible 选项必须支持任意符合 Chat Completions 约定的自定义模型和 Base URL，且不能强制用户使用内置供应商的模型命名规则。

**Portable request and provider compatibility**

- R5. 默认聊天请求只能包含 Customer-Agent 当前需要的通用请求字段，以及存在工具时所需的工具定义和工具选择字段。
- R6. 供应商专属字段只能在 LiteLLM 判定该供应商支持并且请求确实需要时发送，不能由应用层的全局默认值自动注入。
- R7. 配置 DeepSeek 并启用工具调用时，请求不得因为 `logprobs`、`top_logprobs` 或同类不支持的默认字段而失败。
- R8. 六个内置供应商都必须保留现有 Customer-Agent 的消息、工具调用结果、会话上下文和多轮工具循环语义，供应商差异只影响连接和传输适配。

**Configuration lifecycle and backward compatibility**

- R9. 现有配置迁移必须保留原有模型名、Base URL 和 API Key，并为旧配置补充可用的供应商身份。
- R10. 迁移历史火山引擎默认 Base URL 的旧配置时，供应商身份必须落到火山引擎；迁移无法识别的自定义 Base URL 时，必须落到 OpenAI-compatible，而不是在运行时继续猜测。
- R11. API Key 必须继续使用现有的持久化加密和恢复流程，新增的供应商身份和模型名不得被当作秘密处理或写入日志。
- R12. 保存/启用配置前必须验证供应商、模型名、API Key 和所需 Base URL 的完整性，并在失败时保留原有有效配置。

**Tool capability gate and user feedback**

- R13. 配置校验必须区分模型支持工具调用、明确不支持工具调用和能力未知三种结果。
- R14. 对明确不支持工具调用的模型，保存/启用必须失败并显示包含供应商和模型名的可行动提示，应用不得静默关闭工具或降级为无工具模式。
- R15. 对工具能力未知的模型，应用必须显示风险提示并要求用户明确确认后才能启用，且不得把未知状态展示为“已验证支持”。
- R16. 运行时供应商错误、鉴权错误和工具能力错误必须提供可区分的安全反馈，并且不得在 UI、日志或异常文本中泄露 API Key。

**Verification and maintainability**

- R17. 请求适配必须有可独立验证的 mock 契约，能够断言 provider 路由、最终请求字段和工具调用参数，而不依赖真实供应商凭据。
- R18. 回归覆盖必须包含 Issue #27 的 DeepSeek 载荷场景、六个供应商的路由映射、自定义 OpenAI-compatible 端点、旧配置迁移、工具能力阻止启用和已支持模型的工具调用。
- R19. 项目依赖和锁定文件必须包含可复现安装所需的 LiteLLM 版本，并继续兼容项目当前的 Python 版本和 `uv sync` 工作流。

### Actors

- A1. **配置用户：** 选择供应商、填写连接信息、确认工具能力风险并启用配置。
- A2. **设置与配置系统：** 保存、迁移、校验连接配置并保护 API Key。
- A3. **LiteLLM 与供应商端点：** 根据所选 provider 路由请求，转换供应商差异并返回统一聊天响应或明确错误。
- A4. **Customer-Agent 运行时：** 使用统一响应驱动文本回复和现有工具执行循环。

### Key Flows

- F1. **配置并启用 LLM**
  - **Trigger:** 配置用户打开 LLM 设置并提交供应商、模型和连接信息。
  - **Actors:** A1, A2。
  - **Steps:** 设置系统校验必填项；迁移或生成供应商身份；检查工具调用能力；对支持的模型启用配置，对不支持的模型阻止启用，对未知能力要求明确确认。
  - **Outcome:** 只有通过对应能力门槛的配置成为当前活动 LLM 配置。
  - **Covered by:** R1, R2, R9-R15。

- F2. **通过 LiteLLM 生成客服回复**
  - **Trigger:** Customer-Agent 收到需要 LLM 处理的客户消息。
  - **Actors:** A3, A4。
  - **Steps:** 运行时加载活动配置；按显式供应商路由构建便携请求；发送消息和工具定义；将统一响应交给现有工具循环；返回最终客服回复。
  - **Outcome:** 支持工具的供应商继续完成现有多轮工具工作流，不携带不相关的供应商默认字段。
  - **Covered by:** R3-R8, R17-R18。

- F3. **处理连接或能力失败**
  - **Trigger:** 配置校验或供应商调用发现参数、鉴权、能力或服务错误。
  - **Actors:** A1, A2, A3, A4。
  - **Steps:** 保留原有有效配置；显示与错误类别对应的安全提示；不自动关闭工具、不静默切换供应商、不暴露密钥。
  - **Outcome:** 用户知道需要修改哪一类配置，运行时不会把可修复的兼容性问题伪装成普通服务不可用。
  - **Covered by:** R12, R14-R16。

### Acceptance Examples

- AE1. **Issue #27 DeepSeek regression**
  - **Given:** 用户选择 DeepSeek，配置有效 API Key 和模型，并启用 Customer-Agent 工具。
  - **When:** 运行一次 mock 聊天请求。
  - **Then:** 最终供应商载荷不包含由旧火山引擎模型注入的 `logprobs: false`、`top_logprobs: 0` 或其他未被请求的供应商默认字段，且请求适配层不会因这些字段拒绝请求。
  - **Covers:** R5-R7, R17-R18。

- AE2. **Built-in provider routing**
  - **Given:** 用户分别选择六个内置供应商并输入对应模型名。
  - **When:** 运行 mock 请求。
  - **Then:** 每个请求使用其约定的 LiteLLM provider 路由，并保留用户填写的模型标识。
  - **Covers:** R1-R3, R17-R18。

- AE3. **Custom OpenAI-compatible endpoint**
  - **Given:** 用户选择 OpenAI-compatible，填写任意模型名、自定义 Base URL 和 API Key。
  - **Precondition:** 所选 profile 已通过能力门槛和端点信任校验；若工具能力或端点信任为未知，当前 provider、原始模型名、规范化 Base URL、trust mode 和 active tool policy 的确认指纹必须有效。
  - **When:** 运行 mock 请求并附带工具定义。
  - **Then:** 请求通过 OpenAI-compatible 路由发送到用户提供的端点，不要求模型名带有其他内置供应商前缀，也不携带不相关的供应商默认字段。
  - **Covers:** R2, R4-R6, R17-R18。

- AE4. **Known unsupported tool model**
  - **Given:** LiteLLM 或供应商能力信息明确表明所选模型不支持工具调用。
  - **When:** 用户保存或启用配置。
  - **Then:** 保存/启用被阻止，提示包含所选供应商和模型名，并且原有活动配置保持不变。
  - **Covers:** R12-R14, R18。

- AE5. **Unknown tool capability**
  - **Given:** 所选模型的工具调用能力无法从现有能力信息确认。
  - **When:** 用户保存或启用配置。
  - **Then:** UI 明确显示未验证状态并要求用户确认风险，应用不会把该模型标记为已验证支持，也不会静默移除工具定义。
  - **Covers:** R13, R15, R18。

- AE6. **Existing configuration migration**
  - **Given:** 配置文件只有旧的模型名、API Key 和 Base URL，没有供应商身份。
  - **When:** 应用加载并迁移配置。
  - **Then:** 历史火山引擎默认地址迁移为火山引擎，其他无法识别的自定义地址迁移为 OpenAI-compatible，模型名、地址和密钥值保持可用。
  - **Covers:** R9-R12, R18。

- AE7. **Supported tool workflow**
  - **Given:** 所选模型已确认支持工具调用。
  - **When:** LLM 返回一个或多个工具调用。
  - **Then:** Customer-Agent 保留 assistant 工具调用消息，执行现有工具并继续多轮请求，最终返回文本回复。
  - **Covers:** R8, R17-R18。

### Success Criteria

- 六个内置供应商和任意 OpenAI-compatible 端点都能通过统一设置流程完成配置，并在无需环境变量的情况下进入运行时。
- Mock 契约测试能够在不使用真实 API Key 的情况下证明 provider 路由、便携请求字段、工具调用适配和配置迁移结果。
- Issue #27 的 DeepSeek 请求不再因旧的非空 provider 默认字段触发 400 类参数错误。
- 已知不支持工具调用的模型不能成为活动配置，未知能力不会被伪装为已验证支持。
- API Key 的加密存储、日志脱敏和现有 Customer-Agent 工具循环回归测试保持通过。

### Scope Boundaries

**In scope**

- LiteLLM Python SDK 作为应用内聊天传输层。
- 六个内置供应商的设置选项、路由映射、模型名、API Key 和 Base URL 配置。
- 便携请求边界、Issue #27 回归修复、工具能力启用门槛、旧配置迁移、端点信任校验、既有 ProductSync 兼容迁移和 mock 契约测试。

**Deferred for later**

- 模型自动发现、在线模型列表和模型推荐。
- 多个连接档案、运行时模型切换和供应商 fallback 编排。
- LiteLLM 能力矩阵的全面维护，以及除当前客服聊天所需能力之外的 embeddings、images、audio 或 Responses API。
- 运行中账号的紧急凭据撤销、全局停用和账号排空协调器；本次仅明确旧快照的重启生效边界。

**Outside this product's identity**

- 独立 LiteLLM Proxy/Gateway 服务、虚拟密钥、团队计费和集中式供应商管理。

### Dependencies / Assumptions

- LiteLLM 在实施时仍提供本计划所列 provider 路由；规划阶段需要固定一个与 Python 3.11+ 和现有依赖兼容的版本，并以该版本的行为为验收基线。
- LiteLLM 统一了请求和响应形状，但不能保证每个供应商的模型都支持工具调用或所有高级参数；能力门槛必须保留“未知”状态。
- 用户提供的 Base URL 遵循所选供应商或 OpenAI-compatible 端点的要求；应用不根据 URL 猜测供应商，也不擅自拼接未知路径。
- 测试环境不使用真实供应商凭据或真实付费请求；需要真实端到端验证时由维护者在本地提供凭据。

### Outstanding Questions

**Resolve Before Planning**

- None.

**Planning Questions (resolved below)**

- The items listed below are resolved by the Planning Contract and implementation units that follow; they are retained as traceability to the upstream requirements, not as open blockers.

- 选择 LiteLLM 同步/异步调用与现有 asyncio 生命周期的衔接方式。
- 确定“支持 / 不支持 / 未知”能力结果的具体来源，以及未知状态的确认交互如何复用现有设置保存流程。
- 确定旧配置迁移的精确版本标记、历史默认地址识别规则和失败回滚行为。
- 确定 LiteLLM 错误分类到设置页提示和运行时安全反馈的映射方式。
- 确定依赖锁定策略，并验证 LiteLLM 对当前 Python、PyInstaller 打包和 Windows 运行环境的兼容性。

### Sources / Research

- GitHub Issue #27: [反馈下 bug 使用 DEEPSEEK API 后无法正常使用的问题](https://github.com/JC0v0/Customer-Agent/issues/27)。
- Existing request path: `Agent/CustomerAgent/custom/llm_client.py`, `utils/volcengine_models.py`。
- Existing configuration and UI: `config.py`, `Agent/CustomerAgent/custom/agent_config.py`, `ui/setting_ui.py`。
- Existing regression style: `tests/test_regressions.py`。
- LiteLLM provider documentation: [DeepSeek](https://docs.litellm.ai/docs/providers/deepseek), [Volcano Engine](https://docs.litellm.ai/docs/providers/volcano), [Moonshot/Kimi](https://docs.litellm.ai/docs/providers/moonshot), [Z.AI/Zhipu](https://docs.litellm.ai/docs/providers/zai), [DashScope/Qwen](https://docs.litellm.ai/docs/providers/dashscope), [OpenAI-compatible endpoints](https://docs.litellm.ai/docs/providers/openai_compatible)。

## Planning Contract

Product Contract preservation: unchanged. R1-R19, A1-A4, F1-F3, and AE1-AE7 remain the acceptance authority; the sections below resolve the former planning questions and add implementation detail only.

### Resolved Planning Questions

- **Async boundary:** use LiteLLM's direct asynchronous SDK entry point behind a shared provider transport. "Agent/CustomerAgent/custom/llm_client.py" remains the async boundary consumed by "CustomerAgent"; no LiteLLM Proxy, environment-variable configuration, or synchronous call wrapped in a worker is introduced.
- **Capability source:** implement `resolve_tool_capability(profile) -> supported|unsupported|unknown` with this order: app-owned explicit overrides, the pinned LiteLLM capability/model metadata available locally, then "unknown". An override matches provider, raw model name, normalized Base URL, and tool policy exactly; only an explicit boolean capability result is authoritative, while missing or failed metadata remains "unknown". Do not make a paid or credentialed network request while saving settings. Custom OpenAI-compatible models default to "unknown" unless the pinned metadata or an explicit override proves otherwise.
- **Confirmation binding:** an unknown-capability confirmation is bound to provider, raw model name, normalized Base URL, and the active tool policy. Any change invalidates the confirmation. Runtime initialization re-runs the same resolver so editing JSON cannot bypass a known-unsupported block.
- **Base URL and endpoint trust:** a built-in provider with no user override stores an empty Base URL and omits `api_base` so LiteLLM uses its provider default; an explicit override is preserved and passed unchanged. OpenAI-compatible requires a user-provided Base URL. Before the SDK call, require an absolute HTTPS URL with certificate verification for remote endpoints; allow localhost/private endpoints only after an explicit user opt-in, reject embedded URL credentials and metadata/link-local targets, and disable cross-host redirects. The endpoint trust mode and side-effecting-tool authorization are part of the profile-bound confirmation fingerprint; custom or unverified endpoints cannot authorize tools outside the existing registry.
- **Migration:** add an explicit provider identity to fresh defaults and during config load, before "ConfigModel" validation. Track provider/schema migration as a dirty change. Historical Ark/Volcengine URLs used by this repository, including the current "/api/plan/v3" and UI "/api/v3" forms, map to "volcengine"; any other existing custom Base URL maps to "openai". Model name, endpoint, and decrypted key are preserved, and the migrated file is rewritten atomically only after validation succeeds.
- **Activation boundary:** a saved profile is immutable for an already initialized account agent. A successful save is adopted by the next initialization/restart; the UI shows a pending-restart state and names the existing account stop/restart action needed to apply it. This avoids mutating credentials or provider routing in an in-flight async loop and avoids a new account-drain workflow. Emergency revocation and global disable remain deferred; the UI must not imply that replacing a key stops an already running snapshot.
- **Shared consumers:** add one immutable `get_active_llm_profile()` accessor. "database/product_sync.py" captures that validated snapshot once per synchronization run and uses the same provider route and transport boundary because it reads the global "llm" configuration. Its existing multimodal message shape and JSON extraction behavior remain intact; "response_format" is an operation-level option for this consumer and is not added to the normal tool-loop request.
- **Transactional persistence:** a false return from `Config.save()` is a save failure, not success. `Config.atomic_update()` restores both `_config` and `_validated_config` and leaves the previous file untouched on validation, secret-protection, or write failure; provider/schema migration is persisted only after the validated rewrite succeeds.
- **Error contract:** define one `LLMErrorCategory` with authentication, rate-limit, parameter, tool-capability, provider, and generic categories, plus a deterministic precedence for overlapping LiteLLM exceptions. Each category owns a sanitized user message and recovery hint; the same mapping is consumed by settings, CustomerAgent, and ProductSync while logs contain category/type and bounded metadata only.
- **Dependency posture:** pin "litellm==1.96.2" as the implementation baseline because the official GitHub release and PyPI artifact were verified during planning; verify the wheel/hash and official release reference before locking. Do not install a floating or PyPI-only version. If the artifact cannot be provenance-checked, stop dependency work before changing runtime code.

These decisions close the upstream planning questions; implementation should only verify their concrete package and UI details, not reopen the product scope.

### Key Technical Decisions

1. **KTD1 - Shared async LiteLLM transport.** Put provider routing, request construction, LiteLLM invocation, response normalization, and safe error classification behind a reusable transport module. Keep "LLMClient" as the CustomerAgent-facing wrapper and keep its "LLMResponse" contract. This removes the current Volcengine-specific Pydantic request boundary while preserving the existing async lifecycle. Governs R3, R8, R16-R18.

2. **KTD2 - Explicit provider registry.** Persist a provider enum/identity and map it through a single registry: DeepSeek -> "deepseek/", Volcengine -> "volcengine/", OpenAI-compatible -> "openai/", Kimi -> "moonshot/", Zhipu/Z.AI -> "zai/", and Qwen -> "dashscope/". The registry owns the prefix and Base URL policy; model names are never guessed from URLs, and Base URLs are never used to select a provider. Governs R1-R4, R9-R10.

3. **KTD3 - Portable request builder.** （session-settled: user-directed — chosen over only removing the two reported defaults because it prevents the same provider-default leakage from recurring） Build the normal CustomerAgent request from only "model", "messages", "temperature", and, when tools exist, "tools" plus "tool_choice". Do not pass "logprobs", "top_logprobs", or other provider defaults unless an operation explicitly requires a verified supported option. Preserve operation-level "response_format" and multimodal content only for product extraction. Governs R5-R7 and R17.

4. **KTD4 - Three-state capability classifier.** （session-settled: user-approved — chosen over allowing unsupported models to activate because it prevents silent runtime failure） Represent capability as "supported", "unsupported", or "unknown". Known unsupported models block save/enable; unknown models show risk and require a current-profile human confirmation; no state silently removes tools or downgrades to text-only mode. The same policy object is called by the UI and runtime. Governs R12-R16.

5. **KTD5 - Profile snapshot and atomic persistence.** Validate and migrate a complete profile before saving. Preserve the last valid persisted profile on any failure, preserve DPAPI API-key protection, and snapshot the validated profile into each initialized agent/client. Provider identity, model, and endpoint are non-secret configuration; keys remain secret. Governs R9-R12 and F1/F3.

6. **KTD6 - Shared response and error semantics.** Normalize LiteLLM/OpenAI-shaped responses into the existing assistant content/tool-call representation, preserving tool-call IDs, function names, arguments, assistant/tool message order, and usage metadata where available. Translate authentication, rate-limit, provider-parameter, tool-capability, and generic API failures into safe categories; logs contain type/category and bounded metadata, never raw key or exception text. Governs R8, R16, and AE7.

7. **KTD7 - Reproducible desktop dependency.** Add LiteLLM without the Proxy extra, lock the exact verified version and transitive hashes in "uv.lock", and treat clean import plus Windows/PyInstaller startup as dependency gates. The build spec is updated only for imports proven to be omitted by the clean packaged build. Governs R19 and the Windows delivery boundary.

### Alternatives Considered

- **Only remove "logprobs" and "top_logprobs":** rejected because the current Volcengine-shaped schema still injects other non-portable defaults and leaves provider selection implicit.
- **Keep "AsyncOpenAI" and add provider-specific branches:** rejected because the app would continue to own routing, payload filtering, and response differences for every provider.
- **Run LiteLLM Proxy locally:** rejected because it adds a service lifecycle, configuration surface, and packaging burden outside this desktop application's identity.
- **Call every endpoint during save to discover capabilities:** rejected because it spends credentials/possibly money, is unreliable for custom endpoints, and makes saving a network operation. Unknown capability therefore uses explicit confirmation.

### High-Level Technical Design

~~~mermaid
flowchart LR
    UI[Settings UI] --> STORE[Config manager]
    STORE --> MIGRATE[Legacy migration]
    MIGRATE --> VALIDATE[Profile validator]
    VALIDATE --> CAP[Capability resolver]
    CAP --> GATE{supported / unknown confirmed?}
    GATE -- no --> KEEP[Keep last valid profile]
    GATE -- yes --> SNAP[Immutable runtime profile]
    SNAP --> AGENT[CustomerAgent LLMClient]
    SNAP --> SYNC[ProductSyncService]
    AGENT --> TRANSPORT[Shared LiteLLM transport]
    SYNC --> TRANSPORT
    TRANSPORT --> ROUTE[Explicit provider registry]
    ROUTE --> LITELLM[LiteLLM async SDK]
    LITELLM --> PROVIDER[Selected provider endpoint]
    PROVIDER --> NORMALIZE[Response/error normalization]
    NORMALIZE --> LOOP[Existing message + tool loop]
    LOOP --> TOOLS[Existing ToolExecutor]
    TOOLS --> LOOP
~~~

The configuration path produces one validated profile and one capability result through explicit states: checking, supported, unsupported, or unknown-confirmation. Canceling an unknown-capability confirmation leaves the last valid profile active and keeps the edited profile unconfirmed. The runtime path snapshots that profile per initialized account agent and never reads provider identity from customer text or model output. The CustomerAgent path sends tool definitions only when the per-call tool policy allows them, then feeds normalized assistant tool calls into the unchanged bounded loop. The product-sync path captures the same profile once per run and sends its existing text/image content and JSON extraction option without tool definitions. Before either call, the endpoint trust policy validates the destination and redirect behavior. All failure paths return categorized safe feedback and leave the last valid profile untouched.

### System-Wide Impact

- **Configuration schema:** "llm.provider" and a profile-bound unknown-capability confirmation are added; legacy files without provider identity remain loadable through deterministic migration.
- **Settings UI:** the current three text fields become a provider-aware form. Volcengine is no longer the implicit default for every endpoint; OpenAI-compatible requires a Base URL, while built-in providers may use their LiteLLM default or an explicit override.
- **Runtime:** "CustomerAgent" and product knowledge extraction share routing and authentication behavior. Existing "MessageBuilder", "SessionManager", "ToolExecutor", tool registry, session persistence, loop limit, and per-account isolation remain the behavioral contract.
- **Activation:** saving a new valid profile does not mutate already running clients. The UI shows the active snapshot/pending-restart distinction and points to the existing stop/restart action; no new live account-drain coordinator or emergency revocation path is introduced.
- **Security:** the selected endpoint is an explicit outbound trust boundary. Remote endpoints require HTTPS and certificate verification; localhost/private endpoints require explicit opt-in; embedded credentials, metadata/link-local targets, and cross-host redirects are rejected. Never log the key, and never let model/customer content alter provider, Base URL, credentials, or trust mode.
- **Data sharing:** outbound payloads are limited to the existing CustomerAgent messages, approved tool schemas/results, and ProductSync text/image content plus its JSON response option. API keys, authorization headers, session cookies, internal profile fields, and unrelated customer identifiers never enter prompts, provider errors, or logs; README documents that provider-side retention is controlled by the selected provider/custom endpoint.
- **Packaging:** LiteLLM's import graph and provider modules become part of the Windows onedir artifact. The build workflow must prove clean import, application startup, and provider adapter availability from the packaged artifact.
- **Agent-native parity:** settings and API-key entry remain human-only. No agent/tool/MCP surface is added; verification is focused on preserving the existing CustomerAgent tool-loop behavior across provider routes.

### Risks & Dependencies

| Risk / dependency | Mitigation | Verification evidence |
|---|---|---|
| LiteLLM release/provenance or transitive dependency churn | Pin the verified official release, lock hashes, avoid Proxy extras, and fail the dependency gate on provenance mismatch | Clean "uv sync", import smoke, lock diff review, packaged startup |
| Provider prefix or Base URL behavior changes | Centralize six route mappings and never infer provider from URL/model | Six-provider mock matrix plus custom endpoint contract |
| Provider/model capability metadata is incomplete or stale | Treat null/missing metadata as "unknown"; only explicit local/metadata results can be known | Supported/unsupported/unknown tests through UI and runtime |
| LiteLLM tool-call normalization loses IDs or message order | Normalize at one boundary and assert assistant/tool transcript shape | Multi-round mock CustomerAgent loop with tool result IDs |
| Custom endpoint receives an API key unexpectedly | Apply the canonical endpoint trust policy, make endpoint/trust mode visible in confirmation, redact all secrets, and require explicit activation for unknown capability | HTTPS/redirect/private-host negative tests, redaction, and endpoint-bound confirmation tests |
| Settings save races with an in-flight account request | Snapshot profile at initialization; show pending restart and apply only on the existing stop/restart path | Save-during-request test, stale-snapshot UI test, and two-account isolation test |
| Config save returns false after in-memory update | Treat false save results as failure and restore both in-memory snapshots before reporting failure | Forced-save-failure rollback test and persisted-file comparison |
| Provider data crosses a new trust boundary | Keep outbound fields to the existing chat/product extraction payload; exclude keys, headers, cookies, internal profile data, and unrelated identifiers | Payload allowlist, log-sentinel, and README data-sharing checks |
| Product extraction rejects multimodal or JSON options | Keep operation-specific options in the shared adapter and preserve existing fallback-to-basic-info behavior | ProductSync mock with image content, JSON response, malformed JSON, and provider error |
| PyInstaller omits LiteLLM provider modules | Add only verified hidden imports/hooks after a clean Windows build demonstrates the gap | CI compile/unittest gate plus Windows onedir launch smoke |

### Research Basis

- **Repository evidence:** "config.py" already provides Pydantic validation, atomic save, DPAPI secret protection, and reload fallback; "ui/setting_ui.py" currently hard-codes Volcengine defaults; "Agent/CustomerAgent/custom/llm_client.py" validates through "utils/volcengine_models.py"; "database/product_sync.py" is a second direct AsyncOpenAI consumer of "llm.*"; ".github/workflows/build-windows.yml" uses uv sync, compileall, unittest discovery, and the Windows PyInstaller script.
- **Project guidance:** "README.md" and "CLAUDE.md" require uv-managed dependencies, Python 3.11+, mock-first API verification, and Windows packaging validation.
- **Official LiteLLM guidance:** direct Python SDK integration, provider-prefixed model routing, OpenAI-shaped response normalization, and typed exception mapping are documented at [LiteLLM Getting Started](https://docs.litellm.ai/), with provider-specific behavior in the provider links already captured above.
- **Release and supply-chain constraint:** [LiteLLM v1.96.2](https://github.com/BerriAI/litellm/releases/tag/v1.96.2) is a signed official release; [PyPI metadata](https://pypi.org/project/litellm/) provides the Python 3.10+ wheel line. The official [LiteLLM security issue](https://github.com/BerriAI/litellm/issues/24518) records compromised PyPI versions and recommends exact pins plus release verification; this is why the plan requires a verified release/hash rather than a floating latest dependency.

## Implementation Units

### U1. Configuration profile, migration, and capability policy

**Goal:** Establish one validated, backward-compatible LLM profile and one reusable capability policy before changing transport or UI behavior.

**Requirements:** R1-R2, R9-R15, R19. Actors A1-A2. Flows F1 and F3. Acceptance examples AE4-AE6.

**Dependencies:** None.

**Files:**

- "config.py"
- "Agent/CustomerAgent/custom/agent_config.py"
- "utils/llm_provider.py" (new shared provider registry and capability policy)
- "tests/test_llm_config.py" (new)

**Approach:**

1. Add explicit provider identity and profile-bound capability confirmation to the typed configuration model while keeping API-key protection focused on "api_key".
2. Perform legacy provider inference in the config load/migration boundary before typed validation. Map repository Ark/Volcengine defaults to "volcengine"; map unrecognized existing custom URLs to "openai"; preserve all three existing connection values.
3. Make the provider registry the only source for display label, LiteLLM prefix, Base URL requirement/default policy, endpoint trust policy, and capability lookup order. Store an empty Base URL for built-in defaults and preserve only explicit user overrides.
4. Validate provider, model, key, URL/trust requirements, capability state, and confirmation fingerprint as one transaction. Treat a false `Config.save()` result as failure; restore both `_config` and `_validated_config` and leave the previous file untouched.
5. Implement the exact tri-state resolver contract: explicit overrides match provider/raw model/normalized Base URL/tool policy; metadata must provide an explicit boolean; absent or failed metadata is unknown. Make known unsupported models fail closed both from UI-originated saves and direct runtime config loads.
6. Track fresh-schema/provider migration as a dirty change and persist it only after typed validation, secret protection, and atomic replacement all succeed.
7. For custom or unverified endpoints, require explicit endpoint/tool trust confirmation before side-effecting tools run; preserve the existing ToolExecutor identity checks and reject tool names outside the existing registry.

**Patterns to follow:** "Config._load_config", "Config.reload", "Config.update", "Config.atomic_update", "_protect_secrets", "_restore_secrets", and "AgentConfig.load_from_config".

**Test scenarios:**

- **AE6:** Load a legacy config with the current Ark "/api/plan/v3" URL and with an arbitrary custom URL; assert provider mapping, model/base/key preservation, and encrypted key persistence.
- **AE4:** Submit a known unsupported provider/model; assert validation fails and the previous valid profile remains active.
- **AE5:** Submit an unknown provider/model/base combination; assert no verified-support label is produced, confirmation is required, and a confirmation for a different fingerprint is rejected.
- A canceled or closed unknown-capability confirmation leaves the last valid profile active, retains edits only as an unconfirmed draft, and never calls the persistence path.
- Switching providers preserves non-empty user-entered model, key, and endpoint values; built-in default guidance changes without overwriting an explicit endpoint override.
- Invalid/missing provider, model, key, or required custom Base URL must fail without partially updating the profile.
- Provider/model/base values never appear in secret-protection output as API keys, and the raw API key remains protected at rest.

**Verification:** The config test suite proves deterministic migration, atomic rollback, capability-state semantics, and secret preservation without importing a provider SDK or using credentials.

### U2. Portable LiteLLM transport and response contract

**Goal:** Replace the Volcengine-specific request validation path with a shared async LiteLLM adapter that serves both runtime consumers.

**Requirements:** R3-R8, R16-R18. Actors A3-A4. Flow F2. Acceptance examples AE1-AE3 and AE7.

**Dependencies:** U1.

**Files:**

- "utils/llm_transport.py" (new shared async transport and request/error normalization)
- "Agent/CustomerAgent/custom/llm_client.py"
- "utils/volcengine_models.py" (remove after confirming no remaining consumers; current repository scan finds only the LLMClient import)
- "tests/test_llm_transport.py" (new)
- "tests/test_llm_client.py" (new)

**Approach:**

1. Accept the validated profile and an operation shape, then compose the explicit LiteLLM model route from the provider registry and the user's raw model name.
2. Run the endpoint trust preflight before passing "api_key": built-in defaults omit `api_base`, explicit overrides are passed unchanged, remote URLs require HTTPS/certificate verification, local/private URLs require explicit opt-in, and embedded credentials, metadata/link-local targets, and cross-host redirects are rejected. Do not populate environment variables, append "/v1", or guess a provider from the endpoint.
3. Build the normal chat payload with only portable fields. Add a per-call `use_tools` control; attach "tools" and "tool_choice" only when it is true. Keep "response_format" and multimodal content as explicit operation options for product extraction, not global defaults. Enforce the profile's endpoint/tool trust policy before allowing side-effecting tool calls.
4. Call the version-pinned async LiteLLM SDK and normalize object/dict response variants into the existing "LLMResponse" shape, preserving tool-call IDs, names, arguments, content, and usage where available.
5. Classify LiteLLM exceptions through one `LLMErrorCategory` mapping with deterministic precedence for authentication, rate-limit, parameter, tool-capability, provider, and generic failures. Return a sanitized recovery hint to callers and preserve only category/type and bounded metadata in logs.
6. Keep "LLMClient.initialize"/"close" compatible with the account lifecycle; no mutable global profile or cross-account client state is introduced.

**Patterns to follow:** the current "LLMClient.chat" request/response boundary, its content-length-only logging, "LLMResponse", and the repository's unittest.mock style.

**Test scenarios:**

- **AE1:** Mock the LiteLLM async call for DeepSeek with tools; assert the final payload has no "logprobs", "top_logprobs", or equivalent unsolicited defaults.
- **AE2:** For all six providers, assert the exact provider prefix, unchanged raw model identifier, explicit Base URL behavior, and API key passed only to the mocked transport.
- **AE3:** Use an arbitrary custom model and Base URL with tools; assert no built-in model prefix or unrelated provider field is added.
- **AE7:** Normalize a mock assistant response containing one or more tool calls and assert IDs, function names, JSON arguments, content, and usage survive unchanged.
- No-tool requests must set `use_tools=False` and omit both "tools" and "tool_choice"; product-extraction requests must preserve image content and scoped JSON response format without inheriting tool fields.
- Endpoint preflight rejects non-HTTPS remote URLs, embedded credentials, metadata/link-local targets, and cross-host redirects before the mocked call receives an API key; explicit localhost/private opt-in is covered separately.
- Authentication, rate-limit, provider-parameter, and tool-capability exceptions must produce distinct safe categories with no key or raw provider response in logs.

**Verification:** Contract tests inspect the exact call into LiteLLM, not an actual provider. They are the regression gate for Issue #27, all six routes, custom endpoints, portable payloads, and response normalization.

### U3. CustomerAgent and product-sync runtime integration

**Goal:** Adopt the validated profile in both existing LLM consumers while preserving agent behavior, product extraction behavior, and activation semantics.

**Requirements:** R3, R8, R12, R16-R18. Actors A3-A4. Flows F2-F3. Acceptance example AE7; product-sync coverage follows the Planning Contract's Shared consumers decision.

**Dependencies:** U1, U2.

**Files:**

- "Agent/CustomerAgent/custom/customer_agent.py"
- "database/product_sync.py"
- "tests/test_customer_agent_llm.py" (new)
- "tests/test_product_sync_llm.py" (new)

**Approach:**

1. Load one validated profile during "CustomerAgent" initialization, run the capability gate again, and pass an immutable profile snapshot into "LLMClient". Expose the same `get_active_llm_profile()` contract to other consumers.
2. Keep "_run_agent_loop" semantically unchanged: persist the assistant tool-call message, execute the existing tools, append tool results with their IDs, continue until final text or the existing loop limit, and preserve session history. Compression and other no-tool operations call `LLMClient.chat(use_tools=False)`.
3. Preserve per-account lifecycle isolation. A profile saved while a request is active does not mutate that client; a new/restarted agent reads the new profile. The UI shows the stale snapshot until the existing account stop/restart path is used. A failed initialization leaves the account inactive without changing the last valid saved profile.
4. Replace "ProductSyncService"'s direct "AsyncOpenAI" call with the shared transport operation, capturing one validated profile snapshot per synchronization run. Preserve text-plus-image content, "response_format" JSON extraction, malformed-JSON fallback, and basic-info fallback on provider failure.
5. Keep customer/catalog/knowledge data roles and trust handling unchanged; only the existing message/content, approved tool schema/result, and ProductSync image payloads may cross the provider boundary. Provider metadata, endpoint values, API keys, authorization headers, cookies, and unrelated identifiers never enter prompts, provider errors, session history, or logs.

**Patterns to follow:** "CustomerAgent._initialize_async_unlocked", "_run_agent_loop", "SessionManager" persistence, "ToolExecutor" parallel execution, and "ProductSyncService._extract_product_knowledge" cleanup/fallback behavior.

**Test scenarios:**

- **AE7:** Mock a provider response with a tool call followed by final text; assert the exact assistant/tool transcript, tool-call ID, tool execution, second model request, session persistence, and final reply.
- Run the no-tool path and context-compression/summary path separately; assert neither accidentally attaches tools or changes tool choice.
- Assert `ProductSyncService` captures one validated profile per run and cannot observe a mixed provider/key/base tuple during a concurrent settings save.
- Initialize two account-owned agents with different profile snapshots and issue concurrent mocked calls; assert routing, Base URL, and key arguments do not cross accounts.
- Save a new profile during an in-flight request; assert the current client finishes with its original snapshot and the next initialization uses the new profile.
- **Product sync:** preserve image message content, JSON response option, valid JSON parsing, malformed JSON passthrough, provider failure fallback, and missing-key basic-info behavior.
- **Data boundary:** sentinel keys, headers, cookies, internal profile fields, and unrelated customer identifiers never appear in the outbound payload, logs, or safe error text.
- **Custom endpoint tool trust:** a custom or unverified endpoint cannot execute a side-effecting tool without the explicit profile-bound trust confirmation, and unknown tool names are rejected before execution.
- Direct runtime initialization with known unsupported capability must fail closed even if UI validation is bypassed; unknown capability without matching confirmation must not start the tool-enabled agent.

**Verification:** Runtime tests prove agent-native parity and shared-consumer consistency, not merely a successful text completion.

### U4. Provider-aware settings UI and human feedback

**Goal:** Expose the six providers and capability decisions without duplicating or weakening shared validation.

**Requirements:** R1-R2, R10, R12-R16. Actors A1-A2. Flows F1 and F3. Acceptance examples AE2, AE4-AE6.

**Dependencies:** U1, U2; consumes U2's safe error/category vocabulary.

**Files:**

- "ui/setting_ui.py"
- "tests/test_setting_ui.py" (new; keep policy assertions headless where possible)

**Approach:**

1. Add a provider selector for DeepSeek, Volcengine, OpenAI-compatible, Kimi/Moonshot, Zhipu/Z.AI, and Qwen/DashScope; include provider in "getConfig"/"setConfig" and load/migration paths.
2. Stop forcing the Volcengine URL/model for every form. Show provider-aware placeholders/default guidance; require a Base URL for OpenAI-compatible and allow built-in defaults or user overrides for built-in providers. Preserve non-empty user-entered values when switching providers, and provide an explicit reset-to-provider-default action.
3. Route save/enable through the shared profile validator and atomic config update. Define checking, supported, unsupported, unknown-confirmation, and failure states; retain edits for correction, focus the first invalid field, and keep the last valid profile active on rejection. Display provider/model/endpoint context for validation failures without displaying the API key.
4. Block known unsupported capability, show explicit risk for unknown capability, and require confirmation tied to the current provider/model/Base URL, endpoint trust mode, and active tool policy. For custom or unverified endpoints, explicit tool-trust confirmation is required before side-effecting tools run. Only explicit Confirm permits save/enable; Cancel or close leaves the last valid profile active and the draft unconfirmed. Any fingerprint change invalidates confirmation. Never silently remove tools or switch provider.
5. Map U2's `LLMErrorCategory` values to safe user-facing messages and recovery actions for settings, CustomerAgent, and ProductSync; never display raw provider exceptions or credentials.
6. Tell the user when a successful save applies at the next agent initialization/restart, show the active-snapshot/pending-restart distinction, and point to the existing account stop/restart action; do not imply running agents changed in place.

**Patterns to follow:** "LLMConfigCard", "SettingUI.loadConfig", "_loadDefaultConfig", "_validateAndSetConfig", "onSaveConfig", "QMessageBox", and "InfoBar" usage.

**Test scenarios:**

- The provider selector exposes exactly the six in-scope options and round-trips provider/model/key/base values without replacing a custom endpoint.
- **AE4:** Known unsupported capability shows an actionable provider/model error, does not call "config.update", and leaves the prior UI/persisted profile intact.
- **AE5:** Unknown capability shows unverified status and confirmation; changing provider/model/base or the active tool policy after confirmation requires confirmation again.
- **AE6:** Loading a legacy config displays the migrated provider and preserves the existing connection fields.
- Provider changes preserve typed values and update default guidance; reset-to-default is explicit rather than implicit.
- Canceling or closing the unknown-capability confirmation keeps the prior profile active and leaves the edited draft unconfirmed.
- Required-field and malformed-endpoint failures retain edits, focus the first invalid field, and expose non-color status text with accessible names.
- Authentication, rate-limit, parameter, tool-capability, and provider failures show distinct safe recovery guidance without raw exception text.
- Custom or unverified endpoints require explicit tool-trust confirmation for side-effecting tools; changing the endpoint, tool policy, or provider invalidates that confirmation.
- API keys are never included in validation messages, error dialogs, InfoBar content, or diagnostic logs.

**Verification:** Headless policy tests cover serialization and rollback; a focused Windows UI smoke confirms the six options, unknown confirmation, and restart notice render correctly.

### U5. Dependency, packaging, documentation, and release regression

**Goal:** Make the new transport reproducible in development and in the packaged Windows application, and document the user-facing provider contract.

**Requirements:** R17-R19 and all Success Criteria. Flows F1-F3. Acceptance examples AE1-AE7 as release gates.

**Dependencies:** U1-U4.

**Files:**

- "pyproject.toml"
- "uv.lock"
- "scripts/agent_customer.spec"
- "README.md"
- "tests/test_regressions.py" (extend existing regression coverage where the shared test fixture is appropriate)

**Approach:**

1. Add the exact verified LiteLLM release baseline without Proxy extras and refresh the lockfile under Python 3.11-compatible resolution.
2. Run clean dependency/import checks before adding packaging hints. If the PyInstaller artifact misses provider modules, add the narrowest verified hidden-import or hook entry and document why it is needed.
3. Update README configuration guidance with the provider table, route/base URL rules, OpenAI-compatible arbitrary model behavior, required API-key entry in Settings, capability warning/confirmation, endpoint HTTPS/local opt-in policy, migration behavior, restart activation semantics, and provider data-sharing/retention responsibility. Never include real keys, require environment variables, or imply that provider-side retention is controlled by the app.
4. Extend the repository's existing unittest/compileall regression gate and Windows build workflow expectations; no live provider credentials enter CI.

**Patterns to follow:** "pyproject.toml" plus "uv.lock", ".github/workflows/build-windows.yml", "scripts/build_win_exe.py", "scripts/agent_customer.spec", and current "tests/test_regressions.py".

**Test scenarios:**

- Clean Python 3.11 "uv sync" resolves the exact lock and imports the shared transport without provider credentials.
- The full repository compile/unittest gate passes with no live network call or secret fixture.
- A clean Windows onedir build starts the packaged app and imports the LiteLLM transport/provider registry; the artifact contains no test credentials.
- README examples match the six provider routes, required/optional Base URL rules, migration behavior, and restart semantics.
- README explicitly tells users to enter an API Key in Settings, while examples contain no real keys and do not require environment variables; it also explains endpoint trust and provider-side data retention.

**Verification:** CI and local release checks provide installation, regression, and packaging evidence; live provider smoke tests remain a separately authorized manual check.

## Verification Contract

### Traceability Matrix

| Contract | Implementation units | Primary evidence |
|---|---|---|
| R1-R2 | U1, U4 | Provider selector/config model round-trip and required-field tests |
| R3-R4 | U2, U3 | Direct async LiteLLM call contract and six-route/custom-endpoint matrix |
| R5-R7 | U2 | Portable payload assertions and Issue #27 DeepSeek regression |
| R8 | U2, U3 | Response normalization and multi-round tool-loop transcript |
| R9-R12 | U1, U3, U4 | Migration, DPAPI, atomic rollback, profile snapshot, and restart tests |
| R13-R16 | U1, U3, U4 | Three-state capability tests, safe error categories, no silent downgrade/fallback |
| R17-R18 | U2-U5 | Mock contract matrix, runtime parity, shared-consumer contract, full regression gate |
| R19 | U5 | Exact lock, clean sync/import, and Windows packaged startup |

### Automated Gates

1. **Configuration gate:** migration/provider persistence, provider validation, profile-bound confirmation, false-save rollback, and API-key-at-rest tests pass without credentials.
2. **Transport contract gate:** all six provider routes, custom OpenAI-compatible model/base, endpoint trust policy, portable field omission, per-call tool policy, scoped operation options, deterministic exception categorization, and response normalization pass with mocked LiteLLM.
3. **Agent parity gate:** existing CustomerAgent tool loop, multi-round tool results, session persistence, no-tool path, compression path, loop limit, and per-account profile isolation pass.
4. **Product extraction gate:** text/image input, JSON response option, malformed JSON behavior, provider error fallback, and no-key fallback pass.
5. **UI/policy gate:** six choices, provider-switch/default behavior, required-field states, known unsupported block, unknown confirmation cancel/invalidation, safe recovery feedback, endpoint trust messaging, and restart notice pass.
6. **Repository regression gate:** existing compileall and unittest discovery checks pass; no existing regression loses coverage.
7. **Dependency gate:** clean Python 3.11 "uv sync", exact LiteLLM lock/provenance check, import smoke, and no Proxy extra pass.
8. **Windows packaging gate:** clean PyInstaller onedir build and application startup pass on the repository's Windows workflow; provider modules are available from the packaged artifact.

### Manual / Authorized Checks

- With user-supplied staging credentials only, exercise one supported tool-capable model for each built-in provider and one custom OpenAI-compatible endpoint. Record route, Base URL, tool-call response, and safe error behavior; never commit keys or provider payloads containing secrets.
- Confirm that saving a new profile while an account is running leaves the current account unchanged until its next initialization/restart, and that the UI wording matches the actual behavior.
- With a non-secret sentinel payload, verify remote HTTPS enforcement, explicit localhost/private opt-in, redirect rejection, and outbound-field minimization before any credentialed smoke test.

### Quality Gates

- Every R-ID has an implementation unit and observable verification evidence.
- Every feature-bearing unit has concrete happy-path, failure-path, and integration test scenarios.
- No provider is selected by URL/model guessing; no API key is logged, persisted in plaintext, sent to an unintended endpoint, or exposed in user-facing error text.
- Remote endpoints use HTTPS with certificate verification; local/private endpoints require explicit opt-in; embedded credentials, metadata/link-local targets, and cross-host redirects are rejected.
- Outbound payloads contain only the existing operation fields; API keys, authorization headers, cookies, internal profiles, and unrelated identifiers are excluded from prompts, logs, and provider errors.
- Known unsupported capability is fail-closed; unknown capability is visibly unverified and human-confirmed; no tools are silently removed.
- No generic CustomerAgent transport path imports or instantiates the old Volcengine request schema.
- Existing session, tool, trust-boundary, and per-account lifecycle behavior remains intact.

## Definition of Done

- "llm.provider" is explicit for new and migrated configurations; all six provider options and arbitrary OpenAI-compatible model/base combinations work through one direct LiteLLM adapter.
- Issue #27's DeepSeek request no longer receives legacy non-portable defaults such as "logprobs: false" or "top_logprobs: 0".
- The same validated profile/capability policy is enforced by settings, CustomerAgent initialization, and product-sync transport; UI-only validation is not the security boundary.
- `ProductSyncService` is an existing-consumer compatibility path, not a new product capability; its profile snapshot, multimodal/JSON behavior, and fallback semantics are covered by the same transport contract.
- Save failures, including a false persistence result, preserve both the last valid file and in-memory profile.
- Unknown-capability confirmation requires an exact current profile/tool-policy/trust-mode fingerprint; cancel leaves the prior profile active and the draft unconfirmed.
- Existing CustomerAgent tool calls, tool results, session context, multi-round loop, and per-account isolation are behaviorally unchanged across the normalized transport.
- Product knowledge extraction retains its text/image input, JSON parsing, malformed-output behavior, and basic-info fallback while adopting explicit provider routing.
- Failed saves, migrations, capability checks, and runtime initialization preserve the last valid profile and do not mutate already running clients.
- API keys remain DPAPI-protected at rest and absent from logs, prompts, sessions, UI diagnostics, exceptions, tests, and packaged artifacts.
- The old Volcengine-specific request schema is no longer reachable from generic LLM transport; remove "utils/volcengine_models.py" once the repository reference scan confirms no remaining consumer.
- The exact verified LiteLLM release is present in "pyproject.toml"/"uv.lock", installs on Python 3.11, imports cleanly, and is included in a successful Windows packaged startup.
- README and release verification describe provider routes, Base URL rules, capability confirmation, migration, restart semantics, and the no-credentials-in-CI policy.
- All automated gates in the Verification Contract pass, with any authorized live-provider checks recorded separately and no secrets committed.
