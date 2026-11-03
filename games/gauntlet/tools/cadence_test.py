"""Execute the optional deadline scheduler on a 68000 with controlled clock readings.

Checks deadline admission, forward progress, long/VBL/Timer-D wrap and register
preservation. This does not model interrupts or establish MIDI determinism.
"""
import random
import subprocess
import sys
from pathlib import Path

from machine68k import CPUType, Machine, Register as R

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
from bottleneck_audit import symbols
from paths import VASM, VLINK, build_dir, src_dir


def main():
    build = build_dir("gauntlet")
    source = build / "cadence_test.s"
    source.write_text('PIC_VBLS = 3\n\tinclude "cadence.s"\n\tsection text,code\n'
                      '\tcadence_text\n\tsection bss,bss\n\tcadence_vars\n'
                      'vbl_count: ds.l 1\nframes_done: ds.l 1\nframes_drawn: ds.l 1\n')
    obj, binary, mp = [build / ("cadence_test." + ext) for ext in ("o", "bin", "map")]
    subprocess.run([VASM, "-Fvobj", "-quiet", "-I", str(src_dir("gauntlet")), "-o", str(obj), str(source)], check=True)
    subprocess.run([VLINK, "-b", "rawbin1", "-Ttext", "0x100000", "-M" + str(mp), "-o", str(binary), str(obj)], check=True)
    sy, _ = symbols(mp)
    machine = Machine(CPUType.M68000, 16384)
    cpu, mem = machine.cpu, machine.mem
    cpu.pulse_reset()
    mem.w_block(0x100000, binary.read_bytes())
    rng = random.Random(0x434144)
    checked = 0

    def call(name):
        cpu.w_reg(R.A7, 0x8FFFFC)
        mem.w32(0x8FFFFC, 0x900000)
        cpu.w_pc(sy[name])
        for _ in range(400):
            if cpu.r_pc() == 0x900000:
                return cpu.r_reg(R.D0)
            cpu.execute(1)
        raise AssertionError(name + " did not return")

    def put(**values):
        for name, value in values.items():
            addr = sy[name]
            if name in ("cad_busy", "cad_valid", "cad_td_vbl"):
                mem.w8(addr, value)
            elif name in ("cad_flip_vbl", "cad_max_gap"):
                mem.w16(addr, value)
            else:
                mem.w32(addr, value)

    # The unsigned timer delta crosses zero; the coarse clock also wraps at 65536 VBLs.
    for field in (0, 1, 65535, 65536, 65537):
        for delta in (0, 1, 100, 244):
            put(vbl_count=field, cad_td_vbl=3)
            mem.w8(0xFFFA25, (3 - delta) & 255)
            assert call("cad_clock") == (field & 65535) * 245 + delta
            checked += 1
    put(cad_last_flip=65535 * 245 + 240)
    cpu.w_reg(R.A0, sy["cad_last_flip"])
    cpu.w_reg(R.D0, 10)
    assert call("cad_elapsed") == 15
    checked += 1

    # At a full deadline, refuse a further batch; without new state always allow progress.
    for _ in range(1000):
        age, draw, logic = [rng.randrange(0, 1200) for _ in range(3)]
        done = rng.randrange(2)
        busy = rng.randrange(2)
        valid = rng.randrange(2)
        rendered = rng.randrange(age + 1) if busy else 0
        now = 10 * 245
        put(vbl_count=10, cad_td_vbl=3, cad_last_flip=now - age,
            cad_pic_start=now - rendered, cad_pic_game=0, cad_est_render=draw,
            cad_est_logic=logic, frames_drawn=0, frames_done=done,
            cad_busy=busy, cad_valid=valid)
        mem.w8(0xFFFA25, 3)
        expected = valid and (busy or done) and age + max(0, draw - rendered) + logic >= 3 * 245 - 6
        assert bool(call("cad_should_hold")) == bool(expected), (age, draw, logic, busy, done, valid)
        checked += 1

    # Foreground hooks must keep their callers' registers; the game hooks run after MOVEM.
    for name in ("cad_picture_begin", "cad_picture_end"):
        before = [rng.getrandbits(32) for _ in range(15)]
        for i, value in enumerate(before):
            cpu.w_reg(R(i), value)
        call(name)
        assert before == [cpu.r_reg(R(i)) for i in range(15)], name
        checked += 1
    put(cad_valid=1, cad_flip_vbl=65535, cad_max_gap=0, cad_misses=0, vbl_count=2)
    call("cad_flip")
    assert mem.r16(sy["cad_max_gap"]) == 3 and mem.r32(sy["cad_misses"]) == 0
    put(vbl_count=6)
    call("cad_flip")
    assert mem.r16(sy["cad_max_gap"]) == 4 and mem.r32(sy["cad_misses"]) == 1
    checked += 2
    print("%d scheduler cases passed; prototype remains opt-in" % checked)


if __name__ == "__main__":
    main()
