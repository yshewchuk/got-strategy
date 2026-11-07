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
* After collecting, if the player now holds >= as many cards of that house as
  the opponent, they take that house's banner (ties go to the latest
  collector).
* If the move removed the last card of that house from the board and any
  companion cards are still face up, the player picks one and resolves it.
* The game ends as soon as the player to move has no legal move (no cards in
  Varys's row or column). Most banners wins; a banner tie is broken by who holds
  the banner of the largest house (Stark, then Greyjoy, ...).
* Six of the companion cards are dealt face up each game.

Companion cards: the original game has 14; the effects below are a best-effort
reconstruction (the exact card texts could not be verified from this sandbox),
see README.md. They can be disabled with `use_companions=False`.
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
BRAN, DAENERYS, MARGAERY = CARD_BY_NAME["Bran"], CARD_BY_NAME["Daenerys"], CARD_BY_NAME["Margaery"]

DIRS = [(-1, 0), (1, 0), (0, -1), (0, 1)]

# Companion ids
MELISANDRE, GENDRY, JON_SNOW, SANDOR, JAQEN, DROGO, HODOR, BRONN, LORAS, RAMSAY, BRIENNE = range(11)
COMPANIONS = ["Melisandre", "Gendry", "Jon Snow", "Sandor Clegane", "Jaqen H'ghar",
              "Khal Drogo", "Hodor", "Bronn", "Loras Tyrell", "Ramsay Snow", "Brienne"]
COMPANION_TEXT = {
    MELISANDRE: "Take another turn.",
    GENDRY: "Keep him: counts as an extra Baratheon card.",
    JON_SNOW: "Keep him: counts as an extra Stark card.",
    SANDOR: "Kill (discard) one card from your opponent's collection.",
    JAQEN: "Kill one card on the board, one card in any collection, and one face-up companion.",
    DROGO: "Take Daenerys, from the board or from your opponent.",
    HODOR: "Take Bran from the board.",
    BRONN: "Take any one card from the board.",
    LORAS: "Take Margaery, from the board or from your opponent.",
    RAMSAY: "Swap the positions of two cards on the board.",
    BRIENNE: "Steal any one card from your opponent's collection.",
}
FACE_UP_COMPANIONS = 6


class State:
    __slots__ = ("board", "varys", "counts", "cards", "banner", "companions", "to_move",
                 "pending", "rng_used")

    def __init__(self):
        self.board: list[int | None] = []      # 36 cells: card id, VARYS, or None
        self.varys = 0
        self.counts = [[0] * NH, [0] * NH]   # cards (incl. bonus companions) per house per player
        self.cards: list[set] = [set(), set()]  # actual card ids held
        self.banner = [None] * NH            # player index holding each banner
        self.companions: list[int] = []      # face-up companions still available
        self.to_move = 0
        self.pending = None                  # (player, house) when a companion choice is due

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


def _set_banner_after_gain(s: State, p: int, h: int):
    if s.counts[p][h] >= s.counts[1 - p][h] and s.counts[p][h] > 0:
        s.banner[h] = p


def _recheck_banner_after_loss(s: State, h: int):
    holder = s.banner[h]
    if holder is None:
        return
    if s.counts[holder][h] == 0 and s.counts[1 - holder][h] == 0:
        s.banner[h] = None
    elif s.counts[holder][h] < s.counts[1 - holder][h]:
        s.banner[h] = 1 - holder


def apply_move(s: State, move) -> State:
    """Apply a Varys move. Returns new state. If a companion is triggered,
    state.pending is set and the same player must call apply_companion."""
    s = s.copy()
    p = s.to_move
    _, h, dest, cells = move
    for idx in cells:
        card = s.board[idx]
        s.cards[p].add(card)
        s.board[idx] = None
    s.counts[p][h] += len(cells)
    s.board[s.varys] = None
    s.board[dest] = VARYS
    s.varys = dest
    _set_banner_after_gain(s, p, h)
    if s.companions and s.on_board(h) == 0:
        s.pending = p
    else:
        s.to_move = 1 - p
    return s


# ---------- companions ----------
# Companion action: (companion_id, args tuple)

def companion_options(s: State, rng: random.Random | None = None, max_swaps: int | None = 40):
    p = s.pending
    o = 1 - p
    opts = []
    board_cells = [i for i, v in enumerate(s.board) if v is not None and v != VARYS]
    for comp in s.companions:
        if comp in (MELISANDRE, GENDRY, JON_SNOW):
            opts.append((comp, ()))
        elif comp == SANDOR:
            if s.cards[o]:
                opts += [(comp, (c,)) for c in sorted(s.cards[o])]
            else:
                opts.append((comp, ()))
        elif comp == BRIENNE:
            if s.cards[o]:
                opts += [(comp, (c,)) for c in sorted(s.cards[o])]
            else:
                opts.append((comp, ()))
        elif comp == BRONN:
            opts += [(comp, (i,)) for i in board_cells] or [(comp, ())]
        elif comp in (DROGO, HODOR, LORAS):
            opts.append((comp, ()))
        elif comp == RAMSAY:
            pairs = [(a, b) for ai, a in enumerate(board_cells) for b in board_cells[ai + 1:]
                     if CARD_HOUSE[s.board[a]] != CARD_HOUSE[s.board[b]]]
            if max_swaps is not None and len(pairs) > max_swaps:
                pairs = (rng or random).sample(pairs, max_swaps)
            opts += [(comp, pr) for pr in pairs] or [(comp, ())]
        elif comp == JAQEN:
            # Simplified decision: kill the board card / collection card / companion
            # chosen to hurt the opponent most (sub-choices handled greedily in apply).
            opts.append((comp, ()))
    return opts


def _take_card(s: State, p: int, card: int):
    """Move a card into player p's collection from board or opponent."""
    o = 1 - p
    h = CARD_HOUSE[card]
    if card in s.cards[o]:
        s.cards[o].discard(card)
        s.counts[o][h] -= 1
    elif card in s.board:
        s.board[s.board.index(card)] = None
    else:
        return
    s.cards[p].add(card)
    s.counts[p][h] += 1
    _set_banner_after_gain(s, p, h)
    _recheck_banner_after_loss(s, h)


def _kill_from_collection(s: State, owner: int, card: int):
    h = CARD_HOUSE[card]
    s.cards[owner].discard(card)
    s.counts[owner][h] -= 1
    _recheck_banner_after_loss(s, h)


def apply_companion(s: State, action) -> State:
    s = s.copy()
    p = s.pending
    o = 1 - p
    comp, args = action
    s.companions.remove(comp)
    s.pending = None
    extra_turn = False
    if comp == MELISANDRE:
        extra_turn = True
    elif comp == GENDRY:
        s.counts[p][BARATHEON] += 1
        _set_banner_after_gain(s, p, BARATHEON)
    elif comp == JON_SNOW:
        s.counts[p][STARK] += 1
        _set_banner_after_gain(s, p, STARK)
    elif comp == SANDOR and args:
        _kill_from_collection(s, o, args[0])
    elif comp == BRIENNE and args:
        _take_card(s, p, args[0])
    elif comp == BRONN and args:
        _take_card(s, p, s.board[args[0]])
    elif comp == DROGO:
        _take_card(s, p, DAENERYS)
    elif comp == HODOR:
        if BRAN in s.board:
            _take_card(s, p, BRAN)
    elif comp == LORAS:
        _take_card(s, p, MARGAERY)
    elif comp == RAMSAY and args:
        a, b = args
        s.board[a], s.board[b] = s.board[b], s.board[a]
    elif comp == JAQEN:
        _jaqen_greedy(s, p)
    s.to_move = p if extra_turn else o
    return s


def _jaqen_greedy(s: State, p: int):
    o = 1 - p
    # 1) kill opponent's card in the house where it hurts most (prefer flipping a banner)
    best, best_key = None, None
    for c in s.cards[o]:
        h = CARD_HOUSE[c]
        flips = s.banner[h] == o and s.counts[o][h] - 1 < s.counts[p][h]
        key = (flips, -HOUSE_SIZE[h])
        if best_key is None or key > best_key:
            best, best_key = c, key
    if best is not None:
        _kill_from_collection(s, o, best)
    # 2) kill a board card of a house where I hold the banner but it is contested
    best, best_key = None, None
    for i, v in enumerate(s.board):
        if v is None or v == VARYS:
            continue
        h = CARD_HOUSE[v]
        key = (s.banner[h] == p, s.counts[p][h] - s.counts[o][h] <= 1)
        if best_key is None or key > best_key:
            best, best_key = i, key
    if best is not None:
        s.board[best] = None
    # 3) kill the strongest remaining companion (Melisandre / Brienne first)
    pref = [BRIENNE, MELISANDRE, SANDOR, BRONN, JAQEN, DROGO, LORAS, RAMSAY, HODOR, GENDRY, JON_SNOW]
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
