"""Round-robin tournament with adaptive sample sizes.

Every pairing is played in *mirrored pairs*: the same shuffled board is played
twice with seats swapped, which cancels out board luck and first-move advantage.
Batches are added to a pairing until the 95% Wilson interval on the win rate is
narrower than +/- --ci (or --max-games is reached).

Usage: python -m hotk.tournament [--ci 0.03] [--max-games 4000] [--no-companions]
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import time
from multiprocessing import Pool

from .play import play_game
from .strategies import all_strategies

STRATS = {s.name: s for s in all_strategies()}


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def _run_pair(args):
    a, b, seeds, comps = args
    A, B = STRATS[a], STRATS[b]
    a_wins = first_seat_wins = games = 0
    for seed in seeds:
        w = play_game(A, B, seed, comps)       # A in seat 0
        a_wins += w == 0
        first_seat_wins += w == 0
        w = play_game(B, A, seed, comps)       # A in seat 1
        a_wins += w == 1
        first_seat_wins += w == 0
        games += 2
    return a, b, a_wins, games, first_seat_wins


def bradley_terry(names, results, iters=2000):
    """Fit Bradley-Terry strengths, returned on an Elo-like scale (Random = 0)."""
    r = {n: 1.0 for n in names}
    wins = {n: 0.0 for n in names}
    for (a, b), (k, n) in results.items():
        wins[a] += k + 0.5
        wins[b] += n - k + 0.5
    for _ in range(iters):
        new = {}
        for i in names:
            denom = 0.0
            for (a, b), (k, n) in results.items():
                if i in (a, b):
                    j = b if i == a else a
                    denom += (n + 1) / (r[i] + r[j])
            new[i] = wins[i] / denom
        g = math.exp(sum(math.log(v) for v in new.values()) / len(new))
        r = {k: v / g for k, v in new.items()}
    base = r.get("Random", 1.0)
    return {n: 400 * math.log10(r[n] / base) for n in names}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ci", type=float, default=0.03, help="target 95%% CI half-width")
    ap.add_argument("--max-games", type=int, default=4000)
    ap.add_argument("--batch", type=int, default=100, help="mirrored seed pairs per batch")
    ap.add_argument("--no-companions", action="store_true")
    ap.add_argument("--out", default="results.json")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    comps = not args.no_companions

    names = list(STRATS)
    pairs = list(itertools.combinations(names, 2))
    res = {pr: [0, 0] for pr in pairs}
    first_seat = [0, 0]
    next_seed = {pr: 1_000_000 * i for i, pr in enumerate(pairs)}
    t0 = time.time()
    with Pool(args.workers) as pool:
        active = set(pairs)
        while active:
            jobs = []
            for pr in active:
                # split each batch into chunks so workers stay busy
                chunk = max(1, args.batch // 4)
                for c in range(0, args.batch, chunk):
                    seeds = range(next_seed[pr] + c, next_seed[pr] + min(c + chunk, args.batch))
                    jobs.append((pr[0], pr[1], list(seeds), comps))
                next_seed[pr] += args.batch
            for a, b, k, n, fs in pool.imap_unordered(_run_pair, jobs):
                res[(a, b)][0] += k
                res[(a, b)][1] += n
                first_seat[0] += fs
                first_seat[1] += n
            done = set()
            for pr in active:
                k, n = res[pr]
                lo, hi = wilson(k, n)
                if (hi - lo) / 2 <= args.ci or n >= args.max_games:
                    done.add(pr)
            active -= done
            total = sum(n for _, n in res.values())
            print(f"[{time.time() - t0:7.0f}s] games={total} pairs still running={len(active)}", flush=True)

    results = {pr: tuple(v) for pr, v in res.items()}
    elo = bradley_terry(names, results)
    order = sorted(names, key=lambda n: -elo[n])

    # matrix
    def wr(a, b):
        if (a, b) in results:
            k, n = results[(a, b)]
            return k / n, n
        k, n = results[(b, a)]
        return (n - k) / n, n

    print(f"\nCompanions: {'on' if comps else 'off'}   total games: {sum(n for _, n in results.values())}")
    print(f"First-seat win rate: {first_seat[0] / first_seat[1]:.3f}")
    print("\nRatings (Bradley-Terry, Elo scale, Random = 0) and worst matchup:")
    rows = []
    for a in order:
        others = [(wr(a, b)[0], b) for b in names if b != a]
        avg = sum(x for x, _ in others) / len(others)
        worst = min(others)
        rows.append({"strategy": a, "elo": round(elo[a]), "avg_win": round(avg, 3),
                     "worst_win": round(worst[0], 3), "worst_vs": worst[1]})
        print(f"  {a:18s} elo={elo[a]:6.0f}  avg win={avg:.3f}  worst={worst[0]:.3f} vs {worst[1]}")

    print("\nWin-rate matrix (row vs column):")
    short = [n[:9] for n in order]
    print(" " * 18 + " ".join(f"{s:>9s}" for s in short))
    for a in order:
        cells = []
        for b in order:
            cells.append("    --   " if a == b else f"{wr(a, b)[0]:9.3f}")
        print(f"{a:18s}" + " ".join(cells))

    with open(args.out, "w") as f:
        json.dump({
            "companions": comps,
            "first_seat_win_rate": first_seat[0] / first_seat[1],
            "ranking": rows,
            "pairs": [{"a": a, "b": b, "a_wins": k, "games": n,
                       "ci95": [round(x, 4) for x in wilson(k, n)]}
                      for (a, b), (k, n) in results.items()],
        }, f, indent=1)


if __name__ == "__main__":
    main()
