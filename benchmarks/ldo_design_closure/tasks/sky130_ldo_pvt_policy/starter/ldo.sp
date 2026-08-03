* EvoLDO-Bench original SKY130 capless LDO development reference.
* Independently authored for this benchmark; not copied from an external circuit.
* Pin order: VDD VSS VREF ENB VOUT. ENB is active high.
* The DUT contains no independent/controlled ideal source or forced initial state.
.subckt evoldo_sky130_ldo VDD VSS VREF ENB VOUT
RBIAS VDD VBN 120k
XMBIAS VBN VBN VSS VSS sky130_fd_pr__nfet_01v8 L=0.5 W=8
XMTAIL NTAIL VBN VSS VSS sky130_fd_pr__nfet_01v8 L=0.5 W=16
XM1 NLEFT VFB NTAIL VSS sky130_fd_pr__nfet_01v8 L=0.5 W=40
XM2 VCTRL VREF NTAIL VSS sky130_fd_pr__nfet_01v8 L=0.5 W=40
XM3 NLEFT NLEFT VDD VDD sky130_fd_pr__pfet_01v8 L=0.5 W=80
XM4 VCTRL NLEFT VDD VDD sky130_fd_pr__pfet_01v8 L=0.5 W=80
XMPASS VOUT VCTRL VDD VDD sky130_fd_pr__pfet_01v8 L=0.15 W=10
XMOFF VBN ENB VSS VSS sky130_fd_pr__nfet_01v8 L=0.15 W=20
RGOFF VDD VCTRL 5Meg
RFBTOP VOUT VFB 500k
RFBBOT VFB VSS 1Meg
CCOMP VCTRL VOUT 5p
.ends evoldo_sky130_ldo
