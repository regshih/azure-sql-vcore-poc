# Architecture diagrams

These are design diagrams, not screenshots or evidence of a live deployment.
All starting settings are a **POC assumption, not a confirmed customer
requirement.** Measured behavior: **Not demonstrated by this POC run.**

## 1. Provisioned baseline

```mermaid
flowchart LR
    Operator["Operator with approved private access"] --> API
    Runner["Separate VNet-connected runner"] --> API
    Registry["ACR Basic authenticated public endpoint<br/>anonymous and admin disabled"] --> API
    subgraph VNet["Approved virtual network"]
      API["Private FastAPI on Container Apps<br/>0.5 CPU / 1 GiB / one replica"]
      Init["Initialization job<br/>bootstrap managed identity"]
      DNS["Private DNS"] --> PE["SQL private endpoint"]
      API -->|"TLS and runtime Entra token"| PE
      Init -->|"Migration, seed, contained user"| PE
      Runner -->|"Managed identity and scoped blob data role"| BlobPE["Evidence Blob private endpoint"]
      DNS --> BlobPE
    end
    PE --> SQL["Azure SQL Database<br/>GP Gen5 provisioned 2 vCores<br/>public network disabled"]
    BlobPE --> Blob["Private Blob container<br/>full raw run artifacts<br/>lifecycle plus soft-delete retention"]
    Identity["Runtime managed identity<br/>least database privilege"] --> API
    Secrets["Encrypted Container Apps secret references<br/>deployment-generated ephemeral bearer token"] --> API
    Secrets --> Runner
```

## 2. Serverless comparison

```mermaid
flowchart LR
    A["Same database<br/>provisioned 2 vCores"] -->|"Approved scale"| B["Provisioned 4 vCores"]
    B -->|"Restore and capture controls"| A
    A -->|"Validate exact regional capabilities"| C1["GP serverless<br/>suggested 0.5 to 4 vCores<br/>auto-pause disabled"]
    C1 -->|"Separate idle experiment"| C2["Auto-pause enabled<br/>supported delay"]
    C2 -->|"No sessions or user workload CPU"| Paused["Pause eligibility<br/>must be observed"]
    Paused -->|"One timed request"| Resume["Resume latency plus retries<br/>measured separately"]
    Resume -->|"Subsequent stream"| Active["Steady-state measurement"]
    Active -->|"Approved restoration"| A
```

Pause is not guaranteed; feature exclusions and background connections matter.
Configured maximum vCores remain a ceiling.

## 3. Monitoring flow

```mermaid
flowchart LR
    Requests["Workload UTC window and run ID"] --> App["API and dependency telemetry"]
    App --> Insights["Application Insights<br/>public SDK ingestion endpoint"]
    Insights --> Logs["Log Analytics<br/>schema inspected before queries"]
    SQL["Azure SQL"] --> Metrics["Platform metrics<br/>CPU / IO / workers / sessions"]
    SQL --> QS["Query Store and bounded DMVs"]
    Control["Control-plane state and Activity Log"] --> Logs
    Metrics --> REST["Runner MI-only REST collector<br/>distinct ARM and Logs audiences<br/>no diagnostic SQL connection"]
    Logs --> REST
    REST --> Evidence["Correlated private evidence<br/>explicit required and optional coverage"]
    QS --> Observer["Separately approved SQL observer<br/>outside idle and measured workload"]
    Observer --> Evidence
    Evidence --> Report["Sanitized report<br/>measurements separate from estimates"]
```

## 4. Spike handling

```mermaid
flowchart TD
    Incoming["Incoming request"] --> Admission{"Capacity and deadline available?"}
    Admission -->|"No"| Shed["Explicit load-shed outcome"]
    Admission -->|"Yes"| Cache{"Eligible cache hit?"}
    Cache -->|"Yes"| Response["Return response and record latency"]
    Cache -->|"No"| Circuit{"Circuit permits attempt?"}
    Circuit -->|"No"| Reject["Circuit rejection outcome"]
    Circuit -->|"Yes"| Pool["Bounded pool acquisition"]
    Pool --> SQL["Timed SQL execution"]
    SQL -->|"Success"| Response
    SQL -->|"Failure"| Policy{"Retryable, safe, budget and deadline remain?"}
    Policy -->|"Yes"| Delay["Bounded backoff and jitter"]
    Delay --> Circuit
    Policy -->|"No"| Error["Classify final outcome<br/>do not assume throttling"]
```

## 5. In-region availability

```mermaid
flowchart LR
    Client["Client request and recovery observation"] --> App["Resilient application"]
    App -->|"Reconnect after transient interruption"| SQL["Azure SQL managed availability"]
    SQL --> Storage["Service-managed durable storage"]
    Zone["Optional supported zone redundancy"] -.-> SQL
    Health["Resource Health and Service Health"] --> Observe["Correlate with client errors and recovery"]
    Client --> Observe
    SQL --> Observe
```

This is a conceptual service view, not a claim about an exposed replica count or
a customer SLA. Built-in availability is not cross-region DR.

## 6. Cross-region failover group

```mermaid
flowchart LR
    App["Regional application only<br/>no cross-region app failover provisioned"] --> RW["Read-write listener"]
    App -->|"Explicit read-only route, if enabled"| RO["Read-only listener"]
    RW --> Primary["Primary region<br/>one writable database"]
    Primary -->|"Asynchronous replication<br/>lag and data-loss risk evaluated"| Secondary["Secondary region<br/>read-only database"]
    RO --> Secondary
    Private["Private connectivity and DNS<br/>validated in both regions"] -.-> Primary
    Private -.-> Secondary
    Approval["Approved planned failover<br/>manual policy by default"] --> Swap["Role transition and listener reconnection"]
    Swap -.-> Primary
    Swap -.-> Secondary
```

Readable secondary and active/active application hosting do not mean multi-primary
writes. Forced failover may lose data and requires separate explicit approval.

## 7. Evidence collection

```mermaid
flowchart LR
    Manifest["Run manifest<br/>versions, hashes, UTC, changed variable"] --> Raw["Private ignored run directory"]
    Local["VNet-connected local runner<br/>full request artifacts"] --> Raw
    Job["Container Apps runner job<br/>all raw run files"] --> Upload["Mandatory managed-identity upload<br/>fail job if any persistence fails"]
    Upload --> Blob["Private Blob container<br/>run-ID prefix and complete artifact set"]
    Upload --> Summary["POC_EVIDENCE file/hash receipts only<br/>POC_EVIDENCE_UPLOAD manifest hash"]
    Blob --> Inventory["Completion manifest written last<br/>all file paths, lengths, SHA-256"]
    Inventory --> Download
    Blob --> Download["Authorized VNet-connected download<br/>verify inventory and hashes"]
    Summary --> Download
    Download --> Raw
    Platform["Platform metrics, Query Store,<br/>activity and pricing inputs"] --> Raw
    Raw --> Sanitize["Allowlist and identifier replacement"]
    Sanitize --> Scan["Scan worktree, index, history,<br/>evidence and manual review"]
    Scan --> Bundle["Approved sanitized bundle"]
    Bundle --> Decisions["Evidence-based decision<br/>or more testing required"]
```

## 8. Public-repository controls

```mermaid
flowchart LR
    Change["Small reviewable change"] --> Local["Lint, tests, dependency review,<br/>secret and identifier scanning"]
    Local --> PR["Pull request review"]
    PR --> CI["Nondeploying validation CI"]
    CI --> Rules["Owner-configured ruleset<br/>required checks and review"]
    Rules --> Public["Placeholder-only public source"]
    Public -.-> Manual["Separately approved deployment"]
    Manual --> Env["Protected GitHub environment<br/>OIDC federation, no stored client secret"]
    Config["Private untracked customer configuration"] --> Manual
    Evidence["Sanitized evidence approval"] --> Public
```

Rulesets, environment approvals, federation, and scanning features must be
configured by repository owners; files in Git do not enable them automatically.
