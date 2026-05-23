# App store + desktop distribution prep

**Bottom line:** The mobile apps don't exist yet (M5 in the roadmap), but a few preparatory steps have long lead times and are worth doing NOW.

## Apple

### Sign up for Apple Developer Program now ($99/yr)

- https://developer.apple.com/programs/
- Approval takes 1-2 days typically; sometimes 2+ weeks
- Same account covers iOS, iPadOS, macOS, watchOS, tvOS
- You'll be asked for legal entity name — if you haven't formed the LLC yet, sign up as an individual now and convert to organization later (Apple supports the conversion, but it's another 1-2 week wait when you do it)

### As soon as it approves

- **App Store Connect → My Apps → +** → Reserve the name `versawiki` for iOS. Reserving doesn't commit you to ship.
- Same for the macOS app
- **Certificates, Identifiers & Profiles** → Create the App ID `com.versawiki.app` (or `ai.versawiki.app` if you prefer; the bundle ID never changes after first submission)
- Set up two-factor on the Apple ID
- Add Josh's tax / bank info under Agreements, Tax, and Banking (required before any paid app, even free apps need this filled in for analytics)

### macOS signing & notarization

- Already covered by the Apple Developer membership — no extra cost
- Tauri integrates Apple's `notarytool` directly
- You'll need a "Developer ID Application" certificate (different from App Store distribution cert) for direct-download distribution
- Notarization is REQUIRED on macOS 10.15+ — unsigned/unnotarized apps show a scary warning

### iOS / iPadOS App Store

- Build via Expo EAS Build (per the stack decision)
- Submission process: TestFlight first (closed beta to ~10k testers), then App Store review (typically 24-48 hours)
- First app review is often slower and pickier — budget 1-2 weeks for the initial back-and-forth
- App Store Review Guidelines: read https://developer.apple.com/app-store/review/guidelines/. The areas most likely to bite versawiki: account deletion (required, must be in-app), data collection disclosures (`App Privacy` section), encryption export compliance (set in app metadata)

## Google

### Sign up for Play Console ($25 one-time)

- https://play.google.com/console
- Same-day approval typically
- Tax + banking info also required

### As soon as it approves

- Create the app `com.versawiki.app` (or `ai.versawiki.app`) — same bundle ID as iOS for consistency
- Reserve the name
- Tax info, content rating questionnaire, data safety form, target audience (likely 18+ for B2B)
- Privacy policy URL required — needs to be live before submission. Have a placeholder at `https://versawiki.com/privacy` that says "coming soon" if you must; better to have a real one (see launch-readiness.md)

### Play Store submission

- Build via Expo EAS Build
- Internal testing → Closed testing → Open testing → Production
- Initial review usually faster than Apple (~24 hours)
- Required: closed test with at least 12 testers for 14 days BEFORE production submission for new developer accounts (this rule started in 2023; check current at time of submission)

## Windows desktop

### Code signing certificate

- **Not free, not optional in 2026** — Windows SmartScreen warns hard on unsigned binaries
- **Standard OV cert:** $200-400/yr (DigiCert, Sectigo, SSL.com). Takes 1-3 days to validate.
- **EV cert:** $300-700/yr. Immediate SmartScreen reputation. Recommended; the price difference is small for the trust delta.
- Requires you to be on a hardware security key (yubikey or similar) for EV certs — factor in $50 for the key
- Tauri's bundler integrates with signtool directly

### Distribution channels

- **Direct download from versawiki.com** — easiest; Tauri builds the installer; you host on Cloudflare R2; users download
- **Microsoft Store** — optional; $19 one-time developer fee; useful for enterprise customers whose IT requires Store-distributed apps. Not blocking.
- **winget** — Microsoft's package manager; free to publish via PR to the winget-pkgs repo. Nice-to-have for developer customers.

### Auto-update

- Tauri ships with built-in updater
- Hosts update manifests + binaries on R2 (already in the stack)
- Sign updates with the same code-signing cert

## macOS desktop (direct distribution, not Mac App Store)

- Build via Tauri
- Sign with "Developer ID Application" cert (free with Apple Developer Program)
- Notarize via `xcrun notarytool submit`
- Distribute as .dmg from versawiki.com or R2
- Auto-update via Tauri's updater + Sparkle manifest

## Mac App Store (optional, do later)

- Different cert, different sandboxing rules, App Sandbox required
- Generally not worth it for B2B / dev tools — direct distribution is preferred
- Reconsider if you ever target consumer users

## Linux desktop (optional)

- Tauri builds AppImage out of the box (no signing required, just works)
- Snap and Flatpak are optional second hop
- Probably skip until you have a Linux user asking for it

## Timeline summary

| Platform | Account/cert lead | First useful submission lead |
|---|---|---|
| Apple iOS | 1-2 days | After M5 ships + 1-2 weeks review |
| Apple macOS | Same | After M3 ships + 24 hours (notarize) |
| Google Play | Same day | After M5 ships + 24 hours review + 14-day closed test |
| Windows | 1-3 days (cert) | After M3 ships, instant signing |
| Linux | Instant | After M3 ships, instant |

## What to defer

- Do not buy the Windows EV cert until you have a Windows binary to sign
- Do not draft App Store / Play Store descriptions until the app is closer to ready (they'll change three times)
- Do not pay for the Microsoft Store dev fee until a customer asks
- Do not build for Linux until a customer asks (it's free time, but it's still time)
