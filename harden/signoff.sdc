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
# PERIOD IS PER CORNER, and that is not a refinement — a single number is
# WRONG here. A ring oscillator's period is made of the same cells as the
# counter it clocks, so the two track: at the slow corner the ring slows down
# exactly as the counter does. Constraining every corner at the tt period
# demanded 1.094 ns of a counter built from ss cells while the ss ring
# physically runs at 1.494 ns — a fast-ring/slow-counter combination that
# cannot occur in silicon. It produced 5 phantom setup violations, all in
# this domain, WNS -108 ps (run 30758645627).
#
# Measured per corner with flow/ring_prediction.py on the post-H3 netlist,
# once the corners became real (M10). Value = the FASTEST of the three rings
# at that corner, because ro_clk is a mux and the counter must survive
# whichever ring is selected:
#
#     corner              INV     NAND2    NOR2   -> ro_clk period
#     *_ff_n40C_1v95     1.01     1.27     2.04      1.006  (994 MHz)
#     *_tt_025C_1v80     1.13     1.54     2.39      1.116  (896 MHz)
#     *_ss_100C_1v60     1.49     2.28     3.29      1.477  (677 MHz)
#
# Each entry is the min across that PVT's nom/min/max interconnect variants,
# so the constraint is the tightest of the group.
#
# These are PREDICTIONS, and M7 makes them optimistic (no interconnect delay
# in the SDF, one stage per ring dropped by the loop break). Optimistic here
# means the predicted period is SHORTER than reality, so the counter is being
# asked to do more than silicon will: the error is on the safe side. Revisit
# against the first real measurement anyway.
array set ro_period_by_pvt {
    ff_n40C_1v95 1.006
    tt_025C_1v80 1.116
    ss_100C_1v60 1.477
}
set ro_corner "<unset>"
if {[info exists ::env(_CURRENT_CORNER_NAME)]} {
    set ro_corner $::env(_CURRENT_CORNER_NAME)
}
# Default to the globally fastest ring: if the corner cannot be identified we
# over-constrain rather than under-constrain, and say so loudly.
set ro_period 1.006
set ro_matched 0
foreach {pvt period} [array get ro_period_by_pvt] {
    if {[string match "*$pvt*" $ro_corner]} {
        set ro_period $period
        set ro_matched 1
    }
}
if {$ro_matched} {
    puts "signoff.sdc: corner '$ro_corner' -> ro_clk period $ro_period ns"
} else {
    puts "signoff.sdc: WARNING corner '$ro_corner' not recognised; falling back"
    puts "signoff.sdc: to the global fastest ring ($ro_period ns). Expect"
    puts "signoff.sdc: pessimistic setup results in the ring domain at slow PVT."
}

# create_clock takes a PIN or a PORT, never a net — passing the net fails with
# "pins type 'Net' is not..." and kills STA at every corner (run 30755908998).
# The net name `u_ro_meas.ro_clk` is stable because it comes from the RTL
# signal, but its DRIVER is a generated instance (`NAND2_X1 _2736_` today), so
# hardcoding the pin would silently rot on the next resynthesis. Derive it.
set ro_net [get_nets -quiet {u_ro_meas.ro_clk}]
set ro_pin ""
if {$ro_net ne ""} {
    foreach spec {{direction == output} {direction == out}} {
        if {[catch {set try [get_pins -quiet -of_objects $ro_net -filter $spec]}]} {
            continue
        }
        if {$try ne ""} { set ro_pin $try; break }
    }
}
if {$ro_pin eq ""} {
    # Loud, because silently skipping is how this went unnoticed for weeks.
    # Never fall back to an unfiltered get_pins here: that returns the eight
    # prescaler CLK inputs as well as the driver, and defining a clock on each
    # would be worse than defining none.
    if {$ro_net eq ""} {
        set why "the net 'u_ro_meas.ro_clk' itself was not found"
    } else {
        set why "the net exists but its output pin could not be selected"
    }
    puts "signoff.sdc: ERROR ring clock not constrained - $why."
    puts "signoff.sdc: the prescaler is UNCONSTRAINED and M6 is still open."
} else {
    create_clock -name ro_clk -period $ro_period $ro_pin
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
