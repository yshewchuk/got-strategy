from __future__ import annotations

import random

from .engine import apply_companion, apply_move, legal_moves, new_game, winner


def play_game(strat0, strat1, seed: int, use_companions: bool = True, verbose: bool = False) -> int:
    """Play one game. Returns winning seat (0/1). Board layout depends only on seed."""
    board_rng = random.Random(seed)
    s = new_game(board_rng, use_companions)
    rng = random.Random(seed * 7919 + 1)
    strats = (strat0, strat1)
    while True:
        if s.pending is not None:
            a = strats[s.pending].choose_companion(s, rng)
            if verbose:
                print(f"P{s.pending} companion {a}")
            s = apply_companion(s, a)
            continue
        if not legal_moves(s):
            break
        m = strats[s.to_move].choose_move(s, rng)
        if verbose:
            print(f"P{s.to_move} move {m}")
        s = apply_move(s, m)
    return winner(s)
