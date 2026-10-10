# Validation rule catalog

These are the Phase 4 rules for this synthetic demo. All business fields in the
legacy contract are required. Metadata such as `_source_row` is not a business
field. A blank required value gets `VR003` rather than an additional format error
for that same blank field.

| Code | Applies to | Failure condition |
| --- | --- | --- |
| `VR001_INVALID_EMAIL` | Customers | Nonempty email fails basic `local@domain.suffix` syntax |
| `VR002_INVALID_COUNTRY_CODE` | Customers | Nonempty country code is absent from the pinned ISO 3166-1 alpha-2 catalog |
| `VR003_MISSING_REQUIRED` | All tables | Any required business field is blank or missing |
| `VR004_INVALID_DATE` | All date fields | Nonempty date did not convert to a supported calendar date |
| `VR005_INVALID_AMOUNT` | Loan principal and payment amount | Nonempty value is not a finite `Decimal` at at most two decimal places |
| `VR006_NON_POSITIVE_AMOUNT` | Loan principal and payment amount | Amount is zero or negative |
| `VR007_INVALID_STATUS` | Loans | Nonempty canonical status is neither `active` nor `closed` |
| `VR008_DUPLICATE_ID` | All tables | Multiple nonidentical source records have the same normalized table ID |
| `VR009_PROBABLE_DUPLICATE_CUSTOMER` | Customers | Different customer IDs share a normalized email and require identity review |
| `VR010_CUSTOMER_NOT_FOUND` | Loans | Referenced customer is missing or failed validation |
| `VR011_LOAN_NOT_FOUND` | Payments | Referenced loan is missing or failed validation |
| `VR012_PAYMENT_BEFORE_LOAN_START` | Payments | Payment predates the start of its accepted loan |
| `VR013_EXACT_DUPLICATE` | All tables | Transformation removed an exact duplicate source record |

Dates on the loan start day are accepted. Email syntax does not prove delivery
or identity. Country lookup uses [pycountry's local ISO data](https://github.com/pycountry/pycountry#countries-iso-3166-1).
These are project rules, not regulatory or credit-underwriting requirements.

## Duplicate and dependency policy

- Exact duplicates keep the first source occurrence for validation; every removed
  occurrence receives `VR013`. The first occurrence can still fail other rules.
- Conflicting IDs reject all conflicting rows rather than choosing one.
- Probable customer groups reject every member for review, without merging.
- A rejected customer cannot support an accepted loan; a rejected loan cannot
  support an accepted payment. No foreign-key failure is silently ignored.

## Rejection CSV contract

`rejected_records.csv` has one row per rejected source record:

| Column | Meaning |
| --- | --- |
| `table` | Source entity: customers, loans, or payments |
| `_source_row` | CSV record position, counting the header as 1 |
| `record_id` | Original source ID, possibly blank or repeated |
| `rule` | First failure in deterministic validator order |
| `reason` | Readable reason for that first failure |
| `violations` | JSON list of every failed rule, field, and reason |
| `record_json` | JSON object containing the original source business fields |

Primary rejection counts group by `rule` and add up to rejected records.
Counting every entry in `violations` measures rule occurrences, which can exceed
the number of rejected records. Future reconciliation must distinguish them.

With the default generator, there are 650 accepted customers, 500 loans, and
950 payments. Rejected counts are 450, 500, and 1,050. The 50 removed exact
customer duplicates are included in the 450 customer rejections.
