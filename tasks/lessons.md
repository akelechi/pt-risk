# Lessons

- 2026-11-15: A tolerance on a derived quantity should come from the rounding of its inputs,
  not a guess. Energy = lbmp - loss + congestion has three cent-rounded terms, so two
  locations can differ by $0.03; the first guess of $0.011 failed on real data.
- 2026-11-15: NYISO's fall-back hour has no marker; file order is the only disambiguator.
  Test DST handling on verbatim source rows, not synthetic ones.
- 2026-11-15: Headless Chrome follows the system colour scheme; a "light mode" screenshot
  taken on a dark-mode machine is a dark screenshot. Look at the image before filing it.
- 2026-11-15: When I hand-compute an expected value for a test, recompute it a second way
  before trusting it. I typed 60,480 MMBtu for the hand day; the engine's 63,180 was right
  (8 x 4,725 + 4 x 6,345). A failing test can be the test's arithmetic.
- 2026-11-15: Compare prices against rounded offers, not raw floating-point costs. A pooled
  heat rate of 10.5 can be 10.499999999999998, which flips a tie.
- 2026-11-15: SVG labels sized for placeholder dashes overflow once real values arrive.
  Lay out with the widest realistic value.
