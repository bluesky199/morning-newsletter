# 📬 Morning VC Newsletter Agent — Setup Guide

A Claude-powered agent that emails you a personalized morning briefing every day at 8am PT,
covering VC deal activity, AI, energy, and semiconductors.

---

## How It Works

1. **GitHub Actions** triggers at 8am PT every morning
2. **`newsletter.py`** calls Claude (claude-sonnet-4) with the web search tool enabled
3. Claude searches the web for today's news and writes a formatted briefing
4. The script emails the HTML newsletter directly to your inbox

---

## Setup (15 minutes)

### Step 1 — Create a GitHub repository

```bash
git init morning-newsletter
cd morning-newsletter
# Copy newsletter.py here
# Copy .github/workflows/newsletter.yml here (preserve folder structure)
git add .
git commit -m "Initial newsletter agent"
git remote add origin https://github.com/YOUR_USERNAME/morning-newsletter.git
git push -u origin main
```

### Step 2 — Get a Gmail App Password

You need an App Password (not your regular Gmail password) to send via SMTP:

1. Go to your Google Account → **Security**
2. Enable **2-Step Verification** if not already on
3. Search for **"App passwords"** in the Security settings
4. Create a new App Password → select **Mail** → **Other (custom name)**
5. Name it "Newsletter Agent" → copy the 16-character password

### Step 3 — Add GitHub Secrets

In your GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**

Add these four secrets:

| Secret Name        | Value                                      |
|--------------------|--------------------------------------------|
| `ANTHROPIC_API_KEY`| Your Anthropic API key (from console.anthropic.com) |
| `SENDER_EMAIL`     | Your Gmail address (e.g. you@gmail.com)    |
| `SENDER_PASSWORD`  | The 16-char App Password from Step 2       |
| `RECIPIENT_EMAIL`  | Where to deliver the newsletter (can be same as sender) |

### Step 4 — Test It

In your GitHub repo → **Actions** tab → **Morning Newsletter** → **Run workflow**

Check your inbox within ~60 seconds.

---

## Timing Notes

The cron schedule `0 15 * * *` = **15:00 UTC = 8:00 AM PDT (summer)**.

In winter (PST, UTC-8), change it to `0 16 * * *` in the workflow file.

Or use both to handle the transition:
```yaml
- cron: '0 15 * * *'   # 8am PDT (Mar–Nov)
- cron: '0 16 * * *'   # 8am PST (Nov–Mar)
```
Note: this would send twice during transition weeks — simplest fix is to just pick one.

---

## Customization

### Change the topics or tone
Edit `SYSTEM_PROMPT` in `newsletter.py`. For example:
- Add **crypto/web3** as a 5th section
- Change focus to **Series B+ only** deals
- Add a **"Portfolio Watch"** section for specific companies

### Add a personal context block
At the top of `USER_PROMPT`, add something like:
```python
USER_PROMPT = f"""Context: I'm a GP at a seed-stage fund focused on AI infrastructure
and climate tech. My portfolio includes [Company A], [Company B].
...
```
This makes Claude flag relevant news to your specific portfolio/thesis.

### Use a different email provider
Replace the Gmail SMTP block in `send_email()` with:
- **Resend.com** (recommended, great free tier): `pip install resend`
- **SendGrid**: `pip install sendgrid`
- **Postmark**: `pip install postmarkclient`

---

## Cost Estimate

- **Claude API**: ~$0.05–0.15 per newsletter (Sonnet 4 with web search)
- **GitHub Actions**: Free (well within free tier minutes)
- **Gmail SMTP**: Free
- **Total**: ~$1.50–4.50/month

---

## File Structure

```
morning-newsletter/
├── newsletter.py                    # Main agent script
├── .github/
│   └── workflows/
│       └── newsletter.yml           # GitHub Actions schedule
└── README.md                        # This file
```
