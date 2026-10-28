; The renderer in a harness for engine/sim.py (tools/render_test.py, tools/sprite_test.py): no game, no interrupts.
; The harness writes the arcade's video RAM, palette and x scroll at their STE addresses (map.i) while the program
; waits at sim_wait, then lets it draw a picture (render_frame; it stops at sim_render_ret).  The first time,
; init_video runs before the picture (on the first state, as gauntlet.s calls it on the BIOS's).

	include	"map.i"
PIC_TOP = 0				; (as gauntlet.s)
TA_DATA = 98
TA_NOPS = 84
PIC_LINES = 276
BD_PALETTE = 1
BD_HUD = 1
BD_VSWITCH = 1
BD_BAND = 1
BD_BAND_TOP = 162
BD_BAND_N = 57
BD_BAND_REG = $ffff8240+2*15
	include	"borders.s"

	section	text,code
start:
	lea	stack_top,sp
	jsr	sim_wait
	bsr	init_video
.loop:	addq.l	#1,rf_vbls		; (a VBL a picture: render.s counts them in vbl_video, which nothing calls here)
	bsr	render_frame
	jsr	sim_render_ret
	jsr	sim_wait
	bra.s	.loop

sim_wait:
	bra.s	sim_wait
sim_render_ret:
	bra.s	sim_render_ret

	include	"render.s"
	borders_blit_go

	section	bss,bss
	borders_vars
	even
	ds.b	16384
stack_top:
