# Architectural Review: Extract Task API to External Service

## Executive Summary

This document analyzes the current Task API architecture within Comic Pile and evaluates options for extracting it into a separate external service. The Task API provides task management functionality for PRD alignment development, including task claiming, heartbeat tracking, status updates, and coordination dashboards.

**Recommendation:** Keep the Task API embedded in Comic Pile for the foreseeable future. The current architecture provides adequate separation of concerns, and extracting to a separate service would introduce significant complexity with minimal benefits given the project's scale and use case.

---

## 1. Current Architecture

### 1.1 Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     Comic Pile FastAPI                      │
│                      (Monolithic)                           │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  API Layer (FastAPI Router)                         │  │
│  │  ├── threads.py  (Thread CRUD, queue, rating)       │  │
│  │  ├── roll.py     (Dice rolling, session flow)       │  │
│  │  ├── queue.py    (Queue operations)                  │  │
│  │  ├── session.py  (Session management)                │  │
│  │  ├── admin.py    (Admin operations)                  │  │
│  │  └── tasks.py    (Task management)  ←─ FOCUS          │  │
│  └──────────────────────────────────────────────────────┘  │
│                           │                                  │
│                           ▼                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Database Layer (SQLAlchemy ORM)                      │  │
│  │  ├── Thread, Session, Event, User models             │  │
│  │  └── Task model  ←─ Single database                     │  │
│  └──────────────────────────────────────────────────────┘  │
│                           │                                  │
│                           ▼                                  │
│                  SQLite Database                             │
└─────────────────────────────────────────────────────────────┘

External Consumers:
- AI Agents (via curl/httpx)
- Coordinator Dashboard (HTMX)
- Interactive Tests
```

### 1.2 Task API Implementation

**Location:** `app/api/tasks.py` (643 lines)

**Key Endpoints:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/tasks/` | List all tasks |
| GET | `/api/tasks/ready` | Get tasks ready for claiming |
| GET | `/api/tasks/coordinator-data` | Get tasks grouped by status |
| GET | `/api/tasks/{task_id}` | Get single task |
| POST | `/api/tasks/{task_id}/claim` | Claim task for agent |
| POST | `/api/tasks/{task_id}/heartbeat` | Update task heartbeat |
| POST | `/api/tasks/{task_id}/update-notes` | Append status notes |
| POST | `/api/tasks/{task_id}/set-status` | Change task status |
| POST | `/api/tasks/{task_id}/unclaim` | Release task back to pending |
| POST | `/api/tasks/initialize` | Initialize tasks from hardcoded data |

**Dependencies:**

- **Direct Database Access:** Uses SQLAlchemy Session directly
- **Database Model:** `app/models/task.py` (43 lines)
- **Schemas:** `app/schemas/task.py` (80 lines)
- **Integration:** Included in FastAPI app via `app/main.py:109`
- **UI Integration:** Coordinator dashboard at `/tasks/coordinator` renders task data

### 1.3 Database Schema

**Table:** `tasks`

```python
- id: int (PK)
- task_id: str (unique, indexed) - e.g., "TASK-101"
- title: str
- priority: str ("HIGH", "MEDIUM", "LOW")
- status: str (indexed) - "pending", "in_progress", "blocked", "in_review", "done"
- dependencies: str (comma-separated task IDs)
- assigned_agent: str | None
- worktree: str | None
- status_notes: text (appended with timestamps)
- estimated_effort: str
- completed: bool
- blocked_reason: text | None
- blocked_by: str | None
- last_heartbeat: datetime | None
- instructions: text
- created_at: datetime
- updated_at: datetime
```

### 1.4 Current Usage Patterns

**Agent Workflows:**
1. Agents call `POST /api/tasks/{task_id}/claim` to start working
2. Agents call `POST /api/tasks/{task_id}/heartbeat` every 5-10 minutes
3. Agents call `POST /api/tasks/{task_id}/update-notes` to log progress
4. Agents call `POST /api/tasks/{task_id}/set-status` to mark done/blocked
5. Agents call `POST /api/tasks/{task_id}/unclaim` to release task

**Coordinator Dashboard:**
- Displays tasks grouped by status (pending, in_progress, blocked, in_review, done)
- Auto-refreshes every 10 seconds via HTMX
- Shows priority badges, assignment info, dependencies

**Data Access:**
- Direct SQL queries via SQLAlchemy ORM
- Single transaction boundary (Comic Pile database)
- No caching beyond in-memory Python cache in `main.py`

---

## 2. External Service Architecture Options

### 2.1 Separate FastAPI Service (REST)

```
┌─────────────────────┐         ┌─────────────────────────────┐
│   Comic Pile        │         │   Task Service              │
│   (FastAPI)         │         │   (FastAPI)                 │
│                     │         │                             │
│ - Threads           │         │ - Task CRUD                 │
│ - Queue             │◄────────┤ - Task assignment           │
│ - Roll, Rate,       │  HTTP   │ - Heartbeat tracking        │
│ - Sessions          │  REST   │ - Status updates            │
│                     │         │ - Dependency resolution     │
└─────────────────────┘         └─────────────────────────────┘
         │                                │
         │                                │
         ▼                                ▼
    SQLite DB                      Task DB (SQLite)
  (threads, etc.)               (tasks only)
```

**Pros:**
- Independent deployment and scaling
- Clear service boundary
- Task service can evolve independently
- Can use different tech stack in future
- Easier to test task logic in isolation

**Cons:**
- Network latency (microseconds to milliseconds)
- Need service discovery or hardcoded URLs
- Requires inter-service authentication
- Two deployments to manage
- Distributed transaction challenges
- Increased operational complexity

### 2.2 gRPC Service

```
┌─────────────────────┐         ┌─────────────────────────────┐
│   Comic Pile        │         │   Task Service (gRPC)       │
│   (FastAPI)         │         │   (Python)                   │
│                     │         │                             │
│ - Threads           │         │ - Protobuf definitions      │
│ - Queue             │◄────────┤ - Streaming heartbeats      │
│ - Roll, Rate,       │  gRPC   │ - Type-safe communication   │
│ - Sessions          │  binary │ - High performance          │
└─────────────────────┘         └─────────────────────────────┘
```

**Pros:**
- Binary protocol (faster than HTTP/JSON)
- Type-safe via Protobuf
- Built-in streaming support (good for heartbeats)
- Efficient for frequent calls

**Cons:**
- More complex than REST
- Tooling overhead (Protobuf compilation)
- Less accessible (can't curl endpoints easily)
- Overkill for this scale

### 2.3 Message Queue Integration

```
┌─────────────────────┐         ┌─────────────────────────────┐
│   Comic Pile        │         │   Task Service              │
│   (FastAPI)         │         │   (Worker)                  │
│                     │         │                             │
│ - Threads           │         │ - Process events           │
│ - Queue             │◄────────┤ - Update task state         │
│ - Roll, Rate,       │  Redis/ │ - Emit status changes       │
│ - Sessions          │  RabbitMQ                              │
└─────────────────────┘         └─────────────────────────────┘
```

**Pros:**
- Async, decoupled communication
- Natural for heartbeat streams
- Durable event processing
- Can add more consumers later

**Cons:**
- Eventual consistency (harder to get immediate state)
- Requires message broker (RabbitMQ, Redis)
- Complex debugging
- Overkill for synchronous operations

### 2.4 Shared Database vs Separate Database

**Option A: Shared Database**

```
Comic Pile DB (SQLite)
├── threads
├── sessions
├── events
├── users
└── tasks ← Both services access
```

**Pros:**
- Simple data migration (no migration needed)
- Single transaction boundary (can join tables)
- No data replication needed
- Easy to query across services

**Cons:**
- Tight data coupling (both services must know schema)
- Harder to evolve task schema independently
- Violates microservices best practices

**Option B: Separate Database**

```
Comic Pile DB          Task Service DB
├── threads           └── tasks
├── sessions
├── events
└── users
```

**Pros:**
- True data independence
- Each service owns its data
- Can use different database engines
- Clear bounded contexts

**Cons:**
- Need data migration strategy
- No cross-service joins
- Distributed transactions needed for consistency
- Foreign key relationships lost

---

## 3. Tradeoff Analysis

### 3.1 In-Process (Current Architecture)

**Pros:**

| Category | Benefit |
|----------|---------|
| Simplicity | Single codebase, single deployment, single test suite |
| Performance | No network latency, direct database access |
| Transactions | ACID guarantees across all operations |
| Testing | Easy integration tests (single process) |
| Operations | One process to monitor, one set of logs |
| Development | No service discovery, no inter-service auth needed |
| Documentation | One API spec at `/docs` |
| Data Integrity | Foreign keys and referential integrity |

**Cons:**

| Category | Drawback |
|----------|----------|
| Coupling | Task code is part of Comic Pile monolith |
| Deployment | Task service cannot scale independently |
| Reuse | Other projects cannot use task service |
| Boundaries | Task logic mixed with comic-specific code |

### 3.2 External Service

**Pros:**

| Category | Benefit |
|----------|---------|
| Decoupling | Task service is independent, owns its code |
| Scaling | Task service can scale independently (unlikely needed) |
| Reuse | Other projects could use task service |
| Boundaries | Clear bounded context for task management |
| Technology | Could use different stack in future |

**Cons:**

| Category | Drawback |
|----------|----------|
| Complexity | Two services to deploy, monitor, and maintain |
| Latency | Network overhead for all task operations |
| Consistency | Distributed transactions or eventual consistency |
| Auth | Need inter-service authentication (JWT, API keys, mTLS) |
| Discovery | Need service URL configuration or registry |
| Failures | Need circuit breakers, retries, graceful degradation |
| Testing | Integration tests require both services running |
| Data Migration | Need strategy for existing task data |
| Cost | Additional infrastructure (two deployments, possibly two databases) |

---

## 4. Migration Strategies

### 4.1 Big Bang Migration

**Approach:**
1. Create new Task Service as separate FastAPI app
2. Migrate all task data to Task Service database
3. Update Comic Pile to call Task Service APIs
4. Switch over in single deployment
5. Remove task code from Comic Pile

**Timeline:** 1-2 weeks

**Risks:**
- High risk of data corruption during migration
- Hard to rollback if issues arise
- Extended downtime during cutover
- Complex coordination

**Mitigations:**
- Comprehensive backup of task data
- Run migration in staging first
- Parallel run with read-only Comic Pile tasks
- Detailed rollback plan

### 4.2 Strangler Fig Pattern (Incremental)

**Approach:**
1. Create new Task Service alongside existing Comic Pile
2. Add proxy layer to route task requests
3. Gradually migrate endpoints one-by-one:
   - Phase 1: Read-only endpoints (GET /tasks/, GET /tasks/{id})
   - Phase 2: Write endpoints (POST /tasks/{id}/claim, /heartbeat, /update-notes)
   - Phase 3: Status and unclaim endpoints
4. Monitor and validate after each phase
5. Remove old code after all endpoints migrated

**Timeline:** 2-4 weeks

**Risks:**
- Longer migration period
- Need to keep both services in sync during migration
- Complexity of proxy routing logic

**Mitigations:**
- Feature flags to toggle routing
- Comprehensive testing for each phase
- Metrics and monitoring to catch issues early
- Ability to rollback individual endpoints

### 4.3 Database-First Strangler Fig

**Approach:**
1. Create Task Service with shared database access
2. Migrate business logic to Task Service
3. Comic Pile calls Task Service for task operations
4. Separate databases once logic migration complete
5. Finally move Task Service to its own database

**Timeline:** 3-5 weeks

**Risks:**
- Database coupling during intermediate phases
- Complex to separate databases later
- Long migration period increases risk

**Mitigations:**
- Clear contract for database access
- Gradual separation of concerns
- Extensive testing at each phase

---

## 5. Required Code Changes

### 5.1 Comic Pile Changes (if extracting Task Service)

**Files to Modify:**

1. **app/main.py**
   - Remove `from app.api import tasks`
   - Remove `app.include_router(tasks.router, ...)`
   - Remove `from app.api.tasks import get_coordinator_data`
   - Add Task Service client initialization
   - Add configuration for Task Service URL

2. **app/templates/coordinator.html**
   - Change HTMX endpoints to use proxy or new endpoints
   - Update from `/api/tasks/...` to `/tasks/...` (proxy route)

3. **New: app/services/task_client.py**
   - HTTP client to call Task Service
   - Include authentication headers
   - Handle service unavailability (circuit breaker)
   - Example:
   ```python
   class TaskServiceClient:
       def __init__(self, base_url: str):
           self.base_url = base_url
           self.client = httpx.AsyncClient(timeout=5.0)

       async def get_task(self, task_id: str) -> TaskResponse:
           try:
               response = await self.client.get(
                   f"{self.base_url}/tasks/{task_id}",
                   headers={"Authorization": f"Bearer {self.get_token()}"}
               )
               response.raise_for_status()
               return TaskResponse(**response.json())
           except httpx.HTTPError as e:
               # Handle circuit breaker, fallback, or graceful degradation
               raise TaskServiceUnavailable()
   ```

4. **New Proxy Routes (if using proxy pattern)**
   - Forward requests from `/api/tasks/*` to Task Service
   - Add authentication/authorization checks

5. **Environment Variables**
   - `TASK_SERVICE_URL=http://localhost:8001`
   - `TASK_SERVICE_API_KEY=shared-secret-key`
   - `TASK_SERVICE_TIMEOUT=5.0`

### 5.2 Task Service Code Structure

**New Project: `task-service/`**

```
task-service/
├── app/
│   ├── __init__.py
│   ├── main.py (FastAPI app)
│   ├── api/
│   │   ├── __init__.py
│   │   └── tasks.py (task endpoints)
│   ├── models/
│   │   ├── __init__.py
│   │   └── task.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── task.py
│   └── database.py
├── alembic/
├── tests/
├── pyproject.toml
└── README.md
```

**Key Features:**
- Authentication middleware (API key or JWT)
- CORS configuration
- Health check endpoint
- OpenAPI documentation at `/docs`
- Circuit breaker for database failures

---

## 6. Risk Assessment and Mitigation

### 6.1 Technical Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Data loss during migration | Medium | High | Comprehensive backups, dry-run migrations, validate checksums |
| Service unavailable | Medium | Medium | Circuit breaker, cached fallback data, graceful degradation |
| Performance degradation | Low | Medium | Benchmark before/after, optimize queries, add caching |
| Authentication bypass | Low | High | Use proven auth libraries, audit auth logic, rotate keys |
| Distributed transaction failures | High | High | Design for eventual consistency, use sagas pattern |
| Latency impact on user experience | Low | Low | Expect sub-10ms overhead, add frontend loading states |

### 6.2 Operational Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Increased deployment complexity | High | Medium | CI/CD automation for both services, integration tests |
| Monitoring complexity | Medium | Medium | Centralized logging (ELK/Loki), distributed tracing |
| Debugging difficulties | High | Medium | Correlation IDs, distributed tracing, detailed logs |
| Onboarding difficulty | Medium | Low | Update documentation, architecture diagrams |

### 6.3 Business Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Development time wasted | High | Medium | Clearly define criteria for proceeding, stop if not beneficial |
| Reduced team velocity during migration | Medium | Medium | Phase migration, minimize disruptions |
| No tangible benefits | High | High | Conduct cost-benefit analysis before starting, set success metrics |

---

## 7. Alternatives to Custom Task Service

### 7.1 Off-the-Shelf Task Management Tools

**GitHub Projects**

**Pros:**
- Already integrated with GitHub
- Agent can use GitHub REST API
- No deployment needed
- Rich UI included
- Task dependencies supported

**Cons:**
- Requires GitHub account and tokens
- Not customizable for agent workflows
- Public visibility may be undesirable
- Rate limits
- No custom fields (worktree, heartbeat)

**Asana API**

**Pros:**
- Purpose-built for task management
- Robust API
- Webhook support
- Custom fields available

**Cons:**
- Paid plan required for custom fields
- External dependency
- Requires OAuth setup
- Learning curve for team

**Jira API**

**Pros:**
- Highly customizable
- Powerful workflow engine
- Extensive API
- Enterprise features

**Cons:**
- Overkill for this use case
- Expensive
- Complex setup
- Heavyweight for hobbyist project

### 7.2 MCP Server Approach

**Model Context Protocol (MCP)** is a standardized protocol for AI agents to access tools and resources.

**Pros:**
- Standardized agent interface
- Composable tool architecture
- Task service becomes reusable MCP tool
- Agent-agnostic implementation
- Growing ecosystem

**Cons:**
- Emerging standard (still evolving)
- Requires MCP client in agents
- Less mature than REST
- Additional layer of abstraction

**Recommendation:** If the project is committed to using AI agents extensively, an MCP server for task management could be valuable. However, for the current scope, the REST API is sufficient.

### 7.3 Cost/Benefit Analysis

| Approach | Development Cost | Operational Cost | Benefit | Recommendation |
|----------|----------------|-----------------|---------|----------------|
| Keep Task API in Comic Pile | $0 | Low | Simplicity, performance | ✅ Recommended |
| External REST Service | High (2-4 weeks) | Medium | Decoupling, independence | ❌ Not worth it |
| External gRPC Service | Very High | Medium | Performance, type safety | ❌ Overkill |
| Message Queue Integration | High | High | Async, decoupled | ❌ Unnecessary complexity |
| GitHub Projects | Low | Low | No deployment, integrated | ⚠️ Consider if GitHub-first |
| Asana API | Medium | Low | Rich features | ⚠️ Consider if enterprise |
| Jira API | High | High | Enterprise features | ❌ Overkill |
| MCP Server | Medium | Low | Agent-agnostic | ⚠️ Consider long-term |

---

## 8. Recommendation

### 8.1 Primary Recommendation: Keep Task API in Comic Pile

**Rationale:**

1. **Scale Considerations**
   - Comic Pile is a single-user, hobbyist project
   - Task API has ~12 tasks total
   - Traffic is minimal (agents heartbeat every 5-10 minutes)
   - No independent scaling requirements

2. **Complexity vs Benefit**
   - Extracting to external service adds significant complexity
   - Benefits (independent scaling, reuse) are not needed
   - Current architecture is simple and maintainable
   - No performance bottlenecks in Task API

3. **Future-Proofing**
   - If Comic Pile grows to need independent task service:
     - Code is already well-organized (separate module)
     - Business logic is isolated in `tasks.py`
     - Can extract when justified by actual needs
   - Premature optimization is wasteful

4. **Resource Allocation**
   - Development time is better spent on features
   - 2-4 weeks of migration effort could be used elsewhere
   - Maintenance overhead is unnecessary

### 8.2 Secondary Recommendation: If Extracting is Required

**If external task service is deemed necessary (e.g., team expansion, multi-tenant requirements):**

1. **Use REST over gRPC**
   - Easier to debug and test
   - Sufficient performance at this scale
   - More accessible (can use curl, Postman)

2. **Use Strangler Fig Pattern**
   - Incremental migration reduces risk
   - Can rollback individual endpoints
   - Easier to validate each phase

3. **Share Database Initially**
   - Reduces migration complexity
   - Maintain referential integrity
   - Separate databases later if needed

4. **Prioritize:**
   - Authentication: Simple API key shared secret
   - Service Discovery: Environment variable for URL
   - Resilience: Circuit breaker with httpx
   - Monitoring: Add correlation IDs and logging

### 8.3 Alternative Recommendation: Consider GitHub Projects

**If the goal is to reduce custom code:**

1. **Migrate to GitHub Projects:**
   - Use GitHub REST API for task operations
   - Store task data as GitHub issues
   - Remove custom Task API entirely

2. **Implementation:**
   - Create GitHub token for agent authentication
   - Map task metadata to issue labels/custom fields
   - Replace Task API calls with GitHub API calls

3. **Benefits:**
   - No deployment needed
   - Native UI included
   - Agent can work directly with issues
   - Built-in authentication via GitHub

4. **Tradeoffs:**
   - Less control over data model
   - Dependent on GitHub availability
   - Public visibility (unless private repo)
   - Rate limits

---

## 9. Success Criteria

If proceeding with extraction, success criteria should include:

- [ ] All Task API endpoints migrated with 100% feature parity
- [ ] Zero data loss during migration (validate checksums)
- [ ] Performance degradation < 10ms per request
- [ ] Service availability > 99.9% (circuit breaker tested)
- [ ] Authentication tested and documented
- [ ] All existing tests pass
- [ ] Integration tests added for inter-service communication
- [ ] Documentation updated (API.md, AGENTS.md)
- [ ] Deployment automated in CI/CD
- [ ] Monitoring and alerting configured
- [ ] Rollback procedure tested

---

## 10. Conclusion

The current Task API architecture is well-designed for Comic Pile's needs. Extracting it to an external service would introduce significant complexity with minimal benefits at the current scale. The code is already modular and organized, making future extraction straightforward if justified by actual requirements.

**Recommendation:** Do not extract Task API at this time. Continue with current architecture. Revisit this decision if:
- Comic Pile scales to multiple users
- Task management needs independent scaling
- Task service is needed by other projects
- Team size requires service boundaries

The effort is better spent on:
- Feature development (PRD alignment tasks)
- Improving existing functionality
- User experience enhancements
- Performance optimizations (if needed)

---

## Appendix A: Bounded Context Analysis

### 10.1 What is the Bounded Context of Task Management?

**Core Domain Entities:**
- Task: Represents work to be done
- Agent: Actor claiming and working on tasks
- Status: State machine (pending → in_progress → blocked/in_review → done)
- Heartbeat: Liveness signal for active tasks

**Business Rules:**
- Task can only be claimed by one agent at a time
- Tasks with unmet dependencies are not ready
- Heartbeats must be sent by assigned agent
- Dependencies are comma-separated task IDs
- Priority ordering: HIGH > MEDIUM > LOW

**Ubiquitous Language:**
- "Claim" → Assign task to agent, mark in_progress
- "Heartbeat" → Update last_heartbeat timestamp
- "Unclaim" → Release task back to pending
- "Block" → Mark task blocked with reason
- "Done" → Mark task completed

### 10.2 Relationship to Comic Pile Domain

**Coupling Points:**
1. **Database:** Tasks stored in same SQLite database as threads/sessions
2. **UI:** Coordinator dashboard embedded in Comic Pile
3. **Deployment:** Same FastAPI process
4. **Agents:** Same agents work on comic features and tasks

**Separation of Concerns:**
- Task logic is already isolated in `tasks.py` module
- No cross-model dependencies (Task doesn't reference Thread/Session)
- Task API is optional (Comic Pile works without it)
- Tasks are metadata about development work, not comic data

**Conclusion:** Task management is a separate bounded context that is currently co-located for convenience, not architectural necessity. It could be extracted without violating domain boundaries.

---

## Appendix B: Data Consistency Patterns

### 10.3 Distributed Transactions (Not Recommended)

**Two-Phase Commit (2PC):**
- Too complex for SQLite
- Not supported by Python ORMs easily
- Overkill for this use case

**Saga Pattern (Eventual Consistency):**
- Break transactions into compensatable steps
- Emit events for each step
- Use event sourcing to replay if needed
- Complex to implement correctly

### 10.4 Recommended: Eventual Consistency with Idempotency

**Approach:**
- Design operations to be idempotent
- Use optimistic locking (version field)
- Retry on conflict with exponential backoff
- Accept brief inconsistencies (heartbeats, status updates)

**Example:**
```python
@router.post("/{task_id}/heartbeat")
async def heartbeat(task_id: str, request: HeartbeatRequest):
    # Optimistic locking
    task = db.query(Task).filter(Task.task_id == task_id).with_for_update().one()
    if task.assigned_agent != request.agent_name:
        raise HTTPException(403, "Not assigned to this agent")
    task.last_heartbeat = datetime.now()
    db.commit()
    return TaskResponse(**task.dict())
```

---

## Appendix C: Service Discovery Options

### 10.5 Hardcoded URLs (Simplest)

```python
# config.py
TASK_SERVICE_URL = os.getenv("TASK_SERVICE_URL", "http://localhost:8001")
```

**Pros:** Simple, no additional infrastructure
**Cons:** Requires restart to change URL

### 10.6 DNS-Based Discovery

```python
TASK_SERVICE_URL = "http://task-service.default.svc.cluster.local"
```

**Pros:** Works with DNS, no code changes to update
**Cons:** Requires DNS configuration, cluster setup

### 10.7 Service Registry (Consul, etcd)

**Pros:** Dynamic discovery, health checking
**Cons:** Overkill for 2 services, operational overhead

### 10.8 Kubernetes Services

```yaml
apiVersion: v1
kind: Service
metadata:
  name: task-service
spec:
  selector:
    app: task-service
  ports:
    - port: 8000
```

**Pros:** Built-in to Kubernetes, automatic load balancing
**Cons:** Requires Kubernetes deployment

**Recommendation:** Start with hardcoded URLs (environment variables). Upgrade to DNS or Kubernetes services if deploying to those environments.

---

## Appendix D: Authentication Patterns

### 10.9 Shared API Key (Simplest)

```python
# Comic Pile
headers = {"X-API-Key": "shared-secret-key"}

# Task Service
@app.middleware("http")
async def verify_api_key(request: Request, call_next):
    if request.headers.get("X-API-Key") != "shared-secret-key":
        raise HTTPException(401)
    return await call_next(request)
```

**Pros:** Simple to implement
**Cons:** Keys must be rotated manually, shared secret

### 10.10 JWT Tokens

```python
# Generate token
token = jwt.encode({"service": "comic-pile", "exp": exp}, SECRET_KEY)

# Verify token
payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
```

**Pros:** Standardized, can include claims, can expire
**Cons:** Need token management, clock sync

### 10.11 Mutual TLS (mTLS)

**Pros:** Strong security, no shared secrets
**Cons:** Certificate management overhead

**Recommendation:** Use shared API key for simplicity. Upgrade to JWT if more security or fine-grained access control is needed.

---

## Appendix E: Timeline and Effort Estimates

### 10.12 Keep Current Architecture

| Phase | Effort | Timeline |
|-------|--------|----------|
| Decision and documentation | 1 day | Complete |
| N/A | N/A | N/A |

**Total:** 1 day

### 10.13 Extract to External Service (Big Bang)

| Phase | Effort | Timeline |
|-------|--------|----------|
| Create Task Service project | 3 days | Week 1 |
| Implement task endpoints | 5 days | Week 1-2 |
| Add authentication and resilience | 2 days | Week 2 |
| Migrate data and validate | 2 days | Week 2 |
| Update Comic Pile to call Task Service | 3 days | Week 2-3 |
| Testing and debugging | 3 days | Week 3 |
| Documentation and deployment | 1 day | Week 3 |

**Total:** ~3 weeks (19 days)

### 10.14 Extract to External Service (Strangler Fig)

| Phase | Effort | Timeline |
|-------|--------|----------|
| Create Task Service project | 3 days | Week 1 |
| Implement read-only endpoints | 3 days | Week 1-2 |
| Implement write endpoints | 4 days | Week 2 |
| Add proxy routing | 2 days | Week 2 |
| Incremental migration (phase by phase) | 5 days | Week 2-3 |
| Testing and validation | 3 days | Week 3 |
| Remove old code and cleanup | 2 days | Week 3-4 |

**Total:** ~4 weeks (22 days)

---

## References

- [Microservices Patterns](https://microservices.io/patterns/) - Chris Richardson
- [Strangler Fig Pattern](https://martinfowler.com/bliki/StranglerFigApplication.html)
- [Saga Pattern](https://microservices.io/patterns/data/saga.html)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Model Context Protocol](https://modelcontextprotocol.io/)

---

**Document Version:** 1.0
**Author:** Architectural Review (TASK-119)
**Date:** 2026-01-01
**Status:** Ready for Review
