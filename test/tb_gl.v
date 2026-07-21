`default_nettype none
`timescale 1ns / 1ps

/* Gate-level testbench for the ALL-OWN netlist, with post-P&R SDF back-
   annotated. This is the only configuration in which the ring oscillators
   can be simulated at all: at zero delay they are a combinational loop
   that spins forever at one timestamp (PLAN.md phase 4).

   SDF_FILE is passed in with -DSDF_FILE=\"...\" so one testbench serves
   every corner.
*/
module tb ();

  // Dumping is OFF unless asked for: at these frequencies a full-depth FST
  // of a ring oscillator grows without bound (measured: 22 GB of RAM before
  // the run was killed). Build with -DDUMP if you need waves.
`ifdef DUMP
  initial begin
    $dumpfile("tb_gl.fst");
    $dumpvars(2, tb);
    #1;
  end
`endif

  reg clk;
  reg rst_n;
  reg ena;
  reg [7:0] ui_in;
  reg [7:0] uio_in;
  wire [7:0] uo_out;
  wire [7:0] uio_out;
  wire [7:0] uio_oe;

  tt_um_joonatanalanampa_vslice user_project (
      .ui_in  (ui_in),
      .uo_out (uo_out),
      .uio_in (uio_in),
      .uio_out(uio_out),
      .uio_oe (uio_oe),
      .ena    (ena),
      .clk    (clk),
      .rst_n  (rst_n)
  );

  // Annotate BEFORE any activity. Without this the netlist runs at zero
  // delay and the rings hang the simulator.
  initial begin
`ifdef SDF_FILE
    $sdf_annotate(`SDF_FILE, user_project);
`else
    $display("FATAL: tb_gl needs -DSDF_FILE; a zero-delay ring will hang");
    $finish;
`endif
  end

endmodule
