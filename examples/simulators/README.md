# Simulator adapter examples

`analytic_probe_simulator.py` exercises the public JSON-in/JSON-out adapter without a PDK or a
proprietary tool. It is intentionally a first-order RC fixture, not an LDO performance model.

```bash
evoldo-bench simulate-probe examples/simulators/rc_probe_request.json \
  --workspace /tmp/evoldo-sim \
  --simulator-command python "$(pwd)/examples/simulators/analytic_probe_simulator.py"
```

For a redistributable SPICE deck, stage the deck inside the tool workspace and use the optional open
simulator path. The included deck is a passive protocol fixture, not an LDO or PDK claim:

```bash
workspace="$(mktemp -d)"
cp examples/simulators/rc_tran.cir "$workspace/"
evoldo-bench simulate-probe examples/simulators/rc_ngspice_request.json \
  --workspace "$workspace" --ngspice
```

An absent executable, timeout, invalid output, or non-zero exit is reported as `INFRA_FAIL`; it is
never converted into an LDO circuit failure. Private EDA/PDK integration belongs in an out-of-tree
`SiteAdapter` implementation.
