.title EvoLDO SKY130 operating point and quiescent-current gate
.lib "{{MODEL_LIB}}" {{CORNER}}
.include "{{CANDIDATE_NETLIST}}"
.temp {{TEMPERATURE_C}}
VVDD VDD 0 1.8
VVREF VREF 0 1.0
VENB ENB 0 0
XU VDD 0 VREF ENB VOUT evoldo_sky130_ldo
ILOAD VOUT 0 1m
CLOAD VOUT 0 10p
.tran 0.1u 100u
.meas tran vout_final FIND v(VOUT) AT=90u
.meas tran vfb_final FIND v(XU.VFB) AT=90u
.meas tran supply_current AVG par('-i(VVDD)') FROM=80u TO=90u
.meas tran quiescent_current AVG par('-i(VVDD)-0.001') FROM=80u TO=90u
.end
