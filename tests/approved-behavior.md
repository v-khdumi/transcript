# Approved Behavior Change

On 2026-09-07 the user selected "Preserve both transcripts" for the same-second
filename collision. Candidate JSON/text files must receive distinct `_1`, `_2`
suffixes without changing the existing files or export content format.

The baseline characterization still asserts its original overwrite behavior.
The isolated supervisor supplies MODERNIZE_VERIFICATION_VARIANT=baseline only
to the baseline process. Candidate and normal local test runs must assert the
new preservation behavior. No test is skipped and both variants execute the
collision test. This exception does not authorize unrelated behavior changes.

Baseline vulnerability findings remain in the comparison report. Candidate
runtime dependencies must pass the audit before publication approval.