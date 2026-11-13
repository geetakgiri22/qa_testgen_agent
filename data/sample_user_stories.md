# Sample Requirements - Online Banking Portal

REQ-001: User login
As a registered customer, I want to log in with my email and password so that I can access my accounts.
Acceptance Criteria:
- Email must be a valid format and password must be between 8 and 20 characters.
- Successful login redirects the user to the dashboard.
- After 5 consecutive failed attempts the account is locked for 15 minutes.
- An invalid email or password shows a generic error message.

REQ-002: Funds transfer
As a customer, I want to transfer money to a saved beneficiary so that I can pay people quickly.
Acceptance Criteria:
- Transfer amount must be at least 1 and at most 50000 per transaction.
- Amount cannot exceed the available balance.
- A confirmation OTP is required for transfers above 10000.
- A transaction reference number is shown after success.

REQ-003: Profile update
As a customer, I want to update my phone number and address so that the bank can contact me.

REQ-004: Dashboard performance
The dashboard shall load within 3 seconds for 95% of requests under 500 concurrent users.
Acceptance Criteria:
- Page load time is under 3 seconds at the 95th percentile.
- The system supports 500 concurrent sessions without errors.

REQ-005: Statement download
As a customer, I want to download my account statement as PDF so that I can keep records.
Acceptance Criteria:
- Statements can be downloaded for any date range up to 12 months.
- The file is generated within 10 seconds.
- Only the account owner can download the statement.
