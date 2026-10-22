The evidence checker rejected some of your claims. Its notes follow as data; each names a claim
and why it failed (unknown evidence ID, wrong field path, value or unit that does not match the
evidence, a number in the text without a NumberRef, or no source cited).

Return the complete report JSON again, in the same shape. For each rejected claim, either fix it
so it follows the claim rules exactly (correct `evidence_id`, `field`, `value` and `unit`; every
number in the text backed by a NumberRef) or remove it. Do not change claims that passed.
