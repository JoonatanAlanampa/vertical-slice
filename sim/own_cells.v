// own_cells.v — simulation models for the cells in the pinned stdcells
// release (lib.lock). Written HERE, not shipped by the library: lib-v1.0
// contains Liberty, LEF, GDS and SPICE, but no Verilog view.
//
// The `specify` blocks are the whole point. Without them $sdf_annotate has
// nothing to annotate, the netlist simulates at zero delay, and the ring
// oscillators become an infinite loop at a single timestamp (which is
// exactly how a 2 h CI job died — see PLAN.md phase 4). With them, the
// post-P&R SDF drives real per-instance delays and the rings oscillate at
// the frequency our own timing model predicts.
//
// Functional content is deliberately minimal: these models exist to carry
// delays, and the cells' logic was proven by LVS against the layouts in
// stdcells, not here.
//
// Copyright (c) 2026 Joonatan Alanampa
// SPDX-License-Identifier: Apache-2.0

`default_nettype none
`timescale 1ns / 1ps
`celldefine

module INV_X1 (input wire A, output wire Y);
  assign Y = ~A;
  specify
    (A => Y) = (0.04, 0.03);
  endspecify
endmodule

module INV_X2 (input wire A, output wire Y);
  assign Y = ~A;
  specify
    (A => Y) = (0.04, 0.03);
  endspecify
endmodule

module INV_X4 (input wire A, output wire Y);
  assign Y = ~A;
  specify
    (A => Y) = (0.04, 0.03);
  endspecify
endmodule

module BUF_X1 (input wire A, output wire Y);
  assign Y = A;
  specify
    (A => Y) = (0.08, 0.07);
  endspecify
endmodule

module BUF_X2 (input wire A, output wire Y);
  assign Y = A;
  specify
    (A => Y) = (0.08, 0.07);
  endspecify
endmodule

module BUF_X4 (input wire A, output wire Y);
  assign Y = A;
  specify
    (A => Y) = (0.08, 0.07);
  endspecify
endmodule

module NAND2_X1 (input wire A, input wire B, output wire Y);
  assign Y = ~(A & B);
  specify
    (A => Y) = (0.04, 0.04);
    (B => Y) = (0.04, 0.04);
  endspecify
endmodule

module NOR2_X1 (input wire A, input wire B, output wire Y);
  assign Y = ~(A | B);
  specify
    (A => Y) = (0.05, 0.05);
    (B => Y) = (0.05, 0.05);
  endspecify
endmodule

// Positive-edge D flip-flop, no reset — the library has no flop with one,
// which is why ro_meas clears its prescaler during warm-up instead.
module DFF_X1 (input wire CLK, input wire D, output reg Q);
  always @(posedge CLK) Q <= D;
  specify
    (posedge CLK => (Q +: D)) = (0.27, 0.27);
    $setup(D, posedge CLK, 0.0);
    $hold(posedge CLK, D, 0.0);
  endspecify
endmodule

module TIE_X1 (output wire HI, output wire LO);
  assign HI = 1'b1;
  assign LO = 1'b0;
endmodule

// Physical-only cells: no function, present in the netlist for the
// floorplan's sake.
module WELLTAP_X1 ();
endmodule

module DIODE_X1 (input wire DIODE);
endmodule

module FILL_X1 ();
endmodule

module FILL_X2 ();
endmodule

module FILL_X4 ();
endmodule

module FILL_X8 ();
endmodule

`endcelldefine
`default_nettype wire
