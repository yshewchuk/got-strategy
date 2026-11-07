"""Explain what the strongest strategy actually does, in human-usable terms.

Plays the champion against a field of opponents and records, for each of its
decisions, how its choice relates to simple rules of thumb.

Usage: python -m hotk.analyze [--games 200] [--champion AlphaBeta5]
"""
from __future__ import annotations

import argparse
import random
from collections import Counter

from .engine import (COMPANIONS, HOUSES, NH, apply_companion, apply_move, legal_moves,
                     new_game, winner)
from .strategies import all_strategies, evaluate


def opp_best_grab(s):
    ms = legal_moves(s)
    return max((len(m[3]) for m in ms), default=0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--champion", default="AlphaBeta5")
    args = ap.parse_args()
    strats = {s.name: s for s in all_strategies()}
    champ = strats[args.champion]
    field = [s for n, s in strats.items() if n != args.champion]

    f = Counter()
    banners_won = Counter()
    banners_total = Counter()
    comp_pick = Counter()
    final_banners = []
    for g in range(args.games):
        opp = field[g % len(field)]
        seat = g % 2
        rng = random.Random(10_000 + g)
        s = new_game(random.Random(g))
        players = [champ, opp] if seat == 0 else [opp, champ]
        while True:
            if s.pending is not None:
                a = players[s.pending].choose_companion(s, rng)
                if s.pending == seat:
                    comp_pick[COMPANIONS[a[0]]] += 1
                s = apply_companion(s, a)
                continue
            moves = legal_moves(s)
            if not moves:
                break
            if s.to_move == seat:
                m = champ.choose_move(s, rng)
                biggest = max(len(x[3]) for x in moves)
                p = seat
                takes_banner = s.banner[m[1]] != p and s.counts[p][m[1]] + len(m[3]) >= s.counts[1 - p][m[1]]
                any_banner = any(s.banner[x[1]] != p and s.counts[p][x[1]] + len(x[3]) >= s.counts[1 - p][x[1]]
                                 for x in moves)
                nxt = apply_move(s, m)
                # how big a grab does each candidate leave the opponent?
                leaves = {}
                for x in moves:
                    t = apply_move(s, x)
                    leaves[x] = opp_best_grab(t) if t.pending is None else 0
                f["decisions"] += 1
                f["took_biggest_grab"] += len(m[3]) == biggest
                f["took_a_banner"] += takes_banner
                f["banner_available"] += any_banner
                f["took_banner_when_available"] += takes_banner and any_banner
                f["min_opponent_grab"] += leaves[m] == min(leaves.values())
                f["triggered_companion"] += nxt.pending is not None
                f["choices_available"] += len(moves)
                s = nxt
            else:
                s = apply_move(s, players[s.to_move].choose_move(s, rng))
        w = winner(s)
        f["wins"] += w == seat
        for h in range(NH):
            banners_total[HOUSES[h]] += 1
            banners_won[HOUSES[h]] += s.banner[h] == seat
        final_banners.append(s.banners(seat))

    d = f["decisions"]
    print(f"{args.champion} over {args.games} games vs the field: win rate {f['wins'] / args.games:.3f}")
    print(f"  avg moves available per decision : {f['choices_available'] / d:.1f}")
    print(f"  chose the biggest grab           : {f['took_biggest_grab'] / d:.1%}")
    print(f"  took a banner when one was there : {f['took_banner_when_available'] / max(1, f['banner_available']):.1%}")
    print(f"  chose the move leaving the opponent the smallest grab: {f['min_opponent_grab'] / d:.1%}")
    print(f"  moves that cleared a house (companion): {f['triggered_companion'] / d:.1%}")
    print(f"  avg banners at end               : {sum(final_banners) / len(final_banners):.2f} of 7")
    print("  share of each banner won:")
    for h in HOUSES:
        print(f"    {h:10s} {banners_won[h] / banners_total[h]:.1%}")
    print("  companion picks:", dict(comp_pick.most_common()))


if __name__ == "__main__":
    main()
