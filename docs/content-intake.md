# Curriculum content intake

The administrator's `/admin/materials` workspace reads the existing education
database. It does not turn retrieval collections into a curriculum or alter a
learner's placement. Raw textbooks still use the existing `/knowledge` upload,
parsing and indexing workflow.

## Content paths

- Teaching chapters: source file → parsing → local indexing → authorized retrieval
  for Chat. Preserve the original file and its provenance.
- Assessment items: source + answer → normalized JSON → import preview → candidate
  → explicit content review → production item → assessment classification.
  Answers stay behind administrator authorization before an exam is submitted.
- Curriculum scope: the existing course version and knowledge nodes are the
  binding identities. Formal assessment units and difficulty/variant-family tags
  remain in the existing assessment configuration; importing a package creates
  neither a full-grade assessment scope nor promotion eligibility.

## Import format

Select an existing course version in the workspace and upload a UTF-8 JSON file:

```json
{
  "course_version_id": "existing-course-version",
  "source_name": "Original lesson questions v1",
  "items": [{
    "id": "original-question-v1-001",
    "knowledge_node_code": "an-existing-node-code",
    "item_type": "numeric",
    "prompt": "Six groups of seven: how many in total?",
    "expected_answer": "42",
    "explanation": "Multiplying 6 by 7 gives 42.",
    "explanation_source": "authored",
    "difficulty": 2,
    "content_scope": "BUNDLED",
    "source_ref": "self-authored example"
  }]
}
```

Existing seed packages with `knowledge_node_code` are supported. An explicit
`knowledge_node_id` must belong to the selected course. Each batch is limited to
1,000 items and 4 MiB. Import preview reports errors without writing any rows.
Confirmation revalidates the entire batch in a transaction: one invalid item
rejects the batch. Uploaded publication states or reviewer identities are ignored.

Same IDs with identical content are skipped. A changed existing question requires
a new ID and may reference an existing source item with `derived_from_item_id`;
the original is never overwritten. Replaying an identical package returns its
original receipt without inserting items again.

## Rights and review

Main-library import accepts only content declared `BUNDLED`, with provenance and
the existing license/attribution checks. This declaration is not automatic legal
clearance. Private family material retains the family workflow and visibility.
External sources need a valid license and attribution; an original source must
be explicitly declared self-authored. Restricted content is rejected.

Candidates may have incomplete answers, explanations or figures so the quality
workspace can reveal repair work. They cannot be published through this workflow
until the listed content issues are resolved. Visual items are deliberately held
for a separate asset-validation workflow. Publication requires a substantive
review note and a current server-computed revision. Review decisions are appended
with the authenticated administrator identity and may not be overwritten.

“Eligible for exam selection” counts reviewed, gradable and classified items.
It does not mean an exam can be built: coverage, difficulty quotas and the
student's unseen-question history are additional constraints. Never use a small
topic pack as proof of full-grade coverage.

## Starter content and acquisition

The starter button prepares 32 original Chinese number-structure candidates
covering factors, multiples, primes, patterns and word-problem relationships.
Each has an answer and explanation. It creates no approval or competition claim.
This is a bounded topic pack, not a complete Grade 4 or Grade 5 curriculum.

The existing separate curriculum acquisition script can stage allowlisted CEMC
problem/solution pairs with source URLs, SHA-256 hashes and license metadata.
An incomplete pair stays pending. Downloading a source is distinct from checking
its mathematical meaning, normalizing it, and reviewing it for publication.
The admin UI does not yet run scheduled acquisition or unattended publication.

The first isolated validation used 177 existing shared math candidates, the
32-question original pack and two explicitly attributed CEMC adaptations. An
original teaching chapter was separately indexed and retrieved. No production
accounts, learner records, placements or grades were changed by this intake.
