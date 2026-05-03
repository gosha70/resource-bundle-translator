"""Bundle-format adapters.

Each adapter implements :class:`ainemo.core.adapters.base.BundleAdapter`
to convert one resource-bundle format to and from
:class:`ainemo.core.segment.Segment` objects.

Cycle 1 ships four adapters:

- :class:`ainemo.core.adapters.java_properties.JavaPropertiesAdapter`
- :class:`ainemo.core.adapters.i18next_json.I18NextJsonAdapter`
- :class:`ainemo.core.adapters.gettext_po.GettextPoAdapter`
- :class:`ainemo.core.adapters.xliff.XliffAdapter`

Adding a new format means: write a new adapter, ship contract tests
(round-trip property + edge-case fixtures) — no other layer changes.
"""
