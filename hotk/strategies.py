"""Candidate strategies.

Every strategy implements
    choose_move(state, rng) -> move
    choose_companion(state, rng) -> companion action
"""
from __future__ import annotations

import math
import random

from .engine import (HOUSE_SIZE, NH, apply_companion, apply_move, companion_options,
                     is_over, legal_moves, winner)

WIN = 1000.0


# ---------------------------------------------------------------- evaluation

def evaluate(s, p: int) -> float:
    """Static evaluation from player p's perspective (higher is better)."""
    if is_over(s):
        w = winner(s)
        return WIN if w == p else (-WIN if w == 1 - p else 0.0)
    o = 1 - p
    bc = s.board_counts()
    score = 0.0
    for h in range(NH):
        m, t, r = s.counts[p][h], s.counts[o][h], bc[h]
        holder = s.banner[h]
        tb = 1.0 + 0.02 * (NH - h)  # tiny weight so bigger houses break ties
        if holder == p and t + r < m:
            v = 1.0  # opponent can no longer catch up from the board
        elif holder == o and m + r < t:
            v = -1.0
        else:
            v = (0.45 if holder == p else -0.45 if holder == o else 0.0)
            v += 0.12 * (m - t)
        score += tb * v
    return score


def evaluate_banners(s, p: int) -> float:
    """Naive evaluation: just banners held (+ cards as tie-break)."""
    if is_over(s):
        w = winner(s)
        return WIN if w == p else (-WIN if w == 1 - p else 0.0)
    return (s.banners(p) - s.banners(1 - p)) + 0.01 * (sum(s.counts[p]) - sum(s.counts[1 - p]))


def best_companion(s, rng, evalf):
    p = s.pending
    best, best_v = None, -math.inf
    for a in companion_options(s, rng):
        v = evalf(apply_companion(s, a), p) + rng.random() * 1e-6
        if v > best_v:
            best, best_v = a, v
    return best


def resolve_greedy(s, rng, evalf):
    """Resolve any pending companion choice greedily (used inside searches/rollouts)."""
    while s.pending is not None:
        s = apply_companion(s, best_companion(s, rng, evalf))
    return s


# ---------------------------------------------------------------- strategies

class Strategy:
    name = "base"

    def choose_companion(self, s, rng):
        return best_companion(s, rng, evaluate)


class RandomStrategy(Strategy):
    name = "Random"

    def choose_move(self, s, rng):
        return rng.choice(legal_moves(s))

    def choose_companion(self, s, rng):
        return rng.choice(companion_options(s, rng))


class GreedyCards(Strategy):
    """Grab the move that collects the most cards right now."""
    name = "GreedyCards"

    def choose_move(self, s, rng):
        moves = legal_moves(s)
        best = max(len(m[3]) for m in moves)
        return rng.choice([m for m in moves if len(m[3]) == best])

    def choose_companion(self, s, rng):
        return best_companion(s, rng, evaluate_banners)


class SmallHousesFirst(Strategy):
    """Human-style: cheap banners first. Prefer moves that win a banner,
    smallest house first; otherwise grab the most cards of the smallest house."""
    name = "SmallHousesFirst"

    def choose_move(self, s, rng):
        p = s.to_move

        def key(m):
            h, n = m[1], len(m[3])
            wins = s.banner[h] != p and s.counts[p][h] + n >= s.counts[1 - p][h]
            return (wins, h, n, rng.random())  # higher h == smaller house
        return max(legal_moves(s), key=key)


class GreedyBanners(Strategy):
    """1-ply: maximise banner differential right after the move."""
    name = "GreedyBanners"

    def choose_move(self, s, rng):
        p = s.to_move
        return max(legal_moves(s), key=lambda m: evaluate_banners(
            resolve_greedy(apply_move(s, m), rng, evaluate_banners), p) + rng.random() * 1e-6)

    def choose_companion(self, s, rng):
        return best_companion(s, rng, evaluate_banners)


class Heuristic(Strategy):
    """1-ply with the positional evaluation (banner locks + card margins)."""
    name = "Heuristic1"

    def choose_move(self, s, rng):
        p = s.to_move
        return max(legal_moves(s), key=lambda m: evaluate(
            resolve_greedy(apply_move(s, m), rng, evaluate), p) + rng.random() * 1e-6)


class AlphaBeta(Strategy):
    """Depth-limited alpha-beta (negamax-free, handles extra turns) on `evaluate`."""

    def __init__(self, depth: int, endgame: int = 0):
        self.base_depth = depth
        self.endgame = endgame  # solve exactly once this few cards remain on the board
        self.name = f"AlphaBeta{depth}" + (f"+Solve{endgame}" if endgame else "")

    def choose_move(self, s, rng):
        p = s.to_move
        left = sum(s.board_counts())
        self.depth = 99 if left <= self.endgame else self.base_depth
        moves = legal_moves(s)
        rng.shuffle(moves)
        # move ordering: bigger grabs first
        moves.sort(key=lambda m: -len(m[3]))
        best, best_v = moves[0], -math.inf
        alpha = -math.inf
        for m in moves:
            child = resolve_greedy(apply_move(s, m), rng, evaluate)
            v = self._ab(child, self.depth - 1, alpha, math.inf, p, rng)
            if v > best_v:
                best, best_v = m, v
            alpha = max(alpha, v)
        return best

    def _ab(self, s, depth, alpha, beta, p, rng):
        if depth == 0 or is_over(s):
            return evaluate(s, p)
        moves = legal_moves(s)
        moves.sort(key=lambda m: -len(m[3]))
        if s.to_move == p:
            v = -math.inf
            for m in moves:
                v = max(v, self._ab(resolve_greedy(apply_move(s, m), rng, evaluate), depth - 1, alpha, beta, p, rng))
                alpha = max(alpha, v)
                if alpha >= beta:
                    break
            return v
        v = math.inf
        for m in moves:
            v = min(v, self._ab(resolve_greedy(apply_move(s, m), rng, evaluate), depth - 1, alpha, beta, p, rng))
            beta = min(beta, v)
            if alpha >= beta:
                break
        return v


def _rollout(s, rng):
    """Fast semi-random playout: 50% greedy-card move, 50% random."""
    while True:
        if s.pending is not None:
            s = apply_companion(s, rng.choice(companion_options(s, rng, max_swaps=5)))
            continue
        moves = legal_moves(s)
        if not moves:
            return winner(s)
        if rng.random() < 0.5:
            m = max(moves, key=lambda m: len(m[3]))
        else:
            m = rng.choice(moves)
        s = apply_move(s, m)


class MonteCarlo(Strategy):
    """Flat Monte-Carlo: for every legal move, run N playouts; pick the best win rate."""

    def __init__(self, playouts: int = 30):
        self.playouts = playouts
        self.name = f"MonteCarlo{playouts}"

    def choose_move(self, s, rng):
        p = s.to_move
        moves = legal_moves(s)
        if len(moves) == 1:
            return moves[0]
        best, best_v = None, -1.0
        for m in moves:
            child = resolve_greedy(apply_move(s, m), rng, evaluate)
            wins = sum(1 for _ in range(self.playouts) if _rollout(child, rng) == p)
            v = wins + rng.random() * 1e-3
            if v > best_v:
                best, best_v = m, v
        return best


class MCTS(Strategy):
    """UCT Monte-Carlo tree search over Varys moves (companions resolved greedily)."""

    def __init__(self, iterations: int = 400, c: float = 0.9):
        self.iterations = iterations
        self.c = c
        self.name = f"MCTS{iterations}"

    def choose_move(self, s, rng):
        root_player = s.to_move
        moves = legal_moves(s)
        if len(moves) == 1:
            return moves[0]

        class Node:
            __slots__ = ("state", "moves", "children", "n", "w", "player")

            def __init__(self, state):
                self.state = state
                self.moves = legal_moves(state)
                rng.shuffle(self.moves)
                self.children = {}
                self.n = 0
                self.w = 0.0
                self.player = state.to_move  # player to move in this node

        root = Node(s)
        for _ in range(self.iterations):
            node, path = root, [root]
            # selection
            while node.moves and len(node.children) == len(node.moves):
                logn = math.log(node.n)
                best, best_u = None, -1.0
                for i, ch in node.children.items():
                    # ch.w is wins for the player who moved INTO ch (node.player)
                    u = ch.w / ch.n + self.c * math.sqrt(logn / ch.n)
                    if u > best_u:
                        best, best_u = ch, u
                node = best
                path.append(node)
            # expansion
            if node.moves:
                i = len(node.children)
                child_state = resolve_greedy(apply_move(node.state, node.moves[i]), rng, evaluate)
                ch = Node(child_state)
                node.children[i] = ch
                path.append(ch)
                result = _rollout(child_state, rng)
            else:
                result = winner(node.state)
            # backprop: each node credits the player who made the move into it
            for k in range(1, len(path)):
                path[k].n += 1
                if result == path[k - 1].player:
                    path[k].w += 1
            root.n += 1
        best_i = max(root.children, key=lambda i: root.children[i].n)
        return root.moves[best_i]


def all_strategies():
    return [
        RandomStrategy(),
        GreedyCards(),
        SmallHousesFirst(),
        GreedyBanners(),
        Heuristic(),
        AlphaBeta(2),
        AlphaBeta(3),
        AlphaBeta(4),
        AlphaBeta(5),
        AlphaBeta(5, endgame=14),
        MonteCarlo(30),
        MCTS(400),
    ]
