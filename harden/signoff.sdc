# Signoff-only constraints: give STA the ring-oscillator clock domain.
#
# WHY THIS FILE EXISTS (READINESS.md M6)
# -------------------------------------
# Until 2026-08-02 this repo had no SDC at all — no create_clock beyond the
# flow's default, and the run log said so outright:
#     'SIGNOFF_SDC_FILE' is not defined. Using [the default]
# So `ro_clk` was not a clock as far as OpenSTA was concerned, and the fastest
# logic on the die had never been timed: `u_ro_meas.pre` is an 8-bit counter
# clocked DIRECTLY by the selected ring. Post-H3 the rings are predicted at
# 914 / 658 / 412 MHz, against a DFF_X1 whose own liberty puts clk->Q at
# 158-300 ps. Whether that counter closes is the difference between an
# instrument and a random number generator, and nothing was checking it.
#
# WHY SIGNOFF ONLY, AND WHY THAT IS THE WHOLE POINT
# -------------------------------------------------
# LibreLane keeps PNR_SDC_FILE (used by placement, CTS, resizing) separate
# from SIGNOFF_SDC_FILE (used by the STA steps). This file is wired to the
# SIGNOFF one ONLY, deliberately:
#
#   *** DO NOT SET THIS AS PNR_SDC_FILE. ***
#
# If CTS sees `ro_clk` as a clock it will build a clock tree on it — i.e.
# insert buffers onto the ring nodes. That is precisely the H3 defect that
# cost this chip a 1.5-1.7x error in the number it exists to measure, arriving
# by a different road. Measured on run 30752441492, CTS currently leaves the
# rings alone (routed netlist: every ring stage drives exactly one next stage
# plus the three taps), and tools/audit_netlist.py now asserts that on the
# ROUTED netlist every run. Setting this file for P&R would break it.
#
# The ring loop itself needs no explicit break: OpenSTA already breaks the
# combinational cycle on its own, which is visible as exactly one stage per
# ring reporting a 0.000 A->Y arc in the SDF (READINESS.md M7).

# ---------------------------------------------------------------- base
# Keep everything the flow would otherwise have applied. Sourcing the
# fallback is preferred over copying it, so a change to CLOCK_PERIOD or the
# IO delays upstream is picked up here instead of silently diverging; the
# explicit branch is a safety net if the variable is not exported.
if {[info exists ::env(FALLBACK_SDC)] && [file exists $::env(FALLBACK_SDC)]} {
    puts "signoff.sdc: sourcing FALLBACK_SDC $::env(FALLBACK_SDC)"
    source $::env(FALLBACK_SDC)
} else {
    puts "signoff.sdc: FALLBACK_SDC unavailable — applying the explicit copy"
    create_clock -name clk -period 20.0000 [get_ports {clk}]
    set_clock_transition 0.1500 [get_clocks {clk}]
    set_clock_uncertainty 0.2500 clk
    foreach p [get_ports {ena rst_n ui_in[*] uio_in[*]}] {
        set_input_delay 4.0000 -clock [get_clocks {clk}] -add_delay $p
    }
    foreach p [get_ports {uo_out[*] uio_out[*] uio_oe[*]}] {
        set_output_delay 4.0000 -clock [get_clocks {clk}] -add_delay $p
        set_load -pin_load 0.0334 $p
    }
    set_max_transition 0.7500 [current_design]
    set_max_capacitance 0.2000 [current_design]
    set_max_fanout 10.0000 [current_design]
}

# ------------------------------------------------------- the ring domain
# Period = the FASTEST predicted ring, because that is the worst case for the
# counter: ro_clk is a mux of the three, only one enabled at a time, so the
# prescaler must survive whichever is quickest. From flow/ring_prediction.py
# on the post-H3 netlist at nom_tt_025C_1v80: INV 914.1 MHz -> 1.094 ns
# (NAND2 658.3 -> 1.519, NOR2 411.7 -> 2.429).
#
# NOTE this number is a PREDICTION and is known optimistic (M7: no
# interconnect delay in the SDF, one stage per ring dropped by the loop
# break). Silicon may well be faster still. Revisit when the rings are
# measured; if the counter is marginal here it is marginal there.
set ro_period 1.094

set ro_net [get_nets -quiet {u_ro_meas.ro_clk}]
if {$ro_net eq ""} {
    # Loud, because silently skipping is how this went unnoticed for weeks.
    puts "signoff.sdc: ERROR ring clock net 'u_ro_meas.ro_clk' NOT FOUND."
    puts "signoff.sdc: the prescaler is UNCONSTRAINED and M6 is still open."
} else {
    create_clock -name ro_clk -period $ro_period $ro_net
    puts "signoff.sdc: ro_clk constrained at $ro_period ns on u_ro_meas.ro_clk"

    # The ring is free-running and unrelated to clk. Everything that crosses
    # goes through the three-stage synchronizer in ro_meas, so cross-domain
    # paths are not real timing paths and would otherwise be reported as
    # thousands of false violations.
    set_clock_groups -asynchronous -name ro_vs_sys \
        -group [get_clocks {clk}] -group [get_clocks {ro_clk}]

    # The prescaler is a ripple-free binary counter clocked by the ring, so
    # its own setup/hold IS a real check and is left ON purpose-built.
}
