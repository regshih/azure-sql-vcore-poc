# Cost inputs and comparison method

**Retail estimates are planning inputs and are not the customer’s final contracted
price.** No retail rates are hard-coded here. Customer region, currency, budget,
contract, Azure Hybrid Benefit eligibility and reservation preferences are
**TBD**. Cost savings: **Not demonstrated by this POC run.**

All assumed run hours, storage, traffic and retention are a **POC assumption,
not a confirmed customer requirement.** Separate measured usage from estimated
monthly projection and product guidance.

## Retrieve current prices

Use the [Azure pricing calculator](https://azure.microsoft.com/pricing/calculator/),
[Azure SQL pricing](https://azure.microsoft.com/pricing/details/azure-sql-database/single/),
or [Azure Retail Prices API](https://learn.microsoft.com/rest/api/cost-management/retail-prices/azure-retail-prices).
The public retail API endpoint is `https://prices.azure.com/api/retail/prices`.
This endpoint does not require customer identifiers in source.

1. Select the exact approved region and currency.
2. Filter the service/product/SKU/meter for General Purpose, standard-series,
   provisioned or serverless, licensing model and redundancy as applicable.
3. Inspect `unitOfMeasure`, `retailPrice`, `currencyCode`, region, product/SKU,
   meter and effective start date. Avoid accidentally choosing another hardware
   family, license-included versus benefit rate, reservation term, or duplicate
   meter. Follow pagination; the first page is not necessarily complete.
4. Record retrieval UTC and the exact filters/meter metadata **privately**.
5. Include all surrounding services rather than reporting the SQL compute line
   as the whole solution.
6. Keep negotiated discounts, benefit eligibility and reservations as separate,
   explicit inputs. Do not assume retail or calculator output is contracted cost.

Do not issue deployments to discover pricing. If a matching meter cannot be
identified, mark that estimate incomplete rather than inventing a rate.

## Line-item model

| Line item | Quantity and inputs | Important limitation |
| --- | --- | --- |
| Provisioned SQL compute | Fixed configured capacity × billable hours × matching capacity-unit rate, converted to meter units | Some meters already price a complete capacity; avoid multiplying vCores twice |
| Serverless SQL compute | **Total `app_cpu_billed` vCore-seconds** × matching price per vCore-second | Convert hourly meters by 3,600; do not use CPU% as billed usage |
| SQL data storage | Applicable configured/used storage quantity and meter definition | Remains while paused; used, allocated and configured cap differ |
| Backup storage | Redundancy, retained backup quantity, included allowance and retention | Data size alone cannot predict all backup usage |
| Zone redundancy | Exact tier/hardware/region pricing treatment | Do not assume universally free or a universal surcharge |
| DR secondary | Secondary compute/storage/backups and operating hours | Add monitoring, networking and failover capacity needs |
| Monitoring ingestion | Actual ingested GB by destination/table, retention policy and applicable meter | Verbose per-request logging can dominate small POCs |
| Monitoring retention | Retained volume × billable retention beyond applicable included period | Query and archival charges may apply |
| Application hosting | Container Apps resource allocation, replica active/idle time, requests and jobs | One replica for test consistency does not mean zero idle cost |
| Registry | ACR Basic operation/storage/transfer as applicable | Registry persists after app stops |
| Private raw evidence | Blob storage volume/retention, write/read/list operations, private endpoint/DNS and applicable transfer | Full runner artifacts persist after the job stops; approve retention and cleanup |
| Optional cache | Approved product/tier/capacity/hours, networking and transfer | Disabled by default; no automatic paid Redis substitution |
| Private endpoints/DNS | Endpoint hours, processed data, DNS zones/queries as applicable | Database pause does not stop these charges |
| Network transfer | Region/topology-specific outbound and cross-region traffic | Do not assume all private traffic is free |
| Reservations | Term, scope, eligibility, utilization and benefit allocation | Separate commercial scenario, not applied blindly to all tiers |
| Azure Hybrid Benefit | Explicit eligible licenses and selected meter | Customer eligibility must be confirmed |
| Development operating hours | Explicit schedule per resource | Stopping load does not stop provisioned SQL or all supporting costs |

### Current POC retention and endpoint choices

Local SQL backup redundancy, seven-day short-term backup retention, a 5-GB data
cap, Blob lifecycle deletion after 21 days, and seven-day Blob soft delete are
each a **POC assumption, not a confirmed customer requirement.** Customer
retention and recoverability objectives remain **TBD**.

Lifecycle deletion puts soft-delete-enabled blobs into soft-deleted state.
Model approximately **21 + 7 = 28 days** of possible retained/billable evidence,
plus lifecycle processing timing and any separately retained versions; do not
promise precise deletion or zero cost on day 21. Review actual configured rules
and observed quantities. Soft delete is not immutable retention.

The baseline's authenticated public ACR Basic endpoint avoids the Premium tier
needed for an ACR private endpoint. If customer policy requires private registry
access, cost that additional architecture explicitly rather than claiming Basic
already provides it. Public telemetry ingestion is likewise an explicit
supporting-service boundary, not publicly readable telemetry.

## Serverless CPU and memory

For each active second, compute billing is based on:

```text
max(configured minimum vCores,
    CPU used in vCores,
    configured minimum memory GB / 3,
    memory used GB / 3)
```

The documented General Purpose 0.5 minimum / 4 maximum configuration has 2.1 GB
minimum memory, so the active minimum is `max(0.5, 2.1 / 3) = 0.7 vCore`.
This is a product billing example, **not a measured POC result**. Validate the
chosen memory bounds and use the actual `app_cpu_billed` Total metric for the run.
Compute is not billed while paused, but storage and supporting resources remain.

An API with periodic SQL readiness, persistent pools or background queries may
never pause. Geo-replication/failover groups, LTR and DNS aliases can prevent
pause. Model C1 separately from C2 and never remove required features merely to
claim savings.

## Required estimate worksheet

| Input | Value before customer completion |
| --- | --- |
| Region / currency / retrieval UTC / effective price date | TBD |
| Exact product, SKU, meter, unit, price source | TBD |
| Service tier / hardware / compute tier | Record observed run configuration |
| Provisioned vCores or serverless minimum/maximum/memory | Record observed run configuration |
| Active / no-demand / paused hours | Not demonstrated by this POC run. |
| `app_cpu_billed` total, UTC and coverage | Not demonstrated by this POC run. |
| Pause setting and eligibility | Record observed run configuration |
| Data storage and growth | Not demonstrated by this POC run. |
| Backup redundancy/retention/quantity | TBD |
| Zone redundancy and DR topology | TBD |
| Monitoring ingestion/retention | Not demonstrated by this POC run. |
| Hosting/jobs/registry/evidence blobs/cache/endpoints/network quantities | Not demonstrated by this POC run. |
| Benefit/reservation/contract scenario | TBD |
| Monthly horizon and schedule assumptions | TBD |
| Sensitivity: more active time, higher minimum, resume retries | TBD |
| Cleanup date and remaining-charge check | TBD |

## Decision and cleanup

A failed deployment can leave provisioned SQL, Blob, registry and networking
resources billable. An approved retry in another region/new resource group does
not remove that original partial scope. Inventory and budget both scopes
privately, preserve evidence, and obtain explicit cleanup approval for each.
Do not treat a failed application deployment as zero infrastructure cost.

Compare matched workload outcomes first. A cheaper configuration that misses an
approved objective may not be a viable option. A brief accelerated run cannot be
linearly extrapolated to monthly pause, cache or memory behavior without an
explicit model and sensitivity analysis.

Document whether costs are observed usage, retail estimate, or invoiced charges.
Use “more testing required” when coverage or pricing is incomplete. Verify cleanup
of the dedicated POC scope and optional resources, then inspect delayed billing
records for residual charges. Never claim zero cost simply because the last
test stopped.

References: [serverless billing](https://learn.microsoft.com/azure/azure-sql/database/serverless-tier-billing),
[pause eligibility](https://learn.microsoft.com/azure/azure-sql/database/serverless-tier-auto-pause-resume),
[Azure Cost Management](https://learn.microsoft.com/azure/cost-management-billing/costs/overview-cost-management),
[lifecycle deletion and soft delete](https://learn.microsoft.com/azure/storage/blobs/lifecycle-management-policy-delete),
[ACR private endpoints](https://learn.microsoft.com/azure/container-registry/container-registry-private-endpoints).
