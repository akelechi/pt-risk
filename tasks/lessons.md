# Lessons

- 2026-11-15: A tolerance on a derived quantity should come from the rounding of its inputs,
  not a guess. Energy = lbmp - loss + congestion has three cent-rounded terms, so two
  locations can differ by $0.03; the first guess of $0.011 failed on real data.
- 2026-11-15: NYISO's fall-back hour has no marker; file order is the only disambiguator.
  Test DST handling on verbatim source rows, not synthetic ones.
- 2026-11-15: Headless Chrome follows the system colour scheme; a "light mode" screenshot
  taken on a dark-mode machine is a dark screenshot. Look at the image before filing it.
