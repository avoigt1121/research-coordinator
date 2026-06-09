# Claude Code Prompt: Add Next 8 PDAC Datasets

I'm adding the next batch of PDAC bulk transcriptomics datasets to the DecoupleRpy Agent.
Below is everything you need. Work through datasets in priority order, committing to
biodata-registry after each one is validated.

---

## Architecture

Two repos are involved:

**biodata-registry** (`/path/to/biodata-registry`)
- Contains all dataset manifests as YAML in `biodata_registry/manifests/`
- `gse71729_moffitt.yaml` is the fully annotated reference — read it before writing any new manifest
- Auto-discovers manifests at import; no code changes needed to register a new dataset
- Validate with: `pytest tests/` — all tests must pass before committing

**DecoupleRpy_Agent** (`/path/to/DecoupleRpy_Agent`)
- Consumes biodata-registry as a pip package (`pip install -e /path/to/biodata-registry`)
- h5ad files are hosted at `anni-voigt/pdac-research-data` on HuggingFace
- Run `dataset_validate_manifest_against_data` tool against each new dataset before finalizing manifest

---

## Established Pattern (follow this for each dataset)

1. Download expression matrix + metadata from source
2. Assemble into h5ad: samples as obs, genes/probes as var
   - Microarray: var index = probe IDs if `requires_collapse: true`, else gene symbols
   - RNA-seq: var index = gene symbols or Ensembl IDs per manifest
   - Fix mixed-type var columns (cast to str if needed)
3. Upload h5ad to `anni-voigt/pdac-research-data` on HuggingFace
4. Write manifest YAML in `biodata_registry/manifests/`
5. Run `pytest tests/` in biodata-registry — must pass
6. Run `dataset_validate_manifest_against_data` — confirm semantics match actual file
7. Commit manifest to biodata-registry, push to GitHub

---

## Controlled Vocabularies (manifest fields)

- `modality`: bulk_microarray | bulk_rnaseq
- `data_level`: raw_counts | log_expression | log_ratio | normalized | tpm | fpkm
- `feature_id_type`: probe_id | gene_symbol | ensembl_gene_id | entrez_id
- Path A = DESeq2 → only for `data_level: raw_counts`
- Path B = limma/ttest → everything else

---

## Data Quality Check (do this before writing each manifest)

For each dataset, before finalizing the manifest:

1. Read the original paper's Methods section — note cohort composition, exclusion
   criteria, normalization pipeline
2. Check whether "normal" samples are truly healthy tissue or adjacent non-tumor
   pancreatic tissue — this distinction affects valid DE contrasts and must be
   noted in `limitations`
3. Note if subtype labels are clinician-assigned, computationally inferred, or
   absent — encode this distinction in `limitations`
4. If sample counts in GEO/source don't match the paper, flag the discrepancy
   and use only samples with clear metadata
5. Check expression value range — if outside typical bounds (log2 microarray: 2–14,
   raw counts: integer, TPM: 0–1000+), document in `limitations`
6. Verify GPL platform annotation is current — outdated probe mappings silently
   corrupt probe collapse
7. If any issue rises to "this will silently corrupt an analysis if ignored"
   (like TCGA-PAAD's non-PDAC sample contamination), add an enforcement mechanism
   in the manifest — not just a `limitations` note. See `tcga_paad` manifest for
   the `required_filters` pattern used there.

---

## Datasets to Add (in priority order)

### 1–4: GEO Microarray (same pipeline as existing GSE datasets)

**GSE15471** (Badea 2008)
- ~36 matched tumor/normal pairs, Affymetrix
- PDAC vs normal contrast
- Expect `data_level: log_expression`, `feature_id_type: probe_id`, `requires_collapse: true`
- QUALITY FLAG: "Normal" samples are adjacent non-tumor pancreatic tissue, not
  truly healthy pancreas. Document in `limitations`. Valid for tumor-vs-adjacent
  comparisons; caution for claims about healthy baseline expression.

**GSE21501** (Stratford 2010)
- ~63 samples, survival data available
- One of the original PDAC survival signature cohorts
- Check for OS/DFS columns in metadata
- QUALITY CHECK: Verify survival endpoint completeness — some GEO deposits have
  partial survival annotation. Only encode endpoints where >80% of samples have data.

**GSE57495**
- ~63 samples, microarray
- Appears in subtype benchmarking papers
- Same pipeline; no known specific quality issues — run standard checks

**Collisson 2011** (Nature Medicine — original QM/exocrine/classical subtype paper)
- Verify GEO accession before downloading (likely GSE17891 — confirm)
- Critical: get subtype labels (quasi-mesenchymal, exocrine-like, classical) into obs metadata
- QUALITY FLAG: Subtype labels in GEO metadata may not exactly match the paper's
  final assignments. Cross-check sample-level labels against Table S1 in the paper
  supplement before encoding. If they differ, use the paper's supplement as ground truth
  and note the discrepancy in `limitations`.

### 5: ICGC Canadian Cohort

**PACA-CA**
- First check if it's in the `rmoffitt/pdacR` R package (same extraction pattern
  used for paca_au_rnaseq, paca_au_array, puleo_2018 — run `data(package="pdacR")`
  and check available objects)
- If not in pdacR: download from ICGC data portal (icgc.org), expression + donor metadata
- RNA-seq → expect raw counts → Path A / DESeq2
- Key metadata: subtype labels if available, survival endpoints
- QUALITY CHECK: Verify which ICGC data release version is used — sample counts
  changed between releases. Note the release version in `metadata_source`.

### 6: CPTAC-PDA

**CPTAC Pancreatic Ductal Adenocarcinoma**
- Source: CPTAC data portal (cptac-data-portal.georgetown.edu) or PDC portal
- ~140 samples, proteogenomics — we want the RNA-seq layer only, not proteomics
- Confirm data_level from portal readme (may be FPKM or gene-level counts)
- Key metadata: tumor grade, survival if available
- QUALITY FLAG: CPTAC RNA-seq normalization is pipeline-specific and not directly
  comparable to standard RPKM/TPM from other cohorts. Document normalization
  method in `limitations`. Do not combine with other cohorts without batch correction.
- Note: extraction from CPTAC portal is new work — no existing pipeline. Build
  the download/assembly step fresh; the manifest + h5ad integration is identical
  to existing datasets once data is obtained.

### 7–8: Recent Cohorts

**Chan-Seng-Yue 2020** (Nature Genetics — COMPASS subtypes)
- Find GEO accession from the paper (search GEO for "Chan-Seng-Yue pancreatic")
- RNA-seq, ~200 samples
- QUALITY FLAG: COMPASS subtype labels are cell-type deconvolution-based (inferred),
  not clinically assigned. Encode in `limitations` as: "Subtype labels are
  computationally inferred via the COMPASS deconvolution method; not directly
  observed clinical classifications." If labels are in GEO metadata, use them
  directly. If not, note absence — do not infer them.

**Additional cohort (use judgment)**
- Any dataset with n>50, open access, bulk transcriptomics, published survival
  or subtype data not already covered
- Prioritize datasets from 2020–2024 that appear in PDAC subtype benchmarking papers
- Apply all quality checks above before committing

---

## Success Criteria

- All new manifests pass `pytest tests/` in biodata-registry
- All new manifests pass `dataset_validate_manifest_against_data`
- h5ad files uploaded to `anni-voigt/pdac-research-data`
- Each manifest includes: dataset_id, title, accession, organism, modality,
  platform, data_level, feature_id_type, expression_source, metadata_source,
  group_columns, valid_workflows, limitations
- Survival endpoints documented in manifest if available (see puleo_2018.yaml
  as reference for multi-endpoint manifests)
- Quality issues documented in `limitations`; enforcement mechanisms added for
  any issue that would silently corrupt analysis
- biodata-registry pushed to GitHub after each validated dataset

---

## What NOT to Do

- Do not modify any tool code in DecoupleRpy_Agent — the architecture is
  manifest-driven; zero tool changes should be needed
- Do not add datasets with n<20 or no clear tumor/normal or subtype contrast
- Do not invent metadata columns — if a column isn't in the actual file, it
  doesn't go in the manifest
- Do not commit a manifest that fails validation
- Do not encode subtype labels as clinician-assigned if they are computationally
  inferred — the distinction matters for how the agent frames results to users
