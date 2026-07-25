# P4 R1 Manual Round — Deep Dive Explainer
## "An Intarian Welcome"

---

## Part 1: What is a Clearing Price?

In a normal exchange, trades happen continuously — someone posts a bid, someone posts an ask,
they match immediately if they cross.

This auction is **different**. Everyone submits their orders first, then **one single price** is
chosen at the end to settle all trades simultaneously. That price is called the **clearing price**.

### The rule for choosing the clearing price:
> Pick the price that **maximises total volume traded**. If two prices give equal volume, pick the higher one.

---

## Part 2: How Volume is Calculated at Each Price

For any candidate clearing price **P**:

- **Demand at P** = total volume of all bids with price **≥ P**
  (these buyers are willing to pay P or more, so they execute)

- **Supply at P** = total volume of all asks with price **≤ P**
  (these sellers are willing to accept P or less, so they execute)

- **Volume matched at P** = min(Demand at P, Supply at P)
  (you can only trade what both sides agree on)

We compute this for every possible price level, then pick the one with the highest matched volume.

---

## Part 3: The Dryland Flax Orderbook

Here is the existing orderbook **before you submit anything**:

```
BIDS (buyers)        ASKS (sellers)
Price | Volume        Price | Volume
  30  | 30,000          28  | 40,000
  29  |  5,000          31  | 20,000
  28  | 12,000          32  | 20,000
  27  | 28,000          33  | 30,000
```

---

## Part 4: Finding the Natural Clearing Price (Without You)

Let's compute **demand**, **supply**, and **matched volume** at every relevant price:

| Price | Demand (bids ≥ P)         | Supply (asks ≤ P) | Matched = min(D,S) |
|-------|---------------------------|-------------------|--------------------|
|  27   | 30k+5k+12k+28k = **75k** | 0                 | **0**              |
|  28   | 30k+5k+12k     = **47k** | 40k               | **40k** ← MAX      |
|  29   | 30k+5k         = **35k** | 40k               | **35k**            |
|  30   | 30k            = **30k** | 40k               | **30k**            |
|  31   | 0                        | 40k+20k = 60k     | **0**              |

### Result: Natural clearing price = 28 (highest volume = 40k)

Why 28 and not 27?
- At price 27: there are NO sellers willing to sell at 27 or below. Supply = 0. No trades happen.

Why 28 and not 29?
- At price 28: matched = 40k
- At price 29: matched = 35k
- 40k > 35k → price 28 wins

---

## Part 5: Who Gets Filled at Clearing Price 28?

Volume matched = 40k. But total demand = 47k. Supply (40k) is the bottleneck.

Filling happens in **price priority** (highest bids first), then **time priority** (earlier orders first).
You submitted last → you are at the BACK of every queue.

| Bid Level | Volume | Cumulative filled | Notes                        |
|-----------|--------|-------------------|------------------------------|
| @ 30      | 30,000 | 30,000            | Highest priority, fully filled |
| @ 29      | 5,000  | 35,000            | Fully filled                 |
| @ 28      | 12,000 | 40,000            | Only 5k fills (5k left), partial |
| **You @ 28** | any | **0**            | Supply exhausted. You get nothing. |

**Problem: if you bid at 28, you are behind 47k of existing demand with only 40k supply.**
**You always get 0 fills at the natural clearing price.**

---

## Part 6: Your Goal — Shift the Clearing Price to 29

You want to force the clearing price UP to 29, where there is slack for you.

At price 29 (without you):
- Demand = 35k, Supply = 40k → matched = 35k

You need matched volume at 29 to equal or beat matched volume at 28 (= 40k).

**What if you bid 5,000 units at price 29?**

New demand at price 29 = 35k (existing) + 5k (you) = **40k**

| Price | Demand         | Supply | Matched |
|-------|----------------|--------|---------|
|  28   | 47k + 5k = 52k | 40k    | **40k** |
|  29   | 35k + 5k = 40k | 40k    | **40k** ← TIE |

Both price 28 and price 29 give 40k volume. **Tie-break: choose the higher price.**

→ **Clearing price = 29** ✓

---

## Part 7: Who Gets Filled at Clearing Price 29?

Supply at ≤ 29 = 40k (still just the 40k asks at 28).
Demand at ≥ 29 = 35k (existing) + 5k (you) = **40k exactly**.

Supply = Demand = 40k → **everyone gets fully filled**.

| Bid Level    | Volume  | Cumulative | Notes                     |
|--------------|---------|------------|---------------------------|
| @ 30         | 30,000  | 30,000     | Fully filled              |
| @ 29 existing| 5,000   | 35,000     | Fully filled              |
| **You @ 29** | **5,000** | **40,000** | **Fully filled ✓**     |

Your fills: **5,000 units at clearing price 29**
Guild buyback: **30 per unit**
**Profit = (30 − 29) × 5,000 = 5,000 XIRECs**

---

## Part 8: Why Can't You Do Better on Dryland Flax?

### Why not bid at 28?
- Clearing stays at 28. Existing demand (47k) already exceeds supply (40k) before you.
- You're last in queue. Supply is exhausted. 0 fills.

### Why not bid at 30?
- At clearing 30: demand = 30k (existing) + your bid = 40k if you bid 10k+
- Volume at 30 = 40k → ties with 28 → tie-break → clearing = 30
- Profit per unit = 30 − 30 = **0**. Breakeven. Pointless.

### Why not bid more than 5k at 29?
- Say you bid 10k at 29. Demand at 29 = 35k + 10k = 45k. Supply = 40k.
- Supply is now binding. Queue: bid@30(30k) → bid@29_existing(5k) → **you(10k)**: only 5k remaining.
- You still only get **5k fills**. More qty doesn't help once you're past the supply cap.

### The ceiling is structurally 5,000 units
The 5k gap exists only because:
- Supply at ≤29 = 40k
- Existing demand at ≥29 = 35k
- Gap = 40k − 35k = 5k

That gap is your maximum fill. Nothing you do changes it.

---

## Part 9: Summary Table — All Options for Dryland Flax

| Your bid price | Clearing price | Your fills | Profit/unit | Total profit |
|----------------|----------------|------------|-------------|--------------|
| 27             | 28             | 0          | —           | 0            |
| 28             | 28             | 0          | 2           | **0**        |
| **29**         | **29**         | **5,000**  | **1**       | **5,000** ✓ |
| 30             | 30             | 10,000     | 0           | **0**        |
| 31+            | 31+            | some       | negative    | **loss**     |

**Optimal: bid price = 29, quantity ≥ 5,000**

---

## Key Concept: The "Stale Book" Risk

The orderbook is described as "stale" — meaning it was captured at some point before the auction closes.
In Prosperity competitions the book is static for all participants, so this is mostly flavour text.

However, the only scenario where our strategy fails:
- If the ask at price 28 is actually **≤ 35,000** (not 40,000)
- Then supply ≤ existing demand at ≥29, and we get 0 fills
- We need ask@28 > 35,000 for any profit

The book shows 40,000. We have a 5,000 unit buffer. It's fine.

---
---

# EMBER MUSHROOM — Deep Dive

---

## Part 10: The Ember Mushroom Orderbook

Here is the existing orderbook **before you submit anything**:

```
BIDS (buyers)        ASKS (sellers)
Price | Volume        Price | Volume
  20  | 43,000          12  | 20,000
  19  | 17,000          13  | 25,000
  18  |  6,000          14  | 35,000
  17  |  5,000          15  |  6,000
  16  | 10,000          16  |  5,000
  15  |  5,000          17  |      0
  14  | 10,000          18  | 10,000
  13  |  7,000          19  | 12,000
```

**Guild buyback: 20 per unit. Fee: 0.05 buy + 0.05 sell = 0.10 total.**
**Net per unit after fees = 19.90**

Profit per unit = 19.90 − clearing price.
You only make money if clearing price ≤ 19.

---

## Part 11: Finding the Natural Clearing Price (Without You)

Compute cumulative demand and supply at every price level:

| Price | Demand (bids ≥ P)                  | Supply (asks ≤ P)               | Matched |
|-------|-------------------------------------|---------------------------------|---------|
|  13   | 43+17+6+5+10+5+10+7 = **103k**     | 20+25 = **45k**                 | 45k     |
|  14   | 43+17+6+5+10+5+10  = **96k**       | 20+25+35 = **80k**              | 80k     |
|  15   | 43+17+6+5+10+5     = **86k**       | 20+25+35+6 = **86k**            | **86k** ← MAX |
|  16   | 43+17+6+5+10       = **81k**       | 20+25+35+6+5 = **91k**          | 81k     |
|  17   | 43+17+6+5          = **71k**       | 20+25+35+6+5+0 = **91k**        | 71k     |
|  18   | 43+17+6            = **66k**       | 20+25+35+6+5+0+10 = **101k**    | 66k     |
|  19   | 43+17              = **60k**       | 20+25+35+6+5+0+10+12 = **113k** | 60k     |
|  20   | 43                 = **43k**       | 113k                            | 43k     |

### Result: Natural clearing price = 15 (highest volume = 86k)

Notice something special at price 15:
- Demand = 86k
- Supply = 86k
- **Perfectly balanced. Every existing bid and ask gets fully filled.**

This is the critical problem for you: there is **zero slack** in the supply for you to get any fills.

---

## Part 12: Why You Get 0 Fills at Clearing Price 15

At clearing 15, demand = supply = 86k exactly.

Queue (price priority, time priority — you are last):

| Bid Level    | Volume | Cumulative | Notes              |
|--------------|--------|------------|--------------------|
| @ 20         | 43,000 | 43,000     | Fully filled       |
| @ 19         | 17,000 | 60,000     | Fully filled       |
| @ 18         |  6,000 | 66,000     | Fully filled       |
| @ 17         |  5,000 | 71,000     | Fully filled       |
| @ 16         | 10,000 | 81,000     | Fully filled       |
| @ 15         |  5,000 | 86,000     | Fully filled       |
| **You @ 15** | any    | **0 left** | **Supply gone. 0 fills.** |

Even if you bid at any price ≥ 15, you join a queue that is already perfectly saturated.
You need to **shift the clearing price** to a level where supply exceeds existing demand.

---

## Part 13: Finding a Price Where You Have Slack

The key metric: **slack = supply − existing demand** at each price level.

| Price | Existing demand | Supply  | Slack (Supply − Demand) | Profit/unit |
|-------|-----------------|---------|--------------------------|-------------|
|  15   | 86k             | 86k     | **0** — no room         | 4.90        |
|  16   | 81k             | 91k     | **+10k**                | 3.90        |
|  17   | 71k             | 91k     | **+20k**                | 2.90        |
|  18   | 66k             | 101k    | **+35k**                | 1.90        |
|  19   | 60k             | 113k    | **+53k**                | 0.90        |
|  20   | 43k             | 113k    | —                        | −0.10 LOSS  |

The slack tells you the **maximum units you can fill** at each price (you're last in queue, so you only get what existing demand doesn't consume).

---

## Part 14: Profit at Each Candidate Price

**Max profit = slack × profit per unit**

| Your bid price | Slack (max fills) | Profit/unit | Max total profit |
|----------------|-------------------|-------------|-----------------|
| 15             | 0                 | 4.90        | **0**           |
| 16             | 10,000            | 3.90        | 39,000          |
| 17             | 20,000            | 2.90        | 58,000          |
| **18**         | **35,000**        | **1.90**    | **66,500** ← MAX |
| 19             | 53,000            | 0.90        | 47,700          |
| 20+            | —                 | ≤ 0         | loss            |

**Price 18 maximises the product of fills × profit-per-unit.**

Going lower (e.g. 17): higher profit per unit but fewer fills — net is worse.
Going higher (e.g. 19): more fills but lower profit per unit — net is worse.

---

## Part 15: Making the Clearing Price Shift to 18

Without you, clearing = 15 (volume 86k). You need clearing to be 18.

For clearing to shift to 18, the volume at price 18 (with your bid) must **exceed** 86k.

**At price 18 with your bid of X units:**
- Demand at ≥18 = 66k (existing) + X
- Supply at ≤18 = 101k
- Volume = min(66k + X, 101k)

For volume at 18 > 86k:
- Need: 66k + X > 86k → **X > 20k**

For volume at 18 to reach its absolute max (101k):
- Need: 66k + X ≥ 101k → **X ≥ 35k**

**If you bid 35k at price 18:**

| Price | Demand (with you) | Supply | Volume  |
|-------|-------------------|--------|---------|
|  15   | 86k + 35k = 121k  | 86k    | 86k     |
|  16   | 81k + 35k = 116k  | 91k    | 91k     |
|  17   | 71k + 35k = 106k  | 91k    | 91k     |
|  **18** | **66k + 35k = 101k** | **101k** | **101k ← MAX** |
|  19   | 60k + 0   = 60k   | 113k   | 60k     |

*(Note: at price 19, your bid of 18 doesn't count since 18 < 19)*

101k at price 18 beats all others → **clearing = 18** ✓

---

## Part 16: Who Gets Filled at Clearing Price 18?

Supply at ≤18 = 101k. Demand at ≥18 = 66k + 35k (you) = 101k. **Perfectly balanced again.**

| Bid Level    | Volume   | Cumulative | Notes          |
|--------------|----------|------------|----------------|
| @ 20         | 43,000   | 43,000     | Fully filled   |
| @ 19         | 17,000   | 60,000     | Fully filled   |
| @ 18 existing|  6,000   | 66,000     | Fully filled   |
| **You @ 18** | **35,000** | **101,000** | **Fully filled ✓** |

Your fills: **35,000 units at clearing price 18**
Net buyback: **19.90 per unit**
**Profit = (19.90 − 18) × 35,000 = 1.90 × 35,000 = 66,500 XIRECs**

---

## Part 17: Why Can't You Do Better?

### Why not bid at 17 instead of 18?
At price 17: max fills = 20k (slack), profit/unit = 2.90
→ Total = 20k × 2.90 = **58,000** — worse than 66,500.

### Why not bid at 19?
At price 19: max fills = 53k, profit/unit = 0.90
→ Total = 53k × 0.90 = **47,700** — worse.

### Why not bid more than 35k at price 18?
Say you bid 50k at 18:
- Demand at ≥18 = 66k + 50k = 116k
- Supply = 101k → supply is now binding (101k < 116k)
- Queue: bid@20(43k) → bid@19(17k) → bid@18_existing(6k) → **you(50k)**
  - 43k + 17k + 6k = 66k used, 35k remaining for you
  - You still get **35k fills** — same as before
- More quantity doesn't help past the 35k slack cap

---

## Part 18: The Key Risk — The 10k Ask at Price 18

Our 35k fills come from the supply at ≤18 = 101k minus existing demand = 66k.
That 101k total supply includes **10k asks at price 18**.

If that 10k ask doesn't actually exist (stale book risk):
- Supply at ≤18 = 91k
- Slack = 91k − 66k = 25k
- Your fills = 25k
- Profit = 25k × 1.90 = **47,500**

At that point, bidding at 17 (fills = 20k, profit = 58,000) would have been better.

**Crossover: if ask@18 drops below ~5,500 units, bid@17 wins.**
The book shows 10,000. That's ~2× the crossover threshold — we have meaningful margin.

---

## Part 19: Final Summary — All Options for Ember Mushroom

| Your bid | Clearing | Your fills | Profit/unit | Total profit |
|----------|----------|------------|-------------|--------------|
| 15       | 15       | 0          | 4.90        | **0**        |
| 16       | 16       | 10,000     | 3.90        | 39,000       |
| 17       | 17       | 20,000     | 2.90        | 58,000       |
| **18**   | **18**   | **35,000** | **1.90**    | **66,500** ✓ |
| 19       | 19       | 53,000     | 0.90        | 47,700       |
| 20+      | —        | —          | ≤ 0         | loss         |

**Optimal: bid price = 18, quantity ≥ 35,000**

---

## Part 20: Combined Final Answer

| Product          | Bid Price | Bid Qty | Clearing | Your Fills | Profit        |
|------------------|-----------|---------|----------|------------|---------------|
| `DRYLAND_FLAX`   | **29**    | 6,000   | 29       | 5,000      | **5,000**     |
| `EMBER_MUSHROOM` | **18**    | 36,000  | 18       | 35,000     | **66,500**    |
| **TOTAL**        |           |         |          |            | **71,500 XIRECs** |
