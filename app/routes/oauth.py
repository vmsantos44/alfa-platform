"""
Alfa AI Platform - OAuth Routes
Handles Zoho Mail OAuth authorization flow
"""
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
import httpx

from app.config import get_settings

router = APIRouter()


@router.get("/authorize")
async def authorize_zoho_mail():
    """
    Step 1: Redirect user to Zoho authorization page
    Visit: http://localhost:8003/oauth/authorize
    """
    settings = get_settings()

    if not settings.zoho_mail_client_id:
        raise HTTPException(status_code=500, detail="ZOHO_MAIL_CLIENT_ID not configured")

    scopes = "ZohoMail.messages.ALL,ZohoMail.accounts.READ,ZohoMail.folders.READ"

    auth_url = (
        f"{settings.zoho_accounts_domain}/oauth/v2/auth"
        f"?client_id={settings.zoho_mail_client_id}"
        f"&response_type=code"
        f"&redirect_uri={settings.zoho_mail_redirect_uri}"
        f"&scope={scopes}"
        f"&access_type=offline"
        f"&prompt=consent"
    )

    return RedirectResponse(url=auth_url)


@router.get("/callback")
async def oauth_callback(
    code: str = Query(None, description="Authorization code from Zoho"),
    error: str = Query(None, description="Error from Zoho")
):
    """
    Step 2: Handle OAuth callback and exchange code for tokens
    Zoho redirects here after user authorization
    """
    settings = get_settings()

    if error:
        return HTMLResponse(content=f"""
        <html>
            <head><title>Authorization Failed</title></head>
            <body style="font-family: sans-serif; padding: 40px; text-align: center;">
                <h1 style="color: #e53e3e;">❌ Authorization Failed</h1>
                <p>Error: {error}</p>
                <a href="/oauth/authorize">Try Again</a>
            </body>
        </html>
        """, status_code=400)

    if not code:
        return HTMLResponse(content="""
        <html>
            <head><title>No Code Received</title></head>
            <body style="font-family: sans-serif; padding: 40px; text-align: center;">
                <h1 style="color: #e53e3e;">❌ No Authorization Code</h1>
                <p>No authorization code was received from Zoho.</p>
                <a href="/oauth/authorize">Try Again</a>
            </body>
        </html>
        """, status_code=400)

    # Exchange authorization code for tokens
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{settings.zoho_accounts_domain}/oauth/v2/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": settings.zoho_mail_client_id,
                    "client_secret": settings.zoho_mail_client_secret,
                    "redirect_uri": settings.zoho_mail_redirect_uri,
                    "code": code,
                }
            )

            token_data = response.json()

            if "error" in token_data:
                return HTMLResponse(content=f"""
                <html>
                    <head><title>Token Exchange Failed</title></head>
                    <body style="font-family: sans-serif; padding: 40px; text-align: center;">
                        <h1 style="color: #e53e3e;">❌ Token Exchange Failed</h1>
                        <p>Error: {token_data.get('error')}</p>
                        <p>Description: {token_data.get('error_description', 'Unknown error')}</p>
                        <a href="/oauth/authorize">Try Again</a>
                    </body>
                </html>
                """, status_code=400)

            access_token = token_data.get("access_token")
            refresh_token = token_data.get("refresh_token")
            expires_in = token_data.get("expires_in")

            # Get account ID
            account_id = None
            if access_token:
                try:
                    accounts_response = await client.get(
                        f"{settings.zoho_mail_api_url}/accounts",
                        headers={"Authorization": f"Zoho-oauthtoken {access_token}"}
                    )
                    accounts_data = accounts_response.json()
                    if "data" in accounts_data and len(accounts_data["data"]) > 0:
                        account_id = accounts_data["data"][0].get("accountId")
                except Exception as e:
                    print(f"⚠️ Failed to get account ID: {e}")

            return HTMLResponse(content=f"""
            <html>
                <head>
                    <title>Authorization Successful</title>
                    <style>
                        body {{ font-family: sans-serif; padding: 40px; max-width: 800px; margin: 0 auto; }}
                        .success {{ color: #38a169; }}
                        .token-box {{
                            background: #f7fafc;
                            border: 1px solid #e2e8f0;
                            border-radius: 8px;
                            padding: 16px;
                            margin: 16px 0;
                            word-break: break-all;
                            font-family: monospace;
                            font-size: 12px;
                        }}
                        .label {{ font-weight: bold; color: #4a5568; margin-bottom: 8px; }}
                        .warning {{ color: #d69e2e; background: #fffff0; padding: 12px; border-radius: 4px; }}
                    </style>
                </head>
                <body>
                    <h1 class="success">✅ Authorization Successful!</h1>

                    <p class="warning">⚠️ <strong>Important:</strong> Copy these values to your <code>.env</code> file immediately!</p>

                    <div class="label">ZOHO_MAIL_REFRESH_TOKEN:</div>
                    <div class="token-box">{refresh_token or 'Not provided'}</div>

                    <div class="label">ZOHO_MAIL_ACCOUNT_ID:</div>
                    <div class="token-box">{account_id or 'Could not retrieve - get manually'}</div>

                    <div class="label">Access Token (expires in {expires_in}s):</div>
                    <div class="token-box">{access_token or 'Not provided'}</div>

                    <h3>Next Steps:</h3>
                    <ol>
                        <li>Copy the <strong>ZOHO_MAIL_REFRESH_TOKEN</strong> to your <code>.env</code> file</li>
                        <li>Copy the <strong>ZOHO_MAIL_ACCOUNT_ID</strong> to your <code>.env</code> file</li>
                        <li>Restart your server</li>
                        <li>Test the email API at <a href="/api/mail/test">/api/mail/test</a></li>
                    </ol>
                </body>
            </html>
            """)

        except httpx.HTTPError as e:
            return HTMLResponse(content=f"""
            <html>
                <head><title>Request Failed</title></head>
                <body style="font-family: sans-serif; padding: 40px; text-align: center;">
                    <h1 style="color: #e53e3e;">❌ Request Failed</h1>
                    <p>Failed to exchange authorization code: {str(e)}</p>
                    <a href="/oauth/authorize">Try Again</a>
                </body>
            </html>
            """, status_code=500)
