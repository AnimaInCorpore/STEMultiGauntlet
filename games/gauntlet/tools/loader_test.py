"""Run the production GEMDOS loader: matching pack, bad/missing pack and low RAM.

Only startup transport is simulated; live borders and gameplay require Hatari.
Build the normal program first. Private copies stay in build/gauntlet/loader_test/.
"""
import shutil
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[3] / "engine")]
from paths import ROOT, build_dir
from sim import Sim, TRAP1


def main():
    source = ROOT / "run/gauntlet"
    out = build_dir("gauntlet") / "loader_test"
    out.mkdir(exist_ok=True)
    pack = (source / "SPRITES.DAT").read_bytes()
    prg = out / "GAUNTLET.PRG"
    shutil.copy2(source / prg.name, prg)
    for case in ("matching", "missing", "short", "wrong_build", "low_ram", "stack_reserve"):
        dest = out / "SPRITES.DAT"
        dest.unlink(missing_ok=True)
        if case != "missing":
            data = bytearray(pack)
            if case == "short":
                data = data[:-4]
            elif case == "wrong_build":
                data[24] ^= 1
            dest.write_bytes(data)
        s = Sim(prg, ram_kib=4096 if case == "low_ram" else 16384, run_dir=out)
        if case == "stack_reserve":
            s.mem.w32(0x42E, 0x400000 + len(pack))
        for _ in range(2_000_000):
            pc = s.cpu.r_pc()
            if pc == 0x50000 or s.terminated:
                break
            if pc == TRAP1:
                s.gemdos()
            else:
                s.cpu.execute(1)
        else:
            raise AssertionError(case + " did not finish")
        if case == "matching":
            assert s.cpu.r_pc() == 0x50000 and not s.terminated
            assert bytes(s.mem.r_block(0x400000, len(pack))) == pack
            assert s.mem.r16(0x50000) != 0, "runtime was not moved"
        else:
            assert s.terminated and s.cpu.r_pc() != 0x50000, case
            if case in ("low_ram", "stack_reserve"):
                assert s.next_handle == 6, "low RAM must be rejected before disk I/O"
        assert not s.files and not s.log, (case, s.log)
        print(case + ": passed")


if __name__ == "__main__":
    main()
