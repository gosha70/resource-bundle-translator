"""Translation validators.

Validators inspect a (Segment, TranslatedSegment) pair and report any
:class:`Violation` they find. The pipeline (scope 9) runs every
configured validator on every translation; ``error``-severity
violations block the segment from being written, ``warning`` violations
are surfaced in the run summary but don't block.

Cycle-1 ships four validators:

- :class:`ainemo.core.validators.placeholder.PlaceholderParityValidator`
- :class:`ainemo.core.validators.icu.IcuSyntaxValidator`
- :class:`ainemo.core.validators.length.LengthBudgetValidator`
- :class:`ainemo.core.validators.forbidden.ForbiddenTermsValidator`
"""
