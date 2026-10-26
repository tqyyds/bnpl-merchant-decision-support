# Public data and artifact policy

This repository publishes implementation, synthetic fixtures, documentation and aggregate historical evidence.

It excludes restricted course archives, extracted tables, transaction/consumer rows, named merchant recommendation lists, model binaries, feature matrices, submission packages, credentials, absolute user paths and notebook execution outputs. Official ABS/RBA/ASIC source files are linked through the existing manifest/download script rather than redistributed as binaries.

`dashboard/demo.json` contains invented merchant labels, synthetic IDs and invented numerical values. Dashboard screenshots are captured only from that explicit synthetic mode. Historical model metrics in `reports/portfolio/` belong to the real local course-data analysis and are never presented as demo outcomes.

The Git ignore rules protect common generated formats and paths. `scripts/check_public_release.py` checks the tracked file inventory (or the pre-commit source tree), notebook outputs, private-key/token patterns and restricted binary/data extensions. These automated checks support a curated release; they are not a guarantee against every possible disclosure.

Do not commit new records or notebook outputs when reproducing the local pipeline. Data access and publisher terms apply independently of this repository. The absence of a source-code licence is deliberate: publishing this personal portfolio does not relicense course materials or upstream rights.
