.title EvoLDO SKY130 true cold-start gate
.lib "{{MODEL_LIB}}" {{CORNER}}
.include "{{CANDIDATE_NETLIST}}"
.temp {{TEMPERATURE_C}}
VVDD VDD 0 PWL(0 0 10u 0 30u 1.8)
VVREF VREF 0 PWL(0 0 10u 0 30u 1.0)
VENB ENB 0 0
XU VDD 0 VREF ENB VOUT evoldo_sky130_ldo
RLOAD VOUT 0 1.5k
CLOAD VOUT 0 10p
.tran 0.2u 120u
.meas tran vout_final FIND v(VOUT) AT=110u
.meas tran startup_time TRIG v(VOUT) VAL=0.15 RISE=1 TARG v(VOUT) VAL=1.425 RISE=1
.end
