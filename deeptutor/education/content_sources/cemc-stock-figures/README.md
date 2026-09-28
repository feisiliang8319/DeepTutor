# Six existing CEMC figure repairs

The candidate package is `../cemc-stock-figure-repairs-v1.json`. Six source pages from the two existing CEMC A booklets were visually checked. The old 4×7 maze was wrong: its original has 4×8 cells, with 20 traversable cells. All six old explanations included text from the following problem; the new derived explanations cover only their own questions.

Run `python3 deeptutor/education/content_sources/cemc-stock-figures/verify.py` from the repository root. It independently solves the shape equations with exact fractions, enumerates every valid maze path, and recomputes chart, picture-scale, temperature-estimate and elapsed-time answers. The receipt binds every JSON specification by SHA256. SVG hashes and source pages are in `api/static/figures/manifest.json`; all six rendered diagrams were visually checked against the existing PDF pages.

The navigation adaptation covers original part (a) only. Temperature answers allow reasonable graph-reading estimates. No numerical clock time, icon-to-book conversion or temperature-point values appear as answer labels in the student diagram. Original source records/assets remain unchanged. New items remain candidates with the external-figure review hold; this package does not approve formal Quiz use or calibrate difficulty.

Source materials and adapted diagrams retain the CEMC attribution and CC BY-NC 4.0 restriction in the package. This is existing-stock repair, not new source acquisition.
