# Known charm failures

Charms in the curated cache that fail a `hyrum --no-patch --target unit`
run even on the recommended Python 3.12 with the full host prerequisites
installed (see the README's *Host prerequisites* section). These are
**genuine, interpreter-independent** failures: they fail the same way on
the charm's own pinned `ops` and on `ops@main`, so they are charm-side
issues, not `hyrum` or `ops` regressions.

Audited 2026-05-28 (Ubuntu Resolute, system tools: `default-jdk`,
`skopeo`; `charmcraft fetch-libs` applied where needed). Re-derive after
a cache refresh — charm fixes land upstream and rows here should be
removed as they do.

`hyrum` deliberately ships no default ignore list; if you want a quiet
tally, copy the names below into a local `hyrum.toml` `[ignore]` table.

## Genuine test bugs

These are bugs in the charm's own test suite, exposed independently of
the `ops` version. The fix belongs in the charm repo.

| Charm | Symptom | Root cause |
|-------|---------|------------|
| `exim-operator` | `ops.pebble.PathError: not-found - parent directory not found` + a `layer["services"]` assertion mismatch (`exim -bdf` vs `exim -bd -q 30m`) | Test expectations drifted from the charm's actual Pebble layer / file-push paths. |
| `redis-operator` | `ops.pebble.ConnectionError: Cannot connect to Pebble; did you forget to call ... set_can_connect()?` | Test drives `Harness` without `set_can_connect(True)`; relies on the old auto-connect behaviour that current `ops` no longer provides. |
| `tls-truststore-operator` | same `pebble.ConnectionError` as `redis-operator` | same stale-`Harness` `set_can_connect` assumption. |
| `grafana-agent-operator` | `KeyError: ('classic', '')` → `SnapSpecError: Snap spec not found for arch= and confinement=classic` | Snap-management test mocks leave arch/confinement empty; the snap-spec lookup then misses. Over-mocked snap helper. |
| `parca-agent-operator` | `charms.operator_libs_linux.v1.snap.SnapError: foobar` / `something went wrong`; status asserts a specific snap revision | Tests assert exact snap install/refresh behaviour against injected mock errors. Over-mocked snap helper. |
| `snappass-test` | `AttributeError: 'Container' object has no attribute 'pebble_ready_event'` (also seen: `ops.jujucontext._JujuContext` missing) | Charm/test reaches into private `ops` internals that were renamed/removed — a textbook Hyrum's-law breakage. |
| `timescaledb-charm` | `unittest.mock.InvalidSpecError: Cannot spec a Mock object. [object=<MagicMock name='Popen'...>]` | Test `spec`s a `Mock` with another `Mock`; Python 3.12+ `mock` rejects this. Latent test bug exposed by the newer stdlib. |
| `tls-certificates-requirer-operator` | `RuntimeError: Patch is already started` | Test-isolation bug: a `mock` patch is started twice without an intervening stop. |

## Build failures

| Charm | Symptom | Root cause |
|-------|---------|------------|
| `ks-charmed` | `AttributeError: 'build_ext' object has no attribute 'cython_sources'` during `uv pip install` | A transitive dependency ships only an sdist and builds it through a setuptools/distutils path incompatible with the modern toolchain. Dependency-side, not the charm's tests. |

## Tox configuration drift

| Charm | Symptom | Root cause |
|-------|---------|------------|
| `opensearch-operator` | `pytest` collects 0 items from `tests/unit` → "no tests ran", exit 4 | The `unit` tox env points `pytest` at `tests/unit`, but the charm keeps its unit tests under a different layout. The tox config drifted from the tree. |

## Resource-intensive (not a real failure)

These pass when run alone; they fail under `hyrum`'s worker concurrency
because they exhaust host RAM. Skip them, run them in isolation, or
lower `--workers`.

| Charm | Symptom | Root cause |
|-------|---------|------------|
| `mysql-router-operators/kubernetes` | `pytest` exits `-9` (SIGKILL) after ~168 s | Runs `pytest --numprocesses 120`; spawns 120 workers that OOM the host. Also OOM-kills 3–4 unrelated charms running concurrently (e.g. `kafka-k8s-operator`, `loki-k8s-operator`, `mlmd-operator`, `mysql-router-operators/machines`) — the dominant source of run-to-run wobble. |
| `namespace-node-affinity-operator` | `OSError: [Errno 12] Cannot allocate memory` mid-venv | Memory pressure during a concurrent run; passes when run alone. |

## Recoverable with host setup (not failures once set up)

Listed for completeness — these pass once the prerequisite is in place,
so they are **not** counted among the genuine failures above.

| Charm | Fix |
|-------|-----|
| `kafka-k8s-operator`, `kafka-operator` | install `default-jdk` (provides `keytool`) |
| `self-signed-certificates-operator` | run `charmcraft fetch-libs` to vendor `lib/charms/…` |
