; net.s (-D NET, tools/build.py --net): up to four STEs in a MIDI ring (MIDI-Maze style), the game in lockstep.
;
; Every machine runs the whole game; only the players' inputs travel.  The game advances in ticks (60 a second, as
; the arcade's frames): a tick starts only when the game's thread waits (never in the middle of a frame: a VBL that
; comes while a frame runs is not passed on) and when every machine's input for that tick is in.  From the same
; boot state the same inputs give every machine the same game (tools/stemodel.py: the schedule without VBLs in
; the middle of frames runs the attract mode and play; its long frames, a maze being built, just take longer).
;
; The ring: machine k's MIDI OUT to machine k+1's MIDI IN, the last one's to the first's.  A packet is 6 bytes, the
; first with bit 7 set (the receiver frames on it), the others below $80:
;   $80 | kind << 4 | src << 2,  a,  b,  c,  d,  the checksum (the sum of the first five) & $7F
;   kind 0 INPUT: a = the tick T & $7F, b = the input for T & $7F, d = the input for T - 1 & $7F,
;                 c = T's input >> 7 | T's coin << 1 | (T - 1)'s input >> 7 << 2 | (T - 1)'s coin << 3 | T > 0 << 4
;                 (src: its machine; each packet carries the tick before too: a packet lost on the way, a byte
;                 overwritten at a busy port, is made good by the next one, a tick later, before it is needed)
;   kind 1 HELLO: a = the hops so far (from the master, machine 0)
;   kind 2 START: a = the machines in the ring
; Each machine passes on the packets of the others and drops its own when it comes back.  The master (the loader
; found NETMASTR.CFG: d7 = 'NETM' at the start) sends HELLO every half second until it comes back: every machine
; on the way takes the hops as its number and passes HELLO on with one more; back at the master the hops are the
; ring's size, and the master sends START.  (A cable that is not connected yet loses bytes; after HELLO went round,
; every cable works.)  Then every machine sends its input for the ticks up to NET_DELAY ahead of the one it runs
; (the delay hides the ring's latency: ~2 ms a 6-byte packet a hop at 31250 bit/s; 4 machines: ~1.4 KB/s a cable).
; When the ring stalls anyway (two packets in a row lost) every machine sends its last inputs again.
;
; Machine k is player k + 1 (Warrior, Valkyrie, Wizard, Elf): its keyboard, joysticks and pad are that player's
; input, its coin keys (and the pad's) that player's coin slot.

	ifnd NET_DELAY
NET_DELAY = 3				; (ticks: an input is sent for the tick this many after the one running)
	endc
NET_HELLO_VBLS = 25
NET_DUE_MAX = 3
				; (ticks owed at most: a long frame does not make the game race afterwards)
NET_STALL_VBLS = 8			; (VBLs waiting for inputs before this machine sends its last ones again: a
				;  packet lost (two in a row: each carries the tick before too), not one late)
MIDI_CTRL = $fffffc04
MIDI_DATA = $fffffc06
MIDI_RXON = $95				; /16 (31250 bit/s), 8N1, the receiver's interrupt, the transmitter's off
MIDI_TXON = $b5				; the same, the transmitter's interrupt on (while bytes wait)
NET_TXQ = 256				; (bytes waiting to be sent: a power of 2)

net_init:
	move.b	#3,MIDI_CTRL.w		; (master reset)
	move.b	#MIDI_RXON,MIDI_CTRL.w
	lea	net_vars,a0
	move.w	#(net_vars_end-net_vars)/2-1,d0
.c:	clr.w	(a0)+
	dbf	d0,.c
	lea	net_seq,a0
	moveq	#16*4-1,d0
.s:	st	(a0)+
	dbf	d0,.s
	st	net_id			; (no number yet)
	sf	acia_busy
	sf	vbl_busy
	clr.w	vbl_reentered
	cmp.l	#'NETM',net_boot
	bne.s	.x
	st	net_master
	clr.b	net_id
.x:	rts

; net_make_master: F1 before the ring runs (no NETMASTR.CFG on any machine): this machine the master
net_make_master:
	tst.b	net_run
	bne.s	.x
	tst.b	net_id			; (a number from a master's HELLO already: there is one)
	bpl.s	.x
	st	net_master
	clr.b	net_id
.x:	rts

; ---- sending (interrupts off inside) -------------------------------------------------------------------------------
; the 6 bytes at a0 sent, in one piece (the interrupt's forwarding must not come between them), the checksum
; made first: interrupts off for ~150 cycles (dropped when the queue has no room).  Keeps every register.
net_put6:
	move	sr,-(sp)
	or	#$0700,sr
	movem.l	d0-d1/a1,-(sp)
	move.b	(a0),d0			; the checksum
	add.b	1(a0),d0
	add.b	2(a0),d0
	add.b	3(a0),d0
	add.b	4(a0),d0
	and.b	#$7f,d0
	move.b	d0,5(a0)
	move.b	net_txt,d0		; (room: tail - head - 1, mod 256)
	sub.b	net_txh,d0
	subq.b	#1,d0
	cmp.b	#6,d0
	bhs.s	.room
	addq.w	#1,net_txfull
	bra.s	.out
.room:	moveq	#0,d0
	move.b	net_txh,d0
	lea	net_txq,a1
	move.b	(a0),(a1,d0.w)
	addq.b	#1,d0
	move.b	1(a0),(a1,d0.w)
	addq.b	#1,d0
	move.b	2(a0),(a1,d0.w)
	addq.b	#1,d0
	move.b	3(a0),(a1,d0.w)
	addq.b	#1,d0
	move.b	4(a0),(a1,d0.w)
	addq.b	#1,d0
	move.b	5(a0),(a1,d0.w)
	addq.b	#1,d0
	move.b	d0,net_txh
	tst.b	net_txint		; the transmitter's interrupt on
	bne.s	.out
	st	net_txint
	move.b	#MIDI_TXON,MIDI_CTRL.w
.out:	movem.l	(sp)+,d0-d1/a1
	move	(sp)+,sr
	rts

; ---- MIDI IN: a ring of bytes (the fast path, at any level, interrupts off) and their packets (net_process) --------
; net_rxput: a byte waiting at MIDI IN into net_rxq.  Keeps every register; the caller has interrupts off.
net_rxput:
	btst	#0,MIDI_CTRL.w
	beq.s	.x
	movem.l	d0/a0,-(sp)
	moveq	#0,d0
	move.b	net_rqh,d0
	lea	net_rxq,a0
	move.b	MIDI_DATA.w,(a0,d0.w)
	addq.b	#1,d0			; (256 bytes: the byte wraps)
	move.b	d0,net_rqh
	movem.l	(sp)+,d0/a0
.x:	rts

; midi_fast (acia_isr, d0-d2/a0 free): every byte waiting into net_rxq, then the next byte to send when the
; transmitter is empty.  Interrupts off: a few microseconds.
midi_fast:
	move	sr,-(sp)
	or	#$0700,sr
.l:	btst	#0,MIDI_CTRL.w
	beq.s	.tx
	bsr.s	net_rxput
	bra.s	.l
.tx:	move.b	MIDI_CTRL.w,d0
	btst	#1,d0			; the transmitter empty
	beq.s	.y
	tst.b	net_txint
	bne.s	.t
	btst	#7,d0			; (its interrupt asking with none wanted: off, or the line would stay low)
	beq.s	.y
	addq.w	#1,net_txstray
	bra.s	.off
.t:	move.b	net_txt,d1
	cmp.b	net_txh,d1
	beq.s	.off
	moveq	#0,d2
	move.b	d1,d2
	lea	net_txq,a0
	move.b	(a0,d2.w),MIDI_DATA.w
	addq.b	#1,d1
	move.b	d1,net_txt
	bra.s	.y
.off:	sf	net_txint
	move.b	#MIDI_RXON,MIDI_CTRL.w
.y:	move	(sp)+,sr
	rts

; net_process: net_rxq's bytes through net_rx, unless an outer net_process is at it: on the ACIA handler's stack,
; the mask at 3 (the borders' timers, MIDI's own fast path and the VBL may come: a VBL held back here would come late,
; in the top border's wait; a VBL in here does not switch threads and starts no tick: acia_busy).  Returns with interrupts off.  Keeps every register.
net_process:
	move	#$2700,sr
	tst.b	net_proc
	bne.s	.x
	st	net_proc
	st	acia_busy
	move.l	sp,acia_sp
	lea	acia_stack_top,sp
	movem.l	d0-d2/a0,-(sp)
.l:	move	#$2700,sr
	moveq	#0,d0
	move.b	net_rqt,d0
	cmp.b	net_rqh,d0
	beq.s	.e
	lea	net_rxq,a0
	move.b	(a0,d0.w),d1
	addq.b	#1,d0
	move.b	d0,net_rqt
	move	#$2300,sr
	bsr	net_rx
	bra.s	.l
.e:	movem.l	(sp)+,d0-d2/a0
	move.l	acia_sp,sp
	sf	acia_busy
	sf	net_proc
.x:	rts

; ---- the top border's hold (borders.s BD_ACIA_HOLD): its wait must not leave a byte at MIDI IN to be overwritten
; bd_hold_in (the hold's start, interrupts at 6): a byte waiting into net_rxq.  Keeps every register.
bd_hold_in:
	bra	net_rxput

; bd_hold_out (after the border, unmasked again, interrupts off): a byte that came meanwhile into net_rxq; when the
; ACIAs' line is low (an interrupt waiting: its edge came while masked, and the MFP need not raise it again: Hatari's
; does not, and the line stays low, so no later edge comes) or bytes wait in net_rxq: the ACIA's handler now, as if
; its interrupt came.  Keeps every register.
bd_hold_out:
	bsr	net_rxput
	btst	#4,$fffffa01.w		; (GPIP 4: the ACIAs' interrupt line, low: asserted)
	beq.s	.go
	move.l	d0,-(sp)
	move.b	net_rqt,d0
	cmp.b	net_rqh,d0
	movem.l	(sp)+,d0		; (the flags stay)
	beq.s	.x
.go:	pea	.r(pc)			; (an interrupt's frame: the handler's RTE comes back here)
	move	sr,-(sp)
	jmp	acia_isr
.r:
.x:	rts

; d1.b: a byte from MIDI IN
net_rx:
	tst.b	d1
	bpl.s	.data
	tst.b	net_rxn			; (diagnostics: a packet cut short, a byte lost)
	beq.s	.h
	addq.w	#1,net_cut
.h:	move.b	d1,net_rxb		; a header: a packet starts
	move.b	#1,net_rxn
	rts
.data:	moveq	#0,d2
	move.b	net_rxn,d2
	bne.s	.in
	addq.w	#1,net_orphan		; (no header: dropped; diagnostics)
	rts
.in:
	lea	net_rxb,a0
	move.b	d1,(a0,d2.w)
	addq.b	#1,d2
	move.b	d2,net_rxn
	cmp.b	#6,d2
	bne.s	.x
	clr.b	net_rxn
	bra	net_packet
.x:	rts

; a packet in net_rxb
net_packet:
	movem.l	d3-d4/a1,-(sp)
	lea	net_rxb,a0
	move.b	(a0),d0			; (a wrong checksum: a packet made of two broken ones, dropped)
	add.b	1(a0),d0
	add.b	2(a0),d0
	add.b	3(a0),d0
	add.b	4(a0),d0
	and.b	#$7f,d0
	cmp.b	5(a0),d0
	beq.s	.sumok
	addq.w	#1,net_badsum
	bra	.x
.sumok:	move.b	(a0),d0
	move.b	d0,d3
	lsr.b	#2,d3
	and.w	#3,d3			; src
	lsr.b	#4,d0
	and.w	#7,d0			; kind
	beq.s	.input
	cmp.b	#1,d0
	beq.s	.hello
	cmp.b	#2,d0
	beq	.start
	bra	.x
.input:	cmp.b	net_id,d3		; (its own, back: dropped)
	beq	.x
	moveq	#0,d1
	move.b	1(a0),d1		; the tick & $7F
	move.b	3(a0),d4		; T's input and coin
	lsl.b	#7,d4
	or.b	2(a0),d4
	move.b	3(a0),d0
	lsr.b	#1,d0
	and.b	#1,d0
	bsr	net_entry
	btst	#4,3(a0)		; the tick before too (when there is one)
	beq.s	.fw
	subq.b	#1,d1
	and.b	#$7f,d1
	move.b	3(a0),d4
	lsr.b	#2,d4
	lsl.b	#7,d4
	or.b	4(a0),d4
	move.b	3(a0),d0
	lsr.b	#3,d0
	and.b	#1,d0
	bsr	net_entry
.fw:	bsr	net_put6		; passed on
	bra	.x
.hello:	tst.b	net_master
	beq.s	.hn
	tst.b	net_n			; back at the master: the ring's size, START
	bne	.x
	move.b	1(a0),d0
	addq.b	#1,d0
	move.b	d0,net_n
	lea	net_txb,a0
	move.b	#$80|2<<4,(a0)
	move.b	d0,1(a0)
	clr.b	2(a0)
	clr.b	3(a0)
	clr.b	4(a0)
	bsr	net_put6
	bra.s	.x
.hn:	move.b	1(a0),d0
	addq.b	#1,d0
	tst.b	net_id
	bpl.s	.hf
	move.b	d0,net_id		; (its number: the hops)
.hf:	move.b	d0,1(a0)		; passed on, one hop more
	bsr	net_put6
	bra.s	.x
.start:	tst.b	net_master
	bne.s	.sm
	move.b	1(a0),net_n
	bsr	net_put6		; passed on
.sm:	tst.b	net_run
	bne.s	.x
	st	net_run			; the game from tick 0
.x:	movem.l	(sp)+,d3-d4/a1
	rts

; net_entry: machine d3.w's input d4.b and coin d0.b for the tick d1.b (& $7F) into its entry.  Keeps the registers
; but a1.
net_entry:
	move.l	d2,-(sp)
	moveq	#15,d2
	and.w	d1,d2
	lsl.w	#2,d2
	add.w	d3,d2			; (tick & 15) * 4 + the machine
	lea	net_inp,a1
	move.b	d4,(a1,d2.w)
	lea	net_flg,a1
	move.b	d0,(a1,d2.w)
	lea	net_seq,a1
	move.b	d1,(a1,d2.w)		; (last: the entry complete)
	move.l	(sp)+,d2
	rts

; ---- the VBL (after vbl_inputs: net_local, net_coin) ----------------------------------------------------------------
net_vbl:
	btst	#4,$fffffa01.w		; (the ACIAs' line low and nobody at it: an edge missed; the handler now)
	bne	.ok
	tst.b	net_proc
	bne	.ok
	addq.w	#1,net_kicks
	move.b	$fffffc00.w,net_kick_kbd	; (diagnostics: the two ACIAs' status, the line still low after the handler)
	move.b	MIDI_CTRL.w,net_kick_midi
	move	sr,-(sp)
	or	#$0700,sr
	pea	.back(pc)
	move	sr,-(sp)
	jmp	acia_isr
.back:	move	(sp)+,sr
	btst	#4,$fffffa01.w
	bne	.ok
	addq.w	#1,net_kick_stuck
	move.b	$fffffc00.w,net_kick_kbd2
	move.b	MIDI_CTRL.w,net_kick_midi2
	move.b	net_txint,net_kick_txint
	move.b	net_txh,net_kick_txh
	move.b	net_txt,net_kick_txt
	move.b	$fffffa01.w,net_kick_gpip
	move.b	$fffffa0d.w,net_kick_iprb
	move.b	$fffffa11.w,net_kick_isrb
	move.b	$fffffa15.w,net_kick_imrb
.ok:
	tst.b	net_run
	bne.s	.run
	tst.b	net_master		; waiting: the master's HELLO every NET_HELLO_VBLS
	beq.s	.x
	tst.b	net_n
	bne.s	.x
	subq.b	#1,net_hello
	bpl.s	.x
	move.b	#NET_HELLO_VBLS,net_hello
	lea	net_txb,a0
	move.b	#$80|1<<4,(a0)
	clr.b	1(a0)
	clr.b	2(a0)
	clr.b	3(a0)
	clr.b	4(a0)
	bra	net_put6
.x:	rts
.run:	addq.b	#1,net_due		; the arcade's 60 Hz: 6 ticks in 5 VBLs
	subq.b	#1,net_phase
	bpl.s	.p
	move.b	#4,net_phase
	addq.b	#1,net_due
.p:	cmp.b	#NET_DUE_MAX,net_due
	bls.s	.s
	move.b	#NET_DUE_MAX,net_due
.s:	move.l	net_sent,d0		; this machine's inputs up to NET_DELAY ticks ahead
	sub.l	net_tick,d0
	cmp.l	#NET_DELAY,d0
	bgt	.sd
	move.l	net_sent,d0
	moveq	#0,d1
	move.b	net_id,d1
	move.b	net_local,d2
	moveq	#0,d3
	move	sr,-(sp)
	or	#$0700,sr
	move.b	net_coin,d3		; (a coin press: once)
	sf	net_coin
	move	(sp)+,sr
	and.b	#1,d3
	moveq	#15,d4			; its history (resent when the ring stalls)
	and.w	d0,d4
	lea	net_own,a0
	move.b	d2,(a0,d4.w)
	lea	net_ownf,a0
	move.b	d3,(a0,d4.w)
	bsr	net_send_own
	addq.l	#1,net_sent
	bra	.s
.sd:	move.l	net_tick,d0		; the game stalled (a packet lost: an overrun): this machine's last inputs again
	cmp.l	net_last,d0
	beq.s	.st
	move.l	d0,net_last
	clr.b	net_stall
	rts
.st:	tst.b	net_wait		; (only while inputs are missing: not a machine slow for its renderer)
	beq.s	.sx
	addq.b	#1,net_stall
	cmp.b	#NET_STALL_VBLS,net_stall
	blo.s	.sx
	move.b	net_txt,d1		; (only when what was sent has gone: no storm into a full queue)
	cmp.b	net_txh,d1
	bne.s	.sx
	clr.b	net_stall
	addq.w	#1,net_resends
	move.l	net_tick,d1		; (from the tick NET_DELAY + 1 before the one it waits for, the oldest one a
	subq.l	#NET_DELAY+1,d1		;  machine behind it can wait for, to the last sent: every other one, each
	move.l	net_sent,d0		;  packet carries the tick before too)
.r:	subq.l	#1,d0
	bmi.s	.sx
	cmp.l	d1,d0
	blt.s	.sx
	bsr	net_send_own
	subq.l	#1,d0
	bra.s	.r
.sx:	rts

; net_send_own: this machine's packet for tick d0.l (net_own / net_ownf: its input and coin, and the tick before's)
; into its entry and to MIDI OUT.  Keeps d0.
net_send_own:
	movem.l	d1-d5/a0,-(sp)
	moveq	#15,d4
	and.w	d0,d4
	lea	net_own,a0
	move.b	(a0,d4.w),d2		; the input
	lea	net_ownf,a0
	move.b	(a0,d4.w),d3		; the coin
	moveq	#0,d1
	move.b	net_id,d1
	lsl.w	#2,d4
	add.w	d1,d4			; its entry
	lea	net_inp,a0
	move.b	d2,(a0,d4.w)
	lea	net_flg,a0
	move.b	d3,(a0,d4.w)
	lea	net_seq,a0
	moveq	#$7f,d5
	and.b	d0,d5
	move.b	d5,(a0,d4.w)
	lea	net_txb,a0
	lsl.b	#2,d1
	or.b	#$80,d1
	move.b	d1,(a0)			; the header
	move.b	d5,1(a0)		; the tick
	moveq	#$7f,d5
	and.b	d2,d5
	move.b	d5,2(a0)		; its input
	lsr.b	#7,d2
	add.b	d3,d3
	or.b	d3,d2			; c: its input's bit 7, its coin
	clr.b	4(a0)
	tst.l	d0
	beq.s	.c
	moveq	#15,d4			; the tick before's
	and.w	d0,d4
	subq.w	#1,d4
	and.w	#15,d4
	move.l	a0,-(sp)
	lea	net_own,a0
	move.b	(a0,d4.w),d3
	lea	net_ownf,a0
	move.b	(a0,d4.w),d1
	move.l	(sp)+,a0
	moveq	#$7f,d5
	and.b	d3,d5
	move.b	d5,4(a0)		; d: its input
	lsr.b	#7,d3
	lsl.b	#2,d3
	or.b	d3,d2
	and.b	#1,d1
	lsl.b	#3,d1
	or.b	d1,d2
	or.b	#$10,d2			; (the tick before is there)
.c:	move.b	d2,3(a0)
	bsr	net_put6
	movem.l	(sp)+,d1-d5/a0
	rts

; ---- a tick ---------------------------------------------------------------------------------------------------------
; net_tick_try: when a tick is due and every machine's input for it is in: the inputs into the arcade's input words,
; the coins into the sound board's coin byte, the tick counted; d0 = 1 (ne).  Else d0 = 0 (eq).  Keeps the others.
net_tick_try:
	tst.b	net_run
	beq	net_tt_no
	tst.b	net_due
	beq	net_tt_no
	movem.l	d1-d4/a0-a2,-(sp)
	move.l	net_tick,d1
	moveq	#15,d2
	and.w	d1,d2
	lsl.w	#2,d2			; the slot
	and.b	#$7f,d1			; its tick & $7F
	lea	net_seq,a0
	add.w	d2,a0
	moveq	#0,d3
	move.b	net_n,d3
	subq.w	#1,d3
	move.l	a0,a1
.chk:	cmp.b	(a1)+,d1
	bne	net_tt_wait
	dbf	d3,.chk
	lea	net_inp,a1		; all in: the four input words (the players not in the ring: nothing pressed)
	add.w	d2,a1
	lea	net_flg,a2
	add.w	d2,a2
	lea	ARC_IO+1,a0
	moveq	#0,d3			; the player
.pl:	moveq	#0,d4
	cmp.b	net_n,d3
	bhs.s	.none
	move.b	(a1,d3.w),d4
	btst	#0,(a2,d3.w)
	beq.s	.none
	move.w	d3,d0			; its coin
	bsr	coin
.none:	not.b	d4
	move.b	d4,(a0)
	addq.l	#2,a0
	addq.w	#1,d3
	cmp.w	#4,d3
	blo.s	.pl
	lea	net_seq,a0		; the slot free again
	add.w	d2,a0
	moveq	#-1,d4
	move.l	d4,(a0)
net_tick_go:				; (here every machine's game is the same at the same tick: tools' checks)
	sf	net_wait
	addq.l	#1,net_tick
	subq.b	#1,net_due
	movem.l	(sp)+,d1-d4/a0-a2
	moveq	#1,d0
	rts
net_tt_wait:
	st	net_wait
	movem.l	(sp)+,d1-d4/a0-a2
net_tt_no:
	moveq	#0,d0
	rts

net_vars_macro macro
net_vars:
net_tick:	ds.l	1		; (the next tick to run)
net_sent:	ds.l	1		; (the next tick this machine sends its input for)
net_last:	ds.l	1		; (net_tick at the last VBL)
net_own:	ds.b	16		; (this machine's inputs and coins by tick & 15: resent when the ring stalls)
net_ownf:	ds.b	16
net_inp:	ds.b	16*4		; (per tick & 15 and machine: its input (active high), its coin flag, its tick & $7F
net_flg:	ds.b	16*4		;  or $FF: none yet)
net_seq:	ds.b	16*4
net_txq:	ds.b	NET_TXQ
net_rxq:	ds.b	256		; (MIDI IN's bytes, not yet through net_rx)
net_rqh:	ds.b	1
net_rqt:	ds.b	1
net_proc:	ds.b	1		; (net_process at it)
	even
net_rxb:	ds.b	6
net_txb:	ds.b	6
net_txh:	ds.b	1
net_txt:	ds.b	1
net_txint:	ds.b	1		; (the transmitter's interrupt on)
net_rxn:	ds.b	1		; (bytes of the packet coming in)
net_master:	ds.b	1
net_id:		ds.b	1		; (this machine's number, -1: none yet)
net_n:		ds.b	1		; (the machines in the ring, 0: not known yet)
net_run:	ds.b	1		; (the game runs)
net_hello:	ds.b	1
net_due:	ds.b	1		; (ticks owed: 6 in 5 VBLs)
net_phase:	ds.b	1
net_local:	ds.b	1		; (this machine's input now, active high)
net_coin:	ds.b	1		; (a coin key pressed since its last packet)
net_stall:	ds.b	1
net_wait:	ds.b	1		; (the last try found inputs missing)
net_tcoin:	ds.b	1		; (NETTEST: its coin given)
	even
net_overruns:	ds.w	1		; (diagnostics: bytes lost at MIDI IN, the stalls' resends, packets dropped for their
net_resends:	ds.w	1		;  checksum)
net_badsum:	ds.w	1
net_banks:	ds.w	1
net_cut:	ds.w	1
net_txfull:	ds.w	1
net_kicks:	ds.w	1		; (VBLs that found the ACIAs' line stuck low)
net_txstray:	ds.w	1
net_kick_stuck:	ds.w	1
net_kick_kbd:	ds.b	1
net_kick_midi:	ds.b	1
net_kick_kbd2:	ds.b	1
net_kick_midi2:	ds.b	1
net_kick_txint:	ds.b	1
net_kick_txh:	ds.b	1
net_kick_txt:	ds.b	1
net_kick_gpip:	ds.b	1
net_kick_iprb:	ds.b	1
net_kick_isrb:	ds.b	1
net_kick_imrb:	ds.b	1
	even
net_orphan:	ds.w	1
net_why:	ds.w	4		; (VBLs without a tick: the game's frame ran, the renderer starved, none due, inputs missing)
	even
net_vars_end:
net_boot:	ds.l	1		; (the loader's d7: 'NETM' on the master)
	endm
