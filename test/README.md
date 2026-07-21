# Test suite

Runnable on Windows without `make`:

```
python run.py            # both suites (~50 s)
python run.py ro         # ring-oscillator test structures only
python run.py sine       # sine (CORDIC-1) smoke tests only
```

The classic cocotb + Makefile flow works too (`make -B`); waveforms land
in `tb.fst` for GTKWave/Surfer.

## `test_ro.py` — the test structures

Drives the instrument end to end at the pins: select a ring, run a
window, read the latched count back a byte at a time, and check that the
number means what the datasheet says it means.

In RTL simulation all three rings are behavioural chains with the same
lumped `STAGE_DLY`, so they oscillate at the same modelled frequency
(2 x 31 x 0.1 ns = 6.2 ns; the tests assert ~103 prescaled edges per
short window and that the flavors agree to within one quantisation
step). **That equality is the instrument being correct, not physics.**
The flavors only diverge once real cells carry real delays — and those
exist in silicon, which is the point of the chip.

Under `GATES=yes` the three ring-enabling tests are **skipped**, and only
`test_ro_off` (which never lights a ring) runs. This is not caution, it
is necessity: sky130's `FUNCTIONAL` cell models are plain `not`/`buf`
primitives with no delay — `UNIT_DELAY` is applied only to the sequential
cells — so a gate-level ring is a zero-delay combinational loop and the
simulator spins forever at a single timestamp. Measured the hard way: a
`gl_test` job ran 2 h before it was killed. Timing a ring needs an
SDF-annotated run, or silicon.

## `test_sine.py` — the CORDIC-1 half

This RTL is the fabricated chip's, vendored unchanged, so its real
verification lives in [the CORDIC-1 repo](https://github.com/JoonatanAlanampa/CORDIC):
exhaustive 65,536-angle engine check, FFT harmonic check, SymbiYosys
k-induction proof of the control path. What is re-proven here is only
that the mode strap and the read-out mux did not disturb it — the 440 Hz
wake-up tone, a mid-range code, sigma-delta density, and that the rings
stay dark whenever `ui[7]` is low.
