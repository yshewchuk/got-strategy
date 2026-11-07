"""Game engine for a 2-player Game of Thrones "Hand of the King"-style card game.

Rules modelled
--------------
* 36 cards on a 6x6 grid: 35 house characters + Varys.
  House sizes: Stark 8, Greyjoy 7, Lannister 6, Targaryen 5, Baratheon 4,
  Tyrell 3, Tully 2.
* On a turn the active player declares a direction (N/S/E/W) and a house that
  has at least one card in that direction from Varys. Varys moves to the
  FARTHEST card of that house in that direction (jumping over everything) and
  the player takes every card of that house Varys passed over or landed on.
  Varys's old space is left empty.
* At the end of a turn, the player takes the banner of every House where they
  hold >= as many characters as the opponent (so ties go to whoever collected
  last).
* Taking the final character of a House from King's Landing lets the player
  choose one of the six face-up companions and resolve it. If a companion
  *takes* the final character of a House, another companion is chosen
  (chaining); *killing* the final character gives nothing.
* The game ends as soon as the player to move has no legal move (no cards in
  Varys's row or column). Most banners wins; a banner tie is won by the player
  holding the banner of the largest House (Stark 8, then Greyjoy 7, ...).

All of the above is checked against the official rulebook. The rulebook does
not print the companion card texts, so each companion below is tagged with
how well its effect is sourced. Companions can be switched off with
`use_companions=False` to check that conclusions do not hinge on them.
"""
from __future__ import annotations

import random

N = 6
HOUSES = ["Stark", "Greyjoy", "Lannister", "Targaryen", "Baratheon", "Tyrell", "Tully"]
HOUSE_SIZE = [8, 7, 6, 5, 4, 3, 2]
NH = len(HOUSES)
STARK, GREYJOY, LANNISTER, TARGARYEN, BARATHEON, TYRELL, TULLY = range(NH)

CHARACTERS = {
    STARK: ["Eddard", "Robb", "Sansa", "Arya", "Bran", "Rickon", "Lyanna", "Benjen"],
    GREYJOY: ["Balon", "Theon", "Yara", "Euron", "Aeron", "Victarion", "Rodrik"],
    LANNISTER: ["Tywin", "Cersei", "Jaime", "Tyrion", "Kevan", "Lancel"],
    TARGARYEN: ["Daenerys", "Viserys", "Rhaegar", "Aerys", "Aemon"],
    BARATHEON: ["Robert", "Stannis", "Renly", "Joffrey"],
    TYRELL: ["Margaery", "Olenna", "Mace"],
    TULLY: ["Catelyn", "Edmure"],
}
CARD_HOUSE: list[int] = []
CARD_NAME: list[str] = []
for _h in range(NH):
    for _n in CHARACTERS[_h]:
        CARD_HOUSE.append(_h)
        CARD_NAME.append(_n)
NCARDS = len(CARD_HOUSE)  # 35
VARYS = -1
CARD_BY_NAME = {n: i for i, n in enumerate(CARD_NAME)}
BRAN, DAENERYS, MARGAERY, TYRION = (CARD_BY_NAME[n] for n in ("Bran", "Daenerys", "Margaery", "Tyrion"))

DIRS = [(-1, 0), (1, 0), (0, -1), (0, 1)]

# Companion ids. Status of each effect text:
#   [rulebook]  confirmed by the official rulebook
#   [reviews]   described consistently in published reviews
#   [guess]     card exists / effect reconstructed - unverified
(JON_SNOW, GENDRY, SHAE, BRONN, HODOR, LORAS, DROGO, SANDOR, JAQEN,
 MELISANDRE, RAMSAY, BRIENNE, JORAH) = range(13)
COMPANIONS = ["Jon Snow", "Gendry", "Shae", "Bronn", "Hodor", "Loras Tyrell", "Khal Drogo",
              "Sandor Clegane", "Jaqen H'ghar", "Melisandre", "Ramsay Snow", "Brienne", "Jorah Mormont"]
COMPANION_TEXT = {
    JON_SNOW: "[reviews] Stays in your play area and counts as a Stark character (cannot be killed/taken).",
    GENDRY: "[reviews] Stays in your play area and counts as a Baratheon character (cannot be killed/taken).",
    SHAE: "[rulebook: exists, cannot be killed/taken] Counts as a Lannister character. [house is a guess]",
    BRONN: "[rulebook] Take Tyrion Lannister, from King's Landing or an opponent's play area.",
    HODOR: "[rulebook] Take Bran Stark, from King's Landing or an opponent's play area.",
    LORAS: "[reviews] Take Margaery Tyrell, from King's Landing or an opponent's play area.",
    DROGO: "[reviews] Take Daenerys Targaryen from anywhere.",
    SANDOR: "[reviews] Kill any one character (King's Landing or a play area).",
    JAQEN: "[reviews] Kill one character in King's Landing, one in any play area, and one available companion.",
    MELISANDRE: "[guess] Take another turn.",
    RAMSAY: "[guess] Swap the positions of two cards in King's Landing.",
    BRIENNE: "[guess] Take any one character from an opponent's play area.",
    JORAH: "[guess] Take any one Targaryen character from King's Landing.",
}
FACE_UP_COMPANIONS = 6


class State:
    __slots__ = ("board", "varys", "counts", "cards", "banner", "companions", "to_move",
                 "pending", "extra")

    def __init__(self):
        self.board: list[int | None] = []      # 36 cells: card id, VARYS, or None
        self.varys = 0
        self.counts = [[0] * NH, [0] * NH]   # cards (incl. bonus companions) per house per player
        self.cards: list[set] = [set(), set()]  # actual card ids held
        self.banner = [None] * NH            # player index holding each banner
        self.companions: list[int] = []      # face-up companions still available
        self.to_move = 0
        self.pending = None                  # player who must choose a companion now
        self.extra = False                   # Melisandre: current player moves again

    def copy(self) -> "State":
        s = State.__new__(State)
        s.board = self.board[:]
        s.varys = self.varys
        s.counts = [self.counts[0][:], self.counts[1][:]]
        s.cards = [set(self.cards[0]), set(self.cards[1])]
        s.banner = self.banner[:]
        s.companions = self.companions[:]
        s.to_move = self.to_move
        s.pending = self.pending
        s.extra = self.extra
        return s

    # ---------- helpers ----------
    def on_board(self, h: int) -> int:
        return sum(1 for c in self.board if c is not None and c != VARYS and CARD_HOUSE[c] == h)

    def board_counts(self) -> list[int]:
        bc = [0] * NH
        for c in self.board:
            if c is not None and c != VARYS:
                bc[CARD_HOUSE[c]] += 1
        return bc

    def banners(self, p: int) -> int:
        return sum(1 for b in self.banner if b == p)

    def __str__(self):
        rows = []
        for r in range(N):
            row = []
            for c in range(N):
                v = self.board[r * N + c]
                row.append("  ..  " if v is None else (" VARYS" if v == VARYS else f"{HOUSES[CARD_HOUSE[v]][:3]}:{CARD_NAME[v][:2]}"))
            rows.append(" ".join(row))
        return "\n".join(rows)


def new_game(rng: random.Random, use_companions: bool = True) -> State:
    s = State()
    deck = list(range(NCARDS)) + [VARYS]
    rng.shuffle(deck)
    s.board = deck
    s.varys = deck.index(VARYS)
    if use_companions:
        s.companions = sorted(rng.sample(range(len(COMPANIONS)), FACE_UP_COMPANIONS))
    return s


# ---------- moves ----------
# A move is (dir_index, house, dest_index, (collected card cells...))

def legal_moves(s: State):
    moves = []
    vr, vc = divmod(s.varys, N)
    board = s.board
    for d, (dr, dc) in enumerate(DIRS):
        r, c = vr + dr, vc + dc
        path_by_house: dict[int, list[int]] = {}
        while 0 <= r < N and 0 <= c < N:
            idx = r * N + c
            v = board[idx]
            if v is not None:
                path_by_house.setdefault(CARD_HOUSE[v], []).append(idx)
            r += dr
            c += dc
        for h, cells in path_by_house.items():
            moves.append((d, h, cells[-1], tuple(cells)))
    return moves


def _end_turn(s: State, p: int):
    """Rulebook: at the end of his turn the player takes the banner of every
    House where he has >= cards than his opponent (and at least one)."""
    o = 1 - p
    for h in range(NH):
        if s.counts[p][h] > 0 and s.counts[p][h] >= s.counts[o][h]:
            s.banner[h] = p
    s.pending = None
    if s.extra:
        s.extra = False
        s.to_move = p
    else:
        s.to_move = o


def apply_move(s: State, move) -> State:
    """Apply a Varys move. Returns new state. If a companion is triggered,
    state.pending is set and the same player must call apply_companion."""
    s = s.copy()
    p = s.to_move
    _, h, dest, cells = move
    for idx in cells:
        s.cards[p].add(s.board[idx])
        s.board[idx] = None
    s.counts[p][h] += len(cells)
    s.board[s.varys] = None
    s.board[dest] = VARYS
    s.varys = dest
    if s.companions and s.on_board(h) == 0:
        s.pending = p
    else:
        _end_turn(s, p)
    return s


# ---------- companions ----------
# Companion action: (companion_id, args tuple)

def _board_cells(s: State):
    return [i for i, v in enumerate(s.board) if v is not None and v != VARYS]


def companion_options(s: State, rng: random.Random | None = None, max_swaps: int | None = 40):
    p = s.pending
    o = 1 - p
    opts = []
    cells = _board_cells(s)
    for comp in s.companions:
        if comp == SANDOR:
            targets = [("b", i) for i in cells] + [("p", c) for c in sorted(s.cards[o])]
            opts += [(comp, t) for t in targets] or [(comp, ())]
        elif comp == BRIENNE:
            opts += [(comp, (c,)) for c in sorted(s.cards[o])] or [(comp, ())]
        elif comp == JORAH:
            opts += [(comp, (i,)) for i in cells if CARD_HOUSE[s.board[i]] == TARGARYEN] or [(comp, ())]
        elif comp == RAMSAY:
            pairs = [(x, y) for xi, x in enumerate(cells) for y in cells[xi + 1:]
                     if CARD_HOUSE[s.board[x]] != CARD_HOUSE[s.board[y]]]
            if max_swaps is not None and len(pairs) > max_swaps:
                pairs = (rng or random).sample(pairs, max_swaps)
            opts += [(comp, pr) for pr in pairs] or [(comp, ())]
        else:
            # fixed effects; Jaqen's three sub-choices are resolved by a built-in heuristic
            opts.append((comp, ()))
    return opts


def _take_card(s: State, p: int, card: int) -> bool:
    """Move a character into p's play area. Returns True if this took the final
    card of its House from King's Landing (which chains another companion)."""
    o = 1 - p
    h = CARD_HOUSE[card]
    if card in s.cards[p]:
        return False
    if card in s.cards[o]:
        s.cards[o].discard(card)
        s.counts[o][h] -= 1
        from_board = False
    elif card in s.board:
        s.board[s.board.index(card)] = None
        from_board = True
    else:
        return False  # already killed
    s.cards[p].add(card)
    s.counts[p][h] += 1
    return from_board and s.on_board(h) == 0


def _kill_from_play_area(s: State, owner: int, card: int):
    s.cards[owner].discard(card)
    s.counts[owner][CARD_HOUSE[card]] -= 1


def apply_companion(s: State, action) -> State:
    s = s.copy()
    p = s.pending
    o = 1 - p
    comp, args = action
    s.companions.remove(comp)
    chain = False
    if comp == JON_SNOW:
        s.counts[p][STARK] += 1
    elif comp == GENDRY:
        s.counts[p][BARATHEON] += 1
    elif comp == SHAE:
        s.counts[p][LANNISTER] += 1
    elif comp == BRONN:
        chain = _take_card(s, p, TYRION)
    elif comp == HODOR:
        chain = _take_card(s, p, BRAN)
    elif comp == LORAS:
        chain = _take_card(s, p, MARGAERY)
    elif comp == DROGO:
        chain = _take_card(s, p, DAENERYS)
    elif comp == SANDOR and args:
        where, x = args
        if where == "b":
            s.board[x] = None   # killing the final card of a House gives no companion
        else:
            _kill_from_play_area(s, o, x)
    elif comp == BRIENNE and args:
        _take_card(s, p, args[0])
    elif comp == JORAH and args:
        chain = _take_card(s, p, s.board[args[0]])
    elif comp == MELISANDRE:
        s.extra = True
    elif comp == RAMSAY and args:
        x, y = args
        s.board[x], s.board[y] = s.board[y], s.board[x]
    elif comp == JAQEN:
        _jaqen_greedy(s, p)
    if chain and s.companions:
        s.pending = p
    else:
        _end_turn(s, p)
    return s


def _jaqen_greedy(s: State, p: int):
    o = 1 - p
    bc = s.board_counts()
    # 1) kill the opponent's card that most threatens a banner (closest race, biggest house)
    best, best_key = None, None
    for c in s.cards[o]:
        h = CARD_HOUSE[c]
        key = (s.counts[o][h] - 1 <= s.counts[p][h], -abs(s.counts[o][h] - s.counts[p][h]), -h)
        if best_key is None or key > best_key:
            best, best_key = c, key
    if best is not None:
        _kill_from_play_area(s, o, best)
    # 2) kill a King's Landing card the opponent could use to catch up in a race I lead
    best, best_key = None, None
    for i in _board_cells(s):
        h = CARD_HOUSE[s.board[i]]
        lead = s.counts[p][h] - s.counts[o][h]
        key = (lead >= 0, -abs(lead), -h)
        if best_key is None or key > best_key:
            best, best_key = i, key
    if best is not None:
        s.board[best] = None
    # 3) kill the most dangerous remaining companion
    pref = [MELISANDRE, JAQEN, SANDOR, BRIENNE, RAMSAY, BRONN, DROGO, HODOR, LORAS,
            JORAH, JON_SNOW, GENDRY, SHAE]
    for c in pref:
        if c in s.companions:
            s.companions.remove(c)
            break


# ---------- game status ----------

def is_over(s: State) -> bool:
    return s.pending is None and not legal_moves(s)


def winner(s: State) -> int:
    b0, b1 = s.banners(0), s.banners(1)
    if b0 != b1:
        return 0 if b0 > b1 else 1
    for h in range(NH):  # largest house first
        if s.banner[h] is not None:
            return s.banner[h]
    return -1
