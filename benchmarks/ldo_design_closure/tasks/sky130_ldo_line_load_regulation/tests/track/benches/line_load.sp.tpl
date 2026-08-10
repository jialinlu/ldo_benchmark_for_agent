.title EvoLDO SKY130 line/load regulation gate
.lib "{{MODEL_LIB}}" {{CORNER}}
.include "{{CANDIDATE_NETLIST}}"
.temp {{TEMPERATURE_C}}
VVDD VDD 0 PWL(0 1.8 200u 1.8 201u 1.65 400u 1.65)
VVREF VREF 0 1.0
VENB ENB 0 0
XU VDD 0 VREF ENB VOUT evoldo_sky130_ldo
ILOAD VOUT 0 PWL(0 100u 100u 100u 101u 1m 300u 1m 301u 100u 400u 100u)
CLOAD VOUT 0 10p
.tran 0.2u 400u
.meas tran vout_180_light FIND v(VOUT) AT=90u
.meas tran vout_180_heavy FIND v(VOUT) AT=190u
.meas tran vout_165_heavy FIND v(VOUT) AT=290u
.meas tran vout_165_light FIND v(VOUT) AT=390u
.end
