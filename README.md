# Kairovi Do Earn Repeat

Kairovi is an AI-powered platform that connects businesses with gig workers for quick, real-world tasks such as store audits and photo verification. Gemini verifies submitted proof, while approved workers can receive UPI micro-payouts through RazorpayX.

## Setup

Create and activate a virtual environment, then install the dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Create a `.env` file in the project root:

```dotenv
GEMINI_API_KEY=your_gemini_api_key
RAZORPAY_KEY_ID=your_razorpay_key_id
RAZORPAY_KEY_SECRET=your_razorpay_key_secret
RAZORPAYX_ACCOUNT_NUMBER=your_razorpayx_account_number
```

`GEMINI_API_KEY` is required for AI verification. The app uses `gemini-3.6-flash` by default. To override the model, set `GEMINI_MODEL` in `.env`.

## Run

Start the Streamlit app with:

```powershell
python -m streamlit run app.py
```

Then open `http://localhost:8501` in a browser. Use the Gig Worker tab to capture proof with the device camera, or use the Business Agent Portal to post a bounty.

When Razorpay credentials are missing or unavailable, the app shows a mock payout for UI testing and does not transfer money. Live payouts require valid RazorpayX credentials and `RAZORPAYX_ACCOUNT_NUMBER`.
