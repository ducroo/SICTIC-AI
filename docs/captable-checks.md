# What the CLA checks look at, and why (plain-language guide)

A non-lawyer's guide to everything the cap-table skills check about a
startup's Convertible Loan Agreements (CLAs) and about the cap table itself
— the ownership table, the share register and the option pools. [captable.md](captable.md)
describes the pipeline; [captable-design.md](captable-design.md) records the
design rationale and legal sources. This page explains, term by term, what
each thing *is*, what a contract typically says, and what we want to learn
from it.

**The frame.** A convertible loan is money lent to a startup that is not
meant to be repaid in cash but *converted* into shares when a defined event
happens. Investors put money in *before* anyone has to value the company;
the valuation is deferred to the next financing round, and in exchange the
lenders get a discount and/or a valuation ceiling. Almost every item below
serves one of three questions: *How much does the startup owe? When and at
what price does that debt become ownership? And what can go wrong on the
way?*

## Part 1 — What we extract from each agreement

These are the terms in the team-editable checklist
`config/captable/cla_terms.md`. Every extracted value carries a verbatim
quote that is verified against the document; absent terms are recorded with
the sections that were searched.

### Parties and lifecycle

**Lenders.** The people or entities providing the money. Swiss CLAs come in
two shapes: one agreement per lender (ten near-identical PDFs in a data
room) or one pooled agreement listing every investor, often with an annex
table of who lends how much. We record each lender with their kind
(individual, entity, syndicate, nominee), domicile, and own amount. This is
what lets us count lenders across all agreements (the tax rule in Part 2),
recognize name variants (the same person with and without a middle name),
and notice when a single line is really a syndicate with an unknown number
of members behind it.

**Borrower.** The startup, as named in the party block. Trivial-looking, but
it is the safeguard that an agreement belongs to this data room and is not a
template or a subsidiary's contract.

**Status and its evidence.** A document that looks like a CLA can be one of
four things: a signed, open loan; a term sheet or draft (a negotiation state,
not binding); a loan that has already converted (the money became shares
long ago); or a repaid one. Only the first is outstanding debt. We require
a one-sentence justification for the chosen status, because a two-year-old
CLA in a current data room has more likely converted than not, and that
confusion would misstate the debt load entirely.

**Execution date and signature completeness.** When the agreement was
signed, and whether *every* party signed. Interest accrues from the
execution date, and an agreement missing a signature is legally an offer,
not a contract — we demote it to a term sheet. With scanned signature pages
the model often cannot tell; it must say so rather than guess.

### Principal

**Amount and currency.** The sum actually lent under this agreement (not a
round's "up to" maximum), and its currency, because Swiss startups do carry
USD or EUR loans beside CHF ones. We never add across currencies: without a
user-supplied exchange rate, the analysis refuses to compute rather than
silently produce a wrong total.

### Interest

**Interest mode.** Three patterns exist: interest-free (lenders are
compensated only through discount and cap), a fixed rate, or the Swiss
specialty "the lower of X % and the safe-harbor rate". The **safe-harbor
rate** is an interest rate the Federal Tax Administration publishes every
year; up to that rate, interest paid to shareholders is accepted as
commercially justified without question. Interest above it on shareholder
loans counts as a hidden profit distribution with tax consequences, which is
why many agreements tie the rate to it.

**Stated rate and the safe-harbor figure.** In the safe-harbor mode the
percentage in the contract is only a *ceiling*; the effective rate is the
(usually much lower) safe-harbor rate, which contracts often mention in
passing ("currently 1.75 %"). Accruing at the ceiling overstates the debt —
on a five-million loan by several hundred thousand francs. We extract both
figures and accrue at the lower one.

**Day-count convention.** How interest days are counted: act/360 (actual
days divided by 360, which yields slightly more interest), act/365, act/act,
or 30/360 (every month counts thirty days). Over a year the difference is
small; over three years on millions it is real. If the contract is silent we
assume act/365 and say so.

**Compounding.** Whether accrued interest is itself charged interest. The
SECA standard uses simple interest; some agreements capitalize annually. On
older loans this changes the balance noticeably. If unstated we assume
simple interest and disclose it — in the agreements we have seen, this
omission was the most common entry in the list of unregulated points.

### Maturity and conversion triggers

**Maturity date.** The date by which the loan must be repaid or converted if
no financing round has happened. Twelve to thirty-six months is typical. A
loan whose maturity has passed with neither a conversion nor an extension in
the data room is the sharpest question of all: either documents are missing,
or the startup is sitting on a due debt. No maturity date at all is an
investor warning sign — the loan can run forever.

**Conversion at a qualified financing round (QEFR), with its minimums.** The
normal conversion path: once the startup closes a "qualified" round —
defined by a minimum size, say CHF 12 million — the loan automatically
becomes shares at that round's price less the discount. Many definitions
carry a second condition: part of the money must come from *new* investors
("of which at least CHF 8 million from new investors"). Without it, the
existing lenders could stage the round among themselves and force conversion
on their own terms. "Mandatory or voluntary" records whether conversion
happens automatically or at the lender's option.

**Conversion at a change of control (CoC), and a repayment multiple.** What
happens if the startup is sold before a round. Either the loan converts so
the lender shares in the sale proceeds — or the agreement lets the lender
demand repayment of a multiple instead (e.g. "2.5× the principal"). The
latter is a potentially large cash outflow that buyers and founders must
price into any sale.

**Conversion at maturity, and its fixed price.** If no round came by
maturity, the loan may or must convert anyway — at a price that *cannot* be
derived from a round, because there is none. Agreements solve this with a
fixed price per share. This is treacherous: the "Conversion Price"
definition often has several lettered paragraphs, one per trigger, and the
fixed price hides in paragraph (c) or an annex. Miss it and the expired loan
is priced with the wrong mechanism. Multiplied by the share count, the fixed
price also reveals the valuation the startup itself works with.

### Pricing

**Valuation cap.** A ceiling on the valuation at which conversion happens.
Example: cap CHF 8 million; if the round comes at a CHF 20 million
valuation, the lender still converts as if the company were worth 8 million
— many more shares per franc than the new investors get. That is the reward
for early risk; for founders a low cap means heavy dilution.

**Discount and its schedule.** Instead of or in addition to a cap: a rebate
on the round price, typically 15–25 %. The lender pays, say, 80 % of what
new investors pay. Some agreements step the discount over time ("15 % in
the first four months, 25 % after") to push founders towards a quick round.
When both cap and discount apply, the lender gets whichever price is better
for them. A discount above one third becomes delicate under Swiss tax
practice: such a loan is reportedly no longer treated as a "classic"
convertible, with income-tax consequences for the investor — the exact
threshold must be confirmed by tax counsel, which is why it lives in
configuration, not code.

**Valuation floor.** The counterpart of the cap: a minimum valuation below
which conversion does not go. It protects founders in a down round, is rare
in seed loans, and appears mainly in bridge loans between rounds.

**Denominator basis.** To turn a cap (a company valuation) into a price per
share you divide by a share count — but which one? Only the issued shares,
or the "fully diluted" count including every option and pool? The fully
diluted number is larger, gives a lower price, and therefore more shares to
the lender. Agreements state this explicitly and it is negotiated; we never
silently assume either.

### Protections and mechanics

**Subordination and its scope.** In Switzerland the board must notify the
court when liabilities exceed assets (over-indebtedness, art. 725b CO) — for
a loss-making startup with a convertible loan on the balance sheet that
point comes fast. The way out: the lender subordinates the loan, so it is
left out of the over-indebtedness calculation. Missing subordination is a
warning sign. And it must cover the whole amount: if only the principal is
subordinated but not the accrued interest, the company remains
arithmetically over-indebted — a serious structural defect, and we rate it
as one.

**Most-favoured-nation clause (MFN).** A clause that automatically gives this
lender the better terms of any later loan. If a later investor gets 30 %
discount instead of 20 %, the earlier one follows. It can make a later round
unexpectedly expensive and must be known before negotiating.

**Pro-rata rights.** The right to invest additionally in the next round,
beyond the conversion, to keep one's stake. For the startup it means part of
the round is reserved and unavailable to new investors.

**Capital source for the conversion shares.** For a loan to become shares,
new shares must be created — and in Switzerland that takes a shareholder
resolution. Agreements secure it one of three ways: consent declarations
from existing shareholders (the SECA default, its Annex 2), conditional
capital already resolved, or a capital band (possible since 2023: the board
may raise capital within a pre-approved range on its own). Without any of
these, conversion can be blocked at the decisive moment.

**Reference to shareholder consents.** Does the agreement name the consent
declarations concretely (annexed or to be obtained)? Missing consents are an
execution risk — a shareholder can block the required capital increase.

**Accession to the shareholders' agreement (SHA).** Must the lender join the
shareholders' agreement before converting? It is customary and sensible: it
puts them under the same rules as every other shareholder (pre-emption,
drag-along and so on). Without it, conversion creates a shareholder outside
the contractual framework.

**Governing law and forum.** Swiss law with a Swiss forum is the norm;
anything else is at least a question, because the Swiss rules above
(subordination, tax) may then work differently.

### Evidence

**Missing terms with search evidence.** The most important methodological
point. Studies of AI contract extraction show that the commonest failure is
not a misread value but the claim "this clause does not exist" made without
really looking. We therefore accept an absence only with a statement of
which sections were searched — and every found value must carry a verbatim
quote that we locate mechanically in the document. Where the quote does not
match, the extraction is rejected and redone.

## Part 2 — What we assess per agreement, and check across all agreements

The per-agreement assessments are plain arithmetic over the extracted values
(no model involved); the thresholds live in
`config/captable/assessment_rules.json` and can be tuned by the team. Each
yields *market standard*, *deviating* or *absent*, plus a severity from
info to severe.

- **Discount:** 5–30 % counts as customary; above that "deviating"; above
  33.33 % additionally the tax risk (high).
- **Interest rate:** above the 8 % safe-harbor reference = a note, because
  the tax consequences above then loom.
- **QEFR trigger:** absent entirely → unclear how the loan ever becomes
  shares (high); no minimum size → the loan could convert in a tiny round
  (medium); no new-money component → the check whether insiders alone could
  trigger conversion.
- **Change of control:** absent = note; with a repayment multiple = note on
  the possible outflow.
- **Maturity and cap together:** both missing means neither an end date nor
  a valuation limit — unlimited dilution with no time limit (high).
- **Denominator basis unstated:** medium, because the price per share is
  then up for negotiation.
- **Subordination:** absent = high; principal only = severe.
- **Capital source:** no enforceable path = high.
- **MFN, pro-rata, SHA accession:** information findings so they are not
  forgotten when preparing a negotiation.

The cross-agreement checks need all agreements together — the part a human
reading individual PDFs practically cannot do:

- **The 10/20 rule.** A Swiss tax rule: whoever borrows from more than 10
  lenders on identical terms, or from more than 20 on varying terms, no
  longer has loans for tax purposes but a bond issue — and must withhold
  35 % tax on the interest. We group every agreement by identical terms
  (rate, discount, cap, maturity, currency, each normalized) and count
  lenders per group, the same person counting once. A syndicate's members
  count too; since we do not know them, we say explicitly "composition
  undisclosed — verify" rather than a false "within limits".
- **Outstanding principal.** The sum of signed, open loans only, per
  currency. Term sheets and converted loans do not count.
- **Term sheets versus agreements.** If a lender has both a term sheet and a
  signed agreement, the term sheet counts as superseded. If the amounts
  differ, that becomes a question — perhaps they invested less than
  planned.
- **Expired maturities.** If maturity plus the customary 30-day conversion
  window has passed and no conversion, extension or repayment document
  exists, the question follows: is there a conversion demand from the
  lender majority? Is the balance sitting on the balance sheet as a
  subordinated debt?
- **Signature evidence.** For PDFs we search the raw file for traces of
  electronic signatures (e-signature envelope identifiers) that survive even
  when a PDF was later flattened. That corroborates "is signed" beyond the
  extracted signature block. Non-PDF sources are marked not applicable,
  never as failures.
- **Lender already a shareholder.** If a lender of a supposedly open loan
  appears in the share register, the loan may already have converted — a
  neutral note, not an accusation, since they may have been a shareholder
  before.

## Part 3 — What we check about the cap table, the register and the pools

The cap table is the second half of the picture: the CLAs say what debt is
waiting to become shares; the cap table says who owns what today. Both have
to be right for any dilution scenario to mean anything.

### Finding the right documents first

**Classification.** Before extracting anything, every parsed document in
the data room is classified (current cap table, forecast or scenario model,
share register, executed CLA, term sheet, articles of association, ESOP or
PSOP plan, tax ruling, and so on). This stage is mandatory because real
data rooms contain spreadsheets like "Forecast Cap Table Series A" or
"Dilution Calculator" that look exactly like cap tables but describe an
imagined future. Extracting one of those as *the* cap table produces
confident nonsense. Several dated versions of the real cap table are kept
apart as separate states, not merged.

### What we extract

**Holders.** Every row of the cap table: people, entities, the company's
own treasury shares, and pools. For each we record the group the table puts
them in (founders, VC investors, employees, advisors, former employees…),
the legal kind (individual, entity, treasury, pool, authorized capital),
the functional role (founder, investor, employee, advisor, departed), the
holdings per share class, the fully diluted count and the amount invested.
The group and role are taken from the table's own structure, not invented —
that is what makes the later red-flag rubric trustworthy.

**Share classes.** Common and preferred classes with nominal value and
votes per share. The nominal value matters for a legal check below; the
classes matter because CLAs convert into a specific class.

**Pools.** ESOP and PSOP pools (employee option and phantom-share plans),
grantable reserves and authorized capital: total size, granted, and
unallocated. Pools dilute economically without being shareholders, so
they are tracked separately and labelled as reserved positions in every
ownership view.

**Totals and the "fully diluted" definition.** The table's own totals per
class and its fully diluted total — and, crucially, *which* definition of
"fully diluted" the source uses: all pools counted in full, or only granted
options, or granted options plus vested phantom shares. Cap tables rarely
say, and the difference changes the price per share in any valuation
negotiation. If the source does not state it, the rubric flags it. A
subtle rule here: the model may not "prove" the definition by quoting the
totals row — it must find an actual statement, or report it as unstated.

**Row completeness.** An extraction whose holder rows do not add up to the
table's own class totals (within half a percent) is rejected and redone.
This catches the classic failure of a model silently dropping rows from a
long table.

**The share register.** The legal source of truth for who owns issued
shares. We extract the *current* holdings, anchored on the participation
column, so that transfers recorded in the register are not double counted
as new positions.

**Pool overview documents.** Separate ESOP or PSOP overviews with their own
figures per pool, kept per document so they can be compared with the cap
table.

### What we validate — in code, never in a prompt

Every check yields pass, warning or fail with a severity, and a violation
becomes a structured finding, never a silent correction.

**Issued totals per class.** The holder rows of each share class must sum
to the class total the table states. A mismatch means a row was misread,
dropped, or the table itself is inconsistent.

**The diluted equation.** Fully diluted shares must equal issued shares
minus treasury shares plus the option and pool positions. This is the
arithmetic identity every cap table should satisfy; if it does not, either
treasury shares were counted as ownership or a pool was counted twice.

**The diluted row sum.** Independently of the equation, the holders' own
fully diluted counts must add up to the stated fully diluted total. The
equation can pass while this fails — it did, when a pool appeared once as
a group and once as its single member and was extracted twice.

**Register reconciliation.** Every holding in the share register is
compared with the cap-table version *nearest to the register's own date*.
Comparing a March register with a June cap table would report every
legitimate transfer in between as an error — so cross-dated comparisons are
downgraded to warnings and say what the date gap is. Name variants (middle
names, legal-form suffixes) are matched, and the coverage (how many
holdings could be compared) is reported.

**Pool consistency.** The cap table's pool figures are compared with the
pool overview documents, paired by pool identity. Within the family of
employee pools a single pool may be compared across kinds (a table calling
it "grantable" and an overview calling it "ESOP"); one-sided coverage is
tolerated; a date gap is disclosed. A genuine disagreement — the cap table
saying one pool size and the ESOP overview another — stays a failure,
because it is exactly what a diligence question is for.

**Nominal-value floor.** Swiss law forbids issuing shares below their
nominal value (art. 624 CO). If a CLA's cap or discount implies a
conversion price below the nominal value of the class, that conversion is
legally impossible without a share split or a nominal reduction first. The
check derives the implied price and flags it — a finding, never a silent
clamp.

**Loan lifecycle against the cap table.** Whether a lender of an "executed"
loan already appears as a shareholder — the neutral question whether the
loan has in fact converted (see Part 2).

**Cross-snapshot consistency.** Each build is compared with the previous
dated state of the same company: a share class shrinking or disappearing,
or a holder's absolute count dropping without a documented transfer,
becomes a warning ("shrinking holder"). Total shares should only grow
unless a split or cancellation is evidenced. This gives event-style
validation without recording every transaction — a founder quietly losing
shares between two versions is precisely the kind of thing to ask about.

### How results are stored

Every evidenced state of the cap table is kept as its own dated snapshot,
forever; the "latest" pointer is never overwritten by a rebuild of an older
state; and every intermediate work product carries a freshness stamp (the
documents, the configuration including the term checklist, the model) so
that a changed document or an edited checklist re-runs the affected stage
automatically instead of silently reusing stale output.

## Part 4 — What the analysis computes (pure Python, no model)

**Accrued balance.** Principal plus interest to the analysis date, under the
interest mode, the safe-harbor ceiling, the day-count convention and the
compounding. The analysis date and the date the cap table describes are
always both stated, because they are rarely the same.

**Conversion scenarios.** We play through a hypothetical round (valuation
and size derived from the agreement or set by the user) and compute who owns
how much afterwards. The catch is best shown with numbers — the figures
below come from the model itself (`lib/captable/model.py`), not from a hand
calculation.

*The setup.* A startup has 1,000,000 shares: founders 700,000 (70 %), a
seed investor 300,000 (30 %). A convertible loan has an accrued balance of
CHF 500,000 with a 20 % discount and no cap. Now the round comes:
pre-money valuation CHF 8 million, new investors put in CHF 2 million.

*The naive expectation.* New investors reckon 2 of 10 million post-money
= 20 %. The loan converts too, at a discount — so it gets *more* shares
per franc than the new investors. Those bonus shares must dilute somebody.
And here is the problem: **the agreement almost never says whom.** The
market has three established answers, each a legitimate reading of the
same contract:

| Method | Price/share | Loan converts at | Founders | Seed | Loan | New investors |
|---|---|---|---|---|---|---|
| Pre-money | 8.00 | 6.40 | **52.7 %** | 22.6 % | 5.9 % | 18.8 % |
| Percentage-ownership | 7.375 | 5.90 | **51.6 %** | 22.1 % | 6.2 % | **20.0 %** |
| Dollars-invested | 8.50 | 6.80 | **53.5 %** | 22.9 % | 5.6 % | 18.0 % |

1. **Pre-money method.** The price is simply valuation divided by today's
   shares: 8 million / 1 million = CHF 8.00. New investors get 250,000
   shares for their money; the loan, at the discounted 6.40, about 78,000.
   Everyone together now holds more shares than planned — and the new
   investors land at 18.8 % instead of 20 %. **The loan shares dilute
   everyone, including the new investors.** Founder-friendly.
2. **Percentage-ownership method** (also called the post-money method).
   The new investors say: "we negotiated 20 %, we get 20 % — whatever else
   converts." For that to hold, the price per share must drop, here to
   7.375, and the loan converts even more cheaply. **The entire dilution
   from the loan is borne by the existing holders**, founders and seed
   investor alike. Investor-friendly. This method is mathematically
   *circular*: the price depends on the total share count after the round,
   which depends on the loan shares, which depend on the price. The model
   solves it with a fixed-point iteration — what Excel would do with
   "iterative calculation" switched on.
3. **Dollars-invested method.** The loan's CHF 500,000 is treated as round
   money the company already received and that is part of the pre-money
   value. Effect: the price per share *rises* to 8.50, because
   (8 million + 0.5 million) is divided by the same million shares. **The
   new investors bear the dilution from the loan money itself; the founders
   bear only the discount bonus.** The best variant for founders.

*What follows.* In this small example the founders' stake ranges from
51.6 % to 53.5 % depending on the method — almost two percentage points.
When the loan is large relative to the round, as it often is in practice,
the spread widens considerably; the Swiss Angel Investor Handbook's worked
example comes to 55 % versus 64 %. That is exactly the magnitude on which
a founder majority hinges. Therefore:

- **We never pick a method silently.** All three are shown side by side;
  the spread *is* the finding. For a negotiation it means: the method
  belongs in the term sheet, or investors and founders will argue over two
  percentage points at closing.
- **What enters the arithmetic:** the *accrued* balance (with interest and
  the safe-harbor cap), not the nominal amount; with both a cap and a
  discount, whichever price is better for the lender; a floor where one
  exists; and a warning if the conversion price would fall below the
  nominal value (then the conversion is legally impossible).
- **The round parameters** — valuation and size — the model takes from the
  agreement (largest cap as pre-money, the QEFR minimum as round size) and
  states explicitly that these are assumptions, not predictions. With
  `--pre-money` and `--investment` you set your own, for instance the
  company's own valuation anchor from the fixed maturity price.
- **The output per scenario:** price per share, conversion price per loan,
  ownership of every holder (pools marked as reserved positions), the
  founders' post-round stake — and a flag if the founders fall below 50 %
  under *all three* methods.

These scenarios describe conversion *in a round*. If maturity has passed
and the agreement fixes a price, a different mechanism applies — the
separate fixed-maturity-price block below.

**Conversion at the fixed maturity price.** For expired loans: balance
divided by the fixed price gives the shares; fixed price times today's share
count gives the implied company value — the valuation anchor the company
itself works with.

**Issuance stamp duty.** The Confederation levies 1 % on equity paid in
beyond a one-time CHF 1 million exemption. Conversions count as
contributions; together with the round, startups often cross the line
exactly then. We compute the duty and show how much of the exemption is
left.

**Red-flag rubric** (from the Swiss Angel Investor Handbook): founders below
50 % before Series A ("costly mistakes were made"), investors holding more
than twice the founders, "dead equity" (departed founders or employees above
10 %), and a cap table that does not say which definition of "fully diluted"
it uses — something to settle before any valuation negotiation.
