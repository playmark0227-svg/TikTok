# TikTok App Review Submission

This document is a template for submitting our application for review to TikTok for Developers, in order to enable Direct Post via the Content Posting API.

## Application Overview

**App Name**: ViFight TikTok Product PR Auto-Poster
**Developer**: ViFight (sole proprietorship, Japan)
**Contact**: playmark0227@gmail.com
**Privacy Policy**: (URL of the deployed privacy_policy_en.md)
**Terms of Service**: (URL if available)

## Use Case

We operate a TikTok account that publishes daily product PR videos based on popular and well-reviewed items from Amazon Japan and Rakuten affiliate programs. The system is fully automated except for a human approval step performed by the operator (ViFight) before publishing.

### Why we need Content Posting API access

- The operator runs a single TikTok account dedicated to affiliate product promotion
- Daily publishing requires a programmatic interface to maintain consistent posting schedule
- The Content Posting API enables compliant posting with proper attribution (`#PR` `#広告` hashtags + on-video "広告" label)

## End User Flow

The "end user" of this app is **only the operator (ViFight)**. The app is not distributed to other users.

1. **Daily 17:00 JST**: A scheduled job (macOS launchd) starts the pipeline
2. **Product Selection**: The system queries Amazon PA-API and Rakuten Ichiba API for trending products in pre-configured categories (electronics, cosmetics, kitchen, health, gadgets)
3. **Content Generation**:
   - Anthropic Claude API generates a video plan (English prompt for Veo, Japanese caption, hashtags)
   - Google Gemini Veo 3.1 generates two 8-second 9:16 vertical clips
   - FFmpeg combines clips, burns subtitles, adds background music, and overlays the "広告" (Advertisement) label
4. **Operator Approval**: The video is uploaded to Firebase Storage and sent to a private Discord channel where ViFight reviews and approves (✅), requests revisions (✏️), or rejects (❌)
5. **Posting**: Upon approval, the video is posted to the operator's TikTok account via Content Posting API
6. **Logging**: Post metadata is recorded in Firestore for analytics

## Compliance Measures

### Advertising Disclosure (Japan Premiums Act / Stealth Marketing Regulation)

- **In-video overlay**: "広告" (Advertisement) label is burned into all videos in the top-right corner for the entire duration
- **Caption hashtags**: `#PR` and `#広告` are programmatically enforced in every caption
- **Validation**: Captions are validated before posting to ensure compliance hashtags are present

### Content Safety

- Veo prompts are designed to avoid:
  - Real brand names (products are abstracted)
  - Real persons or celebrity likenesses
  - Health/medical efficacy claims (medical device act / 薬機法)
  - Hyperbole regulated by Japanese advertising law ("absolutely", "100%", "industry No.1")
- All generated content is subject to operator approval before posting

### Data Privacy

- We only access our own TikTok account
- We do not collect data from third-party users
- TikTok access tokens are stored encrypted in Firebase Firestore
- Tokens are refreshed automatically and never logged

## Permissions Requested

We request the following scopes:

| Scope | Purpose |
| --- | --- |
| `user.info.basic` | Verify the connected account is the operator's |
| `video.publish` | Publish PR videos via Direct Post |
| `video.upload` | Upload video files via PULL_FROM_URL |

## Demo Account

- TikTok handle: (to be provided)
- Demo video samples: (URLs to be provided)

## Screenshots & Demo Flow

(Include screenshots of)
1. Discord approval flow (sample message)
2. A finalized PR video with "広告" overlay
3. Posted result on TikTok with `#PR #広告` hashtags

## Technical Architecture

```
[Daily 17:00 launchd]
    -> Product Selection (Amazon PA-API + Rakuten API)
    -> Content Generation (Claude API + Veo API)
    -> Video Editing (FFmpeg)
    -> Firebase Storage Upload
    -> Discord Approval (operator)
    -> TikTok Content Posting API
    -> Firestore logging
```

## Contact for Review

For any questions during the review:

- Primary contact: ViFight (playmark0227@gmail.com)
- Response time: Within 1 business day (JST)
