#!/usr/bin/env python3
"""Build a personalized GR IV firmware with GR4-WebCam added.

Input:  an official GR IV 1.11 firmware image (--base).
Output: your copy (--out) with only the GR4-WebCam start-up added; everything else
        in the image is left unchanged. The tool checks this and refuses to write
        the output if any other part would change.

Self-contained: needs only Python 3 with numpy, plus squashfs-tools
(`brew install squashfs`). The base file is opened read-only. Run with sudo if your
OS requires root to preserve special files while repacking.

Container format: independently implemented from the public reference at
https://github.com/radium-wang/ricoh-gr4-firmware-analysis-and-feature-expansion
(frame format attributed there to yeahnope/gr_unpack).
"""
import argparse, subprocess, tempfile, shutil, struct, json, hashlib, os, stat as statmod, bisect
from pathlib import Path
import numpy as np

# The region of the decoded image that holds the editable filesystem (GR IV 1.11).
OFF, SIZE = 26662896, 21848064

MAX_DISTANCE = 0x2000
LITERAL_CHUNK = 0x6000
FOOTER_MAGIC = b'\xa5\x5a\x5a\xa5'


def sha(d: bytes) -> str:
    return hashlib.sha256(d).hexdigest()


def word_sum(d: bytes) -> int:
    if len(d) % 4:
        raise ValueError('unaligned container')
    return sum(w[0] for w in struct.iter_unpack('<I', d)) & 0xffffffff


def decode(data, limit=256 * 1024 * 1024):
    if len(data) < 160 or data[:8] != b'RICOH\0\0\0':
        raise ValueError('not a supported firmware container')
    out = bytearray()
    frames = []
    cursor = 128
    while True:
        start = cursor
        if cursor + 2 > len(data):
            raise ValueError('missing frame terminator')
        descriptor = int.from_bytes(data[cursor:cursor + 2], 'big')
        cursor += 2
        if descriptor == 0:
            return bytes(out), frames, cursor
        size = descriptor & 0x7fff
        end = cursor + size
        if not size or end > len(data):
            raise ValueError(f'invalid frame at {start:#x}')
        output_start = len(out)
        if descriptor & 0x8000:
            out.extend(data[cursor:end]); cursor = end
        else:
            while cursor < end:
                if cursor + 2 > end:
                    raise ValueError(f'truncated flags at {cursor:#x}')
                flags = int.from_bytes(data[cursor:cursor + 2], 'big'); cursor += 2
                for bit in range(15, -1, -1):
                    if cursor == end:
                        break
                    if not flags & (1 << bit):
                        out.append(data[cursor]); cursor += 1
                    else:
                        if cursor + 2 > end:
                            raise ValueError('truncated reference')
                        a, b = data[cursor:cursor + 2]; cursor += 2
                        distance = ((a >> 3) << 8) | b
                        length = a & 7
                        if length == 7:
                            while True:
                                if cursor >= end:
                                    raise ValueError('truncated length')
                                extension = data[cursor]; cursor += 1
                                length += extension
                                if extension != 255:
                                    break
                        if distance == 0:
                            break
                        if distance > len(out):
                            raise ValueError('reference before output')
                        count = length + 3
                        if len(out) + count > limit:
                            raise ValueError('decoded size limit exceeded')
                        if distance >= count:
                            out.extend(out[-distance:len(out) - distance + count])
                        else:
                            pattern = bytes(out[-distance:])
                            out.extend((pattern * ((count + distance - 1) // distance))[:count])
                    if len(out) > limit:
                        raise ValueError('decoded size limit exceeded')
        frames.append(dict(container_start=start, container_end=end,
                           decoded_start=output_start, decoded_end=len(out)))


def diff_offsets(a: bytes, b: bytes):
    aa = np.frombuffer(a, np.uint8); bb = np.frombuffer(b, np.uint8)
    n = min(len(aa), len(bb))
    out = np.nonzero(aa[:n] != bb[:n])[0].tolist()
    if len(a) != len(b):
        out += list(range(n, max(len(a), len(b))))
    return out


def _needs_reemit(frame, changed):
    lo, hi = frame['decoded_start'], frame['decoded_end']
    k = bisect.bisect_left(changed, lo)
    if k < len(changed) and changed[k] < hi:
        return True
    return k > 0 and changed[k - 1] + MAX_DISTANCE > lo


def _literal_frames(data: bytes) -> bytes:
    out = bytearray()
    for pos in range(0, len(data), LITERAL_CHUNK):
        chunk = data[pos:pos + LITERAL_CHUNK]
        out += struct.pack('>H', 0x8000 | len(chunk)) + chunk
    return bytes(out)


def reencode(source: bytes, patched: bytes) -> bytes:
    stock, frames, consumed = decode(source)
    changed = diff_offsets(stock, patched)
    body = bytearray()
    for f in frames:
        if _needs_reemit(f, changed):
            body += _literal_frames(patched[f['decoded_start']:f['decoded_end']])
        else:
            body += source[f['container_start']:f['container_end']]
    body += b'\0\0'
    trailer = bytearray(source[consumed:])
    struct.pack_into('<II', trailer, len(trailer) - 12, len(body), len(patched))
    struct.pack_into('<I', trailer, len(trailer) - 4, 0)
    padding = bytes((-128 - len(body) - len(trailer)) % 4)
    out = bytearray(source[:128] + body + padding + trailer)
    struct.pack_into('<I', out, len(out) - 4, (-word_sum(out)) & 0xffffffff)
    again, _, _ = decode(bytes(out))
    if again != patched or word_sum(out):
        raise ValueError('re-encode failed to reproduce the payload')
    return bytes(out)


def rezero(payload: bytes) -> bytes:
    if len(payload) % 4:
        raise ValueError('payload not word-aligned')
    buf = bytearray(payload)
    old = struct.unpack_from('<I', buf, len(buf) - 4)[0]
    struct.pack_into('<I', buf, len(buf) - 4, (old - word_sum(buf)) & 0xffffffff)
    if word_sum(buf):
        raise ValueError('payload re-zero failed')
    return bytes(buf)


def check_source(data: bytes) -> bytes:
    payload, frames, consumed = decode(data)
    if data[-20:-16] != FOOTER_MAGIC:
        raise SystemExit('unexpected base image (footer); is this the official GR IV 1.11 file?')
    enc, dec = struct.unpack_from('<II', data, len(data) - 12)
    if enc != consumed - 128 or dec != len(payload) or word_sum(data) or word_sum(payload):
        raise SystemExit('unexpected base image; is this the official GR IV 1.11 file?')
    return payload


RC_LINE = ("( n=0; while [ $n -lt 120 ]; do n=$((n+1)); "
           "[ -f /media/storage1/GR4WEB.ON ] && { sh /media/storage1/GR4WEB.SH; break; }; "
           "sleep 2; done ) &\n")
MARK = "# --- GR4WEB autostart ---\n"


def sh(*a, **k):
    return subprocess.run(a, check=True, capture_output=True, text=True, **k)


def patch_rclocal(text: str) -> str:
    if MARK in text:
        return text
    ins = MARK + RC_LINE
    if "\nexit 0" in text:
        i = text.rfind("\nexit 0")
        return text[:i + 1] + ins + text[i + 1:]
    return text.rstrip("\n") + "\n" + ins


def build_new_fs(base_fs: bytes, work: Path) -> bytes:
    (work / 'orig.sqfs').write_bytes(base_fs)
    sh('unsquashfs', '-d', str(work / 'root'), '-no-xattrs', str(work / 'orig.sqfs'))
    rc = work / 'root' / 'etc' / 'rc.local'
    before = rc.read_text()
    rc.write_text(patch_rclocal(before))
    if rc.read_text() == before:
        raise SystemExit('start-up unchanged (already added?) - aborting')
    out = work / 'new.sqfs'
    sh('mksquashfs', str(work / 'root'), str(out),
       '-comp', 'lz4', '-b', '131072', '-noI', '-all-root', '-noappend', '-no-progress')
    new = out.read_bytes()
    if len(new) > SIZE:
        raise SystemExit(f'rebuilt image {len(new)} > {SIZE}; cannot keep the same size.')
    return new + bytes(SIZE - len(new)) if len(new) < SIZE else new


def _tree_spec(root: Path) -> dict:
    # files by content, links by target, devices by (type, major, minor), dirs by presence
    spec = {}
    for p in sorted(root.rglob('*')):
        rel, st = str(p.relative_to(root)), p.lstat()
        m = st.st_mode
        if statmod.S_ISLNK(m):
            spec[rel] = ('link', os.readlink(p))
        elif statmod.S_ISCHR(m):
            spec[rel] = ('chr', os.major(st.st_rdev), os.minor(st.st_rdev))
        elif statmod.S_ISBLK(m):
            spec[rel] = ('blk', os.major(st.st_rdev), os.minor(st.st_rdev))
        elif statmod.S_ISDIR(m):
            spec[rel] = ('dir',)
        elif statmod.S_ISREG(m):
            spec[rel] = ('file', p.read_bytes())
        else:
            spec[rel] = ('other', m & 0o170000)
    return spec


def verify_only_startup(base_fs: bytes, new_fs: bytes, work: Path) -> str:
    (work / 'a.sqfs').write_bytes(base_fs)
    (work / 'b.sqfs').write_bytes(new_fs)
    sh('unsquashfs', '-d', str(work / 'a'), '-no-xattrs', str(work / 'a.sqfs'))
    sh('unsquashfs', '-d', str(work / 'b'), '-no-xattrs', str(work / 'b.sqfs'))
    A, B = _tree_spec(work / 'a'), _tree_spec(work / 'b')
    if set(A) != set(B):
        raise SystemExit('contents differ beyond the start-up file; aborting')
    changed = sorted(k for k in A if A[k] != B[k])
    if changed != ['etc/rc.local']:
        raise SystemExit('unexpected changes: ' + ', '.join(k for k in changed if k != 'etc/rc.local')
                         if any(k != 'etc/rc.local' for k in changed) else 'start-up not added')
    return 'only the start-up file changed; everything else preserved'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--base', required=True, type=Path, help='official firmware image')
    ap.add_argument('--out', required=True, type=Path, help='your copy to write')
    args = ap.parse_args()

    base = args.base.read_bytes()
    payload = check_source(base)
    if payload[OFF:OFF + 4] != b'hsqs':
        raise SystemExit('unexpected base layout; is this the official GR IV 1.11 image?')

    work = Path(tempfile.mkdtemp(prefix='gr4webcam.'))
    try:
        new_fs = build_new_fs(payload[OFF:OFF + SIZE], work)
        note = verify_only_startup(payload[OFF:OFF + SIZE], new_fs, work)
        patched = rezero(payload[:OFF] + new_fs + payload[OFF + SIZE:])
        built = reencode(base, patched)
        bp = decode(built)[0]
        if bp[OFF:OFF + SIZE] != new_fs or bp[:OFF] != payload[:OFF] \
                or bp[OFF + SIZE:-4] != payload[OFF + SIZE:-4]:
            raise SystemExit('a change landed outside the target region; not writing')
        args.out.write_bytes(built)
        print(json.dumps({'base': str(args.base), 'base_sha256': sha(base),
                          'out': str(args.out), 'out_sha256': sha(built),
                          'changed': note, 'everything_else': 'identical'}, indent=2))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
