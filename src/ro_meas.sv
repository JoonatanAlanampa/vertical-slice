// ro_meas.sv — the instrument around the three ring oscillators:
// select one, let it warm up, count its (prescaled) edges for a fixed
// window of system clocks, latch the result for read-out.
//
//   f_ring = count * 2**PRE_BITS / (2**WINDOW / f_clk)
//
// Everything the measurement needs is on the chip; the outside world
// only supplies a known system clock. With f_clk = 25 MHz:
//
//   window   sysclk cycles   duration    count at a 320 MHz ring
//   short    2**12           164 us      ~205
//   long     2**20           41.9 ms     ~52 500     (0.002 % resolution)
//
// Clocking notes (this block deliberately breaks the single-clock rule —
// it is a test structure, and the STA exceptions belong in the hardening
// config, not in the RTL):
//   * `ro_clk` is a combinational mux of the three ring outputs. Only
//     one ring is ever enabled, and the disabled ones settle to a static
//     level, so the mux never glitches during a measurement; `sel` is
//     only ever changed with the FSM idle.
//   * the prescaler runs in the ring's own domain and is cleared DURING
//     WARM-UP, not by `rst`. It has no clock at all while its ring is
//     off, so a reset synchronous to it could never take effect — but
//     the warm-up window is precisely when the ring IS running, so that
//     is where the clear belongs. (The library's DFF_X1 has no reset
//     pin at all, which settles the question: an async-reset flop is not
//     something this chip can be built out of.)
//   * the prescaler's MSB crosses into the system clock domain through a
//     three-stage synchronizer; only its rising edges are counted, which
//     is why the prescaler must divide the ring below f_clk/4.
//
// Copyright (c) 2026 Joonatan Alanampa
// SPDX-License-Identifier: Apache-2.0

`default_nettype none

/* verilator lint_off DECLFILENAME */
module ro_meas #(
    parameter int STAGES    = 31,   // ring length, odd
    parameter int PRE_BITS  = 8,    // ring-domain prescaler: divide by 2**PRE_BITS
    parameter int WIN_SHORT = 12,   // window = 2**WIN_SHORT system clocks
    parameter int WIN_LONG  = 20,
    parameter int WARM      = 256   // system clocks of ring warm-up before counting
) (
    input  wire         clk,
    input  wire         rst,

    input  wire  [1:0]  sel,        // 0 = all off, 1 = INV, 2 = NAND2, 3 = NOR2
    input  wire         run,        // level: keep measuring while high
    input  wire         win_long,

    output logic [23:0] count,      // last completed measurement
    output logic        busy,
    output logic        valid,      // sticky: at least one measurement done
    output wire         div_live    // prescaled ring, synchronized (scope/LED)
);

  // ------------------------------------------------------------ rings
  logic [2:0] ring_en;
  wire  [2:0] osc;

  ro_ring #(.STAGES(STAGES), .FLAVOR("INV"))   u_ro_inv   (.en(ring_en[0]), .osc(osc[0]));
  ro_ring #(.STAGES(STAGES), .FLAVOR("NAND2")) u_ro_nand2 (.en(ring_en[1]), .osc(osc[1]));
  ro_ring #(.STAGES(STAGES), .FLAVOR("NOR2"))  u_ro_nor2  (.en(ring_en[2]), .osc(osc[2]));

  // ------------------------------------------------------- FSM + window
  localparam logic [1:0] S_IDLE = 2'd0, S_WARM = 2'd1, S_MEAS = 2'd2;

  logic [1:0]          st;
  logic [WIN_LONG-1:0] tick;
  logic [23:0]         acc;

  wire armed = (st != S_IDLE);
  wire [WIN_LONG-1:0] win_top = win_long ? {WIN_LONG{1'b1}}
                                         : {{(WIN_LONG-WIN_SHORT){1'b0}}, {WIN_SHORT{1'b1}}};

  // The `rst` term is not redundant: it makes the rings provably dark
  // whenever reset is asserted, without depending on `st` being resolved.
  // In a zero-delay gate-level netlist an X on a ring enable is not a
  // stale value, it is a simulator that may never converge.
  always_comb begin
    ring_en = 3'b000;
    if (!rst && armed && sel != 2'd0) ring_en[sel - 2'd1] = 1'b1;
  end

  // ------------------------------------------- ring-domain prescaler
  logic ro_clk;
  always_comb begin
    case (sel)
      2'd1:    ro_clk = osc[0];
      2'd2:    ro_clk = osc[1];
      2'd3:    ro_clk = osc[2];
      default: ro_clk = 1'b0;
    endcase
  end

  // Cleared throughout WARM (the ring is running then, by construction), so
  // every measurement starts from a known phase. The clear is released one
  // ring cycle either side of the window opening — that race costs at most
  // the same +-1 count the edge quantisation already costs.
  wire pre_clr = (st == S_WARM);

  logic [PRE_BITS-1:0] pre;
  always_ff @(posedge ro_clk)
    if (pre_clr) pre <= '0;
    else         pre <= pre + 1'b1;

  // --------------------------------------- crossing into the system clock
  // Masked outside the measurement window. The prescaler has no reset (see
  // above), so before its first warm-up its bits are whatever the flops
  // powered up as — random in silicon, X in simulation, and either way not
  // something to route to an output pin. Inside S_MEAS it is defined by
  // construction, because WARM just cleared it.
  wire div_raw = (st == S_MEAS) && pre[PRE_BITS-1];

  logic [2:0] sync;
  always_ff @(posedge clk)
    if (rst) sync <= 3'b000;
    else     sync <= {sync[1:0], div_raw};

  wire div_edge = sync[1] & ~sync[2];
  assign div_live = sync[2];

  // ------------------------------------------------------------- control
  always_ff @(posedge clk)
    if (rst) begin
      st    <= S_IDLE;
      tick  <= '0;
      acc   <= '0;
      count <= '0;
      busy  <= 1'b0;
      valid <= 1'b0;
    end else begin
      case (st)
        S_IDLE:
          if (run && sel != 2'd0) begin
            st   <= S_WARM;
            tick <= '0;
            busy <= 1'b1;
          end else
            busy <= 1'b0;

        S_WARM: begin
          tick <= tick + 1'b1;
          if (tick == (WARM - 1)) begin
            st   <= S_MEAS;
            tick <= '0;
            acc  <= '0;
          end
        end

        S_MEAS: begin
          tick <= tick + 1'b1;
          if (div_edge) acc <= acc + 1'b1;
          if (tick == win_top) begin
            count <= div_edge ? acc + 1'b1 : acc;
            valid <= 1'b1;
            busy  <= 1'b0;
            st    <= S_IDLE;
          end
        end

        default: st <= S_IDLE;
      endcase
    end

endmodule
/* verilator lint_on DECLFILENAME */
