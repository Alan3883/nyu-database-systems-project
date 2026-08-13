# Part I — Conceptual model

| File | What it is |
|------|------------|
| `EDA_ER_Diagram.mmd` | Conceptual entity-relationship model, Mermaid source |
| `EDA_ER_Diagram.png` | Rendered ER diagram |
| `EDA_ER_Diagram.pdf` | Print version of the ER diagram |
| `Project_Part1_Report.docx` | Part I report: business requirements and the conceptual model |
| `ProjectPart1.pdf` | The assignment brief, kept for reference |

Twenty entities across four subject areas: party and account, contract and
benefit, distribution, and reference data.

## What Part I established, and what still holds in Part IV

* **The entity set.** ACCOUNT, CUSTOMER, ASSOCIATE, CONTRACT, CONTRACT_BENEFIT,
  CONTRACT_PREMIUM and their relationships. Part II normalised these into 26
  logical tables; Part IV maps them through SQLAlchemy and reads and writes them
  from the running application.
* **The decision that an issued policy is a CONTRACT.** Part III added six quote
  tables *in front of* that entity rather than a parallel POLICY table, and
  Part IV converts an accepted quote into exactly that CONTRACT row. Had Part I
  modelled a separate policy entity, the premium history would have been split
  across two hierarchies.
* **The business questions** that later justified bringing in public-health
  data: regional portfolio review and product research — never individual
  underwriting. That boundary is what the Part IV governance controls enforce.

See the root [`README.md`](../README.md) for how the four parts fit together.
