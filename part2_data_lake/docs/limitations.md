# Limitations

Stated plainly so no reader overestimates what this project demonstrates.

## 1. Cloud analytics ran without Cloud Storage

The cloud requirement was executed on 08/06/26 in Google BigQuery: seven tables loaded, four
analytical queries run, evidence captured in `architecture/cloud_evidence/part3/`.

Cloud Storage was **not** used. It requires an active billing account, and both billing
accounts on the student account were closed. BigQuery Sandbox needs no billing account, so the
tables were loaded there directly from local files. Two consequences follow:

- There is no GCS `part3/` prefix, so the BigQuery tables are native rather than external.
- Sandbox tables expire automatically after 60 days.

The Part II Cloud Storage bucket no longer exists either; its project was deleted after Part II
submission to stop charges. That project remained recoverable until roughly 08/22/26 via
`gcloud projects undelete`. The Part II evidence files in the repository are the graded record
of that deployment and are unchanged.

## 2. The ML corpus is very small

One 18-page report, 4,093 extractable words, 32 chunks. This cannot represent the insurance
market or public health literature. Adding documents could change the cluster structure
substantially.

## 3. Cluster separation is weak

Silhouette 0.1212. All chunks come from one argument by one author, so they genuinely overlap
in vocabulary. The clusters are soft groupings, not crisp topics, and support no automated
decision.

## 4. One cluster is an artefact

Cluster 2 is held together by the publisher's name appearing in citations and credits, not by
subject matter. Its seven chunks are heterogeneous and should not be summarised as one theme.

## 5. No cluster interpretation is approved

All six are `HumanReviewed = FALSE`. Everything in `business_insights.md` is model output plus
the author's reading.

## 6. Insurance data is demonstration data

The 50 accounts, 200 customers, 300 contracts, and 121 quotes were generated to exercise the
schema. A real book of business would change which indexes the planner selects and could
change the physical design conclusions.

## 7. Scale evidence is synthetic

The 222x index improvement was measured on 500,000 generated rows, not real observations. The
generated data has uniform key distribution; real data is skewed, which would change absolute
timings though not the direction of the result.

## 8. Partitioning is not applied to live tables

It is evaluated and proven on synthetic data. `HEALTH_OBSERVATION` holds 320 rows, where
partitioning would add overhead without benefit.

## 9. One governance rule is a process control, not a constraint

The rule that regional context informs underwriter awareness but is not a rating input is
documented in UC-07 and UC-09 and in `model_governance.md`. It is not enforced by the
database, because rating happens outside it. A future implementation should enforce and audit
it in the rating engine.

## 10. No application program

The assignment states one is not required at this stage. The workflow is specified as use
cases and supporting tables with constraint tests, not as running code.

## 11. Text extraction has no OCR

Two pages of DS010 are cover art and a section divider with little text. They are counted and
reported, not recovered. OCR was not used because the PDF has a text layer.

## 12. Single-database deployment

PostgreSQL 16 runs in one local container. No replication, failover, or backup strategy is
implemented or tested.

## 13. The materialized view is refreshed manually

`REFRESH MATERIALIZED VIEW CONCURRENTLY` is documented and tested, but no scheduler runs it.
In production this would be triggered by the curated load job.
