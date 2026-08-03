.title EvoLDO SKY130 load-transient gate
.lib "{{MODEL_LIB}}" {{CORNER}}
.include "{{CANDIDATE_NETLIST}}"
.temp {{TEMPERATURE_C}}
VVDD VDD 0 1.8
VVREF VREF 0 1.0
VENB ENB 0 0
XU VDD 0 VREF ENB VOUT evoldo_sky130_ldo
ILOAD VOUT 0 PWL(0 100u 100u 100u 100.1u 1m 200u 1m 200.1u 100u 400u 100u)
CLOAD VOUT 0 10p
.tran 0.02u 400u
.meas tran vout_pre FIND v(VOUT) AT=90u
.meas tran vout_heavy FIND v(VOUT) AT=190u
.meas tran vout_post FIND v(VOUT) AT=390u
.meas tran vout_dip MIN v(VOUT) FROM=99u TO=150u
.meas tran vout_peak MAX v(VOUT) FROM=199u TO=250u
.end
