# Reproducibility and Main Results — Fashion-VN 

This document is the primary reference for reproducing the pipeline and verifying the project's reported results. The version described here is **set-v2**, which includes models for eight categories: `top`, `dress`, `pants`, `skirt`, `jacket`, `bag`, `hat`, and `set`.

> Reproducibility scope: the data is partitioned using leakage-resistant group splits; the ImageNet-1K ResNet18 backbone is frozen; and VSE, Word2Vec, K-means, and both attribute-head branches are trained from weak title labels. The gold set contains 400 products and is used only for evaluation—not for training, epoch selection, or threshold calibration.

## 1. Research Questions and Outputs

The project addresses three main research questions:

1. Can a shared image–title representation space be learned from Vietnamese e-commerce data using weak supervision?
2. Can combining word semantics with spatial activation maps reveal useful fashion concepts?
3. How do the schema-guided and discovered-concept prediction branches perform against independently annotated gold labels?

The main outputs are:

- a manifest with leakage-resistant splits and weak labels;
- a `512 × 7 × 7` ResNet18 feature cache for each image;
- eight category-specific 512-dimensional VSE models;
- 64-dimensional Word2Vec, 49-dimensional EAAM, and spatial–semantic representations for K-means;
- 208 discovered-concept heads and 36 schema heads;
- image-only predictions with an abstention mechanism;
- gold-set evaluation on 400 products, including bootstrap confidence intervals and error analysis.

## 2. Authoritative Artifacts

| Content | File |
|---|---|
| Data report and Evaluation Protocol | [`outputs/prepared/DATA_REPORT.md`](outputs/prepared/DATA_REPORT.md) |
| set-v2 audit and manifest | [`outputs/prepared_set_v2/audit.json`](outputs/prepared_set_v2/audit.json), [`outputs/prepared_set_v2/manifest.jsonl`](outputs/prepared_set_v2/manifest.jsonl) |
| Gold labels for 400 products | [`outputs/prepared/annotation_blind.csv`](outputs/prepared/annotation_blind.csv) |
| Training configuration and results | [`models/local_resnet18_set_v2/run_summary.json`](models/local_resnet18_set_v2/run_summary.json) |
| Machine-readable evaluation summary | [`outputs/evaluation_set_v2/evaluation_summary.json`](outputs/evaluation_set_v2/evaluation_summary.json) |
| Detailed evaluation report | [`outputs/evaluation_set_v2/evaluation_report_vi.md`](outputs/evaluation_set_v2/evaluation_report_vi.md) |
| Schema predictions | [`outputs/predictions_set_v2_schema/image_scores.csv`](outputs/predictions_set_v2_schema/image_scores.csv) |
| Discovered-concept predictions | [`outputs/predictions_set_v2_discovered/image_scores.csv`](outputs/predictions_set_v2_discovered/image_scores.csv) |

Files under `outputs/evaluation_400` are historical baselines from before the `set` category was fully incorporated. Do not combine those figures with the set-v2 results.

## 3. Reproduction Environment

The reported run used the following environment:

| Component | Configuration |
|---|---|
| Operating system | Windows |
| Python | 3.12.0 |
| PyTorch | 2.14.0, CPU |
| Torchvision | 0.29.0, CPU |
| Backbone | Torchvision ResNet18 with ImageNet-1K pretrained weights |
| Seed | 42 |
| Threads | 4 |
| VSE dimension | 512 |
| K-means | 30 clusters/category, `n_init=10` |
| Ranking-loss margin | 0.2 |
| Batch size | 64 |
| Learning rate | 0.001 |
| Optimizer | AdamW, weight decay `1e-4` |
| Early stopping | Patience 5, maximum 30 epochs |
| Export rule | Score ≥ 0.70 and runner-up margin ≥ 0.15 |

Create the environment from the lock file:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
```

The first cache run may require network access to download the pretrained weights. Torchvision then uses the local cache at `.cache/torch`.

## 4. Input Data Checks

The data must have at least the following structure:

```text
data/
├── fashion_raw.xlsx
└── shopee_img/
    ├── 00001.jpg
    └── ...
```

Do not add images that are not referenced by the data table to the pipeline. Do not automatically replace the gold file, because it is a manually annotated artifact.

SHA-256 checksums for the current run:

| File | SHA-256 |
|---|---|
| `data/fashion_raw.xlsx` | `27a98bfc8794d86a6a86d2dea06223b8e30b6da69e2971a6076f8c868591d3df` |
| `outputs/prepared/annotation_blind.csv` | `4b001415c74f5340a1308daf8d65b0c623849122c29c0237829f8889658d4b72` |
| `outputs/prepared_set_v2/manifest.jsonl` | `337567a29b945d598edf2cbff8a4e4da26980382bf69121489ad7a65fc8e8fdb` |
| `models/local_resnet18_set_v2/run_summary.json` | `26f899bf3981661d0024aa2d84a0a353c02bb941cbf206d8deaf17ae6c5e9b7e` |
| `outputs/evaluation_set_v2/evaluation_summary.json` | `2229f573e90e92b7a69c8c108fe45e1a968c96a3fe6b0f1a89093609ddd82088` |
| `requirements-lock.txt` | `7f991582cc6dc1d377a1733c483fb0b4678bc848cd610d84cd07daabdd13307e` |

Recheck the hashes on Windows:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath 'data/fashion_raw.xlsx'
Get-FileHash -Algorithm SHA256 -LiteralPath 'outputs/prepared/annotation_blind.csv'
Get-FileHash -Algorithm SHA256 -LiteralPath 'outputs/prepared_set_v2/manifest.jsonl'
```

## 5. Rerunning the Pipeline Without Overwriting Current Results

The commands below write all new artifacts to `outputs/reproduction` and `models/reproduction`. They do not overwrite the gold labels or reported models.

### 5.1. Prepare the Data and Create the set-v2 Manifest

```powershell
.\.venv\Scripts\python.exe -m fashion_vn.prepare `
  --xlsx data/fashion_raw.xlsx `
  --image-root data `
  --out outputs/reproduction/prepared `
  --min-df 5 `
  --seed 42 `
  --review-size 200

.\.venv\Scripts\python.exe scripts/build_set_v2_manifest.py `
  --source outputs/reproduction/prepared/manifest.jsonl `
  --out outputs/reproduction/prepared_set_v2 `
  --min-df 5
```

The split is constructed from connected groups based on normalized titles, SHA-256, and exact dHash. Duplicate records remain in the same split to reduce leakage.

### 5.2. Cache Image Features

```powershell
.\.venv\Scripts\python.exe -m fashion_vn.cache `
  --manifest outputs/reproduction/prepared_set_v2/manifest.jsonl `
  --out outputs/reproduction/cache_resnet18 `
  --backbone resnet18 `
  --batch-size 16 `
  --workers 0 `
  --threads 4 `
  --device cpu
```

Images are rotated according to EXIF metadata, converted to RGB, letterboxed to `224 × 224`, normalized with ImageNet statistics, and processed inside `torch.inference_mode()`. Cache entries are stored as `float16` and keyed by the SHA-256 hash of the image content.

### 5.3. Train the Eight VSE Models and Discovered Heads

```powershell
.\.venv\Scripts\python.exe -m fashion_vn.train `
  --manifest outputs/reproduction/prepared_set_v2/manifest.jsonl `
  --cache outputs/reproduction/cache_resnet18 `
  --out models/reproduction/local_resnet18_set_v2 `
  --categories top dress pants skirt jacket bag hat set `
  --min-df 5 `
  --min-products 50 `
  --min-head-examples 20 `
  --dim 512 `
  --clusters 30 `
  --epochs 30 `
  --head-epochs 10 `
  --patience 5 `
  --batch-size 64 `
  --lr 0.001 `
  --seed 42 `
  --threads 4
```

Only rows with valid images that do not carry the `listing_multiple_variants` or `possible_negation_review` flags and belong to one of the eight trained categories are included in VSE training. Validation ranking loss uses weak labels and serves only for early stopping.

### 5.4. Train the Schema Heads

```powershell
.\.venv\Scripts\python.exe -m fashion_vn.schema_heads `
  --manifest outputs/reproduction/prepared_set_v2/manifest.jsonl `
  --cache outputs/reproduction/cache_resnet18 `
  --models models/reproduction/local_resnet18_set_v2 `
  --epochs 30 `
  --min-count 5 `
  --threads 4 `
  --seed 42
```

### 5.5. Run Inference for Both Branches

```powershell
.\.venv\Scripts\python.exe -m fashion_vn.predict `
  --manifest outputs/reproduction/prepared_set_v2/manifest.jsonl `
  --cache outputs/reproduction/cache_resnet18 `
  --models models/reproduction/local_resnet18_set_v2 `
  --out outputs/reproduction/predictions_discovered `
  --head-type discovered `
  --threshold 0.70 `
  --margin 0.15 `
  --threads 4

.\.venv\Scripts\python.exe -m fashion_vn.predict `
  --manifest outputs/reproduction/prepared_set_v2/manifest.jsonl `
  --cache outputs/reproduction/cache_resnet18 `
  --models models/reproduction/local_resnet18_set_v2 `
  --out outputs/reproduction/predictions_schema `
  --head-type schema `
  --threshold 0.70 `
  --margin 0.15 `
  --threads 4
```

### 5.6. Evaluate Against the Gold Set

```powershell
.\.venv\Scripts\python.exe -m fashion_vn.evaluate_wide_gold `
  --gold outputs/prepared/annotation_blind.csv `
  --out outputs/reproduction/evaluation `
  --manifest outputs/reproduction/prepared_set_v2/manifest.jsonl `
  --schema-scores outputs/reproduction/predictions_schema/image_scores.csv `
  --discovered-scores outputs/reproduction/predictions_discovered/image_scores.csv `
  --models models/reproduction/local_resnet18_set_v2 `
  --branches schema discovered `
  --bootstrap 2000
```

`set_type_gold` uses the parent label `set`: the 84 products with `category_gold=set` receive `set`, while the other 316 products receive `not_applicable`. During evaluation, the four weak subtypes—`gym_set`, `sports_set`, `ao_dai`, and `casual_set`—are merged into the parent label. Therefore, this result does not measure subtype discrimination.

### 5.7. Unit Tests and Evaluation Figures

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

.\.venv\Scripts\python.exe scripts/plot_evaluation_confusions.py `
  --evaluation-dir outputs/reproduction/evaluation
```

Run the analysis notebooks in the following order:

1. `notebooks/dataset_initial_audit.ipynb`
2. `notebooks/vietnamese_title_processing_weak_labels.ipynb`
3. `notebooks/image_preprocessing_feature_extraction.ipynb`
4. `notebooks/joint_visual_semantic_embedding.ipynb`
5. `notebooks/spatially_aware_concept_discovery.ipynb`
6. `notebooks/two_attribute_prediction_branches.ipynb`
7. `notebooks/evaluation.ipynb`

The notebooks provide analysis and visualization. The JSON/CSV artifacts listed in Section 2 are the authoritative sources for the reported figures.

## 6. Data Flow and Filtering Rules

![Dataset audit summary](outputs/figures/dataset_audit/figure_3_2_2_dataset_summary.png)

The dataset contains 10,798 products and 10,782 distinct image contents. The current split consists of 8,673 training, 1,071 validation, and 1,054 test products. Within the training split, 7,872 image–title pairs are actually used to train the VSE models:

| Training filter step | Products |
|---|---:|
| Initial training split | 8,673 |
| Exclude categories without a VSE model: `unknown` 223, `fabric` 13, `shoe` 4 | −240 |
| Exclude `listing_multiple_variants` | −552 |
| Exclude `possible_negation_review` | −9 |
| **Used for VSE training** | **7,872** |

The validation set decreases from 1,071 to 969 pairs after excluding 30 `unknown` products and 72 products with multiple variants. There are no broken images in the training subsets, and no additional rows are removed after applying the `DF ≥ 5` vocabulary filter.

## 7. VSE Results

### 7.1. Data by Category

![Inputs to category-specific VSE models](outputs/figures/joint_embedding/figure_3_6_1_embedding_inputs.png)

| Category | Training pairs | Validation pairs | Vocabulary | Best epoch | Best validation ranking loss |
|---|---:|---:|---:|---:|---:|
| top | 1,967 | 240 | 594 | 2 | 0.1582 |
| dress | 1,815 | 198 | 490 | 3 | 0.1659 |
| pants | 1,069 | 139 | 382 | 4 | 0.1449 |
| skirt | 676 | 94 | 253 | 3 | 0.1538 |
| jacket | 1,110 | 134 | 382 | 4 | 0.1449 |
| bag | 413 | 60 | 187 | 8 | 0.2015 |
| hat | 342 | 36 | 174 | 7 | 0.1320 |
| set | 480 | 68 | 241 | 5 | 0.1513 |
| **Total** | **7,872** | **969** | — | — | — |

### 7.2. Ranking-Loss History

![VSE training and weak-validation ranking loss](outputs/figures/joint_embedding/figure_3_6_2_training_histories.png)

Training loss approaches zero in all eight categories, while weak-validation loss typically reaches an early minimum and then plateaus or increases slightly. This gap indicates that the models continue fitting the weak training labels without a corresponding improvement in generalization, making early stopping necessary. `hat` has the lowest best loss (0.1320), while `bag` has the highest (0.2015). Ranking loss is not accuracy and is not computed from the gold labels.

### 7.3. Image–Title Alignment

| Category | Matched cosine mean | Mismatched cosine mean | Gap |
|---|---:|---:|---:|
| top | 0.2484 | 0.0106 | 0.2378 |
| dress | 0.1883 | 0.0032 | 0.1852 |
| pants | 0.2500 | 0.0067 | 0.2433 |
| skirt | 0.2155 | −0.0003 | 0.2158 |
| jacket | 0.1935 | 0.0024 | 0.1911 |
| bag | 0.1692 | 0.0055 | 0.1637 |
| hat | 0.2585 | 0.0039 | 0.2547 |
| set | 0.2739 | 0.0062 | 0.2676 |

Every category has a positive gap, showing that the VSE models place matched image–title pairs closer together on average than mismatched pairs. `set` has the largest gap, while `bag` has the smallest, consistent with the latter category's higher ranking loss.

## 8. Concept-Discovery Results

![Completed spatial-concept discovery runs](outputs/figures/spatial_concepts/figure_3_7_1_completed_runs.png)

The eight categories produce 240 K-means clusters in total; 208 clusters have enough data to train a discovered head. The number of available heads ranges from 18 for `hat` to 30 for `dress`. Vocabulary size does not imply prevalence: a cluster may contain few terms even when those terms appear across many products.

![Top concept composition](outputs/figures/spatial_concepts/figure_3_7_4_concept_composition.png)

The figure above illustrates the concept composition of the `top` category. Bar length represents the number of attribute terms in a cluster; annotations show the total number of training mentions and representative terms. These clusters are automatically discovered concepts, not standardized attribute groups validated by domain experts.

![Spatial similarity of representative terms](outputs/figures/spatial_concepts/figure_3_7_7_spatial_similarity.png)

The mean off-diagonal spatial cosine similarity is approximately 0.908, showing that most activation maps share a central-region bias. Because products are typically positioned near the image center, high spatial similarity does not necessarily indicate a semantic relationship. This result is important evidence of the current dataset's limited spatial discriminability.

## 9. Two Prediction Branches

![Attribute-prediction heads available by category](outputs/figures/prediction_branches/figure_3_8_1_available_heads.png)

| Category | Discovered heads | Schema heads | Schema values |
|---|---:|---:|---:|
| top | 29 | 8 | 36 |
| dress | 30 | 8 | 38 |
| pants | 28 | 5 | 21 |
| skirt | 26 | 4 | 15 |
| jacket | 29 | 5 | 22 |
| bag | 22 | 0 | 0 |
| hat | 18 | 1 | 5 |
| set | 26 | 5 | 20 |
| **Total** | **208** | **36** | **157** |

- **Schema-guided:** predicts predefined attribute groups and is the primary branch for evaluating label-completion performance.
- **Discovered-concept:** explores vocabulary, co-occurrence relationships, and new image–concept associations. F1 against the existing taxonomy measures only how well automatically discovered concepts can be mapped back to the gold schema; it is not the sole measure of discovery value.

## 10. Evaluation Protocol

The gold set contains 400 products: 200 validation and 200 test products. Of the images, 259 are rated `good`, 140 `usable`, and one `poor`; 141 images contain a single product, while 259 contain multiple products or product combinations.

After excluding `unknown`, `not_visible`, `not_applicable`, and `other`, 1,789 observable group instances remain. Applying the routed category's `VISUAL_GROUPS` leaves 362 products and 1,545 group instances; 38 products have no remaining applicable groups, and 244 groups fall outside the output scope.

Two reporting scopes are used:

1. **End-to-end:** all 400 products and 1,789 groups, retaining the impact of routing errors.
2. **Conditional visual scope:** the 362 products and 1,545 groups that the system is designed to predict; these are the primary results for the attribute heads.

A group with no emitted label is counted as an abstention. Abstention does not produce a label-confusion pair, but it still creates a false negative and lowers recall/F1. `Selective exact` measures exact match only on groups with at least one prediction, so it must always be interpreted together with coverage.

## 11. Main Evaluation Results

### 11.1. Category Routing

![Category confusion matrix](outputs/figures/evaluation/figure_4_5_1_category_confusion_matrix.png)

The title-based routing rule achieves an accuracy of **0.7400**, corresponding to 296/400 products. This is not an image category classifier. The `set` category has 84 gold examples, of which 46 are routed correctly; its precision, recall, and F1 are 0.8519, 0.5476, and 0.6667, respectively.

### 11.2. Attribute Prediction Within the Conditional Visual Scope

| Branch | Precision | Recall | Micro-F1 | 95% CI | Macro-F1 | Macro-mAP | Coverage | Selective exact | Abstention |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Schema | 0.7179 | 0.2062 | 0.3203 | [0.2951; 0.3463] | 0.1938 | 0.3859 | 0.3023 | 0.7045 | 0.6977 |
| Discovered | 0.8182 | 0.0272 | 0.0527 | [0.0391; 0.0665] | 0.0315 | 0.3159 | 0.0356 | 0.8182 | 0.9644 |

The schema branch achieves relatively high precision, but coverage is only 30.23%; its main limitations are a 69.77% abstention rate and low recall. The discovered branch has low direct-taxonomy F1 and very limited coverage. However, it demonstrates the ability to extract terms from titles, identify co-occurring term combinations, and associate them with image representations. Its main contribution is therefore vocabulary expansion and the proposal of new concepts or taxonomy candidates for human review.

### 11.3. Schema Results on Validation and Test Sets

| Measurement | Validation | Test |
|---|---:|---:|
| Products | 183 | 179 |
| Attribute groups | 776 | 769 |
| Precision | 0.6964 | 0.7412 |
| Recall | 0.2075 | 0.2048 |
| Micro-F1 | 0.3197 | 0.3210 |
| Macro-F1 | 0.2178 | 0.1757 |
| Macro-mAP | 0.4459 | 0.3926 |
| Coverage | 0.3106 | 0.2939 |
| Selective exact | 0.6805 | 0.7301 |
| Abstention | 0.6894 | 0.7061 |

Micro-F1 is nearly unchanged between validation and test, indicating that aggregate performance is relatively stable. Higher precision but lower macro metrics on the test set shows that performance remains uneven across labels. The gold validation set is used only to report stability, not to select epochs or thresholds.

### 11.4. Schema Results by Attribute Group

| Group | Instances | F1 | Coverage | Exact match | Selective exact |
|---|---:|---:|---:|---:|---:|
| Color | 317 | 0.1055 | 0.1009 | 0.0568 | 0.5625 |
| Sleeve | 179 | 0.3780 | 0.3743 | 0.2346 | 0.6269 |
| Neckline | 154 | 0.2956 | 0.3182 | 0.1948 | 0.6122 |
| Pattern | 348 | 0.2816 | 0.1983 | 0.1695 | 0.8551 |
| Fit | 265 | 0.3819 | 0.5019 | 0.2868 | 0.5714 |
| Length | 105 | 0.5455 | 0.4571 | 0.4000 | 0.8750 |
| Pant cut | 51 | 0.1379 | 0.1373 | 0.0784 | 0.5714 |
| Waist | 80 | 0.4444 | 0.3500 | 0.3000 | 0.8571 |
| Set type | 46 | 0.8500 | 0.7391 | 0.7391 | 1.0000 |

`Set_type` achieves the highest F1, but it evaluates only the binary parent label `set` across 46 instances. Among attributes that describe garments, `length`, `waist`, `fit`, and `sleeve` perform better, while `color` and `pant_cut` have the lowest coverage. High selective-exact scores do not compensate for low coverage and should not be interpreted in isolation.

![Schema attribute confusion matrices](outputs/figures/evaluation/figure_4_5_2_schema_attribute_confusion_matrices.png)

### 11.5. End-to-End Audit

| Branch | Precision | Recall | Micro-F1 | 95% CI | Macro-F1 | Macro-mAP | Coverage | Exact match |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Schema | 0.7179 | 0.1789 | 0.2864 | [0.2613; 0.3112] | 0.1717 | 0.3584 | 0.2610 | 0.1839 |
| Discovered | 0.8182 | 0.0236 | 0.0459 | [0.0339; 0.0583] | 0.0235 | 0.2959 | 0.0307 | 0.0252 |

End-to-end performance is lower than conditional performance because it retains 244 observable groups that fall outside the routed category's `VISUAL_GROUPS`. This table reflects the entire pipeline; the conditional table is more appropriate for evaluating the attribute heads within their intended scope.

### 11.6. Knowledge-Discovery Value

![Discovered knowledge overview](outputs/figures/evaluation/figure_4_5_4_discovered_knowledge_overview.png)

The discovered branch should not be viewed solely as a classifier competing with the schema branch. Its notable outputs include new vocabulary, co-occurrence clusters, out-of-schema candidates, and spatial–semantic relationships. These concepts are data-driven hypotheses and require human review before standardization.

## 12. Verifiable Conclusions

1. The VSE models learn an image–title association signal: the mean matched cosine similarity is higher than the mismatched mean in all eight categories.
2. Weak-validation loss reaches an early minimum; early stopping prevents continued fitting of the training set when validation performance no longer improves.
3. Concept discovery produces 240 clusters and 208 trainable heads, but the spatial representation is affected by a strong central bias.
4. Schema is the primary prediction branch, with conditional micro-F1 of 0.3203, precision of 0.7179, and coverage of 0.3023.
5. The discovered branch has low direct-taxonomy F1 but provides evidence of text-mining capability and associations between images and new concepts.
6. Category routing, composite images, weak-label noise, a frozen backbone, uncalibrated scores, and the small gold set are the main limitations.

## 13. Criteria for a Successful Reproduction

A run is considered a valid reproduction when:

- the audit contains 10,798 products with an 8,673/1,071/1,054 split;
- the total number of VSE training/validation pairs is 7,872/969;
- all eight categories have checkpoints and training histories;
- the totals are 208 discovered heads and 36 schema heads;
- the evaluator reads all 400 gold rows, finds 84 rows with `set_type_gold=set`, and creates 1,545 conditional group instances;
- metric differences from the tables above are limited to reasonable rounding variation;
- any differences in packages, input hashes, seeds, devices, or rules are documented rather than silently mixed with the current results.

## 14. Reproducibility Limitations

- `ResNet18_Weights.DEFAULT` is a Torchvision alias; locking package versions and checking the pretrained cache are necessary to prevent weight changes across versions.
- Some operations may differ very slightly across CPU, GPU, and BLAS/PyTorch versions.
- Gold labels are human-generated data and cannot be regenerated from code alone.
- Categories are routed from titles rather than predicted from images.
- Composite images have not been separated into individual products using detection/cropping.
- Weak labels reflect seller-title content and may contain noise or omit visible attributes.
- Automatically generated clusters are not a standardized taxonomy until they have been validated by domain experts.
