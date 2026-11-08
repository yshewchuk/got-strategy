# Hand of the King: which strategy wins 1v1?

A simulator for the 2-player game *A Game of Thrones: Hand of the King* (Fantasy
Flight, 2016): a 6×6 grid of characters, Varys moving in straight lines, and
companion cards. It includes twelve AI strategies and a round-robin tournament
that keeps playing each pairing until the result is statistically settled.

## TL;DR

**Look ahead and count to the end of the game.** The winning strategy searches about
5 half-moves deep (your move, their reply, ...). Once 14 or fewer cards are left
on the board, it solves the rest of the game exactly. It was the only strategy
with a winning record against every other one, with and without companion cards:

| | With companions | Without companions |
|---|---|---|
| Rating (Random = 0) | **771** (next best 743) | **792** (next best 692) |
| Average win rate vs the field | 78.5% | 87.1% |
| **Worst matchup** | **57.8%** vs AlphaBeta5 (95% CI 55.0–60.6%) | **70.6%** vs MCTS400 (95% CI 67.7–73.3%) |

Simple heuristics lose badly to search. Greedy players ("take the most cards",
"win a banner now", "cheap small houses first") win only 4–12% against the top
strategies.

**Seat matters:** the first player wins about 55% of games between equal players.

## What the winning strategy does, as advice a person can use

Measured over 300 games against the whole field (`results/champion_analysis.txt`).
The game is tight: it averages only **4.7 legal moves** per turn.

1. **Usually take the big grab (80% of its moves), but not always.** In the other
   20% it gives up cards to deny the opponent something better.
2. **Don't hand your opponent a big grab.** In 70% of its moves it picked the move
   that left the opponent the smallest possible next grab. Before moving, look at
   which cards will line up with Varys's new row and column.
3. **Win banners, don't just collect cards.** It took an available banner about
   80% of the time. Once you hold a banner the opponent can't catch up on (they
   can't reach your count with the cards left on the board), stop spending moves
   on that house.
4. **Small houses are the efficient banners.** It won Tully 66%, Baratheon 64% and
   Tyrell 62% of the time, against about 50–55% for Stark and Targaryen. A banner
   is a banner, and 2 Tully cards cost far less than 5 Stark cards. Stark only
   matters as the tie-breaker.
5. **Count out the endgame.** The game ends the moment Varys has no card in his
   row or column. That often means the last few cards are never taken, so you can
   engineer the finish: the move that strands Varys while you are ahead wins.
   Adding exact endgame solving was worth +35 rating with companions and +187
   without, against the same search otherwise.
   **What separates it from the greedy player** (`results/greedybanners_analysis.txt`):
   GreedyBanners takes the biggest grab more often (85% vs 80%) and grabs an
   available banner more often (88% vs 80%), yet ends with 3.1 banners on average
   against the champion's 4.1. The edge is in the ~1 move in 5 where it passes up
   the obvious grab because of what it would set up for the opponent.
6. **Companions:** the bot most often chose card-stealing and card-killing effects
   (Brienne, Sandor, Jaqen) because they swing banner races in both directions at
   once. Clearing a house (to earn a companion) happened on about 20% of its
   moves.

## Strategies tested

| Strategy | Idea |
|---|---|
| Random | uniformly random legal move (baseline) |
| GreedyCards | take the move that collects the most cards |
| SmallHousesFirst | human-style: grab banners of the smallest houses first |
| GreedyBanners | maximise banners held right after the move |
| Heuristic1 | 1-move lookahead with a positional score (banner locks, card margins) |
| AlphaBeta2–5 | minimax with alpha-beta pruning, 2–5 half-moves deep, same score |
| **AlphaBeta5+Solve14** | AlphaBeta5, plus exact search to the end once ≤14 cards remain |
| MonteCarlo30 | for each move, 30 random-ish playouts; pick the best win rate |
| MCTS400 | Monte-Carlo tree search (UCT), 400 iterations per move |

## Method

* Every pairing (66 of them) is played in **mirrored pairs**: the same shuffled
  board is played twice with seats swapped. That cancels out board luck and the
  first-player advantage.
* Batches of 200 games are added to each pairing until the 95% Wilson confidence
  interval on its win rate is within ±3 points, or 2,000 games are reached. That
  gave **93,000 games** in total across the two rule variants.
* Overall ratings are fitted with a Bradley–Terry model on an Elo scale.
* Full matrices: `results/companions.txt` and `results/no_companions.txt`; raw
  counts with CIs are in the `.json` files.

## Rules modelled

Movement, banners, game end and the tie-break were checked against the official
rulebook:

* Declare a direction and a House. Varys moves to the **farthest** card of that
  House in that direction, jumping everything, and you take every card of that
  House he passed or landed on.
* At the end of your turn, you take the banner of every House where you hold
  at least as many cards as your opponent.
* Taking the last card of a House from the board lets you resolve one of the 6
  face-up companions. A companion that *takes* a final card chains into another;
  *killing* a final card gives nothing.
* The game ends when Varys cannot move. Most banners wins; a tie goes to whoever
  holds the banner of the largest House.

**Companion caveat:** the rulebook does not print the 14 companion texts. Each
effect in `hotk/engine.py` is tagged `[rulebook]`, `[reviews]` or `[guess]`, and
only 13 are modelled. The no-companions run is the robustness check: the same
strategy wins there by an even larger margin, so the conclusion doesn't depend on
the guessed companions. To correct a companion, edit `COMPANION_TEXT` and
`apply_companion` in `hotk/engine.py` and rerun.

## Running it

Pure Python 3.10+, standard library only.

```bash
python -m hotk.tournament --ci 0.03 --max-games 2000            # with companions (~45 min on 4 cores)
python -m hotk.tournament --ci 0.03 --max-games 2000 --no-companions
python -m hotk.analyze --games 300 --champion AlphaBeta5+Solve14
```

To add a strategy, subclass `Strategy` in `hotk/strategies.py` with
`choose_move` (and optionally `choose_companion`) and add it to `all_strategies()`.
