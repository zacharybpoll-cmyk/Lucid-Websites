# Lucid User Referral Program

## Overview
Every active Lucid user becomes a distribution channel. Well-designed wellness app referral programs achieve 23-31% participation among active users, generating 17-24% of new customer acquisition.

---

## Program Structure

### For the Referrer (Existing User)
| Benefit | Details |
|---------|---------|
| Reward | 1 free month of Lucid for each successful referral |
| Cap | Up to 12 free months per year (1 referral = 1 month) |
| Stacking | Multiple referrals stack (3 referrals = 3 free months) |
| When earned | When referred friend completes their trial and pays for first month |

### For the Referred Friend
| Benefit | Details |
|---------|---------|
| Extended trial | 2 extra weeks free (on top of standard trial) |
| Discount | 20% off first paid month |
| Referral link | `lucidvoice.com/invite/[USER_CODE]` |

---

## Sharing Mechanics

### In-App Sharing
- **Share button** in Settings/Profile screen
- Generates unique referral link: `lucidvoice.com/invite/[6-char-code]`
- One-tap share to: Messages, WhatsApp, Email, Copy Link
- Shows referral stats: invites sent, friends joined, free months earned

### Share Triggers (When to Prompt)
Prompt sharing at high-engagement moments (not randomly):
1. After viewing a positive trend ("Your voice resilience improved 15% this month — share Lucid with a friend?")
2. After completing 7-day streak ("You've tracked for a full week! Know someone who'd benefit?")
3. After a milestone ("You've been using Lucid for 30 days — invite a friend, get a free month")
4. Never more than 1 share prompt per week
5. Never prompt during negative health insights

### Share Message Templates (User-Editable)
Default message (user can customize before sending):

> "I've been using Lucid to track my vocal health — it's like a fitness tracker for your voice. You get extra free trial time with my link: [LINK]"

---

## Technical Implementation Requirements

### Backend
- Referral code generation (6-char alphanumeric, unique per user)
- Referral tracking table: referrer_id, referred_id, code_used, signup_date, converted_date, reward_granted
- Automatic reward application when referred user converts to paid
- Monthly cap enforcement (12 free months/year)

### Frontend
- Share screen in Settings
- Referral stats dashboard (simple: invites, conversions, months earned)
- Share sheet integration (iOS/macOS native share)
- Smart share prompts at trigger moments

### Analytics
- Track: referral link clicks, signups from referrals, conversion rate, viral coefficient
- Viral coefficient target: >0.3 (each user brings 0.3 new users on average)

---

## Launch Plan

### Phase 1: MVP (Month 2)
- Basic referral link generation
- Manual reward application (founder applies free months)
- Simple share button in Settings
- Track clicks and signups

### Phase 2: Automated (Month 3-4)
- Automatic reward application via Stripe
- In-app referral dashboard
- Smart share prompts at trigger moments
- A/B test share message templates

### Phase 3: Optimize (Month 5+)
- Test different reward amounts (1 month vs 2 weeks vs % discount)
- Add leaderboard for top referrers (optional — test if it motivates)
- Consider two-sided rewards (referrer gets free month AND referred friend gets extended discount)

---

## Success Metrics

| Metric | Target | Industry Benchmark |
|--------|--------|--------------------|
| Referral participation rate | >20% | 23-31% (wellness apps) |
| Referral conversion rate | >25% | 20-35% (referred leads convert higher) |
| % of new users from referrals | >15% | 17-24% (mature programs) |
| Viral coefficient | >0.3 | 0.2-0.5 (non-viral apps) |
| Cost per referred acquisition | < $5 | Essentially the cost of the free month |

---

## Key Principles

1. **Reward the behavior, not the ask.** Give rewards when referrals actually convert, not just sign up.
2. **Make sharing feel natural.** Prompt at positive moments, never during vulnerability.
3. **Keep it dead simple.** One link, one reward, no confusing tiers.
4. **The friend's experience matters more.** If the referred friend has a bad onboarding, the referrer looks bad. Prioritize referred user experience.
5. **Don't be Dropbox.** Referral programs work for retention, not as the primary growth engine. This supplements influencer + content, not replaces them.
