# LLC + bank account + business essentials

**Bottom line:** If you plan to accept money from anyone other than yourself, form the LLC before the first customer. The privacy claims make personal-name operation a real liability risk.

## Why LLC and not just "Josh Fausset, sole proprietor"

The risk you're shielding against: a customer sues over a data incident — alleged breach, misuse of their content, downtime that cost them money. Without an entity, your personal assets (house, savings) are on the table. With an LLC, the company's assets are on the table; personal assets are shielded (with caveats — see "piercing the veil" below).

Also:
- Enterprise customers won't sign contracts with an individual
- Stripe Atlas etc. require an entity to onboard
- Banking + accounting + taxes cleanly separated
- Future co-founder / contractor / investor on-ramps are dramatically easier

## Three paths to LLC, ranked

### 1. Stripe Atlas — Recommended for speed ($500 all-in)

https://stripe.com/atlas

What you get:
- Delaware LLC (the de facto standard for tech)
- EIN (federal tax ID)
- Mercury bank account (or option for Brex)
- Stripe payment processing pre-configured
- Standard operating agreement
- $100 of AWS credits, perks from a few SaaS vendors
- One-year registered agent included

Timeline: ~1 week from sign-up to fully operational
Catch: Delaware franchise tax ($300/yr) + registered agent ($200/yr after year one)

### 2. Direct filing in your home state + DIY

Cost: $50-500 state filing fee + $50-150 for registered agent

What you do:
1. Pick a state. Home state is fine for most cases; Delaware only matters if you're raising VC money.
2. File articles of organization on the state's Secretary of State website
3. Get an EIN at irs.gov (free, 10 minutes)
4. Hire a registered agent (Northwest, ZenBusiness, ~$125/yr) or use your home address if you're OK with it being public
5. Open a Mercury bank account separately

Timeline: 1-2 weeks
Saves: ~$300 vs. Stripe Atlas
Costs you: a few hours of admin work and the assembly job for things Stripe bundles

### 3. Clerky (more lawyer-grade)

https://clerky.com — $300+ for LLC formation, more like $800 for the C-corp path if you ever convert to raise VC money. Used by YC startups.

When to pick: if you think you might raise VC in the next year. Otherwise overkill.

## My recommendation for versawiki specifically

**Stripe Atlas.** Reasons:

- You're a one-person company today and want speed > customization
- Stripe payment processing is going to be the billing stack anyway
- Mercury banking is excellent and the integration is one-click
- $500 once, then $500-700/yr ongoing (DE franchise tax + registered agent + state report fees)

If you want to save $300 and have an extra weekend afternoon, file in your home state directly and open Mercury yourself. Same protections, more paperwork.

## What "form the LLC" actually unlocks

- Sign customer contracts as "Versawiki, LLC"
- Open the bank account
- Open the Stripe account (Stripe requires an EIN for the merchant)
- Sign vendor contracts (Anthropic, OpenAI, Fly.io, Cloudflare — most are fine with individuals but the business names look more professional and accounting is cleaner)
- Issue 1099s if you hire contractors
- Sign an MSA / DPA with enterprise customers (almost always required)

## Pierce-the-veil risks (the LLC isn't magic protection)

The LLC shield can be set aside ("pierced") if a court finds you operated the company sloppily. To stay safe:

- Don't mix personal and business funds. Pay yourself a salary or distribution; don't pay personal bills from the business account.
- Sign contracts as "Josh Fausset, Member, Versawiki LLC" — not just "Josh Fausset"
- Keep separate books. QuickBooks Online or Xero, ~$30/mo
- File annual reports on time (state-specific; usually a few hundred dollars)
- Don't make personal guarantees on business debts unless you have to

## After the LLC: the 30-day startup checklist

| Day | Item |
|---|---|
| 0 | File LLC (Stripe Atlas or direct) |
| 1-3 | EIN issued |
| 3-7 | Mercury/Brex bank account opens |
| 7 | Set up QuickBooks/Xero |
| 7 | Sign up Stripe (or it's already done via Atlas) |
| 7 | Get a business credit card (Brex / Ramp / Mercury IO Mastercard) — building business credit |
| 7-14 | File your DBA / "Versawiki" trademark search (optional, $250-500 for trademark application) |
| 14 | Get a quote on Cyber Liability + E&O insurance (Vouch, Embroker) — don't buy yet, just have the policy ready |
| 14-30 | Decide on the company's domicile-of-record (the address customers see); Stripe Atlas gives you one free for the first year |
| 30 | Sign up for QuickBooks Live or hire a part-time bookkeeper ($200-500/mo) — DON'T do your own books past month one |

## Decisions you don't need to make yet

- C-corp vs LLC: stays LLC until you raise institutional money (then C-corp Delaware conversion costs ~$3k and takes a month)
- S-corp election: helpful tax-wise once you're profitable; talk to a CPA at that point
- Employees vs contractors: 1099 contractors are easier; W-2 employees require payroll provider (Gusto, ~$40/seat/mo)
- Equity grants: not relevant until co-founder or first hire
- Investor docs (SAFE, term sheet): not relevant until you're actually fundraising

## Cost summary (first year, Stripe Atlas path)

| Item | Cost |
|---|---|
| Stripe Atlas | $500 once |
| DE franchise tax | $300/yr |
| Mercury/Brex banking | $0 |
| QuickBooks | $30/mo = $360/yr |
| Cyber liability insurance (when bought) | $500-2000/yr |
| Apple Developer | $99/yr |
| Google Play | $25 once |
| Windows EV cert | $300-700/yr (when needed) |
| Cloudflare | $0 |
| **Total year-one ops** | **~$2000-3500** |

Cost of NOT doing it: personal liability if a single customer has a single bad day. Worth it.

---

## Florida addendum (2026-05-23 — Josh chose Florida)

Stripe Atlas defaults to Delaware and isn't the right pick for Florida. The cheapest, fastest Florida-native path:

### 1. File Articles of Organization at Sunbiz.org — $125, ~15 minutes

https://efile.sunbiz.org/llc_file.html

Fields you'll fill in:
- LLC name: `Versawiki LLC` (verify availability at https://search.sunbiz.org/Inquiry/CorporationSearch/ByName first)
- Principal address: your home or a business address
- Registered agent + agent address: either you (if you're OK with home address being public) or a service like Northwest Registered Agent ($125/yr; cheapest reliable option)
- Members: just you for now (single-member LLC)
- Manager-managed vs member-managed: pick **member-managed** for a one-person LLC
- Effective date: leave blank for "immediately upon filing"

Payment: $125 by credit card. Filing completes same day usually.

### 2. EIN from IRS — $0, ~10 minutes

https://www.irs.gov/businesses/small-businesses-self-employed/apply-for-an-employer-identification-number-ein-online

Has to be done by a "responsible party" (you, with your SSN). Form processes immediately for online filings; you get the EIN on the spot. Save the confirmation PDF.

### 3. Florida annual report — $138.75/yr, due May 1

https://efile.sunbiz.org/annual_report.html

Set a calendar reminder. Late fee is $400 if you miss it. The first one is due the year AFTER you formed (so if you file in 2026, your first annual report is due May 1, 2027).

### 4. Mercury bank account — $0, 1-3 days

https://mercury.com — link the Sunbiz filing PDF + EIN PDF + your ID. Fully digital, opens within a few business days. No minimum balance, no monthly fees.

Alternative: Brex (similar; more enterprise-y feel) or a local Florida bank if you want in-person access.

### 5. Operating Agreement

Florida doesn't require one to be filed with the state, but you should have one in the company records. Single-member templates are free at:
- https://www.legalzoom.com/forms/single-member-llc-operating-agreement (free version exists; ignore the upsells)
- Or copy-paste a vetted one from a startup-attorney blog

Sign it, store with the company records (Dropbox folder, password-protected).

### 6. (Optional but recommended) Florida sales tax registration

If you'll sell SaaS to Florida customers, you may owe Florida sales tax on digital subscriptions in some configurations. Register at https://floridarevenue.com/taxes/registration/ — free. Talk to a Florida CPA about whether SaaS is taxable in your specific shape (rules vary).

### Total cost Florida path (year 1)

| Item | Cost |
|---|---|
| Sunbiz filing | $125 |
| Registered agent | $125/yr (or $0 if you use your home address) |
| EIN | $0 |
| Florida annual report | $138.75/yr (starts year 2) |
| Mercury banking | $0 |
| QuickBooks | $30/mo = $360/yr |
| **Total year 1** | **~$610 (or $485 if you self-registered-agent)** |
| **vs. Stripe Atlas Delaware** | **~$1100 year 1** |

Florida-direct saves you ~$500/yr ongoing and you stay in your home state for tax purposes (simpler filings).
