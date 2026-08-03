# Explanation

```{toctree}
:maxdepth: 1

hyrums-law
charm-tooling
design
```

The dependency-coupling problem that motivates hyrum, its place within the broader charm-development toolchain, and the patcher–runner architecture that keeps fleet runs reproducible and signal-rich.

**[Hyrum's Law and this tool](hyrums-law)**
: What Hyrum's Law says, why it matters for `ops` development, and what problem hyrum solves.

**[Relationship to charm tooling](charm-tooling)**
: How hyrum fits into the broader ecosystem of operator frameworks, testing libraries, and development tools.

**[Architecture and design](design)**
: The patcher–runner model, async worker pool, scope boundaries, and signal-vs-noise considerations.
