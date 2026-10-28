-- How a sign-in was made: the authentication protocol (a device-code sign-in is the one phishing uses), how the token was first transferred, and the service signed in to. Sent by CORE from Microsoft's own record.
-- Sign-ins stored before this have none. Safe to run again.
ALTER TABLE signin_events ADD COLUMN IF NOT EXISTS auth_protocol varchar(40);
ALTER TABLE signin_events ADD COLUMN IF NOT EXISTS transfer_method varchar(40);
ALTER TABLE signin_events ADD COLUMN IF NOT EXISTS resource varchar(160);
