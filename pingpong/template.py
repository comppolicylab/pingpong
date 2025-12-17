from string import Template

email_template = Template("""
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
      <div class="mobile mobile-bg" style="width: 0; max-height: 0; overflow: hidden; display: none;">
         <div class="m-gutter">
            <h1 class="m-title" style="margin-top: 50px; margin-bottom: 30px; font-weight: 600; font-size: 40px; line-height:42px;letter-spacing:-1px;border-bottom:0; font-family: STIX Two Text, serif; font-weight:700;">$title</h1>
         </div>
      </div>
      <div class="mobile mobile-bg" style="width: 0; max-height: 0; overflow: hidden; display: none;">
         <div class="m-gutter">
            <p>$subtitle</p>
            <p>This $type will expire in $expires.</p>
            <p>
               <span style="white-space: nowrap;">
            <div><a href="$link" class="mobile-button-bg" style="display: flex; align-items: center; width: fit-content; row-gap: 8px; column-gap: 8px; font-size: 17px; line-height: 20px;font-weight: 500; border-radius: 9999px; padding: 8px 16px; color: white !important; flex-shrink: 0;">$cta<source srcset="https://pingpong.hks.harvard.edu/circle_plus_solid_2x.png"><img src="https://pingpong.hks.harvard.edu/circle_plus_solid_2x.png" width="17" height="17" class="hero-image" style="display: block;" border="0" alt="right pointing arrow"></a></div></span></p>
            <p>$underline</p>
            </p>
            <p><b>Note:</b> This $type was intended for <span style="white-space: nowrap;"><a href="mailto:$email" style="color:#0070c9;">$email</a></span>. If you weren&#8217;t expecting this $type, there&#8217;s nothing to worry about — you can safely ignore it.</p>
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
            <p class="m3 type-body-m"><b>Button not working?</b> Paste the following link into your browser:<br><span style="overflow-wrap: break-word; word-wrap: break-word; -ms-word-break: break-all; word-break: break-all;"><a href="$link" style="color:#0070c9;">$link</a></p>
         </div>
      </div>
      <!-- END MOBILE -->
      <!-- BEGIN MOBILE FOOTER -->
      <div class="mobile m-footer" style="width:0; max-height:0; overflow:hidden; display:none; margin-bottom: 20px; padding-bottom: 0px; border-radius: 0px 0px 15px 15px;">
         <div class="f-legal" style="padding-left: 0px; padding-right: 0px;">
            <div class="m-gutter">
               <p>You&#8217;re receiving this email because $legal_text.
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
                     margin-top: 20px;">
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
                              <p style="font-family: STIX Two Text, serif;color:#111111; font-weight:700;font-size:40px;line-height:44px;letter-spacing:-1px;border-bottom:0;">$title</p>
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
                              <p>$subtitle</p>
                              <p>This $type will expire in $expires.</p>
                              <p>
                                 <span style="white-space: nowrap;">
                              <div><a href="$link" class="desktop-button-bg" style="display: flex; align-items: center; width: fit-content; row-gap: 8px; column-gap: 8px; font-size: 17px; line-height: 20px;font-weight: 500; border-radius: 9999px; padding: 8px 16px; color: white !important; background-color: rgb(252, 98, 77); flex-shrink: 0;">
                              $cta
                              <source srcset="https://pingpong.hks.harvard.edu/circle_plus_solid_2x.png">
                              <img src="https://pingpong.hks.harvard.edu/circle_plus_solid_2x.png" width="17" height="17" class="hero-image" style="display: block;" border="0" alt="right pointing arrow">
                              </a></div></span></p>
                              <p>$underline</p>
                              </p>
                              <p><b>Note:</b> This $type was intended for <span style="white-space: nowrap;"><a href="mailto:$email" style="color:#0070c9;">$email</a></span>. If you weren&#8217;t expecting this $type, there&#8217;s nothing to worry about — you can safely ignore it.</p>
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
                           <td class="type-body-d" align="left" valign="top" style="padding: 3px 0 0 0;"> <b>Button not working?</b> Paste the following link into your browser:<br><span style="overflow-wrap: break-word; word-wrap: break-word; -ms-word-break: break-all; word-break: break-all;"><a href="$link" style="color:#0070c9;">$link</a></td>
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
                              <p>You&#8217;re receiving this email because $legal_text.
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
""")

notification_template = Template("""
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
      <div class="mobile mobile-bg" style="width: 0; max-height: 0; overflow: hidden; display: none;">
         <div class="m-gutter">
            <h1 class="m-title" style="margin-top: 50px; margin-bottom: 30px; font-weight: 600; font-size: 40px; line-height:42px;letter-spacing:-1px;border-bottom:0; font-family: STIX Two Text, serif; font-weight:700;">$title</h1>
         </div>
      </div>
      <div class="mobile mobile-bg" style="width: 0; max-height: 0; overflow: hidden; display: none;">
         <div class="m-gutter">
            <p>$subtitle</p>
            <br>
         </div>
      </div>
      <div class="mobile mobile-bg" style="width: 0; max-height: 0; overflow: hidden; display: none;">
         <div class="m-gutter">
            <div class="m-divider"></div>
         </div>
      </div>
      <!-- END MOBILE BODY -->
      <!-- BEGIN MOBILE FOOTER -->
      <div class="mobile m-footer" style="width:0; max-height:0; overflow:hidden; display:none; margin-bottom: 20px; padding-bottom: 0px; border-radius: 0px 0px 15px 15px;">
         <div class="f-legal" style="padding-left: 0px; padding-right: 0px;">
            <div class="m-gutter">
               <p>You&#8217;re receiving this email because $legal_text.
               </p>
               <p>Pingpong is developed by the Computational Policy Lab at the Harvard Kennedy School.</p>
            </div>
         </div>
      </div>
      <!-- END MOBILE FOOTER -->
      <!-- desktop header include -->
      <table role="presentation" width="736" class="desktop" cellspacing="0" cellpadding="0" border="0" align="center">
         <tbody>
            <tr>
               <td align="center">
                  <!-- Hero -->
                  <table width="736" role="presentation" cellspacing="0" cellpadding="0" outline="0" border="0" align="center" style="
                     margin-top: 20px;">
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
                              <p style="font-family: STIX Two Text, serif;color:#111111; font-weight:700;font-size:40px;line-height:44px;letter-spacing:-1px;border-bottom:0;">$title</p>
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
                              <p>$subtitle</p>
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
                              <p>You&#8217;re receiving this email because $legal_text.
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
   </body>
</html>
""")

summary_template = Template("""
<!doctype html>
<html>
   <head>
      <meta name="comm-name" content="summary-notification">
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
         .summary-section {
         margin-bottom: 30px;
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
         .summary-container {
         position: relative;
         margin: 20px 0 20px 0;
         display: flex;
         flex-direction: column;
         }
         .summary-box {
         background-color: #ffffff;
         border: 1px solid #d6d6d6;
         border-radius: 8px;
         padding: 20px;
         position: relative;
         box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
         z-index: 1;
         }
         .summary-box p {
         color: #3e3838;
         margin-left: 15px;
         margin-bottom: 0;
         }
         .link-row {
         margin: 2px 0 8px 0px;
         display: flex;
         align-items: center;
         gap: 5px;
         }
         .link-row:last-child {
         margin-bottom: 0;
         }
         .link-label {
         font-size: 12px;
         color: #8a8a8a;
         margin-right: 5px;
         }
         .numbered-circle {
         display: inline-block;
         width: 16px;
         height: 16px;
         border: 1px solid #8a8a8a;
         border-radius: 50%;
         text-align: center;
         line-height: 16px;
         font-size: 12px;
         margin-right: 5px;
         text-decoration: none;
         color: #8a8a8a !important;
         }
         .numbered-circle:hover {
         text-decoration: none !important;
         opacity: 0.8;
         }
         .summary-tab {
         background-color: #f7f7f7;
         border: 1px solid #d6d6d6;
         border-radius: 8px 8px 0 0;
         padding: 4px 12px;
         font-size: 14px;
         color: #3e3838;
         padding-top: 5px;
         padding-bottom: 10px;
         margin-left: 3%;
         margin-bottom: -5px;
         line-height: 120%;
         width: fit-content;
         max-width: 70%;
         box-shadow: 0 -2px 4px rgba(0, 0, 0, 0.05);
         }
         .summary-box ul {
         margin: 0;
         padding: 0 0 0 15px;
         list-style-type: disc;
         color: #3e3838;
         }
         .summary-box ul li {
         color: #3e3838;
         margin-bottom: 2px;
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
         color: #b6320a !important;
         border-color: #b6320a !important;
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
         a.numbered-circle, a.numbered-circle:link, a.numbered-circle:visited {
         color: #9e9e9e !important;
         border-color: #9e9e9e !important;
         }
         a.numbered-circle:hover {
         color: #9e9e9e !important;
         opacity: 0.8;
         text-decoration: none !important;
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
         .summary-box {
         background-color: #2d2d2d;
         border-color: #404040;
         box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
         }
         .summary-box p {
         color: #ffffff !important;
         }
         .summary-tab {
         background-color: #1f1f1f;
         border-color: #404040;
         color: #ffffff;
         box-shadow: 0 -2px 8px rgba(0, 0, 0, 0.2);
         }
         .link-label {
         color: #9e9e9e !important;
         }
         .numbered-circle {
         color: #9e9e9e !important;
         border-color: #9e9e9e !important;
         }
         .numbered-circle:hover {
         color: #9e9e9e !important;
         opacity: 0.8;
         }
         .summary-box ul li {
         color: #ffffff !important;
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
         background-color: white;
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
         background-color: #111517;
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
      <div class="mobile mobile-bg" style="width: 0; max-height: 0; overflow: hidden; display: none;">
         <div class="m-gutter">
            <h1 class="m-title" style="margin-top: 50px; margin-bottom: 30px; font-weight: 600; font-size: 40px; line-height:42px;letter-spacing:-1px;border-bottom:0; font-family: STIX Two Text, serif; font-weight:700;">$title</h1>
         </div>
      </div>
      <div class="mobile mobile-bg" style="width: 0; max-height: 0; overflow: hidden; display: none;">
         <div class="m-gutter">
            <p>Dear $name,</p>
            <p>Here's a summary of all <strong>$courseName</strong> activity on PingPong in $time:</p>
            <div class="summary-section">
               $summary
            </div>
            <p>
            <p> If you’d rather not receive weekly recap emails, you can modify your preferences on your group's <i>Manage Group</i> page.</p>
            <span style="white-space: nowrap;">
               <div><a href="$link" class="mobile-button-bg" style="display: flex; align-items: center; width: fit-content; row-gap: 8px; column-gap: 8px; font-size: 15px; line-height: 16px;font-weight: 500; border-radius: 9999px; padding: 8px 16px; color: rgb(252, 98, 77) !important; border-color: rgb(252, 98, 77); border-width: 1.5px !important; flex-shrink: 0; border: solid;">Manage Preferences</a></div>
            </span>
            </p>
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
            <p class="m3 type-body-m"><b>Button not working?</b> Paste the following link into your browser:<br><span style="overflow-wrap: break-word; word-wrap: break-word; -ms-word-break: break-all; word-break: break-all;"><a href="$link" style="color:#0070c9;">$link</a></p>
         </div>
      </div>
      <!-- END MOBILE -->
      <!-- BEGIN MOBILE FOOTER -->
      <div class="mobile m-footer" style="width:0; max-height:0; overflow:hidden; display:none; margin-bottom: 20px; padding-bottom: 0px; border-radius: 0px 0px 15px 15px;">
         <div class="f-legal" style="padding-left: 0px; padding-right: 0px;">
            <div class="m-gutter">
               <p>You&#8217;re receiving this email because $legal_text.
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
                     margin-top: 20px;">
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
                              <p style="font-family: STIX Two Text, serif;color:#111111; font-weight:700;font-size:40px;line-height:44px;letter-spacing:-1px;border-bottom:0;">$title</p>
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
                              <p>Dear $name,</p>
                              <p>Here's a summary of all <strong>$courseName</strong> activity on PingPong in $time:</p>
                              <div class="summary-section">
                                $summary
                              </div>
                              <p>
                              <p> If you’d rather not receive weekly recap emails, you can modify your preferences on your group's <i>Manage Group</i> page.</p>
                              <span style="white-space: nowrap;">
                                 <div><a href="$link" class="desktop-button-bg" style="display: flex; align-items: center; width: fit-content; row-gap: 8px; column-gap: 8px; font-size: 15px; line-height: 15px;font-weight: 500; border-radius: 9999px; padding: 8px 14px; color: rgb(252, 98, 77) !important; border-color: rgb(252, 98, 77); border-width: 1.5px !important; flex-shrink: 0; border: solid;">
                                    Manage Preferences
                                    </a>
                                 </div>
                              </span>
                              </p>
                              </p>
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
                           <td class="type-body-d" align="left" valign="top" style="padding: 3px 0 0 0;"> <b>Button not working?</b> Paste the following link into your browser:<br><span style="overflow-wrap: break-word; word-wrap: break-word; -ms-word-break: break-all; word-break: break-all;"><a href="$link" style="color:#0070c9;">$link</a></td>
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
                              <p>You&#8217;re receiving this email because $legal_text.
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
""")
