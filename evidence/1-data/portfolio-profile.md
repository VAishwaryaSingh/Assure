# Data profile — the synthetic loan book

Generated directly from [`data/loan_portfolio.parquet`](../../data/loan_portfolio.parquet), [`ecl_results.parquet`](../../data/ecl_results.parquet) and [`ecl_scenarios.parquet`](../../data/ecl_scenarios.parquet). **All data is synthetic** — produced by [`generate_portfolio.py`](../../data/generate_portfolio.py) with a fixed random seed (`42`); nothing here is a real bank, borrower or portfolio. Reporting date: **31 Dec 2025**.

First 25 loans, as a CSV you can open: [`portfolio-sample.csv`](./portfolio-sample.csv).

## The portfolio

| | |
|---|---|
| Loans | **1,500** |
| Original principal | £91,372,800 |
| Current balance (after amortisation) | **£65,646,733** |
| Amortisation type | bullet 216 · reducing_balance 1284 |
| Collateral | commercial 310 · other 149 · residential 513 · unsecured 528 |
| Loan status | default 29 · performing 1431 · watch 40 |
| Risk grade | A 149 · AA 94 · AAA 36 · B 250 · BB 308 · BBB 250 · C 53 · CC 119 · CCC 202 · D 39 |

## What the model produced from it

IFRS 9-style staging and expected credit loss (base case), by stage:

| Stage | Loans | Balance | ECL | Coverage |
|---|---|---|---|---|
| 1 | 1,431 | £62,888,171 | £1,219,756 | 1.94% |
| 2 | 40 | £1,107,545 | £113,515 | 10.25% |
| 3 | 29 | £1,651,017 | £708,388 | 42.91% |
| **Total** | **1,500** | **£65,646,733** | **£2,041,659** | **3.11%** |

Macro scenarios (total ECL across all 1,500 loans):

| Scenario | Weight | ECL |
|---|---|---|
| Base | 60% | £2,041,659 |
| Adverse | 30% | £2,690,319 |
| Severe | 10% | £3,995,847 |
| **Probability-weighted** | | **£2,431,676** |

PD and LGD are authored, disclosed assumptions — not calibrated to any real bank's data. Details: [`docs/methodology.md`](../../docs/methodology.md).
