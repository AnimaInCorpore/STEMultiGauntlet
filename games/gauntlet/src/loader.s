; GAUNTLET.PRG: moves the runtime (runtime.bin, linked at RT_BASE) into place and starts it.  TOS is left behind:
; the runtime takes the whole machine (gauntlet.s).
	include	"map.i"
	include	"runtime_len.i"
	ifnd RESIDENT
RESIDENT = 1
	endc
	if RESIDENT
	include "resident.i"
	endc

MOVER = $800				; (below every load address; neither source nor destination)

	section text,code
	ifd NET
	moveq	#0,d7			; (-D NET: NETMASTR.CFG in the program's folder: this machine is the ring's master,
	clr.w	-(sp)			;  d7 = 'NETM' for the runtime, src/net.s)
	pea	netmaster(pc)
	move	#$3d,-(sp)		; Fopen
	trap	#1
	addq	#8,sp
	tst.l	d0
	bmi.s	.nm
	move	d0,-(sp)
	move	#$3e,-(sp)		; Fclose
	trap	#1
	addq	#4,sp
	move.l	#'NETM',d7
.nm:
	endc
	clr.l	-(sp)
	move	#$20,-(sp)		; Super
	trap	#1
	addq	#6,sp
	if RESIDENT
	; TOS still owns disk I/O and interrupts here. Load the indexed pack into high ST RAM
	; before moving the low runtime over TOS. Leave the final MB for TOS's temporary stack.
	cmp.l	#RS_BASE+RS_BYTES+$100000,$42e.w
	blo	.res_error
	clr.l	RS_BASE
	clr.w	-(sp)
	pea	res_name(pc)
	move.w	#$3d,-(sp)
	trap	#1
	addq.l	#8,sp
	tst.l	d0
	bmi	.res_error
	move.w	d0,d5
	pea	RS_BASE
	move.l	#RS_BYTES,-(sp)
	move.w	d5,-(sp)
	move.w	#$3f,-(sp)
	trap	#1
	lea	12(sp),sp
	move.l	d0,d4
	move.w	d5,-(sp)
	move.w	#$3e,-(sp)
	trap	#1
	addq.l	#4,sp
	cmp.l	#RS_BYTES,d4
	bne.s	.res_error
	cmp.l	#'RS14',RS_BASE
	bne.s	.res_error
	cmp.l	#RS_SIGNATURE,RS_BASE+24
	bne.s	.res_error
	bra.s	.res_loaded
.res_error:
	pea	res_error(pc)
	move.w	#9,-(sp)
	trap	#1
	addq.l	#6,sp
	move.w	#1,-(sp)
	move.w	#$4c,-(sp)
	trap	#1
.res_loaded:
	endc
	move	#$2700,sr
	lea	runtime(pc),a0
	move.l	#RUNTIME_LEN,d0
	lea	RT_BASE,a1
	lea	mover(pc),a2
	lea	MOVER.w,a3
	moveq	#(mover_end-mover)/2-1,d1
.c:	move.w	(a2)+,(a3)+
	dbf	d1,.c
	jmp	MOVER.w

; a0 = source, a1 = destination, d0 = bytes (a multiple of 4): either direction, overlapping
mover:
	cmp.l	a0,a1
	bhi.s	.back
.fwd:	move.l	(a0)+,(a1)+
	subq.l	#4,d0
	bgt.s	.fwd
	bra.s	.go
.back:	add.l	d0,a0
	add.l	d0,a1
.b:	move.l	-(a0),-(a1)
	subq.l	#4,d0
	bgt.s	.b
.go:	jmp	RT_BASE
mover_end:
	if RESIDENT
res_name:	dc.b "SPRITES.DAT",0
res_error:	dc.b "Cannot load SPRITES.DAT: check ST RAM and matching asset file.",13,10,0
	even
	endc
	ifd NET
netmaster:	dc.b	"NETMASTR.CFG",0
	even
	endc

	section data,data
	even
runtime:
	incbin	"runtime.bin"
