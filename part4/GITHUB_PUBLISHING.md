# Publishing the software to GitHub

The Part IV assignment requires the software portion of the project to be
available through a GitHub link, and that link must appear in the report. The
repository has not been published yet, so that requirement is **not complete**.

Everything needed to publish is ready: the tree is organised, `.gitignore` is
written, and the source has been scanned for credentials. What remains is the
commit and push, which must be made under your own identity.

This file is not part of the Brightspace submission.

---

## 1. What to publish

Publish the whole course directory so the repository contains Parts I to IV:

```text
2433-Database/
├── part1/               Part I conceptual model and report
├── part2_data_lake/     Parts II and III: data lake, schema, physical design, ML pipeline
├── part4/               Part IV application, jobs, tests, evidence, report
└── .gitignore           already written; see step 2
```

`Mo_p3_su26/`, `HW/`, and `Lecture/` are not project software. Exclude them.

## 2. The root .gitignore is already written

`2433-Database/.gitignore` exists and has been dry-run against the working
tree. With it in place the commit is **258 files, about 20.7 MB**. It excludes,
in order: credentials; the 300 MB of re-downloadable public data under
`raw/`, `processed/`, and `sample_data/`; the derived retraining fixtures;
packaging output under both `submission/` directories; run logs; the
implementation diaries and pre-work inventories; `HW/`, `Lecture/`, and
`Mo_p3_su26/`; and the usual caches and OS files.

Read it once before you commit. If you disagree with an exclusion, delete the
line — every rule carries a comment saying why it is there.

## 3. Verify no secret is about to be committed

```bash
git init -b main
git add -A
git diff --cached --name-only | grep -iE "\.env$|key|credential|secret" || echo "clean"
git diff --cached --name-only | xargs -I{} sh -c 'grep -lIE "ghp_[A-Za-z0-9]{20}|AKIA[0-9A-Z]{16}|BEGIN [A-Z ]*PRIVATE KEY" "{}" 2>/dev/null' || echo "no key material"
```

`part4/.env` holds the local database password and must not appear. If it does,
stop and fix `.gitignore` before committing.

Expected staged size: roughly 20 MB.

## 4. Commit under your own identity

```bash
git config user.name  "Alan Mo"
git config user.email "bm3883@nyu.edu"

git commit -m "Database Systems course project, Parts I-IV

Part I  conceptual ER model
Part II logical schema, four-zone data lake, ten public datasets
Part III physical design, quote workflow, TF-IDF + K-means over DS010,
        BigQuery Sandbox analytics
Part IV end-to-end Flask + SQLAlchemy application, checksum-driven source
        monitoring, failure-safe retraining, governed ML-to-ODS mapping"
```

Check the author before pushing — this is the step that matters for the
contributor list:

```bash
git log --format='%an <%ae>%n%b' -1
```

The output must show only your name and no `Co-Authored-By:` trailer.

## 5. Create the repository and push

```bash
gh repo create nyu-database-systems-project --public --source=. --remote=origin --push
```

Or, if you prefer to create it in the GitHub web interface first:

```bash
git remote add origin https://github.com/<your-account>/nyu-database-systems-project.git
git push -u origin main
```

## 6. Verify

```bash
gh repo view --web
```

Confirm the repository opens without signing in (the grader will not have
access otherwise), that `part1/`, `part2_data_lake/`, and `part4/` are present,
and that the contributor list shows only you.

## 7. Put the URL in the report

The report currently states that the repository is prepared but not yet
published. Once the URL exists, update it in three places in
`part4/report/Database_Systems_Final_Project_Report.docx`:

1. the title page, under **Software repository**
2. section 1.1, *Software repository*
3. section 9.2, the validation summary row for *Repository*

and change the two **NOT COMPLETE** rows in Appendix F to *Complete*.

Then rebuild the submission archive:

```bash
cd part4
rm -rf submission/mo_final-project_su26 submission/mo_final-project_su26.zip
mkdir -p submission/mo_final-project_su26
cp report/Database_Systems_Final_Project_Report.docx submission/mo_final-project_su26/
cd submission && zip -r -X mo_final-project_su26.zip mo_final-project_su26 -x '*.DS_Store'
unzip -t mo_final-project_su26.zip
```

Also update the status of requirements D3 and D4 in
`part4/docs/final_requirements_traceability.md` from *Not complete* to
*Complete*.

## 8. Restoring the excluded data on a fresh clone

A clone will not contain `raw/`, `processed/`, or the retraining fixtures.
To rebuild them:

```bash
cd part2_data_lake
python3 scripts/download_part2_data.py     # re-downloads the 10 public datasets
python3 scripts/01_inventory_data.py
python3 scripts/02_profile_data.py
python3 scripts/03_build_curated_data.py
cd ../part4
python3 tests/fixtures/make_fixtures.py    # rebuilds the retraining fixtures
```

`part2_data_lake/metadata/download_manifest.json` records each source URL and
its expected SHA-256, so a restored file can be verified against the checksum
the project was built on.
