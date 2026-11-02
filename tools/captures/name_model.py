# SPDX-License-Identifier: AGPL-3.0-or-later
"""Planet, system and region names as the game makes them.

The game makes each part of a name the way nms_namegen's generator does
(generator.py generateName): three letters drawn from one of its eight
alphasets, then one letter at a time, each picked by weight for the three
letters before it, then vowels put in where the name would be hard to say.
Its code differs from nms_namegen's in a few places, which generate_name()
follows:

- It picks each letter for the name's last three letters, comparing the
  weights in single precision, as it holds them.
- When no letter follows those three in eight tries, each in the next
  alphaset, it adds three letters from the name's own alphaset, not from
  the last one tried. Between them it puts an apostrophe if the letter
  before and the first of the three are vowels, a vowel if neither is, and
  nothing otherwise. As in nms_namegen, the letter before is the one its
  count of letters reaches, which leaves out what it puts in like this.
- A 'y' after three consonants starts a new run of consonants.
- Last, it changes a letter of each word of a list (FILTER) in the name,
  drawing it from a few letters the list gives with the word, with a draw
  from the same generator. Every later draw moves on by one, so a word can
  change more than its own letter: which suffix a planet gets, say.

FILTER's words are spelled in ROT13. With these differences, the names the
capture mod recorded agree for all 8,105 planets and 154 regions, and for
135 of 140 systems; the other 5 look like names players gave. planet_name(),
system_name() and region_name() are nms_namegen's functions with this
generator in place of its own; src/core/namegen.ts is the site's port.
"""

from __future__ import annotations

import codecs
import struct
from contextlib import contextmanager

# Each word (ROT13), the place in it of the letter the game changes, and the letters it picks from.
# fmt: off
FILTER = (
    ("nany", 1, "tdwzx"), ("nahf", 1, "tdwzx"), ("nff", 0, "eo"), ("ovgpu", 3, "ao"), ("oybj", 0, "caog"),
    ("obare", 0, "lvsz"), ("pyvg", 3, "cpfn"), ("pbpx", 0, "smlth"), ("phpx", 3, "aeiou"), ("phz", 0, "rgsn"),
    ("phag", 1, "eio"), ("qvpx", 2, "aeol"), ("qbat", 3, "teo"), ("snt", 0, "nmtz"), ("srypu", 0, "njkmp"),
    ("shpx", 0, "zlbw"), ("tbbx", 3, "lnrb"), ("uvgyre", 0, "vmpl"), ("ubzb", 1, "eiu"), ("wvmm", 0, "zrwl"),
    ("xvxr", 2, "rbl"), ("xhag", 3, "aeo"), ("ybir", 2, "mpbt"), ("zvatr", 3, "amlz"), ("zbat", 3, "aoik"),
    ("anmv", 0, "ryvn"), ("arte", 0, "rvlt"), ("avt", 0, "rvxb"), ("betl", 2, "vlos"), ("cnrqb", 0, "tmvs"),
    ("cnxv", 2, "ntr"), ("crqb", 0, "tmvs"), ("cravf", 0, "klsr"), ("cvff", 2, "cokl"), ("cbea", 0, "tvbr"),
    ("cevpx", 0, "stbc"), ("chff", 0, "brsl"), ("dhrr", 2, "nlr"), ("encr", 2, "cnys"), ("frzra", 2, "tzrv"),
    ("frk", 0, "tdrp"), ("funt", 3, "nml"), ("fuvg", 3, "nvsl"), ("fynt", 3, "dnvy"), ("fyhg", 2, "aeo"),
    ("fcnm", 3, "nlr"), ("fcvp", 3, "nlr"), ("fchax", 1, "lh"), ("gneq", 0, "jcgwz"), ("gvg", 2, "nmbc"),
    ("gheq", 3, "nbtp"), ("gjng", 1, "ehi"), ("jnax", 3, "aei"), ("juber", 0, "csa"), ("jbt", 0, "cslv"),
    ("jbc", 0, "csld"),
)
# fmt: on
WORDS = tuple((codecs.decode(word, "rot13"), at, letters) for word, at, letters in FILTER)
VOWELS = "aeiou"
TRIES = 8
LONGEST = 63  # letters the game keeps of a name
UNIT = 1 / 4294967295.0  # a draw, as the fraction of the largest the game makes it


def _is_vowel(letter: str) -> bool:
    return letter != "" and letter in VOWELS


def _f32(value: float) -> float:
    """``value`` rounded to single precision."""
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _weights(generator, context: str, alphaset: int):
    """The letters that may follow ``context`` in ``alphaset``, or None: nms_namegen's lookup, which
    raises where no context in the alphaset starts with that letter, and the game finds none."""
    try:
        return generator.getStringWeights(context, alphaset)
    except KeyError:
        return None


def _pick(entries, target: float, alternate: bool) -> int:
    """Which entry a draw picks, in single precision: by the running total of the weights, or, the other
    way the game has, the nearest of evenly spaced places."""
    if alternate:
        place = _f32(_f32(float(len(entries) - 1)) * target)
        return int(_f32(place + 0.5))
    total = 0.0
    for index, entry in enumerate(entries):
        total = _f32(total + _f32(entry["Item2"]))
        if total >= target:
            return index
    return len(entries) - 1


def _consonant_run(name: str) -> int:
    """Where a run of more than three consonants starts, or -1."""
    run = 0
    for index, letter in enumerate(name):
        if run == 3:
            if letter not in VOWELS + "y":
                return index - 3
            run = 0
        run = 0 if letter in VOWELS else run + 1
    return -1


def filtered(name: str, rng) -> str:
    """``name`` with a letter of each word of FILTER in it changed, one draw from ``rng`` for each."""
    letters = list(name)
    for start in range(len(letters)):
        for word, at, choices in WORDS:
            if "".join(letters[start : start + len(word)]) == word:
                letters[start + at] = choices[rng.random(len(choices))]
                break
    return "".join(letters)


def generate_name(rng, alphaset: int, min_length: int, max_length: int) -> str:
    """One part of a name, as the game makes it, with nms_namegen's PRNG and the alphasets and letter
    weights of its generator."""
    from nms_namegen import generator

    own = alphaset
    name = generator.getCharactersFromAlphaset(rng, alphaset)
    alternate = bool(rng.randi() & 1)
    length = rng.random(max_length - min_length + 1) + min_length - 3
    left, tries, place = length, TRIES, 0
    while place < length:
        target = _f32(rng.randi() * UNIT)
        entries = _weights(generator, name[-3:], alphaset)
        if entries is not None:
            name = (name + entries[_pick(entries, target, alternate)]["Item1"])[:LONGEST]
            left -= 1
            place += 1
            continue
        tries -= 1
        alphaset = (alphaset + 1) & 7
        if tries:
            continue
        if left < 3:
            break
        three = generator.getCharactersFromAlphaset(rng, own)
        before = _is_vowel(name[place + 2 : place + 3])
        if before and _is_vowel(three[0]):
            name += "'"
        elif not before and not _is_vowel(three[0]):
            name += VOWELS[rng.random(5)]
        name = (name + three)[:LONGEST]
        left -= 3
        tries = 1
        place += 3

    first, second = name[0], name[1]
    sayable = (
        (first == "s" and second in "hklmnprtwy")
        or (second == "h" and first in "ctw")
        or (second == "l" and first in "bcfgps")
        or (second == "r" and first in "bcdfgkpt")
        or (second == "w" and first in "dgt")
        or (second == "y" and first in "hmr")
    )
    if first not in VOWELS and second not in VOWELS and not sayable:
        name = name[:1] + VOWELS[rng.random(5)] + name[1:]
    last, before = name[-1], name[-2]
    hard = (
        (last == "b" and before in "gn")
        or (last == "d" and before in "bdfghkmpst")
        or (last == "g" and before == "l")
        or (last == "p" and before in "bdhkt")
        or (last == "r" and before in "bfg")
        or (last == "t" and before == "g")
        or (last == "w" and before not in VOWELS)
    )
    if (before != "g" or last in VOWELS) and hard:
        name = name[:-1] + VOWELS[rng.random(5)] + name[-1:]
    run = _consonant_run(name)
    if run != -1:
        run += rng.random(3) + 1
        name = name[:run] + VOWELS[rng.random(5)] + name[run:]
    return filtered(name, rng)


@contextmanager
def _game_generator():
    """nms_namegen's name functions with generate_name() in place of its generator."""
    import nms_namegen.planet
    import nms_namegen.region
    import nms_namegen.system

    modules = (nms_namegen.planet, nms_namegen.region, nms_namegen.system)
    saved = [module.generateName for module in modules]
    for module in modules:
        module.generateName = generate_name
    try:
        yield
    finally:
        for module, original in zip(modules, saved):
            module.generateName = original


def planet_name(seed_or_code: int, galaxy: int | None = None) -> str:
    """The name of the planet with this seed, or of the planet a portal code points at (nms_namegen's
    planetName)."""
    from nms_namegen.planet import planetName

    with _game_generator():
        return planetName(seed_or_code, galaxy)


def system_name(code: int, galaxy: int) -> str:
    from nms_namegen.system import systemName

    with _game_generator():
        return systemName(code, galaxy)


def region_name(code: int, galaxy: int) -> str:
    from nms_namegen.region import regionName

    with _game_generator():
        return regionName(code, galaxy)
