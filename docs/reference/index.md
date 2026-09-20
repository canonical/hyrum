# Reference

```{toctree}
:maxdepth: 1

cli
configuration
output
supported-charms
charm-discovery
extending
```

Technical specifications for hyrum's command-line surface, the `hyrum.toml` configuration file, the structure of run output, the charms and dependency formats it supports, the repository layouts and filters that decide which charms run, and the protocols to implement when extending hyrum.

**[CLI reference](cli)**
: Every command-line option with full descriptions.

**[Configuration reference](configuration)**
: The `hyrum.toml` configuration file format and all supported keys.

**[Output reference](output)**
: Outcome statuses, summary table format, verbose output, and log file format.

**[Supported charms](supported-charms)**
: The dependency declarations, swap subjects, testing frameworks, and runner backends hyrum supports.

**[Charm discovery and filtering](charm-discovery)**
: The repository layouts hyrum recognises and the order its skip filters are applied in.

**[Extending hyrum](extending)**
: The `Patcher` and `Runner` protocols, for adapting or extending hyrum.
