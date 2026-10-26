# Public edition verification

Verified locally on **26 October 2026 (Australia/Sydney)**, against the assembled public source tree.

| Check | Result |
|---|---|
| Python synthetic suite | **132 passed, 2 skipped** in 14.70 seconds |
| JavaScript transport/render contract suite | **9 passed** |
| Restricted-data checks | The two skipped tests explicitly require local v3 feature files; no course data is included |
| Notebook publication | Six notebook sources retained; outputs, execution counts and attachments removed |
| Data publication | No course archives, extracted tables, merchant recommendation lists or model binaries |
| Release scan | Curated file inventory checked for restricted paths/formats, token/private-key patterns and private absolute paths |

Commands: `python -m pytest -q`, `node --test tests/test_dashboard_client.mjs`, `python scripts/check_public_release.py`.

The original runtime differs from the local publication-check environment. Hosted CI runs Python 3.12 and Node 22 with CPU Torch; its badge reports the independent GitHub result. Passing synthetic tests does not reproduce historical model training or validate real credit-loss performance.
