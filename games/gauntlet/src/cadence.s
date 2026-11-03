; Picture deadline after R-Type: reserve remaining draw time before another logic batch.
; Timer D runs freely without an interrupt; game switches remain at the existing idle yields.
; Expensive pictures can still miss the deadline. cad_flip counts actual gaps and misses.
	ifnd PIC_VBLS
PIC_VBLS = 0			; opt-in prototype: -D PIC_VBLS=3; see resident-sprites.md
	endc
CAD_TPF = 245
CAD_PERIOD = 65536*CAD_TPF

cadence_text macro
	if PIC_VBLS
cadence_init:
	and.b #$f0,$fffffa1d.w
	clr.b $fffffa25.w
	or.b #7,$fffffa1d.w		; /200, 81.38 us/tick; reload 0 means 256
	clr.l cad_est_logic
	clr.l cad_est_render
	clr.l cad_holds
	clr.l cad_misses
	clr.w cad_max_gap
	clr.b cad_busy
	clr.b cad_valid
	rts

cad_clock:
.again:	move.l vbl_count,d0
	moveq #0,d1
	move.b cad_td_vbl,d1
	sub.b $fffffa25.w,d1
	cmp.l vbl_count,d0
	bne.s .again
	mulu #CAD_TPF,d0
	add.l d1,d0
	rts

; d0 = now, a0 = earlier reading -> elapsed, including the low-word VBL wrap.
cad_elapsed:
	sub.l (a0),d0
	bpl.s .done
	add.l #CAD_PERIOD,d0
.done:	rts

cad_estimate:
	move.l (a0),d1
	move.l d1,d2
	lsr.l #4,d2
	sub.l d2,d1
	cmp.l d1,d0
	bhs.s .store
	move.l d1,d0
.store:	move.l d0,(a0)
	rts

cad_picture_begin:
	movem.l d0-d2,-(sp)
	bsr cad_clock
	move.l d0,cad_pic_start
	clr.l cad_pic_game
	st cad_busy
	movem.l (sp)+,d0-d2
	rts

cad_picture_end:
	movem.l d0-d2/a0,-(sp)
	bsr cad_clock
	lea cad_pic_start,a0
	bsr cad_elapsed
	sub.l cad_pic_game,d0
	bpl.s .positive
	moveq #0,d0
.positive:
	move.l d0,cad_last_render
	lea cad_est_render,a0
	bsr cad_estimate
	sf cad_busy
	movem.l (sp)+,d0-d2/a0
	rts

; Runtime has already saved registers at these game-thread boundaries.
cad_game_begin:
	bsr cad_clock
	move.l d0,cad_game_start
	rts

cad_game_end:
	bsr cad_clock
	lea cad_game_start,a0
	bsr cad_elapsed
	tst.b cad_busy
	beq.s .outside
	add.l d0,cad_pic_game
.outside:
	lea cad_est_logic,a0
	bra cad_estimate

; Idle-game VBL only. d0 != 0 holds the next logic batch, not an in-progress game routine.
cad_should_hold:
	tst.b cad_valid
	beq .allow
	tst.b cad_busy
	bne.s .estimate
	move.l frames_done,d0
	cmp.l frames_drawn,d0
	beq .allow			; at least one new state when all existing work was consumed
.estimate:
	bsr cad_clock
	move.l d0,d3
	lea cad_last_flip,a0
	bsr cad_elapsed
	move.l d0,d2
	move.l cad_est_render,d1
	tst.b cad_busy
	beq.s .remaining
	move.l d3,d0
	lea cad_pic_start,a0
	bsr cad_elapsed
	sub.l cad_pic_game,d0
	sub.l d0,d1
	bpl.s .remaining
	moveq #0,d1
.remaining:
	add.l cad_est_logic,d1
	add.l d2,d1
	cmp.l #PIC_VBLS*CAD_TPF-6,d1
	blo.s .allow
	addq.l #1,cad_holds
	moveq #1,d0
	rts
.allow:	moveq #0,d0
	rts

; Existing VBL display path: measure presentation, not render-loop iterations.
cad_flip:
	move.w vbl_count+2,d0
	tst.b cad_valid
	beq.s .first
	move.w d0,d1
	sub.w cad_flip_vbl,d1
	cmp.w cad_max_gap,d1
	bls.s .notmax
	move.w d1,cad_max_gap
.notmax:
	cmp.w #PIC_VBLS,d1
	bls.s .first
	addq.l #1,cad_misses
.first:	move.w d0,cad_flip_vbl
	st cad_valid
	bsr cad_clock
	move.l d0,cad_last_flip
	rts
	endc
	endm

cadence_vars macro
	if PIC_VBLS
	even
cad_est_logic:	ds.l 1
cad_est_render:	ds.l 1
cad_pic_start:	ds.l 1
cad_game_start:	ds.l 1
cad_pic_game:	ds.l 1
cad_last_flip:	ds.l 1
cad_last_render:	ds.l 1
cad_holds:	ds.l 1
cad_misses:	ds.l 1
cad_flip_vbl:	ds.w 1
cad_max_gap:	ds.w 1
cad_td_vbl:	ds.b 1
cad_busy:	ds.b 1
cad_valid:	ds.b 1
	even
	endc
	endm
