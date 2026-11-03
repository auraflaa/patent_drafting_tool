# Form placeholder map

Reference for how the questionnaire and party data fill the five bundled
statutory forms (`backend/app/templates/forms/`). The sample workbook
(`data.xlsx`) is **reference only** — its data is never imported.

## Legend

| Source | Meaning |
|---|---|
| `questionnaire.<field>` | Patent-specific questionnaire field (new or existing) |
| `applicant.<field>` | Primary row from the `applicants` collection |
| `inventor[i].<field>` | Row `i` from the `inventors` collection (1–7) |
| `config.<field>` | Deployment/admin setting |
| `derived.<value>` | Computed at generation time |

## Form 1 — Application for Grant (`FORM1.docx`)

| Template variable | Source | Notes |
|---|---|---|
| `TitleKeyword` | `questionnaire.title_keyword` | After "A SYSTEM AND METHOD FOR ENABLING"; uppercase noun phrase |
| `ApplicantName` | `applicant.full_name_or_org_name` | Primary applicant |
| `ApplicantNationality` | `applicant.country` | |
| `ApplicantAddress` | `applicant.address` | |
| `Inventor1Name` … `Inventor7Name` | `inventor[i].full_name` | Row loop; 1–7 rows rendered |
| `Inventor1Nationality` … | `inventor[i].country` | |
| `Inventor1Address` … | `inventor[i].address` | |
| `AgentName` | `config.agent_name` | Blank until appointed |
| `AgentInPa` | `config.agent_inpa` | |
| `AgentMobile` | `config.agent_mobile` | |
| `GeneratedDate` | `derived.date` | "3rd day of November 2026" |
| `ClaimCount` | `derived.claims` | Count of rendered claims |
| `DrawingCount` | `derived.drawings` | Selected usable figures |
| `PageCount` | manual / blank | python-docx cannot paginate |

**Removed:** hardcoded MIT World Peace University applicant, hardcoded Indian
nationality/address, hardcoded agent Pranav Bhat / IN-PA 4580 / phone, fixed
attachment counts (13 pages, 4 claims, 4 drawings).

## Form 2 — Complete Specification (`FORM2.docx`)

| Template variable | Source |
|---|---|
| `TitleKeyword` | `questionnaire.title_keyword` |
| `ApplicantName`, `ApplicantAddress` | primary applicant |
| `Field`, `Domain`, `Area` | `questionnaire.field`, `.domain`, `.area` |
| `InventionKeyword` | `questionnaire.invention_keyword` |
| `OneLineAboutField` | `questionnaire.one_line_about_field` |
| `TwoLinesAboutDomain` | `questionnaire.two_lines_about_domain` |
| `ThreeLinesAboutArea` | `questionnaire.three_lines_about_area` |
| `FourLinesAboutProblem` | `questionnaire.four_lines_about_problem` (4 lines) |
| `FourLinesAboutSolution` | `questionnaire.four_lines_about_solution` (4 lines) |
| `Advantage1`, `Advantage2` | `questionnaire.advantage1`, `.advantage2` |
| `ProblemKeyword` | `questionnaire.problem_keyword` |
| `ClaimKeyword` | `questionnaire.claim_keyword` |
| `Data1`, `Data2` | `questionnaire.data1`, `.data2` (renamed from `data11`/`data22`) |
| `ExemplaryScenario` | `questionnaire.exemplary_scenario` |
| `DetailedExemplaryScenario` | `questionnaire.detailed_exemplary_scenario` |
| `BestWorkingMethod` | `questionnaire.best_working_method` |
| `PriorArt` | `questionnaire.prior_art` (paragraphs) |
| `GeneratedDate` | `derived.date` |

**Removed:** the five hardcoded US patent references (JP Morgan, Nvidia,
DataRobot, Medtronic, Siemens) and the duplicated
`Four_lines_about_problem` at `p23` (now the solution).

## Form 3 — Statement and Undertaking (`FORM3.docx`)

Static statutory text with an applicant block. Currently contains no
placeholders; the applicant name/address are parameterised from the primary
applicant so the form is not institution-specific.

## Form 5 — Declaration as to Inventorship (`FORM5.docx`)

| Template variable | Source |
|---|---|
| `ApplicantName`, `ApplicantAddress` | primary applicant |
| `Inventor1Name` … `Inventor7Name` | `inventor[i].full_name` (table loop) |
| `GeneratedDate` | `derived.date` |

**Removed:** hardcoded MIT World Peace University applicant and fixed date.

## Drawings (`diagrams.docx`)

| Template variable | Source |
|---|---|
| `InventionKeyword`, `ClaimKeyword`, `Data1`, `Data2` | questionnaire identity fields (callout labels) |
| `FigureBlock` | selected usable figures (YOLO/embedded/upload), rendered by the post-processor |

**Removed:** the static sample diagram image. The block is filled with real
selected figures only; with none selected the sheet is marked incomplete.

## AI refinement groups

The AI rephrases raw questionnaire answers into the long-form fields above.
It never writes claims, abstract, statutory boilerplate, applicant/inventor
names, dates, or agent details. Short keyword fields may be AI-suggested but
are validated as noun phrases.

## YOLO figure detection

PDF pages are rendered and passed through a pluggable ONNX YOLO detector to
locate figure/drawing regions. The resulting crops join embedded DOCX/PPTX
images and direct image uploads as candidates. Users may override a rejected
candidate ("Use anyway").

Model decision: **YOLOv10-b trained on DocLayNet (Apache-2.0)** — e.g. the
`Oblix/yolov10b-doclaynet_ONNX` mirror of `hantian/yolo-doclaynet`. Input
(1,3,640,640) RGB /255 letterboxed; output (1,300,6) decoded
`[xmin,ymin,xmax,ymax,score,class]` boxes, already post-NMS; document-native
classes (`Picture`, `Table`, `Caption`, …) instead of COCO labels.
DocLayout-YOLO was evaluated and **rejected**: it is AGPL-3.0, which a filing
SaaS cannot ship. Set `YOLO_MODEL_PATH` to enable; `YOLO_PROVIDER=cuda`
uses the GPU with CPU fallback. Configure `YOLO_FIGURE_CLASSES` when using
different weights.
