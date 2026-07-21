// ro_ring.sv — one enable-gated ring oscillator, built from ONE cell
// flavor of the self-made standard-cell library.
//
// The whole point of this block is that it is NOT ordinary RTL: it is a
// physical measurement instrument. Each ring is a chain of STAGES gates
// of a single flavor; its oscillation period is 2 * STAGES * tp, so the
// measured frequency is a direct read-out of that cell's propagation
// delay in real silicon at the real supply and the real temperature.
// Three rings (INV / NAND2 / NOR2) give three points of the library's
// delay model — the numbers our own characterizer (stdcells
// flow/characterize.py) predicted from ngspice, and that DEVSIM
// predicted from device physics before that. Closing that loop on
// silicon is the reason this chip exists.
//
// Every stage is an instance of a NAMED CELL in the two hardening
// builds (`USE_HD_CELLS / `USE_OWN_CELLS); only simulation uses
// behavioural gates. See ro_stage at the bottom of this file for why.
//
// STAGES must be ODD. Stage 0 carries the enable, so the "INV" ring is
// 30 inverters + 1 NAND2 (the standard enable-gated ring); the NAND2 and
// NOR2 rings are homogeneous, their stage 0 taking the enable on its
// second input and the other stages tying it to the inactive level.
//
// Copyright (c) 2026 Joonatan Alanampa
// SPDX-License-Identifier: Apache-2.0

`default_nettype none
`timescale 1ns / 1ps

/* verilator lint_off DECLFILENAME */
module ro_ring #(
    parameter int  STAGES    = 31,      // odd
    parameter      FLAVOR    = "INV",   // "INV" | "NAND2" | "NOR2"
    parameter real STAGE_DLY = 0.1      // ns, simulation only (ignored by synthesis)
) (
    input  wire en,
    output wire osc
);

  // The ring is a deliberate combinational loop, and every tool in the
  // flow wants to simplify it away — a chain of 31 inverters is, to a
  // logic optimizer, one inverter. Measured, not assumed: with the nodes
  // merely marked `keep`, yosys+ABC collapsed all three rings to a SINGLE
  // gate each. Which is why a hardening build never lets the mapper near
  // them: every stage is an instance of a NAMED CELL (see ro_stage), so
  // there is nothing to optimize and no doubt about which cell was
  // measured. An "NAND2 ring" that ABC remapped to some other cell would
  // measure nothing.
  /* verilator lint_off UNOPTFLAT */
  (* keep = "true" *) wire [STAGES-1:0] n;
  /* verilator lint_on UNOPTFLAT */

  wire fb = n[STAGES-1];                // loop closure

  genvar i;
  generate
    for (i = 0; i < STAGES; i = i + 1) begin : g_stage
      // input of this stage
      wire a = (i == 0) ? fb : n[i-1];
      // enable leg: the enable on stage 0, the inactive constant elsewhere
      wire b = (i != 0)              ? (FLAVOR == "NOR2" ? 1'b0 : 1'b1)
             : (FLAVOR == "NOR2")    ? ~en
                                     :  en;
      // stage 0 of an inverter ring is the NAND2 that gates it
      localparam STAGE_FLAVOR = (FLAVOR == "INV" && i != 0) ? "INV"
                              : (FLAVOR == "NOR2")          ? "NOR2"
                                                            : "NAND2";

      (* keep = "true" *)
      ro_stage #(.FLAVOR(STAGE_FLAVOR), .STAGE_DLY(STAGE_DLY))
          u_stage (.a(a), .b(b), .y(n[i]));
    end
  endgenerate

  assign osc = n[STAGES-1];

endmodule
/* verilator lint_on DECLFILENAME */

// ---------------------------------------------------------------------
// One ring stage: exactly one gate.
//
// Three build modes, and only the first is ever simulated:
//
//   (default)        behavioural gate with a lumped STAGE_DLY, so the
//                    ring has a finite period in an event simulator.
//                    NEVER harden with this — the mapper collapses the
//                    chain (measured: 31 stages -> 1 gate).
//   `USE_HD_CELLS    sky130_fd_sc_hd cells: the reference build, the
//                    A/B partner of the PPA comparison.
//   `USE_OWN_CELLS   the pinned stdcells release: the chip we are
//                    actually here to measure.
//
// Instantiating cells by name is the whole point of a test structure:
// the measurement is only meaningful if we know exactly which cell it
// timed. It also removes the optimizer from the question entirely — a
// liberty cell instance is opaque to yosys, so the ring survives flatten,
// constant propagation and ABC without needing keep attributes at all.
// ---------------------------------------------------------------------
/* verilator lint_off DECLFILENAME */
module ro_stage #(
    parameter      FLAVOR    = "INV",   // "INV" | "NAND2" | "NOR2"
    parameter real STAGE_DLY = 0.1      // ns, simulation only
) (
    input  wire a,
    input  wire b,      // enable leg; tied to the inactive constant inside a chain
    output wire y
);
  generate
`ifdef USE_OWN_CELLS
    if (FLAVOR == "NAND2") begin : g_cell
      NAND2_X1 u_cell (.A(a), .B(b), .Y(y));
    end else if (FLAVOR == "NOR2") begin : g_cell
      NOR2_X1 u_cell (.A(a), .B(b), .Y(y));
    end else begin : g_cell
      INV_X1 u_cell (.A(a), .Y(y));
    end
`elsif USE_HD_CELLS
    if (FLAVOR == "NAND2") begin : g_cell
      sky130_fd_sc_hd__nand2_1 u_cell (.A(a), .B(b), .Y(y));
    end else if (FLAVOR == "NOR2") begin : g_cell
      sky130_fd_sc_hd__nor2_1 u_cell (.A(a), .B(b), .Y(y));
    end else begin : g_cell
      sky130_fd_sc_hd__inv_1 u_cell (.A(a), .Y(y));
    end
`else
    // Delays on continuous assignments are ignored by synthesis; they
    // exist only to give the event simulator a finite ring period.
    if (FLAVOR == "NAND2") begin : g_beh
      assign #(STAGE_DLY) y = ~(a & b);
    end else if (FLAVOR == "NOR2") begin : g_beh
      assign #(STAGE_DLY) y = ~(a | b);
    end else begin : g_beh
      assign #(STAGE_DLY) y = ~a;
    end
`endif
  endgenerate
endmodule
/* verilator lint_on DECLFILENAME */
