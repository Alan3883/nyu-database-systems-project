# Security and Privacy

## 1. Credentials

**No credential appears anywhere in the repository.** Verified by scanning before packaging.

| Secret | How it is handled |
|--------|-------------------|
| Census API key | Redacted to `<CENSUS_API_KEY>` in the manifest; supplied via `CENSUS_API_KEY` env var |
| GCP project and bucket | Supplied via `GCP_PROJECT` and `GCS_BUCKET` env vars; masked in evidence files |
| PostgreSQL password | Container environment only; never in a file |
| Payment data | Never stored; only a gateway authorization reference |

Cloud evidence files mask project and bucket names before they are written to disk.

## 2. Least privilege

Four NOLOGIN group roles, defined in `database/physical/06_permissions.sql`:

| Role | Privileges | Explicitly denied |
|------|-----------|-------------------|
| `insurance_app` | SELECT everywhere; INSERT/UPDATE on transactional tables; INSERT only on audit tables | DELETE on any business table; UPDATE on audit trails |
| `insurance_analyst` | SELECT only | `CUSTOMER.SSN_TIN` (column-level revoke); all writes |
| `ml_writer` | Read `DATASET`/`DATA_ASSET`/hybrid tables; write ML tables | **Write access to every insurance table** |
| `data_loader` | Load hybrid/reference tables; refresh the view | Insurance transactional tables |

No role holds SUPERUSER. Tested: `test_analyst_cannot_read_ssn` confirms the analyst role has
no column privilege on `SSN_TIN`.

The `ml_writer` restriction is a structural control: even a compromised ML pipeline cannot
modify a customer, quote, or contract record.

## 3. PII minimisation

| Principle | Implementation |
|-----------|----------------|
| Collect only what is needed | `CUSTOMER` holds name, DOB, type, status, and one tax identifier |
| No health records | **No table in the model can hold an individual health record** |
| No cardholder data | `PAYMENT_AUTHORIZATION` stores a gateway reference only, keeping the database out of PCI scope |
| Documents outside the database | PDFs and policy documents stay in the lake/document store; only metadata and checksums are stored |
| Aggregates only for public health | `HEALTH_OBSERVATION` is county and state level |

## 4. Regional health data handling

The most sensitive design question in this project is how public health data touches
insurance records. The answer is deliberately narrow:

1. Public health data is **aggregate** — county and state, never a person.
2. It joins to `ACCOUNT` through `GEOGRAPHIC_AREA`, never to `CUSTOMER`.
3. When it reaches a quote it must be labelled `SourceType='RegionalAggregate'`, and
   `ck_qrf_source` rejects any patient-level source type outright.
4. It is advisory context for underwriter awareness, not a rating input.

See `model_governance.md` section 4 for the fairness analysis behind these controls.

## 5. Encryption

| Layer | At rest | In transit |
|-------|---------|------------|
| Local PostgreSQL | Host disk encryption (FileVault) | Local socket |
| Google Cloud Storage | Google-managed keys, on by default | TLS |
| BigQuery | Google-managed keys, on by default | TLS |
| Cloud transfers | — | TLS via `gcloud` |

## 6. Audit logging

| Layer | Mechanism |
|-------|-----------|
| Quote workflow | `QUOTE_STATUS_HISTORY`, append-only by grant |
| Row changes | `CreatedAt` / `UpdatedAt` with a trigger on `ACCOUNT`, `CUSTOMER`, `CONTRACT` |
| Model runs | `ML_RUN` with config, seed, and metrics |
| Model review | `ML_CLUSTER_SUMMARY.ReviewedBy` and `ReviewedAt` |
| Pipeline runs | `logs/*.log` |
| Cloud operations | `architecture/cloud_evidence/`, with identifiers masked |
| GCP platform | Cloud Audit Logs |

The audit trail is trustworthy because `insurance_app` cannot UPDATE or DELETE
`QUOTE_STATUS_HISTORY` — only insert into it.

## 7. Cloud access control

| Control | Setting |
|---------|---------|
| Bucket access | Uniform bucket-level access, private |
| Public access | None |
| Identity | Cloud IAM, `gcloud auth login` |
| Upload scope | Metadata, curated, samples, ML outputs only |
| Never uploaded | Credentials, service-account keys, database volumes, full raw datasets |

## 8. Data loss and leakage prevention

| Risk | Control |
|------|---------|
| Raw data altered | SHA-256 verified for all 10 files before packaging |
| Secret committed | Credential scan before packaging |
| Over-broad upload | Upload scripts enumerate specific directories |
| Accidental deletion | No DELETE grant on business tables; status change instead |
| Model output leaking into pricing | `ml_writer` cannot write to any insurance table |
| Re-identification from aggregates | Only county and state levels are stored; no small-cell reporting |
