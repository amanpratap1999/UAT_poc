# Phase 2 Acceptance Review Report

## 1. CustomerDiscoveryAgent
- **Implementation**: Located at `src/agent/domain/discovery.py`.
- **Functionality**: Dynamically queries the ServiceNow Table API (`/api/now/table/sys_dictionary`, `sys_ui_policy`, etc.) to discover instance-specific schemas, field constraints (mandatory, read-only, types), and active UI policies.
- **Result**: Successfully discovers data without hardcoding.

## 2. CustomerKnowledgeModel
- **Implementation**: Located at `src/agent/domain/knowledge_model.py`.
- **Functionality**: Stores a versioned deterministic snapshot of metadata mapped to tables and fields (`TableMetadata`, `FieldMetadata`). 
- **Classification Logic**: Accurately classifies anomalies (e.g., if a field is mandatory but the dictionary says it shouldn't be, it returns `APPLICATION_BUG`).

## 3. Deterministic Incident Rules
- **Implementation**: `IncidentLifecycle`, `IncidentPriority`, etc. are preserved intact inside `src/agent/skills/incident/domain/models.py`.
- **Status**: Retained as authoritative. No RAG/LLM reasoning was forced upon standard ITIL incident processes.

## 4. Semantic KnowledgeStore / pgvector
- **Implementation**: `PgVectorKnowledgeStore` is implemented inside `src/agent/knowledge/store.py`.
- **Functionality**: Replaces naive string-matching with cosine distance searches (`<=>`) over a Postgres `vector` column utilizing the `asyncpg` library.

## 5. EmbeddingClient Abstraction
- **Implementation**: Located at `src/agent/knowledge/embeddings.py`.
- **Functionality**: Exposes an `EmbeddingClient` interface. `OpenAIEmbeddingClient` provides the concretized logic to convert domain texts into vector tensors.

## 6. MetadataDriftDetector
- **Implementation**: Located at `src/agent/domain/drift.py`.
- **Functionality**: A continuous background asynchronous daemon that polls `sys_updated_on` timestamps to update the `CustomerKnowledgeModel` dynamically if rules/policies change mid-session.

## 7. Provenance/Evidence of Discovered Facts
- **Implementation**: `CustomerKnowledgeModel.classify_anomaly()` returns a `ClassificationResult` containing a `citation` field.
- **Evidence**: Findings correctly cite authoritative records (e.g., `citation="sys_dictionary:incident.short_description"` or `sys_ui_policy:sys_id`).

## 8. Production vs Development Knowledge-Store Behavior
- **Implementation**: The dependency injection container (`dependencies.py`) provides seamless toggling.
- **Development**: Uses `InMemoryKnowledgeStore` (Markdown-based, text search) when `HAS_POSTGRES` is false or URL is missing.
- **Production**: Uses `PgVectorKnowledgeStore` when a Postgres DB URL is defined and the `pgvector` library is present.
