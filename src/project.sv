/*
 * VERTICAL SLICE — CORDIC-1, re-built out of nothing but our own work,
 * plus the device-physics test structures that measure what we built.
 *
 * The logic is the taped-out CORDIC-1 sine generator (TTSKY26c, commit
 * b646d057) — same RTL, same instrument behaviour — but this time every
 * transistor, cell layout, Liberty timing arc and LEF abstract under it
 * comes from our own library (../stdcells), which in turn is sized from
 * our own device physics (../devphys). The ring oscillators are the
 * measurement that closes that loop on real silicon: one ring per cell
 * flavor, so the die itself reports the propagation delay we predicted.
 *
 * ui[7] is the mode strap:
 *
 *   ui[7] = 0  — SINE MODE (the chip's function; identical to CORDIC-1)
 *     ui[6:0]  frequency code: 0 -> 440 Hz wake-up tone,
 *              1..126 -> code * ~68 Hz, 127 -> ~2 Hz LED breathe
 *     uo[7]    sine sigma-delta (TT Audio Pmod position; RC -> analog)
 *     uo[6]    phase-locked square sync
 *     uo[5:1]  live sine level bar (offset binary)
 *     uo[0]    ~1.5 Hz heartbeat
 *
 *   ui[7] = 1  — TEST-STRUCTURE MODE (the instrumentation)
 *     ui[1:0]  ring select: 0 = all off, 1 = INV, 2 = NAND2, 3 = NOR2
 *     ui[3:2]  read-out mux: 0/1/2 = count[7:0]/[15:8]/[23:16],
 *              3 = status
 *     ui[4]    run (level; measurements repeat while high)
 *     ui[5]    window: 0 = 2**12 clocks (164 us), 1 = 2**20 (41.9 ms)
 *     ui[6]    unused
 *     uo[7:0]  selected read-out byte
 *              status = {heartbeat, div_live, 4'b0, valid, busy}
 *
 * Rings stay powered down unless a measurement is running, so sine mode
 * is bit-identical to the fabricated chip's behaviour.
 *
 * Copyright (c) 2026 Joonatan Alanampa
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module tt_um_joonatanalanampa_vslice (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered, so you can ignore it
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);

  wire rst = ~rst_n;

  assign uio_out = 8'h00;
  assign uio_oe  = 8'h00;

  wire test_mode = ui_in[7];

  // ==================================================== SINE (CORDIC-1)
  // fs = clk / 359 (constant-time bit-serial op) = 69.64 kHz at 25 MHz.
  // f = inc / 2^20 * fs:  code<<10 -> ~68 Hz per step.
  wire [6:0] code = ui_in[6:0];
  wire [19:0] dds_inc = (code == 7'd0)   ? 20'd6625   // 440.0 Hz wake-up tone
                      : (code == 7'd127) ? 20'd30     // ~2 Hz breathe mode
                      : {3'b000, code, 10'b0};

  logic [19:0] phase;

  logic        eng_busy;
  logic        eng_done;
  logic signed [15:0] eng_cos, eng_sin;

  cordic u_cordic (
      .clk(clk), .rst(rst),
      .start(!eng_busy), .mode(1'b0),
      .zi(phase[19:4]), .xi(16'sd0), .yi(16'sd0),
      .done(eng_done), .cos_o(eng_cos), .sin_o(eng_sin),
      /* verilator lint_off PINCONNECTEMPTY */
      .zo()
      /* verilator lint_on PINCONNECTEMPTY */
  );

  always_ff @(posedge clk)
    if (rst) begin
      eng_busy <= 1'b0;
      phase    <= 20'd0;
    end else begin
      if (!eng_busy) begin               // issue the next conversion
        eng_busy <= 1'b1;
        phase    <= phase + dds_inc;
      end else if (eng_done)
        eng_busy <= 1'b0;
    end

  // sample latch: hold the wave steady between conversions
  logic signed [15:0] sin_s;
  always_ff @(posedge clk)
    if (rst)           sin_s <= 16'sd0;
    else if (eng_done) sin_s <= eng_sin;

  // first-order sigma-delta: the carry-out's density IS the sample value
  logic [16:0] sd_sin;
  always_ff @(posedge clk)
    if (rst) sd_sin <= 17'd0;
    else     sd_sin <= {1'b0, sd_sin[15:0]} + {1'b0, sin_s ^ 16'h8000};

  // heartbeat: bit 23 of a free counter = ~1.5 Hz blink at 25 MHz
  logic [23:0] beat;
  always_ff @(posedge clk)
    if (rst) beat <= 24'd0;
    else     beat <= beat + 24'd1;

  wire [7:0] sine_bus = {sd_sin[16],
                         phase[19],
                         sin_s[15:11] ^ 5'b10000,   // LED bar, offset binary
                         beat[23]};

  // ============================================== TEST STRUCTURES (ROs)
  wire [23:0] ro_count;
  wire        ro_busy, ro_valid, ro_div_live;

  ro_meas u_ro_meas (
      .clk(clk), .rst(rst),
      .sel     (ui_in[1:0]),
      .run     (test_mode & ui_in[4]),
      .win_long(ui_in[5]),
      .count   (ro_count),
      .busy    (ro_busy),
      .valid   (ro_valid),
      .div_live(ro_div_live)
  );

  wire [7:0] ro_status = {beat[23], ro_div_live, 4'b0000, ro_valid, ro_busy};

  logic [7:0] ro_bus;
  always_comb
    case (ui_in[3:2])
      2'd0:    ro_bus = ro_count[7:0];
      2'd1:    ro_bus = ro_count[15:8];
      2'd2:    ro_bus = ro_count[23:16];
      default: ro_bus = ro_status;
    endcase

  // ================================================================ mux
  assign uo_out = test_mode ? ro_bus : sine_bus;

  wire _unused = &{ena, uio_in, eng_cos, 1'b0};

endmodule
