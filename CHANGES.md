# 1.0.0 - 03 October 2026

## Features

* `--from-results` and `--status` selector for `check` ([#148](https://github.com/canonical/hyrum/pull/148))
* Add a dev workshop ([#136](https://github.com/canonical/hyrum/pull/136))

## Fixes

* Serialise two runs that share a charms directory ([#140](https://github.com/canonical/hyrum/pull/140))
* Merge runner stderr into stdout so logs keep their order ([#128](https://github.com/canonical/hyrum/pull/128))
* Make show's markdown a table, and its text work without a target ([#152](https://github.com/canonical/hyrum/pull/152))
* Stop tox writing a .venv redirect into charm checkouts ([#163](https://github.com/canonical/hyrum/pull/163))
* Upload the pages artifact when deploying from canonical/hyrum ([#168](https://github.com/canonical/hyrum/pull/168))

## Documentation

* Add initial documentation ([#99](https://github.com/canonical/hyrum/pull/99))
* Remove the fork specific checks ([#167](https://github.com/canonical/hyrum/pull/167))

## Tests

* Enumerate the patcher and runner-detection permutations ([#141](https://github.com/canonical/hyrum/pull/141))

# 1.0.0b1 - 17 September 2026

## Features

* Extract per-charm failure summaries from runner output ([#81](https://github.com/canonical/hyrum/pull/81))
* Add `--save-results` and `hyrum compare` for run-to-run diff ([#82](https://github.com/canonical/hyrum/pull/82))
* Prefer opendev mirrors and add get-charms timeout ([#98](https://github.com/canonical/hyrum/pull/98))
* Polish `hyrum compare`: charm-set drift, JSON output, exit codes ([#83](https://github.com/canonical/hyrum/pull/83))
* Say where the run saved its results and logs ([#126](https://github.com/canonical/hyrum/pull/126))
* Report each status as a share of the runs as well as of the fleet ([#138](https://github.com/canonical/hyrum/pull/138))
* Add `hyrum show PATH`, which prints a saved run's status summary ([#149](https://github.com/canonical/hyrum/pull/149))
* Narrow `get-charms` with `--repo` and `--limit` ([#143](https://github.com/canonical/hyrum/pull/143))
* Add a clean subcommand to reclaim per-charm build artefacts ([#139](https://github.com/canonical/hyrum/pull/139))

## Fixes

* Strip ANSI and collapse $HOME in captured runner output ([#79](https://github.com/canonical/hyrum/pull/79))
* Make OpsSourcePatcher idempotent on existing [tool.uv.sources] ([#80](https://github.com/canonical/hyrum/pull/80))
* Bound get-charms concurrency to avoid FD exhaustion ([#88](https://github.com/canonical/hyrum/pull/88))
* Stop treating Charmhub bugs-url as a git remote ([#89](https://github.com/canonical/hyrum/pull/89))
* Three defects in dependency patching and fault attribution ([#97](https://github.com/canonical/hyrum/pull/97))
* Patching ops to a PyPI version emits one comparison operator ([#123](https://github.com/canonical/hyrum/pull/123))
* `--limit` counts the charms that run, not the charms it looked at ([#124](https://github.com/canonical/hyrum/pull/124))
* Make report percentages unambiguous about their denominator ([#127](https://github.com/canonical/hyrum/pull/127))
* Skip charm-list rows that duplicate an earlier row's checkout ([#125](https://github.com/canonical/hyrum/pull/125))
* Inject the patched poetry dep into the group it came from ([#135](https://github.com/canonical/hyrum/pull/135))
* Make the check help readable in a terminal ([#137](https://github.com/canonical/hyrum/pull/137))
* Make the verbosity rungs cumulative, and add `--brief` ([#133](https://github.com/canonical/hyrum/pull/133))
* Find the charms nested deeper than one directory level ([#134](https://github.com/canonical/hyrum/pull/134))
* Soft-wrap the body of the charm-list refresh PR ([#142](https://github.com/canonical/hyrum/pull/142))

## Documentation

* Install hyrum from PyPI in the README ([#90](https://github.com/canonical/hyrum/pull/90))

## CI

* Correct pinned version comment for upload-sarif action ([#91](https://github.com/canonical/hyrum/pull/91))
* Replace moving-tag comments on pinned actions with fixed versions ([#92](https://github.com/canonical/hyrum/pull/92))
* Swap attest-build-provenance for actions/attest ([#146](https://github.com/canonical/hyrum/pull/146))

# 1.0.0a1 - 07 July 2026

## Features

* Auto-select satisfying Python for poetry lock ([#5](https://github.com/canonical/hyrum/pull/5))
* Add `--log-dir` for per-charm stdout/stderr dumps ([#8](https://github.com/canonical/hyrum/pull/8))
* Default common host-env flags with `--host-env-defaults` ([#17](https://github.com/canonical/hyrum/pull/17))
* Recognise src/reactive/ + src/layer.yaml as legacy ([#27](https://github.com/canonical/hyrum/pull/27))
* Skip charms with no Python source ([#28](https://github.com/canonical/hyrum/pull/28))
* Add tools/get_charms.py for populating the charm cache ([#12](https://github.com/canonical/hyrum/pull/12))
* Add GenericDepPatcher for swapping arbitrary dependencies ([#59](https://github.com/canonical/hyrum/pull/59))
* Scripts to discover public charm repositories on GitHub and Launchpad ([#26](https://github.com/canonical/hyrum/pull/26))
* Add CharmlibPatcher for swapping charmlib deps from canonical/charmlibs ([#25](https://github.com/canonical/hyrum/pull/25))
* Add VendoredLibPatcher for swapping vendored charm libs for PyPI packages ([#60](https://github.com/canonical/hyrum/pull/60))
* Add charm-list with weekly auto-refresh from Charmhub ([#11](https://github.com/canonical/hyrum/pull/11))
* Broaden `--ops-source` to accept version, git+url, owner:branch, and path ([#18](https://github.com/canonical/hyrum/pull/18))

## Fixes

* Always hoist ops companions in uv flavour ([#6](https://github.com/canonical/hyrum/pull/6))
* Recognise PEP 735 [dependency-groups] in uv pyprojects ([#7](https://github.com/canonical/hyrum/pull/7))
* Drop unsupported cooldown.semver-major-days from github-actions block ([#75](https://github.com/canonical/hyrum/pull/75))
* Swap ops-scenario when Poetry charm declares it separately ([#73](https://github.com/canonical/hyrum/pull/73))

## Documentation

* Document host prerequisites for running the charm fleet ([#20](https://github.com/canonical/hyrum/pull/20))
* Add yq and go to host prerequisites ([#29](https://github.com/canonical/hyrum/pull/29))

## Tests

* Adopt -Werror in unit tests ([#36](https://github.com/canonical/hyrum/pull/36))

## Refactoring

* Align with Canonical CLI standards, misc improvements ([#15](https://github.com/canonical/hyrum/pull/15))
* Drop the public namespace down to the intended API ([#49](https://github.com/canonical/hyrum/pull/49))
* Drop click, rich, and pyyaml dependencies ([#33](https://github.com/canonical/hyrum/pull/33))

## Performance

* Run patcher setup/teardown in worker threads ([#9](https://github.com/canonical/hyrum/pull/9))

## CI

* Add pip-audit dependency vulnerability scan ([#21](https://github.com/canonical/hyrum/pull/21))
* Run zizmor in-repo instead of through the charm-tech reusable workflow ([#19](https://github.com/canonical/hyrum/pull/19))
* Add dependency-review-action on PRs ([#35](https://github.com/canonical/hyrum/pull/35))
* Validate that PR titles use conventional commits ([#34](https://github.com/canonical/hyrum/pull/34))
* Add tag-triggered PyPI publish workflow ([#13](https://github.com/canonical/hyrum/pull/13))
* Use actions/attest-sbom for SBOM attestation ([#45](https://github.com/canonical/hyrum/pull/45))
* Fix Test PyPI upload URL ([#46](https://github.com/canonical/hyrum/pull/46))
* Fix `--force-with-lease` stale-info push failure ([#53](https://github.com/canonical/hyrum/pull/53))
* Only skip PR creation for open PRs ([#54](https://github.com/canonical/hyrum/pull/54))
* Hash-pin actions and drop zizmor config ([#71](https://github.com/canonical/hyrum/pull/71))
* Adopt new dependabot conventions ([#70](https://github.com/canonical/hyrum/pull/70))
* Switch attest-sbom to actions/attest v4.1.1 ([#72](https://github.com/canonical/hyrum/pull/72))
