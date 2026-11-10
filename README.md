# kindleforwarder

A self-hosted utility for Kindle Scribes (and other Kindle devices)

## Send Word docs to your Kindle Scribe as PDFs
Word docs are terrible on the Kindle scribe because when you take notes, it inserts the note and makes text flow around it like a drawing. So no crossing out, circling, or anything useful. 
This app runs on the system tray in the background and receives any Word doc (.doc or .docx) and converts it to PDF before sending it on to your Scribe. 

## Receive shared files from your Kindle Scribe as PDFs
Kindle's share feature is terrible because it sends your document as a link which expires. This app runs in the background and receives any shared Kindle file and downloads the linked PDF before sending it to you as an attachment.

## How to set up

1. Make a free gmail address to receive app related emails, such as examplekindleemail@gmail.com
2. In your security settings, enable 2 factor authentication and get an app password (search your account settings to find this). It will be something like "abcd efgh ijkl mnop"
3. Get your kindle scribe's email address from Amazon's "Your Content and Devices" area, and whitelist your examplekindleemail@gmail.com as a sender
4. In your email address that is the default destination for the Kindle's "share" feature, forward all emails from do-not-reply@amazon.com that contain "You sent a file" in the subject line to your  examplekindleemail@gmail.com.
5. Create a file named exactly ".env" in the folder from which you'll run the script using this template:

```
GMAIL_USER = "examplekindleemail@gmail.com"
GMAIL_APP_PASSWORD = "abcd efgh ijkl mnop" 
KINDLE_EMAIL = "my_scribe_email_address_from_amazon@kindle.com"
TO_EMAIL = "myKindleDefaultDestinationEmailAddress@wherever.com"
```

6. Double click kindle_forwarder.pyw and you should see a blue box in your system tray.
7. Add it to your scheduled tasks in Windows to run whenever the system starts if you want.

Important: You must leave your computer on and the app running for this to work!

Disclaimer: This was made with tons of AI. Use with caution.
