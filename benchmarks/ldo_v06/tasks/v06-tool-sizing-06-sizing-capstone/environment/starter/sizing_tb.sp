* EvoLDO SKY130 sizing probe
.lib '{{model}}' tt
.param WP={{pass_width_um}} WI={{input_width_um}} RD={{driver_res_kohm}}k CC={{ccomp_pf}}p RB={{bias_res_kohm}}k RT={{rtop_kohm}}k RBT={{rbot_kohm}}k
VVIN vdd 0 1.8
VREF ref 0 1.0
RBIAS vdd vbn {RB}
XMBIAS vbn vbn 0 0 sky130_fd_pr__nfet_01v8 L=.5 W=8
XMTAIL ntail vbn 0 0 sky130_fd_pr__nfet_01v8 L=.5 W=16
XM1 nleft vfb ntail 0 sky130_fd_pr__nfet_01v8 L=.5 W=20 M={WI/20}
XM2 vctrl ref ntail 0 sky130_fd_pr__nfet_01v8 L=.5 W=20 M={WI/20}
XM3 nleft nleft vdd vdd sky130_fd_pr__pfet_01v8 L=.5 W=80
XM4 vctrl nleft vdd vdd sky130_fd_pr__pfet_01v8 L=.5 W=80
RDRV vctrl gate {RD}
XMPASS vout gate vdd vdd sky130_fd_pr__pfet_01v8 L=.15 W=20 M={WP/20}
RFBT vout vfb {RT}
RFBB vfb 0 {RBT}
CCOMP vctrl vout {CC}
RLOAD vout 0 1.5k
CLOAD vout 0 10p
.tran .1u 20u
.meas tran EVOLDO_VOUT FIND v(vout) AT=19u
.meas tran EVOLDO_IQ AVG par('-i(VVIN)-0.001') FROM=18u TO=19u
.end
