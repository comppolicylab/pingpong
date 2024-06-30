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
         .header-pingpong {
         background-color: #2d2a62;
         }
         .desktop-bg {
         background-color: white;
         }
         .desktop-button-bg {
         background-color: rgb(252, 98, 77);
         }
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
         background-color: #1A1834;
         }
         .desktop-bg {
         background-color: #111517;
         }
         .desktop-button-bg {
         background-color: #b6320a;
         }
         .d-divider {
         border-top: solid 1px #808080 !important;
         }
         body {
         background-color: transparent;
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
      <!-- mobile header include -->
      <div class="mobile" style="width: 0; max-height: 0; overflow: hidden; display: none;">
         <div style="display:none !important;position: absolute; font-size:0; line-height:1; max-height:0; max-width:0; opacity:0; overflow:hidden; color: #333333" class="preheader-hide">
            &nbsp;
         </div>
         <div class="m-hero-section">
            <div class="m-content-hero">
               <div class="m1 hero-head-container" style="padding:0; margin-top: 20px;">
                  <div class="header-pingpong" style="height:126px; display: flex; align-items:center; border-radius: 15px 15px 0px 0px; justify-content: center;">
                     <svg width="233" height="67" viewBox="0 0 233 67" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <circle cx="228.5" cy="46.5" r="4.5" fill="#FC624D"></circle>
                        <path d="M4.264 16.872H16.224C18.928 16.872 21.1467 17.1667 22.88 17.756C24.6133 18.3107 25.9653 19.0733 26.936 20.044C27.9413 21.0147 28.6347 22.1587 29.016 23.476C29.3973 24.7587 29.588 26.128 29.588 27.584C29.588 29.1093 29.38 30.5653 28.964 31.952C28.5827 33.3387 27.8893 34.552 26.884 35.592C25.8787 36.632 24.5093 37.464 22.776 38.088C21.0427 38.6773 18.824 38.972 16.12 38.972H7.384V54H4.264V16.872ZM16.172 36.216C18.252 36.216 19.9507 36.0253 21.268 35.644C22.5853 35.228 23.6253 34.656 24.388 33.928C25.1507 33.2 25.6707 32.316 25.948 31.276C26.2253 30.236 26.364 29.0573 26.364 27.74C26.364 26.3533 26.208 25.1573 25.896 24.152C25.584 23.1467 25.0293 22.3147 24.232 21.656C23.4693 20.9627 22.4293 20.46 21.112 20.148C19.7947 19.8013 18.1307 19.628 16.12 19.628H7.384V36.216H16.172ZM35.4835 27.22H38.4995V54H35.4835V27.22ZM35.2755 16.872H38.7075V21.396H35.2755V16.872ZM45.9408 27.22H48.9568V31.588C50.4128 29.7507 51.9554 28.4333 53.5848 27.636C55.2488 26.804 57.0168 26.388 58.8888 26.388C61.9394 26.388 64.1928 27.2373 65.6488 28.936C67.1048 30.6347 67.8328 33.044 67.8328 36.164V54H64.8168V36.996C64.8168 34.188 64.3141 32.1773 63.3088 30.964C62.3034 29.716 60.7088 29.092 58.5248 29.092C57.4848 29.092 56.3754 29.3 55.1968 29.716C54.0528 30.0973 53.0128 30.7213 52.0768 31.588C51.0368 32.4893 50.2568 33.4253 49.7368 34.396C49.2168 35.332 48.9568 36.632 48.9568 38.296V54H45.9408V27.22ZM77.8489 56.912C78.2302 58.68 79.0622 59.98 80.3449 60.812C81.6275 61.6787 83.5862 62.112 86.2209 62.112C89.1675 62.112 91.3342 61.384 92.7209 59.928C94.1075 58.5067 94.8009 56.0973 94.8009 52.7V48.696C93.6915 50.256 92.3742 51.4693 90.8489 52.336C89.3582 53.168 87.5729 53.584 85.4929 53.584C83.5169 53.584 81.8009 53.22 80.3449 52.492C78.8889 51.7293 77.6929 50.724 76.7569 49.476C75.8209 48.228 75.1275 46.8067 74.6769 45.212C74.2262 43.5827 74.0009 41.9013 74.0009 40.168C74.0009 38.088 74.2782 36.1987 74.8329 34.5C75.3875 32.8013 76.1849 31.3627 77.2249 30.184C78.2649 28.9707 79.5302 28.0347 81.0209 27.376C82.5115 26.7173 84.1929 26.388 86.0649 26.388C87.5555 26.388 89.0635 26.7173 90.5889 27.376C92.1142 28 93.5182 29.1613 94.8009 30.86V27.22H97.8169V53.012C97.8169 56.6173 96.8809 59.46 95.0089 61.54C93.1715 63.62 90.2595 64.66 86.2729 64.66C84.7475 64.66 83.3262 64.5213 82.0089 64.244C80.7262 63.9667 79.5822 63.516 78.5769 62.892C77.6062 62.3027 76.8089 61.5053 76.1849 60.5C75.5609 59.5293 75.1622 58.3333 74.9889 56.912H77.8489ZM94.9049 39.544C94.9049 38.3307 94.8355 37.2907 94.6969 36.424C94.5929 35.5227 94.3849 34.7427 94.0729 34.084C93.7955 33.3907 93.4315 32.784 92.9809 32.264C92.5302 31.744 91.9929 31.2413 91.3689 30.756C90.5022 30.132 89.6702 29.6813 88.8729 29.404C88.0755 29.1267 87.1569 28.988 86.1169 28.988C84.8342 28.988 83.6555 29.196 82.5809 29.612C81.5062 30.028 80.5702 30.6867 79.7729 31.588C78.9755 32.4893 78.3515 33.6507 77.9009 35.072C77.4502 36.4587 77.2249 38.14 77.2249 40.116C77.2249 42.1267 77.4675 43.8253 77.9529 45.212C78.4729 46.564 79.1315 47.6733 79.9289 48.54C80.7262 49.372 81.6275 49.9787 82.6329 50.36C83.6382 50.7413 84.6609 50.932 85.7009 50.932C86.8449 50.932 87.8155 50.8107 88.6129 50.568C89.4102 50.3253 90.2595 49.892 91.1609 49.268C92.3742 48.3667 93.2929 47.2227 93.9169 45.836C94.5755 44.4147 94.9049 42.6467 94.9049 40.532V39.544ZM105.725 16.872H117.685C120.389 16.872 122.608 17.1667 124.341 17.756C126.074 18.3107 127.426 19.0733 128.397 20.044C129.402 21.0147 130.096 22.1587 130.477 23.476C130.858 24.7587 131.049 26.128 131.049 27.584C131.049 29.1093 130.841 30.5653 130.425 31.952C130.044 33.3387 129.35 34.552 128.345 35.592C127.34 36.632 125.97 37.464 124.237 38.088C122.504 38.6773 120.285 38.972 117.581 38.972H108.845V54H105.725V16.872ZM117.633 36.216C119.713 36.216 121.412 36.0253 122.729 35.644C124.046 35.228 125.086 34.656 125.849 33.928C126.612 33.2 127.132 32.316 127.409 31.276C127.686 30.236 127.825 29.0573 127.825 27.74C127.825 26.3533 127.669 25.1573 127.357 24.152C127.045 23.1467 126.49 22.3147 125.693 21.656C124.93 20.9627 123.89 20.46 122.573 20.148C121.256 19.8013 119.592 19.628 117.581 19.628H108.845V36.216H117.633ZM147.22 52.232C148.919 52.232 150.357 51.9373 151.536 51.348C152.715 50.724 153.685 49.892 154.448 48.852C155.211 47.812 155.765 46.5813 156.112 45.16C156.459 43.7387 156.632 42.196 156.632 40.532C156.632 38.9373 156.459 37.4467 156.112 36.06C155.765 34.6387 155.211 33.408 154.448 32.368C153.685 31.328 152.715 30.5133 151.536 29.924C150.357 29.3 148.919 28.988 147.22 28.988C145.556 28.988 144.117 29.3 142.904 29.924C141.725 30.5133 140.755 31.328 139.992 32.368C139.264 33.408 138.727 34.6387 138.38 36.06C138.033 37.4467 137.86 38.9547 137.86 40.584C137.86 42.2133 138.033 43.7387 138.38 45.16C138.727 46.5813 139.264 47.812 139.992 48.852C140.755 49.892 141.725 50.724 142.904 51.348C144.117 51.9373 145.556 52.232 147.22 52.232ZM147.116 54.832C145.14 54.832 143.372 54.5027 141.812 53.844C140.287 53.1853 138.987 52.2493 137.912 51.036C136.872 49.788 136.057 48.2973 135.468 46.564C134.913 44.8307 134.636 42.8893 134.636 40.74C134.636 38.556 134.931 36.58 135.52 34.812C136.144 33.044 136.993 31.536 138.068 30.288C139.177 29.04 140.512 28.0867 142.072 27.428C143.632 26.7347 145.383 26.388 147.324 26.388C149.265 26.388 151.016 26.7173 152.576 27.376C154.136 28.0347 155.453 28.988 156.528 30.236C157.603 31.4493 158.417 32.9227 158.972 34.656C159.561 36.3893 159.856 38.3133 159.856 40.428C159.856 42.612 159.561 44.588 158.972 46.356C158.383 48.124 157.533 49.6493 156.424 50.932C155.349 52.18 154.015 53.1507 152.42 53.844C150.86 54.5027 149.092 54.832 147.116 54.832ZM166.292 27.22H169.308V31.588C170.764 29.7507 172.307 28.4333 173.936 27.636C175.6 26.804 177.368 26.388 179.24 26.388C182.291 26.388 184.544 27.2373 186 28.936C187.456 30.6347 188.184 33.044 188.184 36.164V54H185.168V36.996C185.168 34.188 184.666 32.1773 183.66 30.964C182.655 29.716 181.06 29.092 178.876 29.092C177.836 29.092 176.727 29.3 175.548 29.716C174.404 30.0973 173.364 30.7213 172.428 31.588C171.388 32.4893 170.608 33.4253 170.088 34.396C169.568 35.332 169.308 36.632 169.308 38.296V54H166.292V27.22ZM198.2 56.912C198.582 58.68 199.414 59.98 200.696 60.812C201.979 61.6787 203.938 62.112 206.572 62.112C209.519 62.112 211.686 61.384 213.072 59.928C214.459 58.5067 215.152 56.0973 215.152 52.7V48.696C214.043 50.256 212.726 51.4693 211.2 52.336C209.71 53.168 207.924 53.584 205.844 53.584C203.868 53.584 202.152 53.22 200.696 52.492C199.24 51.7293 198.044 50.724 197.108 49.476C196.172 48.228 195.479 46.8067 195.028 45.212C194.578 43.5827 194.352 41.9013 194.352 40.168C194.352 38.088 194.63 36.1987 195.184 34.5C195.739 32.8013 196.536 31.3627 197.576 30.184C198.616 28.9707 199.882 28.0347 201.372 27.376C202.863 26.7173 204.544 26.388 206.416 26.388C207.907 26.388 209.415 26.7173 210.94 27.376C212.466 28 213.87 29.1613 215.152 30.86V27.22H218.168V53.012C218.168 56.6173 217.232 59.46 215.36 61.54C213.523 63.62 210.611 64.66 206.624 64.66C205.099 64.66 203.678 64.5213 202.36 64.244C201.078 63.9667 199.934 63.516 198.928 62.892C197.958 62.3027 197.16 61.5053 196.536 60.5C195.912 59.5293 195.514 58.3333 195.34 56.912H198.2ZM215.256 39.544C215.256 38.3307 215.187 37.2907 215.048 36.424C214.944 35.5227 214.736 34.7427 214.424 34.084C214.147 33.3907 213.783 32.784 213.332 32.264C212.882 31.744 212.344 31.2413 211.72 30.756C210.854 30.132 210.022 29.6813 209.224 29.404C208.427 29.1267 207.508 28.988 206.468 28.988C205.186 28.988 204.007 29.196 202.932 29.612C201.858 30.028 200.922 30.6867 200.124 31.588C199.327 32.4893 198.703 33.6507 198.252 35.072C197.802 36.4587 197.576 38.14 197.576 40.116C197.576 42.1267 197.819 43.8253 198.304 45.212C198.824 46.564 199.483 47.6733 200.28 48.54C201.078 49.372 201.979 49.9787 202.984 50.36C203.99 50.7413 205.012 50.932 206.052 50.932C207.196 50.932 208.167 50.8107 208.964 50.568C209.762 50.3253 210.611 49.892 211.512 49.268C212.726 48.3667 213.644 47.2227 214.268 45.836C214.927 44.4147 215.256 42.6467 215.256 40.532V39.544Z" fill="white"></path>
                        <circle cx="36.5" cy="18.5" r="4.5" fill="#FC624D"></circle>
                     </svg>
                  </div>
               </div>
            </div>
         </div>
      </div>
      <!-- end mobile addressee include -->
      <!-- BEGIN MOBILE BODY -->
      <div>
      <div class="mobile mobile-bg" style="width: 0; max-height: 0; overflow: hidden; display: none;"">
         <div class="m-gutter">
            <h1 class="m-title" style="margin-top: 50px; margin-bottom: 30px; font-weight: 600; font-size: 40px; line-height:42px;letter-spacing:-1px;border-bottom:0; font-family: STIX Two Text, serif; font-weight:700;"> $title</h1>
         </div>
      </div>
      <div class="mobile mobile-bg" style="width: 0; max-height: 0; overflow: hidden; display: none;">
         <div class="m-gutter">
            <p>$subtitle</p>
            <p>This $type will expire in 7 days.</p>
            <p>
               <span style="white-space: nowrap;">
            <div><a href="$link" class="mobile-button-bg" style="display: flex; align-items: center; width: fit-content; row-gap: 8px; column-gap: 8px; font-size: 17px; line-height: 20px;font-weight: 500; border-radius: 9999px; padding: 8px 16px; color: white !important; flex-shrink: 0;">$cta<svg xmlns="http://www.w3.org/2000/svg" width="17" height="17" fill="none" role="img" aria-label="circle plus solid" viewBox="0 0 24 24"><path fill="currentColor" fill-rule="evenodd" d="M12 2c5.514 0 10 4.486 10 10s-4.486 10-10 10-10-4.486-10-10 4.486-10 10-10zm0-2c-6.627 0-12 5.373-12 12s5.373 12 12 12 12-5.373 12-12-5.373-12-12-12zm2 12l-4.5 4.5 1.527 1.5 5.973-6-5.973-6-1.527 1.5 4.5 4.5z" clip-rule="evenodd"/></svg></a></div></span></p>
            <p>$underline</p>
            </p>
            <p><b>Note:</b> This $type was intended for <span style="white-space: nowrap;"><a href="$email" style="color:#0070c9;">$email</a></span>. If you weren&#8217;t expecting this $type, there&#8217;s nothing to worry about — you can safely ignore it.</p>
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
               <p>Pingpong is developed by the Computational Policy Lab at the Harvard Kennedy School. All content © 2024 Computational Policy Lab. All rights reserved.</p>
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
                  <table width="712" role="presentation" cellspacing="0" cellpadding="0" outline="0" border="0" align="center" style="
                     margin-top: 20px;"">
                     <tbody>
                        <tr>
                           <td class="d1" align="center" style="padding: 0 0 0 0;">
                              <div class="header-pingpong" style="width:736px; height:166px; display: flex; align-items:center; border-radius: 15px 15px 0px 0px; justify-content: center;">
                                 <svg width="233" height="67" viewBox="0 0 233 67" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <circle cx="228.5" cy="46.5" r="4.5" fill="#FC624D"></circle>
                                    <path d="M4.264 16.872H16.224C18.928 16.872 21.1467 17.1667 22.88 17.756C24.6133 18.3107 25.9653 19.0733 26.936 20.044C27.9413 21.0147 28.6347 22.1587 29.016 23.476C29.3973 24.7587 29.588 26.128 29.588 27.584C29.588 29.1093 29.38 30.5653 28.964 31.952C28.5827 33.3387 27.8893 34.552 26.884 35.592C25.8787 36.632 24.5093 37.464 22.776 38.088C21.0427 38.6773 18.824 38.972 16.12 38.972H7.384V54H4.264V16.872ZM16.172 36.216C18.252 36.216 19.9507 36.0253 21.268 35.644C22.5853 35.228 23.6253 34.656 24.388 33.928C25.1507 33.2 25.6707 32.316 25.948 31.276C26.2253 30.236 26.364 29.0573 26.364 27.74C26.364 26.3533 26.208 25.1573 25.896 24.152C25.584 23.1467 25.0293 22.3147 24.232 21.656C23.4693 20.9627 22.4293 20.46 21.112 20.148C19.7947 19.8013 18.1307 19.628 16.12 19.628H7.384V36.216H16.172ZM35.4835 27.22H38.4995V54H35.4835V27.22ZM35.2755 16.872H38.7075V21.396H35.2755V16.872ZM45.9408 27.22H48.9568V31.588C50.4128 29.7507 51.9554 28.4333 53.5848 27.636C55.2488 26.804 57.0168 26.388 58.8888 26.388C61.9394 26.388 64.1928 27.2373 65.6488 28.936C67.1048 30.6347 67.8328 33.044 67.8328 36.164V54H64.8168V36.996C64.8168 34.188 64.3141 32.1773 63.3088 30.964C62.3034 29.716 60.7088 29.092 58.5248 29.092C57.4848 29.092 56.3754 29.3 55.1968 29.716C54.0528 30.0973 53.0128 30.7213 52.0768 31.588C51.0368 32.4893 50.2568 33.4253 49.7368 34.396C49.2168 35.332 48.9568 36.632 48.9568 38.296V54H45.9408V27.22ZM77.8489 56.912C78.2302 58.68 79.0622 59.98 80.3449 60.812C81.6275 61.6787 83.5862 62.112 86.2209 62.112C89.1675 62.112 91.3342 61.384 92.7209 59.928C94.1075 58.5067 94.8009 56.0973 94.8009 52.7V48.696C93.6915 50.256 92.3742 51.4693 90.8489 52.336C89.3582 53.168 87.5729 53.584 85.4929 53.584C83.5169 53.584 81.8009 53.22 80.3449 52.492C78.8889 51.7293 77.6929 50.724 76.7569 49.476C75.8209 48.228 75.1275 46.8067 74.6769 45.212C74.2262 43.5827 74.0009 41.9013 74.0009 40.168C74.0009 38.088 74.2782 36.1987 74.8329 34.5C75.3875 32.8013 76.1849 31.3627 77.2249 30.184C78.2649 28.9707 79.5302 28.0347 81.0209 27.376C82.5115 26.7173 84.1929 26.388 86.0649 26.388C87.5555 26.388 89.0635 26.7173 90.5889 27.376C92.1142 28 93.5182 29.1613 94.8009 30.86V27.22H97.8169V53.012C97.8169 56.6173 96.8809 59.46 95.0089 61.54C93.1715 63.62 90.2595 64.66 86.2729 64.66C84.7475 64.66 83.3262 64.5213 82.0089 64.244C80.7262 63.9667 79.5822 63.516 78.5769 62.892C77.6062 62.3027 76.8089 61.5053 76.1849 60.5C75.5609 59.5293 75.1622 58.3333 74.9889 56.912H77.8489ZM94.9049 39.544C94.9049 38.3307 94.8355 37.2907 94.6969 36.424C94.5929 35.5227 94.3849 34.7427 94.0729 34.084C93.7955 33.3907 93.4315 32.784 92.9809 32.264C92.5302 31.744 91.9929 31.2413 91.3689 30.756C90.5022 30.132 89.6702 29.6813 88.8729 29.404C88.0755 29.1267 87.1569 28.988 86.1169 28.988C84.8342 28.988 83.6555 29.196 82.5809 29.612C81.5062 30.028 80.5702 30.6867 79.7729 31.588C78.9755 32.4893 78.3515 33.6507 77.9009 35.072C77.4502 36.4587 77.2249 38.14 77.2249 40.116C77.2249 42.1267 77.4675 43.8253 77.9529 45.212C78.4729 46.564 79.1315 47.6733 79.9289 48.54C80.7262 49.372 81.6275 49.9787 82.6329 50.36C83.6382 50.7413 84.6609 50.932 85.7009 50.932C86.8449 50.932 87.8155 50.8107 88.6129 50.568C89.4102 50.3253 90.2595 49.892 91.1609 49.268C92.3742 48.3667 93.2929 47.2227 93.9169 45.836C94.5755 44.4147 94.9049 42.6467 94.9049 40.532V39.544ZM105.725 16.872H117.685C120.389 16.872 122.608 17.1667 124.341 17.756C126.074 18.3107 127.426 19.0733 128.397 20.044C129.402 21.0147 130.096 22.1587 130.477 23.476C130.858 24.7587 131.049 26.128 131.049 27.584C131.049 29.1093 130.841 30.5653 130.425 31.952C130.044 33.3387 129.35 34.552 128.345 35.592C127.34 36.632 125.97 37.464 124.237 38.088C122.504 38.6773 120.285 38.972 117.581 38.972H108.845V54H105.725V16.872ZM117.633 36.216C119.713 36.216 121.412 36.0253 122.729 35.644C124.046 35.228 125.086 34.656 125.849 33.928C126.612 33.2 127.132 32.316 127.409 31.276C127.686 30.236 127.825 29.0573 127.825 27.74C127.825 26.3533 127.669 25.1573 127.357 24.152C127.045 23.1467 126.49 22.3147 125.693 21.656C124.93 20.9627 123.89 20.46 122.573 20.148C121.256 19.8013 119.592 19.628 117.581 19.628H108.845V36.216H117.633ZM147.22 52.232C148.919 52.232 150.357 51.9373 151.536 51.348C152.715 50.724 153.685 49.892 154.448 48.852C155.211 47.812 155.765 46.5813 156.112 45.16C156.459 43.7387 156.632 42.196 156.632 40.532C156.632 38.9373 156.459 37.4467 156.112 36.06C155.765 34.6387 155.211 33.408 154.448 32.368C153.685 31.328 152.715 30.5133 151.536 29.924C150.357 29.3 148.919 28.988 147.22 28.988C145.556 28.988 144.117 29.3 142.904 29.924C141.725 30.5133 140.755 31.328 139.992 32.368C139.264 33.408 138.727 34.6387 138.38 36.06C138.033 37.4467 137.86 38.9547 137.86 40.584C137.86 42.2133 138.033 43.7387 138.38 45.16C138.727 46.5813 139.264 47.812 139.992 48.852C140.755 49.892 141.725 50.724 142.904 51.348C144.117 51.9373 145.556 52.232 147.22 52.232ZM147.116 54.832C145.14 54.832 143.372 54.5027 141.812 53.844C140.287 53.1853 138.987 52.2493 137.912 51.036C136.872 49.788 136.057 48.2973 135.468 46.564C134.913 44.8307 134.636 42.8893 134.636 40.74C134.636 38.556 134.931 36.58 135.52 34.812C136.144 33.044 136.993 31.536 138.068 30.288C139.177 29.04 140.512 28.0867 142.072 27.428C143.632 26.7347 145.383 26.388 147.324 26.388C149.265 26.388 151.016 26.7173 152.576 27.376C154.136 28.0347 155.453 28.988 156.528 30.236C157.603 31.4493 158.417 32.9227 158.972 34.656C159.561 36.3893 159.856 38.3133 159.856 40.428C159.856 42.612 159.561 44.588 158.972 46.356C158.383 48.124 157.533 49.6493 156.424 50.932C155.349 52.18 154.015 53.1507 152.42 53.844C150.86 54.5027 149.092 54.832 147.116 54.832ZM166.292 27.22H169.308V31.588C170.764 29.7507 172.307 28.4333 173.936 27.636C175.6 26.804 177.368 26.388 179.24 26.388C182.291 26.388 184.544 27.2373 186 28.936C187.456 30.6347 188.184 33.044 188.184 36.164V54H185.168V36.996C185.168 34.188 184.666 32.1773 183.66 30.964C182.655 29.716 181.06 29.092 178.876 29.092C177.836 29.092 176.727 29.3 175.548 29.716C174.404 30.0973 173.364 30.7213 172.428 31.588C171.388 32.4893 170.608 33.4253 170.088 34.396C169.568 35.332 169.308 36.632 169.308 38.296V54H166.292V27.22ZM198.2 56.912C198.582 58.68 199.414 59.98 200.696 60.812C201.979 61.6787 203.938 62.112 206.572 62.112C209.519 62.112 211.686 61.384 213.072 59.928C214.459 58.5067 215.152 56.0973 215.152 52.7V48.696C214.043 50.256 212.726 51.4693 211.2 52.336C209.71 53.168 207.924 53.584 205.844 53.584C203.868 53.584 202.152 53.22 200.696 52.492C199.24 51.7293 198.044 50.724 197.108 49.476C196.172 48.228 195.479 46.8067 195.028 45.212C194.578 43.5827 194.352 41.9013 194.352 40.168C194.352 38.088 194.63 36.1987 195.184 34.5C195.739 32.8013 196.536 31.3627 197.576 30.184C198.616 28.9707 199.882 28.0347 201.372 27.376C202.863 26.7173 204.544 26.388 206.416 26.388C207.907 26.388 209.415 26.7173 210.94 27.376C212.466 28 213.87 29.1613 215.152 30.86V27.22H218.168V53.012C218.168 56.6173 217.232 59.46 215.36 61.54C213.523 63.62 210.611 64.66 206.624 64.66C205.099 64.66 203.678 64.5213 202.36 64.244C201.078 63.9667 199.934 63.516 198.928 62.892C197.958 62.3027 197.16 61.5053 196.536 60.5C195.912 59.5293 195.514 58.3333 195.34 56.912H198.2ZM215.256 39.544C215.256 38.3307 215.187 37.2907 215.048 36.424C214.944 35.5227 214.736 34.7427 214.424 34.084C214.147 33.3907 213.783 32.784 213.332 32.264C212.882 31.744 212.344 31.2413 211.72 30.756C210.854 30.132 210.022 29.6813 209.224 29.404C208.427 29.1267 207.508 28.988 206.468 28.988C205.186 28.988 204.007 29.196 202.932 29.612C201.858 30.028 200.922 30.6867 200.124 31.588C199.327 32.4893 198.703 33.6507 198.252 35.072C197.802 36.4587 197.576 38.14 197.576 40.116C197.576 42.1267 197.819 43.8253 198.304 45.212C198.824 46.564 199.483 47.6733 200.28 48.54C201.078 49.372 201.979 49.9787 202.984 50.36C203.99 50.7413 205.012 50.932 206.052 50.932C207.196 50.932 208.167 50.8107 208.964 50.568C209.762 50.3253 210.611 49.892 211.512 49.268C212.726 48.3667 213.644 47.2227 214.268 45.836C214.927 44.4147 215.256 42.6467 215.256 40.532V39.544Z" fill="white"></path>
                                    <circle cx="36.5" cy="18.5" r="4.5" fill="#FC624D"></circle>
                                 </svg>
                              </div>
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
      <table role="presentation" class="desktop desktop-bg" width="736" class="desktop" cellspacing="0" cellpadding="0" border="0" align="center">
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
      <table role="presentation" class="desktop desktop-bg"  width="736" class="desktop" cellspacing="0" cellpadding="0" border="0" align="center">
         <tbody>
            <tr>
               <td align="center">
                  <table role="presentation" width="550" cellspacing="0" cellpadding="0" border="0" align="center">
                     <tbody>
                        <tr>
                           <td class="d1" align="left" valign="top" style="padding: 0;">
                              <p>$subtitle</p>
                              <p>This $type will expire in 7 days.</p>
                              <p>
                                 <span style="white-space: nowrap;">
                              <div><a href="$link" class="desktop-button-bg" style="display: flex; align-items: center; width: fit-content; row-gap: 8px; column-gap: 8px; font-size: 17px; line-height: 20px;font-weight: 500; border-radius: 9999px; padding: 8px 16px; color: white !important; flex-shrink: 0;">$cta<svg xmlns="http://www.w3.org/2000/svg" width="17" height="17" fill="none" role="img" aria-label="circle plus solid" viewBox="0 0 24 24"><path fill="currentColor" fill-rule="evenodd" d="M12 2c5.514 0 10 4.486 10 10s-4.486 10-10 10-10-4.486-10-10 4.486-10 10-10zm0-2c-6.627 0-12 5.373-12 12s5.373 12 12 12 12-5.373 12-12-5.373-12-12-12zm2 12l-4.5 4.5 1.527 1.5 5.973-6-5.973-6-1.527 1.5 4.5 4.5z" clip-rule="evenodd"/></svg></a></div></span></p>
                              <p>$underline</p>
                              </p>
                              <p><b>Note:</b> This $type was intended for <span style="white-space: nowrap;"><a href="$email" style="color:#0070c9;">$email</a></span>. If you weren&#8217;t expecting this $type, there&#8217;s nothing to worry about — you can safely ignore it.</p>
                           </td>
                        </tr>
                     </tbody>
                  </table>
               </td>
            </tr>
         </tbody>
      </table>
      <table role="presentation" class="desktop desktop-bg" width="736" class="desktop" cellspacing="0" cellpadding="0" border="0" align="center">
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
      <table role="presentation" class="desktop desktop-bg" width="736" class="desktop" cellspacing="0" cellpadding="0" border="0" align="center">
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
            <tr>
               <td align="center" class="desktop-bg" style="margin: 0 auto; padding:0 20px 0 20px;">
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
                              <p>Pingpong is developed by the Computational Policy Lab at the Harvard Kennedy School.<br>All content © 2024 Computational Policy Lab. All rights reserved.</p>
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
