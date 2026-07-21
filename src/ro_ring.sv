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
// Two build modes:
//   default            — behavioural gates with a lumped STAGE_DLY, so
//                        the ring oscillates in an event simulator and
//                        the read-out path can be tested end to end.
//   `USE_OWN_CELLS     — structural instantiation of the pinned stdcells
//                        release (INV_X1 / NAND2_X1 / NOR2_X1). Zero
//                        delay in RTL sim (do not simulate this mode —
//                        it is for hardening and for gate-level sim with
//                        the characterized library).
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
(* keep_hierarchy *)
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
  // merely marked `keep`, yosys+ABC still collapsed all three rings to a
  // SINGLE gate each. What holds is a per-stage module boundary
  // (`keep_hierarchy` stops flatten, so ABC never sees two stages at
  // once) reinforced by `keep` on every instance.
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
// One ring stage: exactly one gate, kept in its own module so that no
// optimizer can see two of them at the same time.
// ---------------------------------------------------------------------
/* verilator lint_off DECLFILENAME */
(* keep_hierarchy *)
module ro_stage #(
    parameter      FLAVOR    = "INV",   // "INV" | "NAND2" | "NOR2"
    parameter real STAGE_DLY = 0.1      // ns, simulation only
) (
    input  wire a,
    input  wire b,      // enable leg; tied to the inactive constant inside a chain
    output wire y
);
`ifdef USE_OWN_CELLS
  // hardening / gate-level: the pinned stdcells release, by cell name
  generate
    if (FLAVOR == "NAND2")     begin : g_own  NAND2_X1 u_cell (.A(a), .B(b), .Y(y));
    end else if (FLAVOR == "NOR2") begin : g_own  NOR2_X1 u_cell (.A(a), .B(b), .Y(y));
    end else                   begin : g_own  INV_X1   u_cell (.A(a),         .Y(y));
    end
  endgenerate
`else
  // simulation / foundry-library reference build. Delays on continuous
  // assignments are ignored by synthesis (yosys warns and drops them);
  // they exist only to give the event simulator a finite ring period.
  generate
    if (FLAVOR == "NAND2")     begin : g_beh  assign #(STAGE_DLY) y = ~(a & b);
    end else if (FLAVOR == "NOR2") begin : g_beh  assign #(STAGE_DLY) y = ~(a | b);
    end else                   begin : g_beh  assign #(STAGE_DLY) y = ~a;
    end
  endgenerate
`endif
endmodule
/* verilator lint_on DECLFILENAME */
