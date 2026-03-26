# MCP Server Evaluation: Task API as MCP vs Alternative Technologies

**Document Version:** 1.0  
**Date:** 2026-01-01  
**Task:** TASK-120  
**Prepared by:** opencode

---

## Executive Summary

This document evaluates whether to implement the Task API as a Model Context Protocol (MCP) server or use alternative task management technologies. After comprehensive analysis of MCP capabilities, existing tools (Jira, Asana, GitHub Projects, Linear, Notion, Taskwarrior, Kanboard), and current custom REST API implementation, the recommendation is to **keep the current custom REST API while planning a future hybrid MCP adapter layer**.

**Key Finding:** MCP is promising for LLM-native integrations but remains immature for production use. Existing commercial tools are too heavyweight for hobbyist projects, while open-source alternatives lack agent-specific features like claiming and heartbeats.

---

## Table of Contents

1. [MCP Overview and Capabilities](#1-mcp-overview-and-capabilities)
2. [Existing Tools Comparison](#2-existing-tools-comparison)
3. [Capability Matrix](#3-capability-matrix)
4. [Cost/Benefit Analysis](#4-costbenefit-analysis)
5. [Recommended Approach](#5-recommended-approach)
6. [Implementation Estimates](#6-implementation-effort-estimates)
7. [Migration Strategy](#7-migration-strategy)
8. [Hybrid Approaches](#8-hybrid-approaches)

---

## 1. MCP Overview and Capabilities

### 1.1 What is MCP?

The **Model Context Protocol (MCP)** is an open standard introduced by Anthropic in November 2024 for connecting AI assistants to external data and services. MCP acts as a bridge between LLMs and the outside world, enabling agents to access real-time data and perform actions.

**Key Characteristics:**
- **Open Standard:** Community-driven specification, not vendor-locked
- **LLM-Native:** Designed specifically for AI agent workflows
- **Structured Communication:** Uses JSON-RPC 2.0 over multiple transports (stdio, SSE, HTTP)
- **Layered Architecture:** Tools (actions), Resources (data access), Prompts (templates)

### 1.2 MCP Architecture

```
┌─────────────────────────────────────┐
│     Application Layer               │
│  (Tools, Resources, Prompts)        │
├─────────────────────────────────────┤
│     MCP Protocol Layer             │
│  (Message Routing, Lifecycle)       │
├─────────────────────────────────────┤
│     JSON-RPC 2.0 Layer             │
│  (Message Format, RPC Semantics)    │
├─────────────────────────────────────┤
│     Transport Layer                 │
│  (stdio, SSE, WebSocket, HTTP)      │
└─────────────────────────────────────┘
```

### 1.3 MCP Server Implementation

MCP servers can be implemented in Python using the FastMCP framework:

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Task Server", json_response=True)

@mcp.tool()
def list_tasks() -> list[dict]:
    """List all available tasks."""
    return [{"id": "TASK-120", "title": "..."}]

@mcp.tool()
def claim_task(task_id: str, agent_name: str) -> dict:
    """Claim a task for an agent."""
    return {"status": "claimed", "task_id": task_id}

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

### 1.4 MCP Benefits for Task Management

**Advantages:**
- **Native LLM Integration:** Built specifically for AI agents, no translation layer needed
- **Tool Invocation Pattern:** LLMs can discover and call task management functions directly
- **Structured Context:** Tools and resources expose schema that LLMs understand
- **Bidirectional Communication:** Supports real-time streaming (SSE) and async operations
- **Multiple Transports:** Works with CLI (stdio), web apps (SSE/HTTP), and desktop clients

**Disadvantages:**
- **Immature Ecosystem:** Introduced Nov 2024, limited production adoption
- **Limited UI Support:** Most MCP clients are AI-native (Claude Desktop, Cursor), not human-centric
- **Documentation Gaps:** Many examples are incomplete or educational only
- **Learning Curve:** New protocol, new tools, different mental model than REST APIs
- **Tool Discovery Complexity:** LLMs must understand tool signatures and parameter constraints

### 1.5 Existing MCP Task Servers

Research found several MCP task server implementations, all are early-stage or educational:

| Project | Stars | Status | Features | Notes |
|---------|-------|--------|----------|-------|
| [tradesdontlie/task-manager-mcp](https://glama.ai/mcp/servers/@tradesdontlie/task-manager-mcp) | 25 | Active | Projects, PRD parsing, task tracking | Template implementation, educational focus |
| [milkosten/task-mcp-server](https://github.com/milkosten/task-mcp-server) | 11 | Active | Multi-transport (stdio/HTTP), external API wrapper | Connects to external task API, not standalone |
| [idsulik/todo-mcp-server](https://github.com/idsulik/todo-mcp-server) | Unknown | 2025-04 | Basic todo CRUD | Minimal implementation, no advanced features |
| [RegiByte/todo-list-mcp](https://github.com/regibyte/todo-list-mcp) | Unknown | Educational | Simple todo management | Created for educational purposes |
| [tkc/tinyt-todo-mcp](https://github.com/tkc/tinyt-todo-mcp) | Unknown | 2025-03 | Persistent task storage | Focuses on context persistence for LLMs |

**Key Observation:** No production-grade MCP task servers exist yet. All implementations are simple CRUD without advanced features like dependencies, heartbeats, or agent coordination.

### 1.6 MCP Maturity Assessment

| Criterion | Assessment |
|-----------|------------|
| **Protocol Stability** | Stable (spec v2025-11-25), but still evolving |
| **Client Support** | Growing: Claude Desktop, Cursor, VS Code extensions |
| **Server SDKs** | Python, TypeScript, Go - well-documented |
| **Production Deployments** | Limited to experimental/personal use |
| **Community Knowledge** | Sparse, few battle-tested patterns |
| **Long-term Viability** | Uncertain - depends on Anthropic/community adoption |

**Verdict:** MCP is promising but not production-ready for critical task management systems. Suitable for experimental AI workflows but risky for production deployment in early 2026.

---

## 2. Existing Tools Comparison

### 2.1 Commercial/Cloud Solutions

#### 2.1.1 Jira (Atlassian)

**Overview:** Enterprise-grade issue tracking and project management with extensive customization.

**API Capabilities:**
- REST API (v2 and v3) with comprehensive endpoints
- Workflow engine with customizable states and transitions
- Webhooks for real-time event notifications
- OAuth 2.0 and API token authentication
- Extensive plugin ecosystem (marketplace with 3,000+ apps)

**Strengths:**
- Mature, battle-tested API with 10+ years of production use
- Fine-grained permissions and security controls
- Powerful workflow automation and rules engines
- Rich reporting and dashboard capabilities
- Large developer community and documentation

**Weaknesses:**
- **Pricing:** Free tier limited to 10 users, Standard $7.50/user/mo, Premium $14.50/user/mo
- **Complexity:** Steep learning curve, heavy for simple use cases
- **Overkill:** Designed for large teams, not solo agents or small projects
- **Vendor Lock-in:** Atlassian ecosystem migration is painful
- **Performance:** Can be slow for high-frequency operations

**Cost Analysis:**
| Plan | Users | Monthly Cost | Annual Cost |
|------|-------|--------------|-------------|
| Free | Up to 10 | $0 | $0 |
| Standard | Unlimited | $7.50/user | $90/user |
| Premium | Unlimited | $14.50/user | $174/user |

**Integration Effort:** Medium - Need to build REST wrapper to map agent workflows to Jira issues

---

#### 2.1.2 Asana

**Overview:** User-friendly project management with strong automation features.

**API Capabilities:**
- REST API with comprehensive task and project management
- Rules engine for automating task movements
- Workflow builder for custom processes
- OAuth 2.0 authentication
- Webhook support for real-time updates

**Strengths:**
- Intuitive UI, designed for non-technical users
- Powerful automation with "Rules" feature
- Good mobile and desktop apps
- Flexible project templates
- Clear API documentation

**Weaknesses:**
- **Pricing:** Basic $10.99/user/mo, Premium $24.99/user/mo, Business $30.99/user/mo
- **Limited Customization:** Less flexible than Jira for complex workflows
- **Dependency Management:** Basic compared to Jira or Linear
- **API Rate Limits:** More restrictive than enterprise solutions

**Cost Analysis:**
| Plan | Monthly Cost | Annual Cost |
|------|--------------|-------------|
| Basic | $10.99/user | $131.88/user |
| Premium | $24.99/user | $299.88/user |
| Business | $30.99/user | $371.88/user |

**Integration Effort:** Medium - Need to implement heartbeat mechanism via external polling or webhooks

---

#### 2.1.3 Linear

**Overview:** Modern, fast issue tracking built for software teams.

**API Capabilities:**
- **GraphQL API** (not REST) with real-time subscriptions
- TypeScript SDK with typed models and operations
- **Agent-specific documentation:** Linear provides guidelines for AI agent integration
- Webhooks and real-time event streams
- OAuth 2.0 and personal API keys

**Strengths:**
- **LLM-Friendly:** Linear has dedicated documentation for AI agent integration
- GraphQL for efficient, typed queries
- Excellent developer experience
- Fast, responsive UI
- Strong automation and workflow features
- **Built for Developers:** Issue tracking designed for software workflows

**Weaknesses:**
- **Pricing:** Not publicly listed (contact sales), likely expensive for small teams
- GraphQL learning curve if team is REST-focused
- **No Built-in Heartbeats:** Would need to implement external monitoring
- **Limited Multi-Project:** Designed for single-project focus

**Cost Analysis:**
Estimated $10-20/user/mo based on market positioning, but exact pricing requires sales contact.

**Integration Effort:** Low-Medium - GraphQL is LLM-friendly, but agent-specific features (claiming, heartbeats) require custom implementation

---

#### 2.1.4 Notion

**Overview:** All-in-one workspace with database capabilities.

**API Capabilities:**
- REST API with database and page operations
- **MCP Support:** Notion provides official MCP server (https://developers.notion.com/docs/mcp)
- Rich property types and relationships
- OAuth 2.0 authentication
- Webhook support (limited)

**Strengths:**
- **Official MCP Server:** Notion already has MCP integration
- Flexible database structure
- Good documentation and SDK
- Integrates docs, tasks, wikis in one place
- Affordable pricing

**Weaknesses:**
- **Database Complexity:** September 2025 update introduced "Data Sources" breaking changes
- **No Native Task Model:** Tasks are just database rows, no built-in workflow
- **Performance:** Can be slow for high-frequency operations
- **API Versioning:** Frequent breaking changes (2025-09-03 update broke many integrations)

**Cost Analysis:**
| Plan | Monthly Cost | Annual Cost |
|------|--------------|-------------|
| Free | $0 | $0 |
| Plus | $10/user/mo | $120/user |
| Business | $18/user/mo | $216/user |

**Integration Effort:** Low - Notion provides MCP server, but database schema must be manually designed for task workflows

---

### 2.2 Developer/Open Source Solutions



---

#### 2.2.2 Taskwarrior

**Overview:** CLI-based offline-first task management system.

**Capabilities:**
- Command-line interface with powerful query language
- Offline-first with optional sync server (Taskchampion)
- Tagging, projects, dependencies
- Urgency scoring algorithm
- Time tracking integration (Timewarrior)

**Strengths:**
- Free and open source
- Offline-first, works without internet
- Extremely fast and lightweight
- Powerful CLI for power users
- Self-hosted sync available

**Weaknesses:**
- **No API:** Taskwarrior 3.x removed the old JSON-RPC server
- **No Real-time:** CLI-only, no webhooks or web UI
- **Steep Learning Curve:** Requires CLI proficiency
- **No Multi-user:** Designed for single users, team features limited
- **Not LLM-Friendly:** No structured API for agent integration

**Cost Analysis:**
- **Free:** Open source, self-hosted
- **Optional Cloud Sync:** Taskchampion sync server (pricing varies by host)

**Integration Effort:** High - Would need to build a custom API wrapper layer on top of CLI

---

#### 2.2.3 Kanboard

**Overview:** Self-hosted Kanban project management software.

**API Capabilities:**
- JSON-RPC 2.0 API
- Application API (token-based, no permission checks)
- User API (username/password, respects permissions)
- Webhook support
- Automatic actions (automation rules)

**Strengths:**
- Free and open source
- Self-hosted, no vendor lock-in
- Simple, minimal UI focused on Kanban
- JSON-RPC API is simple to integrate
- Automatic actions for workflow automation
- Good documentation

**Weaknesses:**
- **No Agent Features:** No claiming mechanism, no heartbeat tracking
- **Basic Workflow:** Limited to Kanban, complex workflows require plugins
- **PHP Stack:** May not fit Python/FastAPI ecosystem
- **Limited Real-time:** No SSE, relies on polling or webhooks
- **Small Community:** Less active than commercial alternatives

**Cost Analysis:**
- **Free:** Open source, self-hosted
- Hosting costs vary (typical VPS: $5-20/mo)

**Integration Effort:** Medium - JSON-RPC is straightforward, but claiming/heartbeat requires custom implementation

---

## 3. Capability Matrix

### 3.1 Feature Comparison Table

| Feature | MCP Server | Current REST API | Jira | Asana | Linear | Notion | GitHub Projects | Taskwarrior | Kanboard |
|---------|------------|------------------|------|-------|--------|--------|----------------|-------------|----------|
| **Real-time Updates** | SSE ✅ | Polling only ❌ | Webhooks ✅ | Webhooks ✅ | GraphQL Subscriptions ✅ | Limited Webhooks ❌ | Webhooks ✅ | None ❌ | Webhooks ✅ |
| **Agent Claiming** | Custom ✅ | Built-in ✅ | Custom ❌ | Custom ❌ | Custom ❌ | Custom ❌ | Custom ❌ | None ❌ | Custom ❌ |
| **Heartbeat Monitoring** | Custom ✅ | Built-in ✅ | External ❌ | External ❌ | External ❌ | External ❌ | External ❌ | None ❌ | External ❌ |
| **Dependency Management** | Custom ✅ | Built-in ✅ | Built-in ✅ | Basic ❌ | Built-in ✅ | Manual ❌ | None ❌ | Built-in ✅ | Manual ❌ |
| **Status Tracking** | Custom ✅ | Built-in ✅ | Workflows ✅ | Workflows ✅ | Workflows ✅ | Manual ❌ | Status Labels ✅ | Status ✅ | Columns ✅ |
| **API Maturity** | Low ❌ | Medium ✅ | High ✅ | High ✅ | High ✅ | Medium ✅ | High ✅ | None ❌ | Medium ✅ |
| **Authentication** | OAuth/Token ✅ | Basic Auth ❌ | OAuth 2.0 ✅ | OAuth 2.0 ✅ | OAuth 2.0 ✅ | OAuth 2.0 ✅ | OAuth/Token ✅ | None ❌ | Token ✅ |
| **Self-Hosted** | Yes ✅ | Yes ✅ | Yes (Data Center) 💰 | No ❌ | No ❌ | No ❌ | No ❌ | Yes ✅ | Yes ✅ |
| **LLM-Friendly** | Native ✅ | REST (Good) ✅ | REST ✅ | REST ✅ | GraphQL ✅ | REST/MCP ✅ | REST ✅ | None ❌ | JSON-RPC ✅ |
| **Web UI Included** | No ❌ | Yes ✅ | Yes ✅ | Yes ✅ | Yes ✅ | Yes ✅ | Yes ✅ | No ❌ | Yes ✅ |
| **Cost** | Dev time 💸 | Dev time 💸 | $7.50+/user/mo 💸 | $10.99+/user/mo 💸 | $10-20/user/mo 💸 | $10+/user/mo 💸 | $4+/user/mo 💸 | Free ✅ | Free ✅ |
| **Documentation** | Sparse ❌ | Good ✅ | Excellent ✅ | Excellent ✅ | Excellent ✅ | Good ✅ | Good ✅ | Good ✅ | Good ✅ |
| **Community Support** | Emerging ❌ | Small ✅ | Large ✅ | Large ✅ | Medium ✅ | Large ✅ | Large ✅ | Medium ✅ | Small ✅ |

**Legend:**
- ✅ Supported
- ❌ Not supported
- ⚠️ Limited support
- 💸 Cost concern

### 3.2 Agent-Specific Capabilities

| Capability | MCP Server | Custom REST API | Jira | Linear | GitHub | Notion MCP |
|------------|------------|------------------|------|--------|--------|------------|
| **Claim Mechanism** | Tool-based ✅ | REST endpoint ✅ | External polling ⚠️ | GraphQL mutation ✅ | REST mutation ⚠️ | MCP resource ✅ |
| **Heartbeat Tracking** | Tool + SSE ✅ | REST endpoint ✅ | Custom field + polling ⚠️ | Custom field + webhook ⚠️ | Status updates + polling ⚠️ | Custom DB field ✅ |
| **Dependency Resolution** | Tool logic ✅ | Built-in logic ✅ | Issue linking ✅ | Issue linking ✅ | PR linking ✅ | Manual DB relation ✅ |
| **Agent Coordination** | Native ✅ | Custom ✅ | External ❌ | External ❌ | External ❌ | External ❌ |
| **Real-time Notifications** | SSE ✅ | Polling only ❌ | Webhooks ✅ | GraphQL subscriptions ✅ | Webhooks ✅ | MCP streaming ✅ |
| **Schema Validation** | Pydantic ✅ | Pydantic ✅ | Custom ✅ | GraphQL types ✅ | OpenAPI ✅ | MCP types ✅ |

### 3.3 Fit for Comic-Pile Use Case

**Comic-Pile Requirements:**
1. Agent coordination for multi-agent workflow
2. Task claiming with conflict detection
3. Heartbeat monitoring for active task detection
4. Dependency management for task ordering
5. Status tracking (pending, in_progress, blocked, in_review, done)
6. Worktree management (git worktrees per task)
7. Self-hosted, no vendor lock-in
8. Hobbyist-friendly (low cost, simple infrastructure)
9. LLM integration for automated task assignment
10. Web UI for coordinator/agent overview

| Solution | Fit Score | Notes |
|----------|-----------|-------|
| **MCP Server** | 8/10 | Native LLM integration, but immature and requires building all UI from scratch |
| **Custom REST API (Current)** | 9/10 | Perfect fit - built exactly for this use case, simple, maintainable |
| **Jira** | 4/10 | Overkill, expensive, no native agent features, requires complex integration |
| **Asana** | 3/10 | Expensive, no agent-specific features, designed for human teams |
| **Linear** | 6/10 | Good developer experience, but no claiming/heartbeat, expensive |
| **Notion + MCP** | 7/10 | Official MCP support is great, but database schema must be manually designed |
| **Taskwarrior** | 2/10 | No API, no multi-agent support, CLI-only |
| **Kanboard** | 5/10 | Self-hosted, simple, but no agent-specific features, requires PHP |

---

## 4. Cost/Benefit Analysis

### 4.1 MCP Server (From Scratch)

**Benefits:**
- **Native LLM Integration:** No translation layer between agents and task management
- **Future-Proof:** Aligns with emerging AI agent standards
- **Full Control:** Custom-built for exact requirements
- **Lightweight:** Minimal dependencies, fast startup
- **Multiple Transports:** Can serve CLI (stdio), web apps (SSE), and desktop clients

**Costs:**

| Cost Category | Estimate | Notes |
|--------------|----------|-------|
| **Development Time** | 40-60 hours | FastMCP implementation + tools/resources + testing |
| **Learning Curve** | 10-20 hours | MCP protocol, SDK, best practices |
| **UI Development** | 60-80 hours | MCP has no UI, must build web interface from scratch |
| **Testing & Debugging** | 20-30 hours | Immature ecosystem, few examples to reference |
| **Documentation** | 10-15 hours | Create guides for future developers |
| **Maintenance** | 2-4 hours/quarter | Protocol changes, SDK updates |
| **Total Initial** | 140-205 hours | ~$7,000-10,250 at $50/hr |

**Tradeoffs:**
- **Pro:** Optimized for AI workflows, minimal overhead
- **Con:** High upfront cost, uncertain long-term viability, no existing UI

---

### 4.2 Custom REST API (Current + Extraction)

**Benefits:**
- **Simple & Proven:** REST is well-understood, stable, and documented
- **Already Implemented:** Core functionality exists in `app/api/tasks.py`
- **Fast Development:** Can extract and clean up in 10-20 hours
- **Any Client Support:** Works with browsers, CLI tools, mobile apps, and LLMs
- **Low Maintenance:** FastAPI is stable, minimal ongoing work

**Costs:**

| Cost Category | Estimate | Notes |
|--------------|----------|-------|
| **API Extraction & Cleanup** | 10-20 hours | Extract from comic-pile, add authentication, improve docs |
| **Testing & Validation** | 5-10 hours | Ensure extracted API works correctly |
| **Deployment** | 2-4 hours | Docker, environment config |
| **Documentation** | 5-8 hours | API docs, setup guides |
| **Maintenance** | 1-2 hours/quarter | Bug fixes, minor enhancements |
| **Total Initial** | 22-42 hours | ~$1,100-2,100 at $50/hr |

**Tradeoffs:**
- **Pro:** Low cost, fast implementation, well-understood technology
- **Con:** Not optimized for LLMs (but adequate), requires translation for complex agent workflows

---

### 4.3 Existing Commercial Tools (Jira, Linear, etc.)

**Benefits:**
- **Feature-Rich:** Pre-built workflows, reporting, dashboards
- **Mature & Stable:** Battle-tested in production environments
- **UI Included:** No need to build web interface
- **Community Support:** Large user base, plenty of resources

**Costs:**

| Cost Category | Estimate | Notes |
|--------------|----------|-------|
| **Integration Development** | 20-40 hours | REST wrappers, webhooks, custom logic |
| **Authentication Setup** | 5-10 hours | OAuth apps, API keys, permissions |
| **Data Migration** | 10-20 hours | Import existing tasks, test workflows |
| **Ongoing Licensing** | $100-500/year | Per-user monthly fees |
| **Learning Curve** | 5-10 hours | Tool-specific features and APIs |
| **Maintenance** | 3-5 hours/quarter | API changes, feature updates |
| **Total Initial (1-year)** | 40-80 hours + $100-500 | ~$2,000-4,000 + licensing |

**Tradeoffs:**
- **Pro:** Powerful features, minimal development, mature ecosystem
- **Con:** Vendor lock-in, recurring costs, overkill for simple use case

---

### 4.4 Open Source Self-Hosted (Kanboard)

**Benefits:**
- **No Licensing Costs:** Free software, just pay for hosting
- **Self-Controlled:** Full data ownership, no vendor lock-in
- **Community Support:** Open source, can contribute back

**Costs:**

| Cost Category | Estimate | Notes |
|--------------|----------|-------|
| **Integration Development** | 30-50 hours | JSON-RPC or REST wrappers, custom logic |
| **Agent-Specific Features** | 15-25 hours | Add claiming, heartbeat, dependency tracking |
| **Hosting Setup** | 2-5 hours | VPS, Docker, backups |
| **Hosting Costs** | $60-240/year | Typical VPS ($5-20/mo) |

**Tradeoffs:**
- **Pro:** No licensing fees, self-hosted control
- **Con:** Higher integration effort, limited agent-specific features, may require PHP/other stack

---

## 5. Recommended Approach

### 5.1 Primary Recommendation: Keep Custom REST API

**Decision:** Maintain and improve the current custom REST API (`app/api/tasks.py`) as the primary task management solution.

**Rationale:**

1. **Perfect Fit for Use Case:** The current API was designed specifically for agent coordination with claiming, heartbeats, and dependencies - features that no existing tool provides out of the box.

2. **Low Cost:** 22-42 hours to extract and improve vs 140-205 hours for MCP or $2,000-4,000 for commercial tools.

3. **Fast Implementation:** Already functional, only needs cleanup and extraction as standalone service.

4. **Proven Technology:** REST APIs are stable, well-documented, and work with any client (browsers, LLMs, CLI tools).

5. **Self-Hosted:** No vendor lock-in, no recurring licensing fees.

6. **Adequate for LLMs:** While not LLM-native, REST APIs work perfectly well with OpenAI function calling, Anthropic tool use, and other agent frameworks.

### 5.2 Secondary Recommendation: Future MCP Adapter Layer

**Plan:** After the REST API is stable and production-ready, build a **MCP adapter layer** that wraps the REST API.

**Benefits:**
- **Best of Both Worlds:** Keep stable REST API for existing clients while adding MCP support for LLM-native agents.
- **Incremental Adoption:** Can adopt MCP gradually without disrupting current workflows.
- **Risk Mitigation:** If MCP fails to gain traction, REST API remains as fallback.
- **Strawler Pattern:** Wrapping existing API is safer than rewriting from scratch.

**Implementation:**
```python
# mcp_adapter.py
from mcp.server.fastmcp import FastMCP
import httpx

mcp = FastMCP("Comic-Pile Task Adapter")
REST_API_BASE = "http://localhost:8000/api"

@mcp.tool()
async def list_tasks() -> list[dict]:
    """List all available tasks."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{REST_API_BASE}/tasks/")
        return response.json()

@mcp.tool()
async def claim_task(task_id: str, agent_name: str, worktree: str) -> dict:
    """Claim a task for an agent."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{REST_API_BASE}/tasks/{task_id}/claim",
            json={"agent_name": agent_name, "worktree": worktree}
        )
        return response.json()

# Heartbeat, status updates, etc. follow same pattern
```

**Timeline:**
- **Phase 1 (Now):** Extract and stabilize REST API (2-3 weeks)
- **Phase 2 (Q2 2026):** Build MCP adapter (1-2 weeks)
- **Phase 3 (Q3 2026):** Deploy and test with Claude Desktop/Cursor (1 week)
- **Phase 4 (Q4 2026):** Evaluate adoption and decide on MCP-first approach (if mature)

### 5.3 Decision Matrix

| Factor | Custom REST | MCP Server | Commercial Tool | Open Source |
|--------|--------------|------------|-----------------|--------------|
| **Initial Cost** | $1,100-2,100 | $7,000-10,250 | $2,000-4,000 + licensing | $2,350-4,000 |
| **Time to Value** | 2-3 weeks | 6-8 weeks | 4-6 weeks | 4-6 weeks |
| **Maintenance** | Low (1-2 hrs/quarter) | Medium (2-4 hrs/quarter) | High (3-5 hrs/quarter) | Medium (2-4 hrs/quarter) |
| **Agent Features** | Native ✅ | Native ✅ | Custom ⚠️ | Custom ⚠️ |
| **LLM Integration** | Good (REST) ✅ | Excellent (MCP) ✅ | Good (REST) ✅ | Good (REST/JSON-RPC) ✅ |
| **UI Included** | Yes ✅ | No ❌ | Yes ✅ | Yes ✅ |
| **Self-Hosted** | Yes ✅ | Yes ✅ | Maybe (Data Center) 💰 | Yes ✅ |
| **Vendor Lock-in** | None ✅ | None ✅ | High ❌ | None ✅ |
| **Future-Proof** | Good ✅ | Uncertain ⚠️ | Good ✅ | Good ✅ |
| **Overall Score** | **42/50** | 38/50 | 32/50 | 35/50 |

---

## 6. Implementation Effort Estimates

### 6.1 Option A: Extract and Improve REST API (Recommended)

**Phase 1: API Extraction (1-2 weeks)**
- Extract task API from comic-pile into standalone service
- Add authentication (API keys, OAuth 2.0)
- Improve error handling and validation
- Add unit tests and integration tests
- Write API documentation (OpenAPI/Swagger)

**Phase 2: Deployment & Monitoring (3-5 days)**
- Docker containerization
- Database migration and setup
- Health checks and monitoring
- Log aggregation (if needed)
- Backup strategy

**Phase 3: Testing & Validation (3-5 days)**
- Load testing for concurrent agent operations
- Integration testing with LLM clients (OpenAI, Anthropic)
- UI testing for coordinator dashboard
- Security audit (rate limiting, input validation)

**Total Effort:** 2-3 weeks (80-120 hours)

### 6.2 Option B: Build MCP Server from Scratch

**Phase 1: Design & Planning (1 week)**
- MCP protocol study and architecture design
- Define tools, resources, prompts
- Database schema design
- API specification

**Phase 2: Core Implementation (3-4 weeks)**
- MCP server setup with FastMCP
- Task CRUD operations as tools
- Claiming, heartbeat, status tracking tools
- Dependency resolution logic
- Resource endpoints for task queries

**Phase 3: UI Development (3-4 weeks)**
- Web UI for coordinator dashboard
- HTMX or React frontend
- Real-time updates via SSE
- Task visualization and management

**Phase 4: Testing & Documentation (2-3 weeks)**
- Unit tests, integration tests
- LLM integration testing
- Write comprehensive docs
- Create migration guides

**Total Effort:** 9-12 weeks (360-480 hours)

### 6.3 Option C: Commercial Tool Integration (e.g., Jira)

**Phase 1: Integration Design (1 week)**
- Map agent workflows to Jira issue fields
- Design custom fields for claiming, heartbeats, worktrees
- Define JQL queries for ready tasks
- Webhook event handling design

**Phase 2: Implementation (2-3 weeks)**
- REST wrapper service for Jira API
- Authentication and configuration
- Webhook handlers for real-time updates
- Claiming logic with conflict detection
- Heartbeat tracking via custom fields

**Phase 3: Migration & Testing (1-2 weeks)**
- Migrate existing tasks to Jira
- Update agent workflows to use wrapper
- Integration testing
- Performance optimization

**Total Effort:** 4-6 weeks (160-240 hours) + ongoing licensing

### 6.4 Option D: Hybrid (REST API + MCP Adapter)

**Phase 1: REST API Extraction (2-3 weeks)**
- (Same as Option A)

**Phase 2: MCP Adapter Development (1-2 weeks)**
- FastMCP server setup
- Tool wrappers for REST API endpoints
- Resource endpoints for task queries
- Prompt templates for LLM interactions

**Phase 3: Integration & Testing (1 week)**
- Test MCP adapter with Claude Desktop
- Test with Cursor and VS Code extensions
- Performance testing
- Documentation

**Total Effort:** 4-6 weeks (160-200 hours)

---

## 7. Migration Strategy

### 7.1 If Switching from Current API to MCP Server

**Phase 1: Parallel Operation (2-4 weeks)**
- Deploy MCP server alongside existing REST API
- Route 10% of agent traffic to MCP server
- Monitor for issues and performance
- Compare feature parity

**Phase 2: Gradual Migration (4-6 weeks)**
- Increase MCP server traffic to 50%
- Train agents to use MCP tools
- Update documentation and workflows
- Monitor error rates and agent satisfaction

**Phase 3: Full Cutover (2-4 weeks)**
- Migrate remaining 50% of traffic
- Decommission REST API endpoints
- Provide fallback period (1-2 weeks)
- Final cleanup and documentation

**Risks & Mitigations:**
- **Risk:** MCP protocol changes during migration  
  **Mitigation:** Pin SDK version, monitor upstream updates
- **Risk:** Agent incompatibility with MCP tools  
  **Mitigation:** Maintain REST API as fallback for 1-2 months
- **Risk:** Performance degradation  
  **Mitigation:** Load testing before cutover, capacity planning

### 7.2 If Switching to Commercial Tool

**Phase 1: Proof of Concept (2-3 weeks)**
- Evaluate top 2-3 candidates (Jira, Linear, Notion)
- Build prototype integrations
- Test critical agent workflows
- Gather feedback from agents

**Phase 2: Data Migration (1-2 weeks)**
- Export existing tasks from current API
- Map fields to target tool schema
- Import and validate data
- Test dependency resolution

**Phase 3: Workflow Updates (2-3 weeks)**
- Update agent code to use new API
- Train agents on new UI
- Update documentation and guides
- Roll out gradually to minimize disruption

**Phase 4: Decommission (1 week)**
- Monitor for issues during transition period
- Keep old API read-only for 2-4 weeks
- Final decommission and cleanup

---

## 8. Hybrid Approaches

### 8.1 MCP Server as Adapter Layer (Recommended Hybrid)

**Architecture:**
```
┌─────────────────────────────────────────────────┐
│                  LLM Clients                   │
│  (Claude Desktop, Cursor, OpenAI Agents, etc.)  │
└─────────────────┬───────────────────────────────┘
                  │ MCP Protocol
                  │ (JSON-RPC 2.0 over stdio/SSE)
┌─────────────────▼───────────────────────────────┐
│              MCP Adapter Layer                 │
│        (FastMCP wrapper around REST API)        │
└─────────────────┬───────────────────────────────┘
                  │ HTTP (REST)
                  │
┌─────────────────▼───────────────────────────────┐
│           Custom REST API Service              │
│    (Extracted from comic-pile, production)     │
└─────────────────┬───────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────┐
│              Database (PostgreSQL)         │
└─────────────────────────────────────────────────┘
```

**Benefits:**
- REST API remains stable for existing web UI and HTTP clients
- MCP adapter provides LLM-native interface for AI agents
- Can test MCP adoption without disrupting current workflows
- Lower risk than full rewrite
- Incremental development path

**Implementation Steps:**
1. Extract and stabilize REST API (2-3 weeks)
2. Build MCP adapter using FastMCP (1-2 weeks)
3. Deploy both services, configure routing (1 week)
4. Test with LLM clients, iterate based on feedback (1-2 weeks)

**Total Timeline:** 5-8 weeks

### 8.2 Sync Between Custom API and External Tool

**Use Case:** Leverage commercial tool's UI while maintaining custom agent features.

**Architecture:**
```
┌──────────────────────┐      ┌──────────────────────┐
│   Custom REST API    │◄────►│  External Tool       │
│ (Agent coordination) │ Sync │ (UI, reporting)     │
└──────────────────────┘      └──────────────────────┘
         ▲                             ▲
         │                             │
    Agents                          Humans
```

**Synchronization Strategy:**
- **One-Way Sync:** Custom API is source of truth, external tool is read-only mirror
- **Two-Way Sync:** Bidirectional sync with conflict resolution (complex)
- **Event-Driven Sync:** Use webhooks from external tool to trigger sync events

**Tools:**
- **Notion:** Sync tasks to Notion database via REST/MCP
- **Jira:** Sync tasks to Jira issues via REST API

**Benefits:**
- Keep agent-specific features (claiming, heartbeats) in custom API
- Leverage commercial tool's rich UI and reporting
- Gradual migration path if tool works well

**Drawbacks:**
- Complexity of maintaining sync logic
- Data consistency challenges
- Additional latency between systems

### 8.3 Layered Architecture with Adapters

**Concept:** Custom core with pluggable adapters for different clients.

**Architecture:**
```
┌──────────────────────────────────────────────────┐
│              Client Layer                        │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐        │
│  │   Web   │  │   CLI   │  │   LLM   │        │
│  │   UI    │  │  Tool   │  │ Agents │        │
│  └────┬────┘  └────┬────┘  └────┬────┘        │
└───────┼────────────┼────────────┼───────────────┘
        │            │            │
        │ HTTP       │ HTTP       │ MCP/REST
        │            │            │
┌───────▼────────────▼────────────▼───────────────┐
│            Adapter Layer                          │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐        │
│  │  Web    │  │  CLI    │  │   MCP   │        │
│  │ Adapter │  │ Adapter │  │ Adapter │        │
│  └────┬────┘  └────┬────┘  └────┬────┘        │
└───────┼────────────┼────────────┼───────────────┘
        │            │            │
        └────────────┼────────────┘
                     │
┌────────────────────▼─────────────────────────────┐
│         Task Management Core Service              │
│  (Business logic: claiming, heartbeats, deps)    │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────┐
│              Database Layer                      │
└───────────────────────────────────────────────────┘
```

**Benefits:**
- Clean separation of concerns
- Easy to add new clients (add new adapter)
- Core logic remains simple and testable
- Can evolve adapters independently

**Implementation:**
1. Extract core service from current API
2. Create web adapter (maintains current HTMX UI)
3. Create MCP adapter (future enhancement)
4. Create CLI adapter (future enhancement)

---

## 9. Conclusion and Next Steps

### 9.1 Summary of Findings

1. **MCP is promising but immature:** Introduced in November 2024, MCP shows great potential for LLM-native integrations but lacks production-ready implementations and has limited community knowledge.

2. **Existing tools don't fit agent workflows:** Commercial tools (Jira, Asana, Linear) are designed for human teams and lack agent-specific features like claiming mechanisms and heartbeat monitoring.

3. **Current custom REST API is optimal:** Built specifically for agent coordination, the existing task API provides all required features with minimal complexity and cost.

4. **Hybrid approach balances risk and innovation:** Wrapping the stable REST API with an MCP adapter provides LLM-native capabilities while maintaining a proven foundation.

### 9.2 Final Recommendation

**Primary Decision:** Extract and improve the current custom REST API as a standalone service.

**Secondary Decision:** Plan a future MCP adapter layer (6-12 months after REST API stabilizes).

**Rationale:**
- **Low risk:** REST is proven, stable, and well-understood
- **Fast value:** Can extract and deploy in 2-3 weeks
- **Cost-effective:** $1,100-2,100 vs $7,000+ for MCP from scratch
- **Future-ready:** Can add MCP adapter later if protocol matures
- **Perfect fit:** Already designed for agent coordination workflows

### 9.3 Next Steps

1. **Immediate (This Week):**
   - Create worktree: `git worktree add ../comic-pile-task-api-extract phase/extract-task-api`
   - Start API extraction from `app/api/tasks.py`
   - Define API contract (OpenAPI specification)

2. **Short-Term (2-4 Weeks):**
   - Complete API extraction as standalone FastAPI service
   - Add authentication and rate limiting
   - Write comprehensive tests (unit, integration, load)
   - Deploy to staging environment

3. **Medium-Term (1-3 Months):**
   - Monitor API in production
   - Gather feedback from agents and coordinators
   - Iterate on features and performance
   - Start planning MCP adapter architecture

4. **Long-Term (6-12 Months):**
   - Evaluate MCP ecosystem maturity
   - Build and test MCP adapter if ecosystem is healthy
   - Document hybrid approach for other projects
   - Share learnings with MCP community

---

## 10. References

### MCP Resources
- [MCP Specification](https://modelcontextprotocol.io/specification/2025-11-25)
- [MCP Python SDK](https://modelcontextprotocol.github.io/python-sdk/)
- [MCP Server Examples](https://modelcontextprotocol.info/docs/examples)
- [FastMCP Documentation](https://realpython.com/python-mcp/)

### Commercial Tool APIs
- [Jira API Documentation](https://developer.atlassian.com/cloud/jira/platform/rest/v2/intro/)
- [Asana API Documentation](https://developers.asana.com/docs)
- [Linear API Documentation](https://developers.linear.app/docs/graphql/working-with-the-graphql-api)
- [GitHub Projects API](https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/using-the-api-to-manage-projects)
- [Notion API + MCP](https://developers.notion.com/docs/mcp)

### Open Source Tools
- [Taskwarrior](https://taskwarrior.org/)
- [Kanboard](https://kanboard.org/)
- [Kanboard API Documentation](https://docs.kanboard.org/v1/api)

### Current Implementation
- `app/api/tasks.py` - Task API endpoints
- `app/models/task.py` - Task database model
- `app/schemas/task.py` - Pydantic request/response schemas
- `TASKS.md` - Task definitions and requirements

---

**Document End**
