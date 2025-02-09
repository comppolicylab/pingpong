from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from .auth import encode_session_token
from .now import offset
from .testutil import with_authz, with_authz_series, with_user, with_institution


async def test_me_without_token(api):
    response = api.get("/api/v1/me")
    assert response.status_code == 200
    assert response.json() == {
        "error": None,
        "profile": None,
        "status": "missing",
        "pending_term_id": None,
        "token": None,
        "user": None,
    }


async def test_me_with_expired_token(api, now):
    response = api.get(
        "/api/v1/me",
        cookies={
            "session": encode_session_token(123, nowfn=offset(now, seconds=-100_000)),
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "error": "Token expired",
        "profile": None,
        "pending_term_id": None,
        "status": "invalid",
        "token": None,
        "user": None,
    }


async def test_me_with_invalid_token(api):
    response = api.get(
        "/api/v1/me",
        cookies={
            # Token with invalid signature
            "session": (
                "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
                "eyJzdWIiOiIxMjMiLCJleHAiOjE3MDk0NDg1MzQsImlhdCI6MTcwOTQ0ODUzM30."
                "pRnnClaC1a6yIBFKMdA32pqoaJOcpHyY4lq_NU28gQ"
            ),
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "error": "Signature verification failed",
        "profile": None,
        "status": "invalid",
        "token": None,
        "pending_term_id": None,
        "user": None,
    }


async def test_me_with_valid_token_but_missing_user(api, now):
    response = api.get(
        "/api/v1/me",
        cookies={
            "session": encode_session_token(123, nowfn=offset(now, seconds=-5)),
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "error": "We couldn't locate your account. Please try logging in again.",
        "profile": None,
        "status": "error",
        "pending_term_id": None,
        "token": None,
        "user": None,
    }


@with_user(123)
async def test_me_with_valid_user(api, user, now, valid_user_token):
    response = api.get(
        "/api/v1/me",
        cookies={
            "session": valid_user_token,
        },
    )
    assert response.status_code == 200
    response_json = response.json()

    # Check if `updated` exists and is a valid timestamp
    updated_value = response_json["user"].get("updated")
    if updated_value is not None:
        try:
            datetime.fromisoformat(updated_value)  # Validate ISO 8601 format
        except ValueError:
            pytest.fail(f"Invalid timestamp format: {updated_value}")

    expected_response = {
        "error": None,
        "profile": {
            "email": "user_123@domain.test",
            "gravatar_id": "45d4d5ec84ab81529df672c3abf0def25df67c0c64859aea0559bc867ea64b19",
            "image_url": (
                "https://www.gravatar.com/avatar/"
                "45d4d5ec84ab81529df672c3abf0def25df67c0c64859aea0559bc867ea64b19"
            ),
            "name": None,
        },
        "status": "valid",
        "token": {"exp": 1704153540, "iat": 1704067140, "sub": "123"},
        "user": {
            "created": "2024-01-01T00:00:00",
            "email": "user_123@domain.test",
            "id": 123,
            "name": "user_123@domain.test",
            "external_logins": [],
            "first_name": None,
            "last_name": None,
            "display_name": None,
            "has_real_name": False,
            "state": "verified",
        },
        "pending_term_id": None,
    }

    # Remove `updated` from actual response before assertion
    response_json["user"].pop("updated", None)

    assert response_json == expected_response


@with_user(123)
@with_authz_series(
    [
        {"grants": []},
        {"grants": [("user:123", "admin", "institution:1")]},
        {"grants": [("user:123", "can_create_institution", "root:0")]},
        {"grants": [("user:123", "can_create_class", "institution:1")]},
        {"grants": [("user:122", "admin", "root:0")]},
    ]
)
async def test_config_no_permissions(api, valid_user_token):
    response = api.get(
        "/api/v1/config",
        cookies={
            "session": valid_user_token,
        },
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "Missing required role"}


@with_user(123)
@with_authz(
    grants=[
        ("user:123", "admin", "root:0"),
    ],
)
async def test_config_correct_permissions(api, valid_user_token):
    response = api.get(
        "/api/v1/config",
        cookies={
            "session": valid_user_token,
        },
    )
    assert response.status_code == 200


async def test_auth_with_invalid_token(api):
    invalid_token = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjMiLCJleHAiOjE3MDk0NDg1MzQsImlhdCI6MTcwOTQ0ODUzM30."
        "pRnnClaC1a6yIBFKMdA32pqoaJOcpHyY4lq_NU28gQ"
    )
    response = api.get(f"/api/v1/auth?token={invalid_token}")
    assert response.status_code == 401
    assert response.json() == {"detail": "Signature verification failed"}


async def test_auth_with_expired_token(api, now):
    expired_token = encode_session_token(123, nowfn=offset(now, seconds=-100_000))
    response = api.get(f"/api/v1/auth?token={expired_token}", allow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login/?expired=true&forward=/"


@with_user(123, "foo@bar.com")
async def test_auth_valid_token(api, now):
    valid_token = encode_session_token(123, nowfn=offset(now, seconds=-5))
    response = api.get(f"/api/v1/auth?token={valid_token}", allow_redirects=False)
    assert response.status_code == 303
    # Check where redirect goes
    assert response.headers["location"] == "http://localhost:5173/"


@with_user(123, "foo@bar.com")
async def test_auth_valid_token_with_redirect(api, now):
    valid_token = encode_session_token(123, nowfn=offset(now, seconds=-5))
    response = api.get(
        f"/api/v1/auth?token={valid_token}&redirect=/foo/bar", allow_redirects=False
    )
    assert response.status_code == 303
    # Check where redirect goes
    assert response.headers["location"] == "http://localhost:5173/foo/bar"


@with_user(123, "foo@hks.harvard.edu")
async def test_auth_valid_token_with_sso_redirect(api, now):
    valid_token = encode_session_token(123, nowfn=offset(now, seconds=-5))
    response = api.get(
        f"/api/v1/auth?token={valid_token}&redirect=/foo/bar", allow_redirects=False
    )
    assert response.status_code == 303
    # Check where redirect goes
    assert (
        response.headers["location"]
        == "http://localhost:5173/api/v1/login/sso?provider=harvardkey&redirect=/foo/bar"
    )


async def test_magic_link_login_no_user(api, config, monkeypatch):
    # Patch the email driver in config.email
    send_mock = AsyncMock()
    monkeypatch.setattr(config.email.sender, "send", send_mock)
    response = api.post(
        "/api/v1/login/magic",
        json={"email": "me@org.test"},
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "User does not exist"}
    # Send should not have been called
    send_mock.assert_not_called()


@with_user(123)
async def test_magic_link_login(api, config, monkeypatch):
    # Patch the email driver in config.email
    send_mock = AsyncMock()
    monkeypatch.setattr(config.email.sender, "send", send_mock)
    response = api.post(
        "/api/v1/login/magic",
        json={"email": "user_123@domain.test"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    send_mock.assert_called_once_with(
        "user_123@domain.test",
        "Log back in to PingPong",
        """
<!doctype html>
<html>
   <head>
      <meta name="comm-name" content="invite-notification">
   </head>
   <body style="margin:0; padding:0;" class="body">
      <!-- head include -->
      <!-- BEGIN HEAD -->
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <meta http-equiv="content-type" content="text/html;charset=utf-8">
      <meta name="format-detection" content="date=no">
      <meta name="format-detection" content="address=no">
      <meta name="format-detection" content="email=no">
      <meta name="color-scheme" content="light dark">
      <meta name="supported-color-schemes" content="light dark">
      <style type="text/css">
         body {
         width: 100% !important;
         padding: 0;
         margin: 0;
         background-color: #201e45;
         font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', Helvetica, Arial, sans-serif;
         font-weight: normal;
         text-rendering: optimizelegibility;
         -webkit-font-smoothing: antialiased;
         }
         a, a:link {
         color: #0070c9;
         text-decoration: none;
         }
         a:hover {
         color: #0070c9;
         text-decoration: underline !important;
         }
         sup {
         line-height: normal;
         font-size: .65em !important;
         vertical-align: super;
         }
         b {
         font-weight: 600 !important;
         }
         td {
         color: #333333;
         font-size: 17px;
         font-weight: normal;
         line-height: 25px;
         }
         .type-body-d, .type-body-m {
         font-size: 14px;
         line-height: 20px;
         }
         p {
         margin: 0 0 16px 0;
         padding: 0;
         }
         .f-complete {
         color: #6F6363;
         font-size: 12px;
         line-height: 15px;
         }
         .f-complete p {
         margin-bottom: 9px;
         }
         .f-legal {
         padding: 0 0% 0 0%;
         }
         .preheader-hide {
         display: none !important;
         }
         /* DARK MODE DESKTOP */
         @media (prefers-color-scheme: dark) {
         .header-pingpong {
         background-color: #1A1834 !important;
         }
         .desktop-bg {
         background-color: #111517 !important;
         }
         .desktop-button-bg {
         background-color: #b6320a !important;
         }
         .d-divider {
         border-top: solid 1px #808080 !important;
         }
         body {
         background-color: transparent !important;
         color: #ffffff !important;
         }
         a, a:link {
         color: #62adf6 !important;
         }
         td {
         border-color: #808080 !important;
         color: #ffffff !important;
         }
         p {
         color: #ffffff !important;
         }
         .footer-bg {
         background-color: #333333 !important;
         }
         }
         @media only screen and (max-device-width: 568px) {
         .desktop {
         display: none;
         }
         .mobile {
         display: block !important;
         color: #333333;
         font-size: 17px;
         font-weight: normal;
         line-height: 25px;
         margin: 0 auto;
         max-height: inherit !important;
         max-width: 414px;
         overflow: visible;
         width: 100% !important;
         }
         .mobile-bg {
         background-color: white;
         }
         .mobile-button-bg {
         background-color: rgb(252, 98, 77);
         }
         sup {
         font-size: .55em;
         }
         .m-gutter {
         margin: 0 6.25%;
         }
         .m-divider {
         padding: 0px 0 30px 0;
         border-top: solid 1px #d6d6d6;
         }
         .f-legal {
         padding: 0 5% 0 6.25%;
         background: #f1f4ff !important;
         }
         .bold {
         font-weight: 600;
         }
         .hero-head-container {
         width: 100%;
         overflow: hidden;
         position: relative;
         margin: 0;
         height: 126px;
         padding-bottom: 0;
         }
         .m-gutter .row {
         position: relative;
         width: 100%;
         display: block;
         min-width: 320px;
         overflow: auto;
         margin-bottom: 10px;
         }
         .m-gutter .row .column {
         display: inline-block;
         vertical-align: middle;
         }
         .m-gutter .row .column img {
         margin-right: 12px;
         }
         u+.body a.gmail-unlink {
         color: #333333 !important;
         }
         /* M-FOOT */
         .m-footer {
         background: #f1f4ff;
         padding: 19px 0 28px;
         color: #6F6363;
         }
         .m-footer p, .m-footer li {
         font-size: 12px;
         line-height: 16px;
         }
         ul.m-bnav {
         border-top: 1px solid #d6d6d6;
         color: #555555;
         margin: 0;
         padding-top: 12px;
         padding-bottom: 1px;
         text-align: center;
         }
         ul.m-bnav li {
         border-bottom: 1px solid #d6d6d6;
         font-size: 12px;
         font-weight: normal;
         line-height: 16px;
         margin: 0 0 11px 0;
         padding: 0 0 12px 0;
         }
         ul.m-bnav li a, ul.m-bnav li a:visited {
         color: #555555;
         }
         }
         /* DARK MODE MOBILE */
         @media (prefers-color-scheme: dark) {
         .mobile {
         color: #ffffff;
         }
         .mobile-bg {
         background-color: #111517;
         }
         .m-title {
         color:#ffffff;
         }
         .mobile-button-bg {
         background-color: #b6320a;
         }
         .f-legal {
         background: #333333 !important;
         }
         .m-divider {
         border-top: solid 1px #808080;
         }
         .m-footer {
         background: #333333;
         }
         }
      </style>
      <!--[if gte mso 9]>
      <style type="text/css">
         sup
         { font-size:100% !important }
      </style>
      <![endif]-->
      <!-- END HEAD -->
      <!-- end head include -->
      <div class="mobile" style="width: 0; max-height: 0; overflow: hidden; display: none;">
         <div style="display:none !important;position: absolute; font-size:0; line-height:1; max-height:0; max-width:0; opacity:0; overflow:hidden; color: #333333" class="preheader-hide">
            &nbsp;
         </div>
         <div class="m-hero-section">
            <div class="m-content-hero">
               <div class="m1 hero-head-container" style="padding:0; margin-top: 20px;">
                  <div class="header-pingpong" style="height:126px; display: flex; align-items:center; background-color: #2d2a62; border-radius: 15px 15px 0px 0px; justify-content: center;">
                     <source srcset="https://pingpong.hks.harvard.edu/pingpong_logo_2x.png">
                     <img src="https://pingpong.hks.harvard.edu/pingpong_logo_2x.png" width="165" height="47.45" class="hero-image" style="display: block;" border="0" alt="PingPong">
                  </div>
               </div>
            </div>
         </div>
      </div>
      <!-- BEGIN MOBILE BODY -->
      <div>
      <div class="mobile mobile-bg" style="width: 0; max-height: 0; overflow: hidden; display: none;"">
         <div class="m-gutter">
            <h1 class="m-title" style="margin-top: 50px; margin-bottom: 30px; font-weight: 600; font-size: 40px; line-height:42px;letter-spacing:-1px;border-bottom:0; font-family: STIX Two Text, serif; font-weight:700;">Welcome back!</h1>
         </div>
      </div>
      <div class="mobile mobile-bg" style="width: 0; max-height: 0; overflow: hidden; display: none;">
         <div class="m-gutter">
            <p>Click the button below to log in to PingPong. No password required. It&#8217;s secure and easy.</p>
            <p>This login link will expire in a day.</p>
            <p>
               <span style="white-space: nowrap;">
            <div><a href="http://localhost:5173/api/v1/auth?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjMiLCJleHAiOjE3MDQxNTM2MDAsImlhdCI6MTcwNDA2NzIwMH0.Z6PEytos_I5QVHJp0kIzmoTjI_PyZIT5P8YVwo2SVCU&redirect=/" class="mobile-button-bg" style="display: flex; align-items: center; width: fit-content; row-gap: 8px; column-gap: 8px; font-size: 17px; line-height: 20px;font-weight: 500; border-radius: 9999px; padding: 8px 16px; color: white !important; flex-shrink: 0;">Login to PingPong<source srcset="https://pingpong.hks.harvard.edu/circle_plus_solid_2x.png"><img src="https://pingpong.hks.harvard.edu/circle_plus_solid_2x.png" width="17" height="17" class="hero-image" style="display: block;" border="0" alt="right pointing arrow"></a></div></span></p>
            <p></p>
            </p>
            <p><b>Note:</b> This login link was intended for <span style="white-space: nowrap;"><a href="mailto:user_123@domain.test" style="color:#0070c9;">user_123@domain.test</a></span>. If you weren&#8217;t expecting this login link, there&#8217;s nothing to worry about — you can safely ignore it.</p>
            <br>
         </div>
      </div>
      <div class="mobile mobile-bg" style="width: 0; max-height: 0; overflow: hidden; display: none;">
         <div class="m-gutter">
            <div class="m-divider"></div>
         </div>
      </div>
      <!-- END MOBILE BODY -->
      <!-- mobile include -->
      <!-- BEGIN MOBILE -->
      <div class="mobile get-in-touch-m mobile-bg" style="width: 0; max-height: 0; overflow: hidden; display: none;">
         <div class="m-gutter">
            <p class="m3 type-body-m"><b>Button not working?</b> Paste the following link into your browser:<br><span style="overflow-wrap: break-word; word-wrap: break-word; -ms-word-break: break-all; word-break: break-all;"><a href="http://localhost:5173/api/v1/auth?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjMiLCJleHAiOjE3MDQxNTM2MDAsImlhdCI6MTcwNDA2NzIwMH0.Z6PEytos_I5QVHJp0kIzmoTjI_PyZIT5P8YVwo2SVCU&redirect=/" style="color:#0070c9;">http://localhost:5173/api/v1/auth?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjMiLCJleHAiOjE3MDQxNTM2MDAsImlhdCI6MTcwNDA2NzIwMH0.Z6PEytos_I5QVHJp0kIzmoTjI_PyZIT5P8YVwo2SVCU&redirect=/</a></p>
         </div>
      </div>
      <!-- END MOBILE -->
      <!-- BEGIN MOBILE FOOTER -->
      <div class="mobile m-footer" style="width:0; max-height:0; overflow:hidden; display:none; margin-bottom: 20px; padding-bottom: 0px; border-radius: 0px 0px 15px 15px;">
         <div class="f-legal" style="padding-left: 0px; padding-right: 0px;">
            <div class="m-gutter">
               <p>You&#8217;re receiving this email because because you requested a login link from PingPong.
               </p>
               <p>Pingpong is developed by the Computational Policy Lab at the Harvard Kennedy School.</p>
            </div>
         </div>
      </div>
      <!-- END MOBILE FOOTER -->
      <!-- end mobile footer include -->
      <!-- desktop header include -->
      <table role="presentation" width="736" class="desktop" cellspacing="0" cellpadding="0" border="0" align="center">
         <tbody>
            <tr>
               <td align="center">
                  <!-- Hero -->
                  <table width="736" role="presentation" cellspacing="0" cellpadding="0" outline="0" border="0" align="center" style="
                     margin-top: 20px;"">
                     <tbody>
                        <tr>
                           <td class="d1 header-pingpong" align="center" style="width:736px; height:166px; background-color: #2d2a62; border-radius: 15px 15px 0px 0px; padding: 0 0 0 0;">
                              <source media="(min-device-width: 568px)" srcset="https://pingpong.hks.harvard.edu/pingpong_logo_2x.png">
                              <img src="https://pingpong.hks.harvard.edu/pingpong_logo_2x.png" width="233" height="67" class="hero-image" style="display: block;" border="0" alt="PingPong">
                           </td>
                        </tr>
                     </tbody>
                  </table>
               </td>
            </tr>
         </tbody>
      </table>
      <!-- end desktop header include -->
      <!-- BEGIN DESKTOP BODY -->
      <table role="presentation" class="desktop desktop-bg" width="736" class="desktop" cellspacing="0" cellpadding="0" border="0" align="center" style="background-color: white;">
         <tbody>
            <tr>
               <td>
                  <table cellspacing="0" width="550" border="0" cellpadding="0" align="center" class="pingpong_headline" style="margin:0 auto">
                     <tbody>
                        <tr>
                           <td align="" style="padding-top:50px;padding-bottom:25px">
                              <p style="font-family: STIX Two Text, serif;color:#111111; font-weight:700;font-size:40px;line-height:44px;letter-spacing:-1px;border-bottom:0;">Welcome back!</p>
                           </td>
                        </tr>
                     </tbody>
                  </table>
               </td>
            </tr>
         </tbody>
      </table>
      <table role="presentation" class="desktop desktop-bg" width="736" class="desktop" cellspacing="0" cellpadding="0" border="0" align="center" style="background-color: white;">
         <tbody>
            <tr>
               <td align="center">
                  <table role="presentation" width="550" cellspacing="0" cellpadding="0" border="0" align="center">
                     <tbody>
                        <tr>
                           <td class="d1" align="left" valign="top" style="padding: 0;">
                              <p>Click the button below to log in to PingPong. No password required. It&#8217;s secure and easy.</p>
                              <p>This login link will expire in a day.</p>
                              <p>
                                 <span style="white-space: nowrap;">
                              <div><a href="http://localhost:5173/api/v1/auth?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjMiLCJleHAiOjE3MDQxNTM2MDAsImlhdCI6MTcwNDA2NzIwMH0.Z6PEytos_I5QVHJp0kIzmoTjI_PyZIT5P8YVwo2SVCU&redirect=/" class="desktop-button-bg" style="display: flex; align-items: center; width: fit-content; row-gap: 8px; column-gap: 8px; font-size: 17px; line-height: 20px;font-weight: 500; border-radius: 9999px; padding: 8px 16px; color: white !important; background-color: rgb(252, 98, 77); flex-shrink: 0;">
                              Login to PingPong
                              <source srcset="https://pingpong.hks.harvard.edu/circle_plus_solid_2x.png">
                              <img src="https://pingpong.hks.harvard.edu/circle_plus_solid_2x.png" width="17" height="17" class="hero-image" style="display: block;" border="0" alt="right pointing arrow">
                              </a></div></span></p>
                              <p></p>
                              </p>
                              <p><b>Note:</b> This login link was intended for <span style="white-space: nowrap;"><a href="mailto:user_123@domain.test" style="color:#0070c9;">user_123@domain.test</a></span>. If you weren&#8217;t expecting this login link, there&#8217;s nothing to worry about — you can safely ignore it.</p>
                           </td>
                        </tr>
                     </tbody>
                  </table>
               </td>
            </tr>
         </tbody>
      </table>
      <table role="presentation" class="desktop desktop-bg" width="736" class="desktop" cellspacing="0" cellpadding="0" border="0" align="center" style="background-color: white;">
         <tbody>
            <tr>
               <td align="center">
                  <table role="presentation" width="550" cellspacing="0" cellpadding="0" border="0" align="center">
                     <tbody>
                        <tr>
                           <td width="550" style="padding: 10px 0 0 0;">&nbsp;</td>
                        </tr>
                        <tr>
                           <td width="550" valign="top" align="center" class="d-divider" style="border-color: #d6d6d6; border-top-style: solid; border-top-width: 1px; font-size: 1px; line-height: 1px;"> &nbsp;</td>
                        </tr>
                        <tr>
                           <td width="550" style="padding: 4px 0 0 0;">&nbsp;</td>
                        </tr>
                     </tbody>
                  </table>
               </td>
            </tr>
         </tbody>
      </table>
      <!-- END DESKTOP BODY -->
      <!-- desktop footer include -->
      <!-- BEGIN DESKTOP get-in-touch-cta -->
      <table role="presentation" class="desktop desktop-bg" width="736" class="desktop" cellspacing="0" cellpadding="0" border="0" align="center" style="background-color: white;">
         <tbody>
            <tr>
               <td align="center">
                  <table role="presentation" width="550" cellspacing="0" cellpadding="0" border="0" align="center">
                     <tbody>
                        <tr>
                           <td class="type-body-d" align="left" valign="top" style="padding: 3px 0 0 0;"> <b>Button not working?</b> Paste the following link into your browser:<br><span style="overflow-wrap: break-word; word-wrap: break-word; -ms-word-break: break-all; word-break: break-all;"><a href="http://localhost:5173/api/v1/auth?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjMiLCJleHAiOjE3MDQxNTM2MDAsImlhdCI6MTcwNDA2NzIwMH0.Z6PEytos_I5QVHJp0kIzmoTjI_PyZIT5P8YVwo2SVCU&redirect=/" style="color:#0070c9;">http://localhost:5173/api/v1/auth?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjMiLCJleHAiOjE3MDQxNTM2MDAsImlhdCI6MTcwNDA2NzIwMH0.Z6PEytos_I5QVHJp0kIzmoTjI_PyZIT5P8YVwo2SVCU&redirect=/</a></td>
                        </tr>
                        <tr height="4"></tr>
                     </tbody>
                  </table>
               </td>
            </tr>
         </tbody>
      </table>
      <!-- END DESKTOP get-in-touch-cta -->
      <!-- BEGIN DESKTOP FOOTER -->
      <table role="presentation" width="736" class="desktop" cellspacing="0" cellpadding="0" border="0" align="center" style="margin-bottom: 20px;">
         <tbody>
            <tr class="desktop-bg" style="background-color: white;">
               <td align="center" class="desktop-bg" style="margin: 0 auto; padding:0 20px 0 20px;" style="background-color: white;">
                  <table role="presentation" cellspacing="0" cellpadding="0" border="0" class="footer">
                     <tbody>
                        <tr>
                           <td style="padding: 19px 0 20px 0;"> </td>
                        </tr>
                     </tbody>
                  </table>
               </td>
            </tr>
            <tr>
               <td align="center" class="footer-bg" style="margin: 0 auto;background-color: #f1f4ff;padding:0 37px 0 37px; border-radius: 0px 0px 15px 15px;">
                  <table role="presentation" width="662" cellspacing="0" cellpadding="0" border="0" class="footer">
                     <tbody>
                        <td align="left" class="f-complete" style="padding: 19px 0 20px 0;">
                           <div class="f-legal">
                              <p>You&#8217;re receiving this email because because you requested a login link from PingPong.
                              </p>
                              <p>Pingpong is developed by the Computational Policy Lab at the Harvard Kennedy School.</p>
                           </div>
                        </td>
                     </tbody>
                  </table>
               </td>
            </tr>
         </tbody>
      </table>
      <!-- END DESKTOP FOOTER -->
      <!-- end desktop footer include -->
   </body>
</html>
""",
    )


@with_user(123, "foo@hks.harvard.edu")
@with_institution(11, "Harvard Kennedy School")
async def test_create_class_missing_permission(api, now, valid_user_token, institution):
    response = api.post(
        "/api/v1/institution/11/class",
        json={
            "name": "Test Class",
            "term": "Fall 2024",
            "private": False,
        },
        cookies={
            "session": valid_user_token,
        },
    )
    assert response.status_code == 403


@with_user(123, "foo@hks.harvard.edu")
@with_institution(11, "Harvard Kennedy School")
@with_authz(
    grants=[
        ("user:123", "can_create_class", "institution:11"),
    ],
)
async def test_create_class(api, now, institution, valid_user_token, authz):
    response = api.post(
        "/api/v1/institution/11/class",
        json={
            "name": "Test Class",
            "term": "Fall 2024",
            "private": False,
        },
        cookies={
            "session": valid_user_token,
        },
    )
    assert response.status_code == 200
    response_data = response.json()
    assert response.json() == {
        "id": 1,
        "institution_id": 11,
        "name": "Test Class",
        "term": "Fall 2024",
        "private": False,
        "any_can_create_assistant": False,
        "any_can_publish_assistant": False,
        "any_can_publish_thread": False,
        "any_can_upload_class_file": False,
        "created": response_data["created"],
        "updated": None,
        "institution": {
            "id": 11,
            "name": "Harvard Kennedy School",
            "description": None,
            "logo": None,
            "updated": None,
            "created": response_data["institution"]["created"],
        },
        "lms_class": None,
        "lms_last_synced": None,
        "lms_status": "none",
        "lms_user": None,
        "download_link_expiration": None,
        "last_rate_limited_at": None,
    }
    assert await authz.get_all_calls() == [
        ("grant", "institution:11", "parent", "class:1"),
        ("grant", "user:123", "teacher", "class:1"),
        ("grant", "class:1#supervisor", "can_manage_threads", "class:1"),
        ("grant", "class:1#supervisor", "can_manage_assistants", "class:1"),
    ]


@with_user(123, "foo@hks.harvard.edu")
@with_institution(11, "Harvard Kennedy School")
@with_authz(
    grants=[
        ("user:123", "can_create_class", "institution:11"),
    ],
)
async def test_create_class_private(api, now, institution, valid_user_token, authz):
    response = api.post(
        "/api/v1/institution/11/class",
        json={
            "name": "Test Class",
            "term": "Fall 2024",
            "private": True,
        },
        cookies={
            "session": valid_user_token,
        },
    )
    assert response.status_code == 200
    response_data = response.json()
    assert response.json() == {
        "id": 1,
        "institution_id": 11,
        "name": "Test Class",
        "term": "Fall 2024",
        "private": True,
        "any_can_create_assistant": False,
        "any_can_publish_assistant": False,
        "any_can_publish_thread": False,
        "any_can_upload_class_file": False,
        "created": response_data["created"],
        "updated": None,
        "institution": {
            "id": 11,
            "name": "Harvard Kennedy School",
            "description": None,
            "logo": None,
            "updated": None,
            "created": response_data["institution"]["created"],
        },
        "lms_class": None,
        "lms_last_synced": None,
        "lms_status": "none",
        "lms_user": None,
        "download_link_expiration": None,
        "last_rate_limited_at": None,
    }
    assert await authz.get_all_calls() == [
        ("grant", "institution:11", "parent", "class:1"),
        ("grant", "user:123", "teacher", "class:1"),
    ]
