#!/usr/bin/env python3
"""
Morning VC & Tech Newsletter Agent
Runs daily at 8am PT, uses Claude with web search to compile
personalized briefings on VC deals, AI, energy, and semiconductors.
"""

import os
import json
import re
import smtplib
import requests
import anthropic
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from urllib.parse import urlencode
import pytz

# ── Config ────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY     = os.environ["ANTHROPIC_API_KEY"]
SENDER_EMAIL          = os.environ["SENDER_EMAIL"]
SENDER_PASSWORD       = os.environ["SENDER_PASSWORD"]
RECIPIENT_EMAIL       = os.environ["RECIPIENT_EMAIL"]
FEEDBACK_WEBHOOK_URL  = os.environ.get("FEEDBACK_WEBHOOK_URL", "")
GITHUB_TOKEN          = os.environ.get("GITHUB_TOKEN_NEWSLETTER", "")
GITHUB_REPO           = os.environ.get("GITHUB_REPO", "")   # set to github.repository in workflow

WATCHLIST_FILE = "watchlist.json"
SKIP_FILE      = "skip.txt"


# ── Watchlist helpers ─────────────────────────────────────────────────────────
def load_watchlist() -> list:
    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE) as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def save_watchlist(items: list):
    trimmed = items[:5]
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(trimmed, f, indent=2)
    print(f"📋 Watchlist saved: {trimmed}")


# ── Skip / pause helpers ──────────────────────────────────────────────────────
def check_and_clear_skip() -> bool:
    """Return True if today's send should be skipped (skip.txt exists in repo)."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return False

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{SKIP_FILE}"

    resp = requests.get(url, headers=headers, timeout=10)
    if resp.status_code != 200:
        return False

    # File found — delete it and skip today
    sha = resp.json().get("sha", "")
    requests.delete(
        url,
        headers=headers,
        json={"message": "chore: auto-remove skip.txt [skip ci]", "sha": sha},
        timeout=10,
    )
    print("⏭️  skip.txt found — skipping today's newsletter and removing the file.")
    return True


# ── Prompts ───────────────────────────────────────────────────────────────────
def build_system_prompt(watchlist: list) -> str:
    watch_block = ""
    if watchlist:
        items_str = "\n".join(f"  • {w}" for w in watchlist)
        watch_block = f"""
── 📌 TO WATCH (from recent editions) ──
Check for follow-up developments on these flagged companies/themes:
{items_str}
If any have news today, include a "📌 To Watch" section immediately after the email header
(before Section 1). If none have relevant updates, omit the section entirely.
"""

    return f"""You are a sharp, senior VC analyst writing a daily morning briefing for a venture capital investor.
Your reader is time-constrained and sophisticated — they want signal, not noise.

Tone: direct, insightful, no filler. Write like a trusted colleague, not a journalist.
Format: clean HTML email (inline styles only, no external CSS).
{watch_block}
── CONTENT PRIORITIES ──
• Weight news HEAVILY toward US startup and VC activity. Include international news only if it
  is a major market-moving event that US investors cannot ignore.
• Apply an AI lens to EVERY section — energy and semiconductors should lead with stories where
  AI is a key driver (data-center power, AI chip supply, etc.).
• Prioritize startup and early/growth-stage VC activity over large incumbents (Google,
  Microsoft, Meta, Amazon, Apple). Mention incumbents ONLY when their action directly creates
  a tangible opportunity or threat for startups.
• In the VC section: cover a balance of early-stage (Seed, Series A) AND late-stage
  (Series C+, pre-IPO) deals.
  - Prefix early-stage headlines with 🌱
  - Prefix late-stage headlines with 🚀

── SECTIONS (in order) ──
1. 💰 VC Deal Activity — 6–8 notable funding rounds, exits, and firm news from the last 24 hrs.
   For each: deal size, sector, lead investor, and what it signals about the market.
2. 🤖 AI — 5–6 most important developments for a VC: new models, infra plays, enterprise
   adoption, regulatory moves, research commercialization.
3. ⚡ Energy — 4–5 items: cleantech deals, grid infrastructure, nuclear/fusion milestones,
   policy shifts. Lead with AI-adjacent energy plays (data-center power, AI-optimized grid tech).
4. 🔬 Semiconductors — 4–5 items: fab news, chip design startups, supply chain shifts, CHIPS
   Act updates, AI chip demand signals.
5. 💡 So What? — 4–5 punchy bullet points on the single biggest cross-sector theme of the day
   and what it means for dealflow or portfolio companies.
6. 📅 This Week's Signals — 2–3 bullets on patterns across this week's news and where smart
   money appears to be moving.

── PER-ITEM FORMAT ──
For each news item:
• Bolded headline — make the headline text a hyperlink to the source article URL
• 2–3 sentences of context: what happened, why it matters to a VC, what to watch
• Source name (e.g., "— TechCrunch" or "— Bloomberg")

── OUTPUT FORMAT ──
Your response MUST begin with EXACTLY this line (fill in the blank, max 80 characters):
SUBJECT: <concise subject summarising the biggest story and top theme>
<!--START-->
Then write the full HTML email body (everything between <body> tags — do NOT include
<!DOCTYPE>, <html>, <head>, or <body> tags, just the inner HTML content).

At the very end of your HTML output, append this comment with the top 5 companies or themes
to monitor in coming days:
<!-- WATCHLIST: ["item1", "item2", "item3", "item4", "item5"] -->

── QUALITY RULES ──
• Search for today's news before writing. Be specific — include company names, dollar amounts,
  and investor names wherever possible.
• Skip anything older than 48 hours.
• No "Now I'll write..." preamble or meta-commentary — go straight to the content."""


USER_PROMPT_TEMPLATE = """Today is {date_str}.

Search for the latest news and compile today's morning briefing covering:
1. US startup funding rounds and VC market activity (last 24 hours)
2. AI industry headlines from a VC investor perspective — US-first
3. Energy / cleantech headlines where AI or data-center demand is a driver
4. Semiconductor headlines relevant to AI and startups

Write the full briefing as well-formatted HTML (inner body content only, inline styles).
Make it scannable with clear section headers and subtle section dividers."""


# ── HTML email wrapper ─────────────────────────────────────────────────────────
def wrap_in_email_template(content: str, date_str: str, subject: str) -> str:
    today_iso = datetime.now(pytz.timezone("US/Pacific")).strftime("%Y-%m-%d")

    feedback_block = ""
    if FEEDBACK_WEBHOOK_URL:
        up_url   = f"{FEEDBACK_WEBHOOK_URL}?{urlencode({'date': today_iso, 'rating': 'up'})}"
        down_url = f"{FEEDBACK_WEBHOOK_URL}?{urlencode({'date': today_iso, 'rating': 'down'})}"
        skip_url = f"{FEEDBACK_WEBHOOK_URL}?{urlencode({'action': 'skip', 'date': today_iso})}"

        feedback_block = f"""
  <div style="border-top: 2px solid #e2e8f0; margin-top: 40px; padding-top: 24px; text-align: center;">
    <p style="margin: 0 0 14px; font-size: 13px; color: #475569; font-weight: 600; letter-spacing: 0.3px;">
      How was today's briefing?
    </p>
    <a href="{up_url}"
       style="display: inline-block; margin: 0 6px; padding: 9px 22px;
              background: #16a34a; color: #ffffff; text-decoration: none;
              border-radius: 6px; font-size: 14px; font-weight: 600;">
      👍&nbsp; Useful
    </a>
    <a href="{down_url}"
       style="display: inline-block; margin: 0 6px; padding: 9px 22px;
              background: #dc2626; color: #ffffff; text-decoration: none;
              border-radius: 6px; font-size: 14px; font-weight: 600;">
      👎&nbsp; Not today
    </a>
    <p style="margin: 16px 0 0;">
      <a href="{skip_url}"
         style="font-size: 12px; color: #94a3b8; text-decoration: underline;">
        Skip tomorrow's edition
      </a>
    </p>
  </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
             max-width: 680px; margin: 0 auto; padding: 28px 20px;
             background: #ffffff; color: #1a1a1a; line-height: 1.65;">

  <!-- ── Header ── -->
  <div style="border-bottom: 3px solid #0f172a; padding-bottom: 18px; margin-bottom: 30px;">
    <h1 style="margin: 0; font-size: 22px; color: #0f172a;
               letter-spacing: -0.5px; font-weight: 800;">
      📬 Morning VC Briefing
    </h1>
    <p style="margin: 5px 0 0; font-size: 13px; color: #64748b;">{date_str}</p>
    <p style="margin: 10px 0 0; font-size: 15px; color: #334155;
              font-style: italic; line-height: 1.55; border-left: 3px solid #3b82f6;
              padding-left: 12px;">
      {subject}
    </p>
  </div>

  <!-- ── Body ── -->
  {content}

  <!-- ── Feedback ── -->
  {feedback_block}

  <!-- ── Footer ── -->
  <div style="border-top: 1px solid #e2e8f0; margin-top: 32px; padding-top: 14px;
              font-size: 11px; color: #94a3b8; text-align: center; line-height: 1.6;">
    Morning VC Briefing &middot; Powered by Claude &middot; {date_str}
  </div>

</body>
</html>"""


# ── Call Claude with web search ────────────────────────────────────────────────
def generate_newsletter(watchlist: list) -> tuple:
    """Returns (html_content, subject_line, new_watchlist)."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    pt = pytz.timezone("US/Pacific")
    date_str = datetime.now(pt).strftime("%A, %B %d, %Y")

    system_prompt = build_system_prompt(watchlist)
    user_prompt   = USER_PROMPT_TEMPLATE.format(date_str=date_str)

    print("🔍 Calling Claude with web search...")

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8192,
        system=system_prompt,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_text = ""
    for block in response.content:
        if block.type == "text":
            raw_text += block.text

    if not raw_text.strip():
        raise ValueError("Claude returned no text content")

    # ── Parse subject line ────────────────────────────────────────────────────
    pt = pytz.timezone("US/Pacific")
    fallback_subject = f"Morning VC Briefing — {datetime.now(pt).strftime('%A, %B %d, %Y')}"
    subject     = fallback_subject
    html_content = raw_text

    if raw_text.startswith("SUBJECT:"):
        parts = raw_text.split("<!--START-->", 1)
        if len(parts) == 2:
            subject_raw  = parts[0].replace("SUBJECT:", "").strip()
            subject      = subject_raw[:80]
            html_content = parts[1].strip()
        else:
            # Fallback: first line only
            first_nl     = raw_text.find("\n")
            subject_raw  = raw_text[:first_nl].replace("SUBJECT:", "").strip()
            subject      = subject_raw[:80]
            html_content = raw_text[first_nl:].strip()

    # ── Parse watchlist from hidden comment ───────────────────────────────────
    new_watchlist = watchlist
    wl_match = re.search(
        r"<!--\s*WATCHLIST:\s*(\[.*?\])\s*-->",
        html_content,
        re.DOTALL,
    )
    if wl_match:
        try:
            parsed = json.loads(wl_match.group(1))
            if isinstance(parsed, list):
                new_watchlist = parsed
            # Strip the comment from the HTML
            html_content = (
                html_content[: wl_match.start()] + html_content[wl_match.end() :]
            ).strip()
        except json.JSONDecodeError:
            pass

    print(f"✅ Newsletter generated ({len(html_content)} chars)")
    print(f"📌 Subject: {subject}")
    return html_content, subject, new_watchlist


# ── Send via Gmail SMTP ────────────────────────────────────────────────────────
def send_email(html_body: str, subject: str, date_str: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = RECIPIENT_EMAIL

    full_html = wrap_in_email_template(html_body, date_str, subject)
    msg.attach(MIMEText(full_html, "html"))

    print(f"📧 Sending to {RECIPIENT_EMAIL}...")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())

    print("✅ Email sent!")


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    pt       = pytz.timezone("US/Pacific")
    date_str = datetime.now(pt).strftime("%A, %B %d, %Y")

    print(f"\n🗞  Starting newsletter generation for {date_str}\n")

    # 1. Check skip flag (GitHub repo file)
    if check_and_clear_skip():
        print("⏭️  Skipping today's newsletter as requested.\n")
        return

    # 2. Load previous watchlist for context
    watchlist = load_watchlist()
    if watchlist:
        print(f"📋 Loaded watchlist from previous run: {watchlist}")

    # 3. Generate newsletter via Claude
    newsletter_html, subject, new_watchlist = generate_newsletter(watchlist)

    # 4. Send
    send_email(newsletter_html, subject, date_str)

    # 5. Persist updated watchlist for next run
    if new_watchlist:
        save_watchlist(new_watchlist)

    print("\n🎉 Done!\n")


if __name__ == "__main__":
    main()
